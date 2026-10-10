"""The ledger: what a person approved, kept permanently.

This is the line the whole system is built around. Everything before it --
parsed rows, suggested classifications, edited treatments -- is *staging*, and
staging is mutable on purpose, because a review workflow where nothing can be
corrected is a review workflow nobody uses. Everything from here on is
permanent, because Indian company law expects a financial record that cannot be
silently altered.

Three consequences, all of them structural rather than conventional:

* **The tables are append-only in the database.** No UPDATE grant, no DELETE
  grant, and a trigger that raises if either is somehow attempted. Application
  code cannot violate this, which is the point -- see
  ``core.db.rls.append_only_sql``.
* **A correction is a new entry pointing at the old one.** There is no
  ``superseded_by`` column to write, because writing it would require an UPDATE
  on the original. The link lives only on the correcting entry, and the reverse
  direction is a query. That constraint produced a better design than the one
  originally sketched: the original entry is not merely *treated* as untouched,
  it is untouchable.
* **Entries balance, checked by the database at commit.** A deferred constraint
  trigger sums each entry's lines. Deferred because an entry is written one line
  at a time and is legitimately unbalanced in between.

Voucher numbers are per client, per financial year, and contiguous -- which is
what auditors expect, and why they are allocated from a sequence row under a
lock at approval time rather than counted from existing entries.
"""

from __future__ import annotations

from django.db import models
from django.utils import timezone

from banking.models import StatementTransaction
from classify.models import LedgerAccount, Party
from core.fy import fy_label
from core.models import Client, FirmScopedModel, User, UUIDModel
from core.money import format_inr
from documents.models import Document


class VoucherType(models.TextChoices):
    """Tally's voucher types, as far as a bank statement can produce them."""

    PAYMENT = "Payment", "Payment"
    RECEIPT = "Receipt", "Receipt"
    #: Money moving between two accounts the client owns. Neither income nor
    #: expenditure, and reported separately.
    CONTRA = "Contra", "Contra"
    JOURNAL = "Journal", "Journal"
    #: The supplier's invoice, booked on its own date, before and apart from the payment (``ledger.billing``).
    PURCHASE = "Purchase", "Purchase"
    SALES = "Sales", "Sales"
    #: A return. A debit note reverses a purchase; a credit note reverses a sale.
    DEBIT_NOTE = "Debit Note", "Debit Note"
    CREDIT_NOTE = "Credit Note", "Credit Note"


class EntryKind(models.TextChoices):
    """Where an entry came from, which decides how it may be edited.

    A bank entry is one statement row posted, and its edit, removal and correction all run through that row's
    classification. A voucher entry has no bank row: it is a bill booked by a person, and it is edited or removed
    through the bill. The editing code checks this, so one kind can never be pushed down the other's path.
    """

    BANK = "BANK", "Posted from a bank statement row"
    VOUCHER = "VOUCHER", "A purchase, sales or note voucher"
    JOURNAL = "JOURNAL", "A journal voucher"


class Direction(models.TextChoices):
    DEBIT = "DR", "Debit"
    CREDIT = "CR", "Credit"


class VoucherSequence(UUIDModel, FirmScopedModel):
    """Next voucher number for one client, financial year and voucher type.

    A counter row rather than a ``MAX(entry_no) + 1`` query, because two
    approvals landing at once would both read the same maximum and allocate the
    same number. The row is locked with ``SELECT FOR UPDATE`` during allocation,
    so the second waits. Auditors expect contiguous numbering per book, and a
    duplicated or skipped voucher number is the kind of thing they open with.
    """

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="voucher_sequences")
    financial_year = models.PositiveSmallIntegerField(help_text="Starting year, e.g. 2025.")
    voucher_type = models.CharField(max_length=16, choices=VoucherType.choices)
    next_number = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "ledger_voucher_sequence"
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "client", "financial_year", "voucher_type"],
                name="uniq_voucher_sequence",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.voucher_type} {self.financial_year} -> {self.next_number}"


class EntryMarker(models.TextChoices):
    """Why a reviewer might want to look at this entry first.

    Set when the AI did something a person did not ask for, so it can be found
    among hundreds of entries, and cleared when a person has looked. Purely a
    finding aid: it changes nothing about what the entry means.
    """

    NONE = "", "No marker"
    #: The AI posted this itself because it was very sure. Nobody has looked.
    AI_POSTED = "AI_POSTED", "Posted by the AI"
    #: A person corrected a similar entry and the AI applied that lesson here.
    AI_REVISED = "AI_REVISED", "Changed by the AI after a correction"


