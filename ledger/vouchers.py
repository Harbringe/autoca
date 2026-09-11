"""Turning classified bank rows into double-entry vouchers.

A voucher is derived, never stored. Its date, amount, narration and bank side
come from the statement row; its other side comes from the classification. Both
are already persisted, both are already audited, and a third copy would be a
third thing to keep in step -- the first time a reviewer corrects a ledger, a
stored voucher becomes a lie that still exports cleanly.

The part worth reading carefully is :func:`voucher_type_for`. Everything else
here is mechanical.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from classify.models import LedgerGroup


class VoucherType:
    """Tally's voucher types, as far as a bank statement can produce them."""

    PAYMENT = "Payment"
    RECEIPT = "Receipt"
    #: Money moving between two accounts the client owns. Neither income nor
    #: expenditure, and Tally reports on it separately.
    CONTRA = "Contra"


@dataclass(frozen=True)
class VoucherLine:
    """One side of the entry."""

    ledger_name: str
    #: Tally's sign convention, not accounting's: a **negative** amount is a
    #: debit and a positive one is a credit. This trips up everyone who writes a
    #: Tally importer, and the failure is quiet -- the voucher imports, the
    #: totals are right, and every entry is the wrong way round.
    amount: Decimal

    @property
    def is_debit(self) -> bool:
        return self.amount < 0

    @property
    def is_deemed_positive(self) -> str:
        """Tally's own flag for "this line is the debit side"."""
        return "Yes" if self.is_debit else "No"


@dataclass(frozen=True)
class Voucher:
    date: str  # YYYYMMDD, Tally's format
    voucher_type: str
    narration: str
    #: The ledger Tally shows in the Particulars column: the *other* side.
    party_ledger: str
    lines: tuple[VoucherLine, ...]
    #: Stable across re-exports, derived from the transaction's dedupe hash, so
    #: a statement exported twice does not become two sets of vouchers in Tally.
    remote_id: str
    reference: str = ""

    def __post_init__(self):
        total = sum(line.amount for line in self.lines)
        if total != 0:
            raise ValueError(
                f"Voucher does not balance: lines sum to {total}, not zero. "
                f"Tally would reject this, but only after importing everything "
                f"before it."
            )


def voucher_type_for(classification) -> str:
    """Payment, Receipt, or Contra.

    Direction decides between Payment and Receipt: money out of the bank is a
    Payment, money in is a Receipt. That part is not interesting.

    The Contra case is. A transfer between two accounts the client owns is not
    expenditure and not income, and the only thing in the data that says so is
    the *group* of the ledger on the other side. Both conditions are checked --
    the narration looked like a self-transfer, and the ledger it was placed in
    is a bank or cash account -- because either one alone gets it wrong: a
    client who pays a supplier who happens to share their surname trips the
    first, and a genuine transfer misfiled against an expense ledger trips the
    second. Requiring both means a Contra is only ever produced when the
    evidence and the reviewer agree.
    """
    ledger = classification.ledger
    if classification.is_self_transfer and ledger is not None and ledger.is_bank_or_cash:
        return VoucherType.CONTRA
    return VoucherType.PAYMENT if classification.transaction.is_debit else VoucherType.RECEIPT


def build_voucher(classification) -> Voucher:
    """Derive the voucher for one classified transaction.

    Raises if the row is still in the review queue. An unreviewed row has no
    ledger, and the alternative -- posting it to a suspense account so the
    export "works" -- puts rows nobody has looked at into a client's books.
    """
    transaction = classification.transaction
    ledger = classification.ledger
    if ledger is None:
        raise UnclassifiedTransactionError(
            f"Transaction {transaction.pk} on {transaction.value_date:%d-%m-%Y} "
            f"({transaction.narration[:60]!r}) has not been classified. Exporting "
            f"it would put a row nobody has reviewed into the client's books."
        )

    bank_ledger = transaction.bank_account.ledger_name
    amount = transaction.amount

    # Money out: debit the other ledger, credit the bank. Money in: the reverse.
    # Negative is the debit side; see VoucherLine.amount.
    if transaction.is_debit:
        lines = (VoucherLine(ledger.name, -amount), VoucherLine(bank_ledger, amount))
    else:
        lines = (VoucherLine(bank_ledger, -amount), VoucherLine(ledger.name, amount))

    return Voucher(
        date=transaction.value_date.strftime("%Y%m%d"),
        voucher_type=voucher_type_for(classification),
        narration=transaction.narration,
        party_ledger=ledger.name,
        lines=lines,
        remote_id=f"autoca-{transaction.dedupe_hash[:32]}",
        reference=transaction.cheque_number,
    )


class UnclassifiedTransactionError(RuntimeError):
    """A transaction reached the exporter without a ledger."""


def ledger_master_group(group: str) -> str:
    """The Tally group name for a :class:`~classify.models.LedgerGroup` value."""
    return dict(LedgerGroup.choices).get(group, "Suspense A/c")
