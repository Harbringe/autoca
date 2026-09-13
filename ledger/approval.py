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

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from classify.models import ClassificationMethod, TransactionClassification
from core.fy import financial_year
from core.money import format_inr
from core.rbac import require_permission
from ledger.models import Direction, JournalEntry, JournalLine, VoucherSequence, VoucherType


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

    The Contra case is. A transfer between two accounts the client owns is not
    expenditure and not income, and the only thing in the data that says so is
    the *group* of the ledger on the other side. Both conditions are checked --
    the narration looked like a self-transfer, and the ledger it was placed in
    is a bank or cash account -- because either alone gets it wrong: a client
    paying a supplier who shares their surname trips the first, and a genuine
    transfer misfiled against an expense ledger trips the second. Requiring both
    means a Contra is produced only when the evidence and the reviewer agree.
    """
    ledger = classification.ledger
    if classification.is_self_transfer and ledger is not None and ledger.is_bank_or_cash:
        return VoucherType.CONTRA
    return VoucherType.PAYMENT if classification.transaction.is_debit else VoucherType.RECEIPT


@transaction.atomic
def approve(classification, *, membership, narration: str | None = None) -> ApprovalResult:
    """Post one classified transaction to the ledger.

    Raises rather than returning a failure, because every reason this can fail
    is a bug or a permission problem, not an outcome a caller should branch on.
    """
    require_permission(membership, "journal.approve")

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

    voucher_type = voucher_type_for(classification)
    mirror = _mirror_for(classification) if voucher_type == VoucherType.CONTRA else None
    if mirror is not None:
        # The other account's statement already recorded this transfer. Writing
        # it again would count the money twice in both bank ledgers.
        entry = mirror
        classification.mirrored_entry_id = mirror.pk
    else:
        entry = _write_entry(
            classification,
            voucher_type=voucher_type,
            narration=narration if narration is not None else transaction_row.narration,
            approved_by=membership.user,
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
            "method", "needs_review", "confidence", "reviewed_by", "reviewed_at", "mirrored_entry_id",
        ]
    )

    if learned_from_model and classification.treatment is not None:
        from classify.engine import learn_rule_from

        learn_rule_from(classification, classification.treatment, membership.user)

    return ApprovalResult(entry=entry, classification=classification, mirrored=mirror is not None)


@transaction.atomic
def approve_many(classifications, *, membership) -> list[ApprovalResult]:
    """Post a batch. All or nothing.

    The high-confidence block of the review screen is approved this way. One
    transaction around the lot means a single bad row does not leave the batch
    half-posted, which would be worse than not posting it at all -- the reviewer
    would have to work out which half.
    """
    return [approve(row, membership=membership) for row in classifications]


@transaction.atomic
def correct(entry: JournalEntry, *, membership, treatment, narration: str | None = None):
    """Record a correction to a posted entry.

    The original is untouched -- it cannot be touched -- and stays visible. The
    correction is a new entry carrying a reversal of the original's lines plus
    the corrected ones, linked back by ``supersedes``. That is how accounting
    corrections are supposed to work and what company law expects; it also means
    the trial balance is right at every point in the chain rather than only at
    the end.
    """
    require_permission(membership, "journal.correct")

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

    return _write_entry(
        classification,
        voucher_type=entry.voucher_type,
        narration=narration if narration is not None else entry.narration,
        approved_by=membership.user,
        supersedes=entry,
        reversal_of=entry,
    )


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


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

    claimed = TransactionClassification.objects.filter(
        firm_id=classification.firm_id, mirrored_entry_id__isnull=False
    ).values("mirrored_entry_id")

    candidates = (
        JournalEntry.objects.filter(
            firm_id=classification.firm_id,
            client_id=txn.bank_account.client_id,
            voucher_type=VoucherType.CONTRA,
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


def _write_entry(
    classification, *, voucher_type, narration, approved_by, supersedes=None, reversal_of=None
) -> JournalEntry:
    txn = classification.transaction
    client = txn.bank_account.client
    year = financial_year(txn.value_date)

    entry = JournalEntry.objects.create(
        firm_id=classification.firm_id,
        client=client,
        entry_no=allocate_voucher_number(client, year, voucher_type),
        financial_year=year,
        entry_date=txn.value_date,
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
        for line in reversal_of.lines.all():
            lines.append(
                JournalLine.build(
                    entry=entry,
                    ledger_account=line.ledger_account,
                    vendor=line.vendor,
                    direction=(
                        Direction.CREDIT if line.is_debit else Direction.DEBIT
                    ),
                    amount_paise=line.amount_paise,
                )
            )

    lines.extend(_double_entry(entry, classification))
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
                vendor=classification.vendor,
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
            vendor=classification.vendor,
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