class JournalEntry(UUIDModel, FirmScopedModel):
    """One approved, permanent accounting entry.

    Append-only. Nothing on this row changes after it is written, including its
    approval fields -- an entry is created *because* it was approved, so there
    is no unapproved state for it to be in.
    """

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="journal_entries")

    entry_no = models.PositiveIntegerField()
    financial_year = models.PositiveSmallIntegerField()
    entry_date = models.DateField()
    voucher_type = models.CharField(max_length=16, choices=VoucherType.choices)
    narration = models.TextField(blank=True)
    #: See ``EntryKind``. Every entry that existed before bills is a bank entry, hence the database default.
    entry_kind = models.CharField(
        max_length=8, choices=EntryKind.choices, default=EntryKind.BANK, db_default=EntryKind.BANK
    )

    #: The statement row this came from. The requirements document's "reference
    #: to the source line": any entry traces back to the exact line of the exact
    #: PDF that produced it, which turns "where did this come from?" into a
    #: click rather than an investigation.
    source_transaction = models.ForeignKey(
        StatementTransaction,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="journal_entries",
    )

    #: The entry this one corrects. Only ever set on the *correcting* entry --
    #: there is deliberately no reverse column, because writing one would mean
    #: updating a row in an append-only table. Use ``superseded_by``.
    supersedes = models.ForeignKey(
        "self", on_delete=models.PROTECT, null=True, blank=True, related_name="superseded_by_set"
    )

    approved_by = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name="approved_entries"
    )
    approved_at = models.DateTimeField()

    #: See ``EntryMarker``. Blank for an entry a person posted or has reviewed.
    marker = models.CharField(
        max_length=12, choices=EntryMarker.choices, blank=True, default=EntryMarker.NONE
    )

    class Meta:
        db_table = "ledger_journal_entry"
        ordering = ["entry_date", "entry_no"]
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "client", "financial_year", "voucher_type", "entry_no"],
                name="uniq_voucher_number_per_book",
            ),
        ]
        indexes = [
            models.Index(fields=["firm", "client", "entry_date"], name="idx_entry_client_date"),
        ]

    def __str__(self) -> str:
        return f"{self.voucher_type} #{self.entry_no} of {self.fy_label}"

    @property
    def fy_label(self) -> str:
        return fy_label(self.entry_date)

    @property
    def superseded_by(self) -> JournalEntry | None:
        """The entry that corrects this one, if any. A query, not a column."""
        return self.superseded_by_set.first()

    @property
    def is_superseded(self) -> bool:
        return self.superseded_by_set.exists()

    @property
    def total_paise(self) -> int:
        """The entry's value: the debit side, which equals the credit side."""
        return sum(line.amount_paise for line in self.lines.all() if line.is_debit)


class JournalLine(UUIDModel, FirmScopedModel):
    """One side of one entry. Append-only, like the entry it belongs to."""

    entry = models.ForeignKey(JournalEntry, on_delete=models.PROTECT, related_name="lines")
    ledger_account = models.ForeignKey(
        LedgerAccount, on_delete=models.PROTECT, related_name="journal_lines"
    )
    party = models.ForeignKey(
        Party, on_delete=models.PROTECT, null=True, blank=True, related_name="journal_lines"
    )

    direction = models.CharField(max_length=2, choices=Direction.choices)
    #: Always positive. The direction column carries which way it goes, because
    #: "a debit of minus five hundred" is not a thing an accountant says and a
    #: sign convention is one more thing to get backwards.
    amount_paise = models.BigIntegerField()

    #: Debits positive, credits negative -- the form the balance trigger sums.
    #: Maintained here rather than computed in the trigger so the invariant is
    #: one addition rather than a CASE expression that could drift from this
    #: model's idea of the sign.
    signed_paise = models.BigIntegerField()

    rcm = models.BooleanField(default=False)
    tds_section = models.CharField(max_length=16, blank=True)

    class Meta:
        db_table = "ledger_journal_line"
        ordering = ["-signed_paise"]  # debits first, as an entry is written
        constraints = [
            models.CheckConstraint(
                condition=models.Q(amount_paise__gt=0),
                name="ck_line_amount_is_positive",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(direction="DR", signed_paise__gt=0)
                    | models.Q(direction="CR", signed_paise__lt=0)
                ),
                name="ck_line_sign_matches_direction",
            ),
        ]
        indexes = [
            models.Index(fields=["firm", "ledger_account"], name="idx_line_ledger"),
        ]

    def __str__(self) -> str:
        return f"{self.ledger_account_id} {self.direction} {format_inr(self.amount_paise)}"

    @property
    def is_debit(self) -> bool:
        return self.direction == Direction.DEBIT

    @classmethod
    def build(cls, *, entry, ledger_account, direction, amount_paise, **extra) -> JournalLine:
        """Construct a line with its signed form kept in step with its direction."""
        amount = abs(int(amount_paise))
        return cls(
            firm_id=entry.firm_id,
            entry=entry,
            ledger_account=ledger_account,
            direction=direction,
            amount_paise=amount,
            signed_paise=amount if direction == Direction.DEBIT else -amount,
            **extra,
        )


