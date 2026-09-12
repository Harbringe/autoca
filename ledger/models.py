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

from banking.models import StatementTransaction
from classify.models import LedgerAccount, Vendor
from core.fy import fy_label
from core.models import Client, FirmScopedModel, User, UUIDModel
from core.money import format_inr


class VoucherType(models.TextChoices):
    """Tally's voucher types, as far as a bank statement can produce them."""

    PAYMENT = "Payment", "Payment"
    RECEIPT = "Receipt", "Receipt"
    #: Money moving between two accounts the client owns. Neither income nor
    #: expenditure, and reported separately.
    CONTRA = "Contra", "Contra"
    JOURNAL = "Journal", "Journal"


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
    vendor = models.ForeignKey(
        Vendor, on_delete=models.PROTECT, null=True, blank=True, related_name="journal_lines"
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
