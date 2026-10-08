"""Approval: the moment a suggestion becomes a permanent entry.

Everything here happens in one database transaction, because the steps are only
correct together. Allocating a voucher number and then failing to write the
entry burns a number and breaks the contiguity auditors expect; writing the
entry and failing to mark the suggestion accepted leaves a row that will be
approved twice.

The permission check is server-side and is not optional. A CA carries personal
legal responsibility for what is filed, so "who may approve" is a professional
boundary, not a UI preference — hiding the button is not enforcement.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from classify.models import ClassificationMethod, TransactionClassification
from classify.narration import Channel
from core.access import can_sign_off, require_posting_rights
from core.fy import financial_year
from core.money import format_inr
from core.rbac import require_permission
from ledger.models import (
    Direction,
    EntryMarker,
    JournalEntry,
    JournalLine,
    VoucherSequence,
    VoucherType,
)


class NotApprovableError(RuntimeError):
    """The row is not in a state that can be posted."""


class AlreadyPostedError(NotApprovableError):
    """This transaction already has a live entry in the ledger."""


@dataclass(frozen=True)
class ApprovalResult:
    entry: JournalEntry
    classification: TransactionClassification
    #: True when no entry was written because the other account's statement
    #: already posted this transfer; ``entry`` is that existing entry.
    mirrored: bool = False


#: How far apart the two sides of one transfer may be dated. Inter-bank
#: transfers settle a day or two apart, and across a weekend a little more.
MIRROR_WINDOW_DAYS = 5


def voucher_type_for(classification) -> str:
    """Payment, Receipt, or Contra.

    Direction decides between Payment and Receipt: money out of the bank is a
    Payment, money in is a Receipt. That part is not interesting.

    The Contra case is. Money moving between two accounts the client owns --
    two banks, or the bank and the cash box -- is not expenditure and not
    income, and in Tally that is a Contra voucher by definition of the ledger
    on the other side: the *group* decides. So the group alone decides here.
    The narration's own opinion (``is_self_transfer``) is not required: an ATM
    withdrawal names no counterparty and never looks like a self-transfer, yet
    it is the textbook Contra. The one misfile the group cannot catch --
    placing a row in the very account it came from -- ``approve`` refuses
    outright.
    """
    ledger = classification.ledger
    if classification.transaction.bank_account.is_liability:
        return _loan_voucher_type(classification)
    if ledger is not None and ledger.is_bank_or_cash:
        return VoucherType.CONTRA
    return VoucherType.PAYMENT if classification.transaction.is_debit else VoucherType.RECEIPT


def _loan_voucher_type(classification) -> str:
    """The voucher a row of a LOAN statement is, as Tally would book it.

    Cash moved only when the other side is a bank or cash ledger: an instalment (a credit on the loan, paid out
    of the bank) is a Payment, and a disbursal (a debit on the loan, paid into the bank) is a Receipt. Interest
    and charges (the other side an expense) move no cash at all, so they are Journal vouchers, not Payments.
    """
    ledger = classification.ledger
    if ledger is not None and ledger.is_bank_or_cash:
        return VoucherType.RECEIPT if classification.transaction.is_debit else VoucherType.PAYMENT
    return VoucherType.JOURNAL


def _loan_involved(classification) -> bool:
    """A loan account on one side, whichever statement this row came from."""
    from classify.models import LedgerGroup

    ledger = classification.ledger
    return classification.transaction.bank_account.is_liability or (
        ledger is not None and ledger.group == LedgerGroup.LOAN
    )


@transaction.atomic
def approve(classification, *, membership, narration: str | None = None, settlement=None) -> ApprovalResult:
    """Post one classified transaction to the ledger.

    A row placed on a supplier's or customer's own account must come with a ``settlement``: a person's decision about
    which of that party's bills it pays, or whether it is held on account or as an advance. Nothing reaches a party's
    account without one (see ``ledger.settlement``).

    Raises rather than returning a failure, because every reason this can fail
    is a bug or a permission problem, not an outcome a caller should branch on.
    """
    require_permission(membership, "journal.approve")
    require_posting_rights(membership, classification.transaction.bank_account.client)

    if classification.ledger is None:
        raise NotApprovableError(
            f"Transaction on {classification.transaction.value_date:%d-%m-%Y} "
            f"({classification.transaction.narration[:60]!r}) has no ledger. "
            f"Nothing unreviewed goes into the books."
        )

    transaction_row = classification.transaction
    _require_ledger_in_use(classification.ledger)
    if classification.ledger.name == transaction_row.bank_account.ledger_name:
        raise NotApprovableError(
            f"Transaction on {transaction_row.value_date:%d-%m-%Y} is placed in "
            f"{classification.ledger.name!r}, the bank account it came from. That "
            f"would debit and credit the same ledger. Place it in the other side "
            f"of the transaction."
        )

    if classification.mirrored_entry_id or _live_entry_for(transaction_row) is not None:
        raise AlreadyPostedError(
            f"Transaction on {transaction_row.value_date:%d-%m-%Y} for "
            f"{format_inr(transaction_row.amount_paise)} is already posted. To "
            f"change it, record a correction against the existing entry."
        )

    from ledger.editing import locked_through

    through = locked_through(transaction_row.bank_account.client_id)
    if through is not None and transaction_row.value_date <= through:
        raise NotApprovableError(
            f"Transaction on {transaction_row.value_date:%d-%m-%Y} falls inside books signed "
            f"off through {through:%d-%m-%Y}, so it can no longer be posted. Ask a senior to "
            f"reopen the books."
        )

    from ledger import settlement as settling

    party = settling.party_for_ledger(classification.ledger)
    if party is not None:
        if settlement is None:
            raise NotApprovableError(settling.needed_message(party, transaction_row.amount_paise))
        settling.validate(party, settling.line_direction_for(transaction_row), transaction_row.amount_paise, settlement)
        # The party is the account, so the line says so: the party reports and the open items read it from there.
        if classification.party_id != party.pk:
            classification.party = party
    elif settlement is not None:
        raise NotApprovableError("This row is not on a party's account, so there is nothing to settle.")

    voucher_type = voucher_type_for(classification)
    mirror = (
        _mirror_for(classification)
        if voucher_type == VoucherType.CONTRA or _loan_involved(classification)
        else None
    )
    if mirror is not None:
        # The other account's statement already recorded this transfer. Writing
        # it again would count the money twice in both bank ledgers.
        entry = mirror
        classification.mirrored_entry_id = mirror.pk
    else:
        entry = _write_entry(
            classification,
            voucher_type=voucher_type,
            narration=narration if narration is not None else book_narration_for(classification),
            approved_by=membership.user,
        )
        if party is not None:
            settling.apply(
                entry.lines.get(ledger_account=classification.ledger), settlement, transaction_row.amount_paise
            )

    # Approving a model's suggestion is a person agreeing with it, and that
    # agreement is worth remembering: next month the same payee is a rule hit
    # in the high band instead of another model call and another review.
    learned_from_model = classification.method == ClassificationMethod.LLM

    classification.method = ClassificationMethod.REVIEWED
    classification.needs_review = False
    classification.confidence = 1.0
    classification.reviewed_by = membership.user
    classification.reviewed_at = timezone.now()
    classification.save(
        update_fields=[
            "method", "needs_review", "confidence", "reviewed_by", "reviewed_at", "mirrored_entry_id", "party",
        ]
    )

    if learned_from_model and classification.treatment is not None:
        from classify.engine import learn_rule_from

        learn_rule_from(classification, classification.treatment, membership.user)

    return ApprovalResult(entry=entry, classification=classification, mirrored=mirror is not None)


def book_narration_for(classification) -> str:
    """The narration the voucher carries.

    The one the model wrote, if it wrote one; otherwise a plain sentence in the
    form a CA would write, built from what the row already knows. The bank's
    own string is never used as a narration -- it is evidence of the movement,
    not a description of the entry -- but it is quoted at the end so the
    voucher still traces to the statement line by eye.
    """
    if classification.book_narration:
        return classification.book_narration
    txn = classification.transaction
    ledger = classification.ledger.name if classification.ledger else "the ledger"
    amount = format_inr(txn.amount_paise)
    party = classification.counterparty.strip()
    channel = classification.channel if classification.channel not in ("", "UNKNOWN") else "bank"
    if txn.bank_account.kind == "CARD":
        # A purchase or charge on the card raises what is owed; a payment or a refund lowers it.
        bank_side = classification.ledger is not None and classification.ledger.is_bank_or_cash
        if txn.is_debit:
            head = f"Being {amount} spent on the card towards {ledger}"
        else:
            head = f"Being {amount} paid to the card from {ledger}" if bank_side else f"Being {amount} credited to the card against {ledger}"
        return f"{head} (card statement: {txn.narration.strip()[:80]})"
    if txn.bank_account.kind == "LOAN":
        # A debit on the loan raises what is owed; a credit lowers it. "Paid" and "received" would read backwards.
        bank_side = classification.ledger is not None and classification.ledger.is_bank_or_cash
        if txn.is_debit:
            head = f"Being loan of {amount} disbursed into {ledger}" if bank_side else f"Being {amount} charged on the loan towards {ledger}"
        else:
            head = f"Being {amount} repaid towards the loan from {ledger}" if bank_side else f"Being {amount} credited to the loan against {ledger}"
        return f"{head} (loan statement: {txn.narration.strip()[:80]})"
    if classification.ledger is not None and classification.ledger.is_bank_or_cash:
        head = f"Being {amount} transferred to {ledger}" if txn.is_debit else f"Being {amount} received into bank from {ledger}"
    elif txn.is_debit:
        head = f"Being {amount} paid" + (f" to {party}" if party else "") + f" towards {ledger}"
    else:
        head = f"Being {amount} received" + (f" from {party}" if party else "") + f" as {ledger}"
    return f"{head} by {channel} ({txn.narration.strip()[:80]})"


@transaction.atomic
def approve_many(classifications, *, membership, settlements=None) -> list[ApprovalResult]:
    """Post a batch. All or nothing.

    The high-confidence block of the review screen is approved this way. One
    transaction around the lot means a single bad row does not leave the batch
    half-posted, which would be worse than not posting it at all -- the reviewer
    would have to work out which half.
    """
    settlements = settlements or {}
    return [approve(row, membership=membership, settlement=settlements.get(row.pk)) for row in classifications]


@transaction.atomic
def correct(
    entry: JournalEntry, *, membership, treatment, narration: str | None = None, note: str = "", learn: bool = True
):
    """Correct a posted entry.

    While the books are still a working draft this simply *changes the entry*:
    what it was is kept in the change log (``ledger.editing``) and nothing is
    lost, but the books are not left carrying the scaffolding of getting them
    right. Once a senior has signed the entry's period off, it cannot be changed
    -- the database refuses -- and the correction is a new entry that reverses
    the original's lines and carries the corrected ones, linked by
    ``supersedes`` and dated after the sign-off. Either way the original is
    never silently lost.
    """
    from ledger import editing

    require_permission(membership, "journal.correct")
    require_posting_rights(membership, entry.client)
    # Both paths below work through the entry's bank row. A purchase, sales or note voucher has none, and is changed
    # through its bill, so refuse here in words instead of failing on a missing statement row.
    editing.require_bank_entry(entry)

    if not editing.is_locked(entry):
        from ledger.learning import learn_after_correction

        require_not_own_bank_ledger(entry, treatment.ledger)

        revised = editing.revise_in_place(
            entry, treatment, actor=membership.user, narration=narration, note=note
        )
        # A correction is usually a lesson about the payee: learn it, and apply it to
        # the similar entries the AI placed on its own. `learn=False` means "this entry
        # only" -- a refund, a one-off -- and then nothing else is touched.
        if learn:
            learn_after_correction(revised, treatment, membership.user)
        return revised

    # Books a senior has signed are the senior's to amend: a correction here is
    # an adjustment in the open period against signed figures. Anyone else is told
    # the entry is locked, which is the fact that matters to them.
    if not can_sign_off(membership, entry.client):
        raise editing.EntryLockedError(
            f"This entry is inside books signed off through "
            f"{editing.locked_through(entry.client_id):%d-%m-%Y}. Only the client's senior CA "
            f"or a firm administrator can adjust it; ask them."
        )
    require_not_own_bank_ledger(entry, treatment.ledger)

    from ledger.models import BillAllocation

    if BillAllocation.objects.filter(line__entry=entry).exists():
        # A reversing line on the party's account would sit on the same side as the bill it was meant to reopen, and the
        # allocations on the original are locked with it, so the books could not be made to show the bill open again.
        raise NotApprovableError(
            f"{entry} settles bills and is inside signed-off books, so it cannot be corrected here. Record a journal "
            f"voucher dated after the sign-off, or ask a senior to reopen the books."
        )

    if entry.is_superseded:
        raise NotApprovableError(
            f"{entry} has already been corrected by {entry.superseded_by}. "
            f"Correct that entry instead; the chain must stay linear."
        )

    _require_ledger_in_use(treatment.ledger)
    classification = entry.source_transaction.classification
    classification.apply(
        treatment, method=ClassificationMethod.REVIEWED, confidence=1.0, user=membership.user
    )
    classification.needs_review = False
    classification.reviewed_at = timezone.now()
    classification.save()

    through = editing.locked_through(entry.client_id)
    return _write_entry(
        classification,
        voucher_type=entry.voucher_type,
        narration=narration if narration is not None else entry.narration,
        approved_by=membership.user,
        supersedes=entry,
        reversal_of=entry,
        # The original's date is inside the locked period, and so would the
        # correction's be. A correction to closed books is an adjustment in the
        # open period, which is what an accountant would do by hand.
        entry_date=max(entry.entry_date, through + datetime.timedelta(days=1)),
    )


def auto_post(classification) -> JournalEntry | None:
    """Post a row on the AI's own authority -- only when it is very sure.

    The one place an entry reaches the books with nobody having looked, so the
    conditions are deliberately many and every one of them errs towards leaving
    the row in the queue:

    * the row is placed, by a rule or the model, with high confidence (0.90+);
    * the model asked no question -- a question means it was not sure;
    * the ledger is in use and is not Suspense, which is where nobody decided;
    * the ledger is not one the model opened that no person has yet posted to --
      a new head is exactly where a confident mistake would otherwise spread;
    * it is not money that moved electronically landing in a cash ledger: UPI,
      NEFT, a card and the like never pass through the cash box, so a "cash
      withdrawal" by UPI is a transfer to another account read wrongly;
    * it is not already posted, nor the twin of a transfer already posted;
    * its date is not inside books a senior has signed off.

    What it posts is not permanent: until sign-off a CA can change or remove it,
    and it carries a marker (``EntryMarker.AI_POSTED``) so it can be found. No
    rule is learned from it -- the AI agreeing with itself is not evidence.
    """
    from classify.models import LedgerGroup, LedgerStatus
    from classify.treatment import ReviewBand
    from ledger.editing import locked_through

    txn = classification.transaction
    ledger = classification.ledger
    if (
        ledger is None
        or classification.method not in (ClassificationMethod.RULE, ClassificationMethod.LLM)
        or classification.review_band != ReviewBand.HIGH
        or classification.open_question
        or classification.mirrored_entry_id
        or ledger.group == LedgerGroup.SUSPENSE
        or ledger.status != LedgerStatus.ACTIVE
        or ledger.name == txn.bank_account.ledger_name
        # A payment on a party's account settles bills, and a person says which. Never the machine's to post.
        or ledger.is_party_account
        or (ledger.group == LedgerGroup.CASH and classification.channel in ELECTRONIC_CHANNELS)
        or (ledger.proposal_reason and not _a_person_has_posted_to(ledger))
        or _live_entry_for(txn) is not None
    ):
        return None
    through = locked_through(txn.bank_account.client_id)
    if through is not None and txn.value_date <= through:
        return None

    voucher_type = voucher_type_for(classification)
    if voucher_type == VoucherType.CONTRA or _loan_involved(classification):
        mirror = _mirror_for(classification)
        if mirror is not None:
            classification.mirrored_entry_id = mirror.pk
            classification.save(update_fields=["mirrored_entry_id"])
            return mirror
    return _write_entry(
        classification,
        voucher_type=voucher_type,
        narration=book_narration_for(classification),
        approved_by=None,
        marker=EntryMarker.AI_POSTED,
    )


def auto_post_settlement(classification, bill, tds_paise: int = 0) -> JournalEntry | None:
    """Post a bank row as the payment of a bill, when ``ledger.matching`` has found them to be one and the same.

    The row goes on the party's own account and the bill is allocated in the same step, so the bill is settled and the
    bank row is explained by one entry. Like every entry the machine posts it is marked ``AI_POSTED`` and can be corrected
    or removed by a person until sign-off. ``tds_paise`` is the tax a customer deducted before paying a sales bill: the
    receipt is the bill less that, and the entry then has a third line, to TDS Receivable. Refused (``None``) for a row a person has handled, already posted, inside signed-off
    books, or that is not a plain payment or receipt on a bank account.
    """
    from classify.models import LedgerGroup
    from ledger import billing
    from ledger.editing import locked_through

    txn = classification.transaction
    if (
        classification.method == ClassificationMethod.REVIEWED
        or classification.mirrored_entry_id
        or txn.bank_account.is_liability
        or classification.is_self_transfer
        or _live_entry_for(txn) is not None
    ):
        return None
    through = locked_through(txn.bank_account.client_id)
    if through is not None and (txn.value_date <= through or bill.bill_date <= through):
        return None
    if bill.party.client_id != txn.bank_account.client_id:
        return None
    if tds_paise and (txn.is_debit or bill.kind != "SALES"):
        return None  # only a receipt against a sales bill carries tax the customer deducted

    side = LedgerGroup.CREDITOR if bill.direction == Direction.CREDIT else LedgerGroup.DEBTOR
    ledger = billing.party_ledger_for(bill.party, side=side)
    if ledger.name == txn.bank_account.ledger_name:
        return None

    classification.ledger = ledger
    classification.party = bill.party
    classification.method = ClassificationMethod.RULE
    classification.confidence = 1.0
    classification.needs_review = False
    classification.rationale = (
        f"Matched to {bill.reference}: the amount is the bill less the {bill.party.tds_section} TDS the customer deducts, "
        "the same party, and nothing else fits."
        if tds_paise
        else f"Matched to {bill.reference}: the same amount, the same party, and nothing else fits."
    )
    classification.save(update_fields=["ledger", "party", "method", "confidence", "needs_review", "rationale"])

    tds_receipt = (
        (billing.standard_ledger(bill.client, "TDS Receivable"), tds_paise, bill.party.tds_section) if tds_paise else None
    )
    note = f", less Rs {tds_paise / 100:,.2f} TDS deducted by the customer" if tds_paise else ""
    entry = _write_entry(
        classification,
        voucher_type=voucher_type_for(classification),
        narration=f"Against {bill.reference} of {bill.party.canonical_name}{note} (matched automatically)",
        approved_by=None,
        marker=EntryMarker.AI_POSTED,
        tds_receipt=tds_receipt,
    )
    line = entry.lines.get(ledger_account=ledger)
    billing.allocate(line, amount_paise=txn.amount_paise + tds_paise, bill=bill)
    return entry


def auto_post_client(client) -> int:
    """Post everything for ``client`` that ``auto_post`` is willing to. Returns the count.

    Each row is its own savepoint: one that the database refuses -- a locked
    period, a constraint -- stays in the queue and does not take the rest down.
    """
    from django.db import DatabaseError

    from classify.engine import pending_approval

    posted = 0
    for row in list(pending_approval(client)):
        try:
            with transaction.atomic():
                if auto_post(row) is not None:
                    posted += 1
        except DatabaseError:
            continue
    return posted


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


#: Ways money moves that never involve notes and coins changing hands.
ELECTRONIC_CHANNELS = frozenset({
    Channel.UPI, Channel.NEFT, Channel.RTGS, Channel.IMPS,
    Channel.TRANSFER, Channel.CARD, Channel.MANDATE,
})


def _a_person_has_posted_to(ledger) -> bool:
    return JournalLine.objects.filter(ledger_account=ledger, entry__approved_by__isnull=False).exists()


def _mirror_for(classification) -> JournalEntry | None:
    """The entry the other account's statement already posted for this transfer, if any.

    The same transfer, seen from the other side, writes identical lines: the
    receiving bank debited, the paying bank credited, the same amount. So a match
    is a live Contra with exactly those two lines, dated within a few days,
    sourced from a different bank account, and not already claimed by another row.
    """
    import datetime

    txn = classification.transaction
    bank = _bank_ledger_for(classification)
    other = classification.ledger
    debit_ledger, credit_ledger = (other, bank) if txn.is_debit else (bank, other)
    window = datetime.timedelta(days=MIRROR_WINDOW_DAYS)
    # A loan instalment is a Payment on the bank's side and a Payment on the loan's, never a Contra, so when a loan
    # is involved the twin may be any of these. It still has to be exactly these two ledgers and this amount, from
    # a different account, so nothing unrelated can match.
    twin_types = (
        (VoucherType.CONTRA, VoucherType.PAYMENT, VoucherType.RECEIPT)
        if _loan_involved(classification)
        else (VoucherType.CONTRA,)
    )

    claimed = TransactionClassification.objects.filter(
        firm_id=classification.firm_id, mirrored_entry_id__isnull=False
    ).values("mirrored_entry_id")

    candidates = (
        JournalEntry.objects.filter(
            firm_id=classification.firm_id,
            client_id=txn.bank_account.client_id,
            voucher_type__in=twin_types,
            superseded_by_set__isnull=True,
            entry_date__gte=txn.value_date - window,
            entry_date__lte=txn.value_date + window,
        )
        .exclude(source_transaction__bank_account_id=txn.bank_account_id)
        .exclude(pk__in=claimed)
        .filter(lines__ledger_account=debit_ledger, lines__direction=Direction.DEBIT, lines__amount_paise=txn.amount_paise)
        .filter(lines__ledger_account=credit_ledger, lines__direction=Direction.CREDIT, lines__amount_paise=txn.amount_paise)
        .distinct()
    )
    return min(candidates, key=lambda e: abs((e.entry_date - txn.value_date).days), default=None)


def _require_ledger_in_use(ledger) -> None:
    """A proposed ledger is a question for a CA, not somewhere entries may go."""
    from classify.models import LedgerStatus

    if ledger is not None and ledger.status != LedgerStatus.ACTIVE:
        raise NotApprovableError(
            f"{ledger.name!r} is a ledger the model proposed and no CA has accepted. "
            f"Accept it, merge it into an existing ledger, or place the row elsewhere."
        )


def require_not_own_bank_ledger(entry_or_classification, ledger) -> None:
    """The other side of a bank entry cannot be the bank account it came off.

    Both legs would land on the same ledger and the entry would move no money. The review
    endpoint refuses this; every path that changes an entry's treatment must too.
    """
    from django.core.exceptions import ValidationError

    txn = getattr(entry_or_classification, "source_transaction", None) or entry_or_classification.transaction
    if ledger.name == txn.bank_account.ledger_name:
        raise ValidationError(
            "This is the bank account the transaction came from. Choose the other side of the entry."
        )


def reversal_lines(entry, original) -> list[JournalLine]:
    """Every line of ``original`` the other way round, so the two net to nothing."""
    return [
        JournalLine.build(
            entry=entry,
            ledger_account=line.ledger_account,
            party=line.party,
            direction=Direction.CREDIT if line.is_debit else Direction.DEBIT,
            amount_paise=line.amount_paise,
        )
        for line in original.lines.all()
    ]


def _write_entry(
    classification, *, voucher_type, narration, approved_by, supersedes=None, reversal_of=None,
    entry_date=None, marker=EntryMarker.NONE, tds_receipt=None,
) -> JournalEntry:
    txn = classification.transaction
    client = txn.bank_account.client
    entry_date = entry_date or txn.value_date
    year = financial_year(entry_date)

    entry = JournalEntry.objects.create(
        firm_id=classification.firm_id,
        client=client,
        entry_no=allocate_voucher_number(client, year, voucher_type),
        financial_year=year,
        entry_date=entry_date,
        marker=marker,
        voucher_type=voucher_type,
        narration=narration,
        source_transaction=txn,
        supersedes=supersedes,
        approved_by=approved_by,
        approved_at=timezone.now(),
    )

    lines = []
    if reversal_of is not None:
        # Reverse every line of the entry being corrected, so the two together
        # net to nothing and only the new treatment stands.
        lines.extend(reversal_lines(entry, reversal_of))

    lines.extend(_double_entry(entry, classification))
    if tds_receipt is not None:
        # A customer paid net of the TDS they deducted: the bank got the net, the customer's account clears in full, and the
        # difference is tax the client will claim, held in TDS Receivable.
        tds_ledger, tds_paise, section = tds_receipt
        for line in lines:
            if line.ledger_account_id == classification.ledger_id and line.direction == Direction.CREDIT:
                line.amount_paise += tds_paise
                line.signed_paise -= tds_paise
        lines.append(
            JournalLine.build(
                entry=entry, ledger_account=tds_ledger, direction=Direction.DEBIT, amount_paise=tds_paise, tds_section=section
            )
        )
    JournalLine.objects.bulk_create(lines)
    return entry


def _double_entry(entry, classification) -> list[JournalLine]:
    """The two sides of a bank transaction.

    Money out of the bank: debit the other ledger, credit the bank. Money in:
    the reverse. The bank ledger is always one side, because every row here came
    off a bank statement.
    """
    txn = classification.transaction
    bank_ledger = _bank_ledger_for(classification)
    other = classification.ledger
    amount = txn.amount_paise

    shared = {"rcm": classification.rcm, "tds_section": classification.tds_section}
    if txn.is_debit:
        return [
            JournalLine.build(
                entry=entry,
                ledger_account=other,
                party=classification.party,
                direction=Direction.DEBIT,
                amount_paise=amount,
                **shared,
            ),
            JournalLine.build(
                entry=entry,
                ledger_account=bank_ledger,
                direction=Direction.CREDIT,
                amount_paise=amount,
            ),
        ]
    return [
        JournalLine.build(
            entry=entry,
            ledger_account=bank_ledger,
            direction=Direction.DEBIT,
            amount_paise=amount,
        ),
        JournalLine.build(
            entry=entry,
            ledger_account=other,
            party=classification.party,
            direction=Direction.CREDIT,
            amount_paise=amount,
            **shared,
        ),
    ]


def _bank_ledger_for(classification):
    from classify.seeds import contra_ledger_for

    return contra_ledger_for(classification.transaction.bank_account)


def allocate_voucher_number(client, year: int, voucher_type: str) -> int:
    """Next number in this book, under a row lock.

    ``MAX(entry_no) + 1`` would let two concurrent approvals read the same
    maximum and allocate the same number. Locking the counter row makes the
    second wait for the first.
    """
    sequence, _ = VoucherSequence.objects.get_or_create(
        firm_id=client.firm_id, client=client, financial_year=year, voucher_type=voucher_type
    )
    locked = VoucherSequence.objects.select_for_update().get(pk=sequence.pk)
    number = locked.next_number
    locked.next_number = number + 1
    locked.save(update_fields=["next_number"])
    return number


def _live_entry_for(transaction_row) -> JournalEntry | None:
    """The entry currently standing for this transaction, ignoring corrected ones."""
    for entry in transaction_row.journal_entries.all():
        if not entry.is_superseded:
            return entry
    return None