class BooksAction(models.TextChoices):
    REQUESTED = "REQUESTED", "Approval requested"
    RETURNED = "RETURNED", "Returned for changes"
    #: The senior says the books are good. Locks nothing: entries stay editable, and a change after this is reported.
    APPROVED = "APPROVED", "Approved by the senior"
    #: The permanent lock, on a date the client's schedule names. (Stored as SIGNED_OFF since the lock was first built.)
    SIGNED_OFF = "SIGNED_OFF", "Sealed"
    REOPENED = "REOPENED", "Reopened"


class BooksEvent(UUIDModel, FirmScopedModel):
    """One step in getting a client's books signed off. Append-only.

    The books move through three states -- open, waiting for the senior, locked --
    and this is the record of every move between them. The current state is read
    off the latest event rather than stored, so it cannot disagree with its own
    history.
    """

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="books_events")
    action = models.CharField(max_length=12, choices=BooksAction.choices)
    #: The date the books are (or were) signed off through. Set on SIGNED_OFF
    #: and REOPENED; the date a request covers is the latest entry, so blank there.
    through_date = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True, default="")
    #: On APPROVED: a fingerprint of what the books start from (opening balances), so a change to a starting figure after
    #: the approval is noticed even though it is not an entry. Blank on every other action.
    fingerprint = models.CharField(max_length=64, blank=True, default="", db_default="")
    actor = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    class Meta:
        db_table = "ledger_books_event"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["firm", "client", "created_at"], name="idx_books_event")]

    def __str__(self) -> str:
        return f"{self.get_action_display()} {self.through_date or ''}".strip()


class ChangeAction(models.TextChoices):
    EDITED = "EDITED", "Ledger changed"
    REMOVED = "REMOVED", "Entry removed"
    AI_REVISED = "AI_REVISED", "Revised by the AI after a correction"
    RENUMBERED = "RENUMBERED", "Voucher renumbered at sign-off"
    RECTIFIED = "RECTIFIED", "Rectified by a journal after sign-off"


class EntryChange(UUIDModel, FirmScopedModel):
    """What an entry looked like before somebody changed or removed it. Append-only.

    Until sign-off an entry may be edited or deleted, which is what a working
    draft needs and exactly what an audit trail must not lose. So every change
    leaves the entry's previous state here -- who, when, why, and the complete
    before -- and a removed entry is recoverable from it. ``entry_id`` is a plain
    id, not a foreign key: the whole point is that the entry may no longer exist.
    """

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="entry_changes")
    entry_id = models.UUIDField(db_index=True)
    voucher_type = models.CharField(max_length=16)
    entry_no = models.PositiveIntegerField()
    entry_date = models.DateField()
    action = models.CharField(max_length=12, choices=ChangeAction.choices)
    before = models.JSONField(default=dict)
    after = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True, default="")
    #: Null when the change was the AI's own.
    actor = models.ForeignKey(User, on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    class Meta:
        db_table = "ledger_entry_change"
        ordering = ["created_at"]
        indexes = [models.Index(fields=["firm", "client", "created_at"], name="idx_entry_change")]

    def __str__(self) -> str:
        return f"{self.get_action_display()} {self.voucher_type} #{self.entry_no}"


class ImportKind(models.TextChoices):
    CHART_OPENING = "CHART_OPENING", "Chart of accounts and opening balances"


class ImportStatus(models.TextChoices):
    PREVIEW = "PREVIEW", "Previewed, not applied"
    CONFIRMED = "CONFIRMED", "Applied"
    DISCARDED = "DISCARDED", "Discarded"


class LedgerImportRun(UUIDModel, FirmScopedModel):
    """One uploaded Tally masters file, staged and then, if a person chooses, applied.

    Staging is mutable and the books are not (the same line the whole product
    draws): the preview writes nothing but this row, whose ``rows`` carry only
    what the import needs -- a name, a group, an amount -- and no file is kept.
    Confirming applies exactly what the person chose, once.
    """

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="ledger_import_runs")
    kind = models.CharField(max_length=16, choices=ImportKind.choices, default=ImportKind.CHART_OPENING)
    financial_year = models.PositiveSmallIntegerField(help_text="Starting year, e.g. 2025.")
    uploaded_by = models.ForeignKey(User, null=True, on_delete=models.SET_NULL, related_name="+")
    file_sha256 = models.CharField(max_length=64)
    source_format = models.CharField(max_length=8)
    #: False when the person asked for the chart only, e.g. because the file's
    #: balances are not at the start of the year.
    include_openings = models.BooleanField(default=True)
    status = models.CharField(max_length=12, choices=ImportStatus.choices, default=ImportStatus.PREVIEW)
    books_from = models.DateField(null=True, blank=True)
    counts = models.JSONField(default=dict)
    rows = models.JSONField(default=list)
    #: A fingerprint of the client's chart when the preview was made. A confirm
    #: against a different chart is refused: the preview no longer describes it.
    chart_stamp = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    result = models.JSONField(default=dict, blank=True)
    confirmed_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ledger_import_run"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["firm", "client", "created_at"], name="idx_import_run_client")]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} FY{self.financial_year} ({self.status})"


class LedgerOpening(UUIDModel, FirmScopedModel):
    """A ledger's balance at the start of a financial year, as imported.

    Not a journal entry, on purpose: an opening is a starting position, not a
    transaction. It takes no voucher number, is not in the Day Book, and can be
    replaced by a better import until the year is signed off, where an entry
    could only ever be reversed. ``ledger.reports`` adds it to a ledger's
    opening, and the counterpart shows as "Difference in opening balances".

    The composite foreign keys (see 0010) keep the ledger and the run in the
    same client's books, in PostgreSQL.
    """

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="ledger_openings")
    ledger = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT, related_name="openings")
    financial_year = models.PositiveSmallIntegerField(help_text="Starting year, e.g. 2025.")
    #: Debits positive, credits negative, like ``JournalLine.signed_paise``.
    signed_paise = models.BigIntegerField()
    run = models.ForeignKey(LedgerImportRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="openings")

    class Meta:
        db_table = "ledger_opening"
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "client", "ledger", "financial_year"], name="uniq_opening_per_ledger_year"
            ),
        ]
        indexes = [models.Index(fields=["firm", "client", "financial_year"], name="idx_opening_client_year")]

    def __str__(self) -> str:
        return f"{self.ledger_id} FY{self.financial_year} {format_inr(self.signed_paise)}"


# ---------------------------------------------------------------------------
# Bills: what a party owes, or is owed, and what has settled it
# ---------------------------------------------------------------------------


class BillKind(models.TextChoices):
    PURCHASE = "PURCHASE", "Purchase invoice"
    SALES = "SALES", "Sales invoice"
    DEBIT_NOTE = "DEBIT_NOTE", "Debit note (a purchase return)"
    CREDIT_NOTE = "CREDIT_NOTE", "Credit note (a sales return)"
    OPENING = "OPENING", "Opening balance, as a bill"


class Bill(UUIDModel, FirmScopedModel):
    """One invoice, note or opening balance that a party owes or is owed.

    The fact that makes party-wise accounting possible: the invoice exists in the books on its own date, separate from
    whatever later pays it. ``entry`` is the voucher that booked it; ``BillAllocation`` rows say what has settled it.

    Never edited once posted. Whether it is open, part-settled or settled is *computed* from its allocations
    (``ledger.billing.open_amount``) and is never stored, so it cannot drift from them.

    ``direction`` is the side the bill sits on in the party's ledger: a purchase or a credit note is a credit (the
    client owes), a sale or a debit note a debit (the party owes). An opening bill is either. A settling line is
    always the opposite side.

    ``invoice_key`` is the invoice's identity, the same one the GST module uses (``core.identity``), so a bill, an
    uploaded register row and a GSTR-2B row are recognised as one invoice. It is kept as first written even if the
    supplier's GSTIN is added later.
    """

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="bills")
    party = models.ForeignKey(Party, on_delete=models.PROTECT, related_name="bills")
    kind = models.CharField(max_length=12, choices=BillKind.choices)
    direction = models.CharField(max_length=2, choices=Direction.choices)

    #: The supplier's invoice number (for a sale, ours). Distinct from the firm's voucher number, which renumbering
    #: at sign-off may change.
    reference = models.CharField(max_length=64)
    bill_date = models.DateField()
    due_date = models.DateField(null=True, blank=True)
    #: The date of the voucher that booked it, which is what the sign-off lock reads. For an opening bill, the date
    #: the balance stands at.
    booked_on = models.DateField()
    financial_year = models.PositiveSmallIntegerField()

    taxable_paise = models.BigIntegerField(default=0)
    cgst_paise = models.BigIntegerField(default=0)
    sgst_paise = models.BigIntegerField(default=0)
    igst_paise = models.BigIntegerField(default=0)
    cess_paise = models.BigIntegerField(default=0)
    #: Signed: the rupee rounding a bill carries, positive when it rounds up.
    round_off_paise = models.BigIntegerField(default=0)
    #: Deducted at booking and not payable to the party.
    tds_paise = models.BigIntegerField(default=0)
    #: Reverse charge: the GST is the client's own liability, not part of what the party is owed.
    rcm = models.BooleanField(default=False)
    #: What the party's ledger was credited or debited for: taxable + tax + round-off - TDS (tax left out under RCM).
    total_paise = models.BigIntegerField()

    entry = models.OneToOneField(
        JournalEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="bill"
    )
    #: The uploaded invoice, protected: evidence behind the books must not vanish with a deleted file. A bill with none is
    #: allowed but is an open item ("needs document"), never silent.
    document = models.ForeignKey(
        Document, null=True, blank=True, on_delete=models.PROTECT, related_name="bills"
    )

    invoice_key = models.CharField(max_length=64, db_index=True)
    #: Blind index of the client's own GSTIN this belongs to, so each bill lands in the right GST return without the
    #: books importing anything from ``gst/``.
    own_gstin_hash = models.CharField(max_length=64, blank=True, default="", db_index=True)

    class Meta:
        db_table = "ledger_bill"
        ordering = ["bill_date", "created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["firm", "client", "kind", "financial_year", "invoice_key"],
                name="uniq_bill_per_invoice",
            ),
            models.CheckConstraint(condition=models.Q(total_paise__gt=0), name="ck_bill_total_is_positive"),
            models.CheckConstraint(
                condition=(
                    models.Q(taxable_paise__gte=0, cgst_paise__gte=0, sgst_paise__gte=0, igst_paise__gte=0)
                    & models.Q(cess_paise__gte=0, tds_paise__gte=0)
                ),
                name="ck_bill_amounts_are_not_negative",
            ),
            # A purchase and a credit note are what the client owes (a credit); a sale and a debit note, what the
            # party owes (a debit). An opening balance may be either.
            models.CheckConstraint(
                condition=(
                    models.Q(kind__in=["PURCHASE", "CREDIT_NOTE"], direction="CR")
                    | models.Q(kind__in=["SALES", "DEBIT_NOTE"], direction="DR")
                    | models.Q(kind="OPENING")
                ),
                name="ck_bill_direction_matches_kind",
            ),
        ]
        indexes = [
            models.Index(fields=["firm", "client", "party"], name="idx_bill_party"),
            models.Index(fields=["firm", "client", "bill_date"], name="idx_bill_date"),
            models.Index(fields=["firm", "own_gstin_hash", "invoice_key"], name="idx_bill_gst_key"),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.reference} ({format_inr(self.total_paise)})"


class AllocationKind(models.TextChoices):
    AGAINST_BILL = "AGAINST_BILL", "Against a bill"
    #: Paid or received without naming a bill. A party balance waiting to be applied to one.
    ON_ACCOUNT = "ON_ACCOUNT", "On account"
    #: Paid or received before the invoice exists.
    ADVANCE = "ADVANCE", "Advance"


class BillAllocation(UUIDModel, FirmScopedModel):
    """How much of one journal line settles one bill, or waits unapplied.

    A line on a party's ledger is either wholly accounted for by allocations or has a remainder that is simply not
    yet allocated, which is an open item. The database refuses an allocation total above the bill or above the line.
    """

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="bill_allocations")
    line = models.ForeignKey(JournalLine, on_delete=models.PROTECT, related_name="allocations")
    bill = models.ForeignKey(Bill, null=True, blank=True, on_delete=models.PROTECT, related_name="allocations")
    kind = models.CharField(max_length=12, choices=AllocationKind.choices)
    amount_paise = models.BigIntegerField()

    class Meta:
        db_table = "ledger_bill_allocation"
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount_paise__gt=0), name="ck_allocation_is_positive"),
            models.CheckConstraint(
                condition=(
                    models.Q(kind="AGAINST_BILL", bill__isnull=False)
                    | (~models.Q(kind="AGAINST_BILL") & models.Q(bill__isnull=True))
                ),
                name="ck_allocation_bill_matches_kind",
            ),
        ]
        indexes = [
            models.Index(fields=["firm", "bill"], name="idx_allocation_bill"),
            models.Index(fields=["firm", "line"], name="idx_allocation_line"),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {format_inr(self.amount_paise)}"


class ReadingStatus(models.TextChoices):
    OPEN = "OPEN", "Waiting for a person"
    BOOKED = "BOOKED", "Booked as a bill"
    ATTACHED = "ATTACHED", "Attached to a bill already booked"
    DISCARDED = "DISCARDED", "Set aside"


class InvoiceReading(UUIDModel, FirmScopedModel):
    """What an uploaded invoice file appears to say, as a draft, until a person books it or sets it aside.

    The file itself is a ``Document``; this is the reading of it. The reading is never the books: nothing is booked
    until a person confirms (``ledger.invoice_intake.book_reading``), and the bill that results carries the document, so
    the invoice and the entry are one thing. A reading attached to a bill that was booked by hand first links them
    from this side (``bill``), because a bill is never edited.

    The fields read (supplier name, GSTINs, amounts) are personal data and are kept encrypted in ``payload_enc``;
    ``checks`` holds only the names and results of the arithmetic that proves or faults the reading, which carry none.
    """

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="invoice_readings")
    document = models.OneToOneField(Document, on_delete=models.PROTECT, related_name="reading")
    #: ``PURCHASE`` (a supplier's invoice to the client) or ``SALES`` (the client's invoice to a customer).
    #: Blank while it is not known which (the client's own GSTIN is not on the file, or not on record): a person says.
    kind = models.CharField(
        max_length=12, blank=True, default="", choices=[(BillKind.PURCHASE, "Purchase"), (BillKind.SALES, "Sales")]
    )
    status = models.CharField(max_length=10, choices=ReadingStatus.choices, default=ReadingStatus.OPEN)
    #: The bill was booked by the system from this file, not by a person. Cleared once a person changes or confirms it.
    auto_booked = models.BooleanField(default=False, db_default=False)
    #: Why the system did not book this file itself, in words for the alert and the screen. Blank when it did.
    attention = models.CharField(max_length=255, blank=True, default="", db_default="")
    #: Every check passed. A reading that is not proved is still shown, with what failed, for a person to fix.
    proved = models.BooleanField(default=False)
    checks = models.JSONField(default=list)
    #: Why nothing could be read (a scan, say), in words for the screen. Blank when something was.
    unreadable_reason = models.CharField(max_length=255, blank=True, default="")
    payload_enc = models.BinaryField(null=True, blank=True)
    #: The invoice's identity as the books and the GST module know it, so a reading finds the bill booked from it.
    invoice_key = models.CharField(max_length=64, blank=True, default="", db_index=True)
    bill = models.OneToOneField(Bill, null=True, blank=True, on_delete=models.PROTECT, related_name="reading")
    decided_by = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="decided_readings"
    )
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ledger_invoice_reading"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["firm", "client", "status"], name="idx_reading_client_status")]

    def __str__(self) -> str:
        return f"Reading of {self.document_id} ({self.get_status_display()})"


class CloseAcknowledgement(UUIDModel, FirmScopedModel):
    """A person's reason why one open item may stand while the books are signed off.

    It does not make the item go away: the item stays listed, and this records who said it could stand and why, which is
    what lets sign-off go ahead. ``item_key`` names the item (see ``ledger.close.item_key``), so the reason stays with
    that very item and lapses if the item is fixed.
    """

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="close_acknowledgements")
    item_key = models.CharField(max_length=200)
    note = models.CharField(max_length=500)
    acknowledged_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="close_acknowledgements"
    )
    acknowledged_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "ledger_close_acknowledgement"
        constraints = [
            models.UniqueConstraint(fields=["firm", "client", "item_key"], name="uniq_close_ack_per_item"),
        ]

    def __str__(self) -> str:
        return f"{self.item_key}: {self.note[:40]}"


class AssetMethod(models.TextChoices):
    SLM = "SLM", "Straight line (Companies Act)"
    WDV = "WDV", "Written-down value, by days in use (Companies Act)"
    WDV_IT = "WDV_IT", "Written-down value, 180-day rule (Income-tax)"


class FixedAsset(UUIDModel, FirmScopedModel):
    """One asset in the client's register: what it cost, when it was put to use, and how it is depreciated.

    The cost comes from a purchase the books already hold (``bill``), so the register and the ledger are the same money seen
    twice, not two copies that can drift: a purchase that debits a fixed-asset ledger and is not in the register is an open
    item. Depreciation is *computed* from these terms (``ledger.depreciation``), never stored, so it is right whatever the
    terms are changed to.
    """

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="fixed_assets")
    name = models.CharField(max_length=200)
    ledger = models.ForeignKey(LedgerAccount, on_delete=models.PROTECT, related_name="assets")
    bill = models.ForeignKey(Bill, null=True, blank=True, on_delete=models.PROTECT, related_name="assets")
    cost_paise = models.BigIntegerField()
    residual_paise = models.BigIntegerField(default=0)
    put_to_use = models.DateField()
    method = models.CharField(max_length=8, choices=AssetMethod.choices, default=AssetMethod.SLM)
    life_years = models.PositiveSmallIntegerField(default=0)
    rate_bp = models.PositiveIntegerField(default=0, help_text="Annual rate in basis points: 1500 is 15%.")
    disposed_on = models.DateField(null=True, blank=True)
    disposal_paise = models.BigIntegerField(null=True, blank=True, help_text="What it was sold for.")

    class Meta:
        db_table = "ledger_fixed_asset"
        ordering = ["put_to_use", "name"]
        constraints = [
            models.CheckConstraint(condition=models.Q(cost_paise__gt=0), name="ck_asset_cost_positive"),
            models.CheckConstraint(
                condition=models.Q(residual_paise__gte=0, residual_paise__lt=models.F("cost_paise")), name="ck_asset_residual_below_cost"
            ),
        ]
        indexes = [models.Index(fields=["firm", "client"], name="idx_asset_client")]

    def __str__(self) -> str:
        return f"{self.name} ({format_inr(self.cost_paise)})"


class StockItem(UUIDModel, FirmScopedModel):
    """One product the client buys or sells: its master record, with the purchase and sales ledgers kept for it.

    Created from the lines of a booked invoice when item-wise booking is chosen. A line is matched to an existing item by the
    words that identify the product (``ledger.item_memory``), so batch codes and counts do not make a new item each time.
    """

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="stock_items")
    name = models.CharField(max_length=200)
    unit = models.CharField(max_length=16, blank=True, default="", db_default="")
    hsn_sac = models.CharField(max_length=8, blank=True, default="", db_default="")
    purchase_ledger = models.ForeignKey(LedgerAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    sales_ledger = models.ForeignKey(LedgerAccount, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        db_table = "ledger_stock_item"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["firm", "client", "name"], name="uniq_stock_item_name")]

    def __str__(self) -> str:
        return self.name


class StockEntryKind(models.TextChoices):
    OPENING = "OPENING", "Opening stock"
    ADJUSTMENT = "ADJUSTMENT", "Stock adjustment"


class StockEntry(UUIDModel, FirmScopedModel):
    """A stock movement that no bill carries: opening stock, or a count correction (damage, shortage, samples, a count found over).

    Purchases and sales move stock through their own invoice lines (``ledger.inventory``); these are the movements with no
    invoice behind them, so the register can start from what the client actually held and be put right at a physical count.
    The value is what the stock was carried at. This is the stock register only: the stock-in-trade figure in the accounts is
    booked through the opening balances or the closing-stock entry, not by this row.
    """

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="stock_entries")
    kind = models.CharField(max_length=12, choices=StockEntryKind.choices)
    entry_date = models.DateField()
    direction = models.CharField(max_length=3, choices=[("IN", "In"), ("OUT", "Out")])
    name = models.CharField(max_length=200)
    unit = models.CharField(max_length=16, blank=True)
    quantity = models.DecimalField(max_digits=18, decimal_places=3)
    value_paise = models.BigIntegerField(default=0, db_default=0)
    note = models.CharField(max_length=300, blank=True, default="", db_default="")
    created_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        db_table = "ledger_stock_entry"
        ordering = ["entry_date", "name"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="ck_stock_quantity_positive"),
            models.CheckConstraint(condition=models.Q(value_paise__gte=0), name="ck_stock_value_not_negative"),
        ]
        indexes = [models.Index(fields=["firm", "client", "entry_date"], name="idx_stock_entry_client_date")]

    def __str__(self) -> str:
        return f"{self.get_kind_display()}: {self.name} x {self.quantity}"


class DepreciationPosting(UUIDModel, FirmScopedModel):
    """The journal entry that books one financial year's depreciation, so it is booked once and can be found again.

    The entry itself is an ordinary Journal voucher (Dr Depreciation, Cr each asset ledger). This row is only the link from
    the year to that entry, and what the register said when it was posted, so a later change to an asset is noticed
    (``ledger.assets.depreciation_status``) instead of the books quietly disagreeing with the register.
    """

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="depreciation_postings")
    financial_year = models.PositiveSmallIntegerField(help_text="Starting year: 2025 is FY 2025-26.")
    entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, related_name="depreciation_posting")
    total_paise = models.BigIntegerField()

    class Meta:
        db_table = "ledger_depreciation_posting"
        constraints = [
            models.UniqueConstraint(fields=["firm", "client", "financial_year"], name="uniq_depreciation_per_year"),
        ]

    def __str__(self) -> str:
        return f"Depreciation FY{self.financial_year} {format_inr(self.total_paise)}"


class TdsChallan(UUIDModel, FirmScopedModel):
    """The challan detail of one payment to the tax department: which section it was for, its BSR code and serial number.

    The payment itself is an ordinary bank entry debited to ``TDS Payable``; this adds what the quarterly return needs.
    One challan per payment, so a payment cannot be reported twice.
    """

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="tds_challans")
    entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, related_name="tds_challan")
    section = models.CharField(max_length=16)
    bsr_code = models.CharField(max_length=7)
    serial = models.CharField(max_length=5)
    paid_on = models.DateField()

    class Meta:
        db_table = "ledger_tds_challan"
        ordering = ["paid_on"]
        indexes = [models.Index(fields=["firm", "client", "section"], name="idx_tds_challan_section")]

    def __str__(self) -> str:
        return f"Challan {self.bsr_code}/{self.serial} for {self.section}"


class Employee(UUIDModel, FirmScopedModel):
    """A person the client pays a salary to, with an account of their own for what is owed them.

    The account is a Current Liabilities ledger opened on their first salary run: a salary run credits what they are owed
    to it, and the bank payment that pays them is placed on it by a person. Their name is personal data, so the ledger is
    kept out of what the model is shown, like a party's account.
    """

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="employees")
    name = models.CharField(max_length=200)
    ledger = models.OneToOneField(
        LedgerAccount, null=True, blank=True, on_delete=models.PROTECT, related_name="employee_record"
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "ledger_employee"
        ordering = ["name"]
        constraints = [models.UniqueConstraint(fields=["firm", "client", "name"], name="uniq_employee_name_per_client")]

    def __str__(self) -> str:
        return self.name


class PayrollRun(UUIDModel, FirmScopedModel):
    """One month's salaries, booked as one journal entry. One run per month."""

    client = models.ForeignKey(Client, on_delete=models.PROTECT, related_name="payroll_runs")
    year = models.PositiveSmallIntegerField()
    month = models.PositiveSmallIntegerField()
    entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, related_name="payroll_run")
    gross_paise = models.BigIntegerField()
    net_paise = models.BigIntegerField()

    class Meta:
        db_table = "ledger_payroll_run"
        ordering = ["-year", "-month"]
        constraints = [models.UniqueConstraint(fields=["firm", "client", "year", "month"], name="uniq_payroll_per_month")]


class PayrollLine(UUIDModel, FirmScopedModel):
    """What one employee was paid in a run, and what was deducted. Figures are typed from the salary sheet, not computed."""

    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name="lines")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="payroll_lines")
    gross_paise = models.BigIntegerField()
    pf_employee_paise = models.BigIntegerField(default=0)
    pf_employer_paise = models.BigIntegerField(default=0)
    esi_employee_paise = models.BigIntegerField(default=0)
    esi_employer_paise = models.BigIntegerField(default=0)
    tds_paise = models.BigIntegerField(default=0)
    other_deduction_paise = models.BigIntegerField(default=0)
    net_paise = models.BigIntegerField()

    class Meta:
        db_table = "ledger_payroll_line"
        constraints = [models.UniqueConstraint(fields=["run", "employee"], name="uniq_payroll_line_per_employee")]
