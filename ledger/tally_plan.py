"""What a parsed Tally voucher becomes in the books. Pure: the chart arrives as :class:`Facts`, never the ORM.

The lines are **never rebuilt**. The books must equal Tally's, so a voucher is written with exactly the lines it had and the
bill's figures are *derived* from them. Where they cannot be derived (the lines do not tie to a taxable value, tax and
round-off), the voucher is still written -- the money is right -- and the bill is left out with a note.
"""

from __future__ import annotations

from dataclasses import dataclass

from classify.models import LedgerGroup as G
from ledger.models import BillKind, EntryKind, VoucherType
from ledger.tally_parse import normal_name
from ledger.tally_vouchers import ParsedVoucher

_TYPES = {
    "sales": VoucherType.SALES,
    "purchase": VoucherType.PURCHASE,
    "credit note": VoucherType.CREDIT_NOTE,
    "debit note": VoucherType.DEBIT_NOTE,
    "journal": VoucherType.JOURNAL,
    "payment": VoucherType.PAYMENT,
    "receipt": VoucherType.RECEIPT,
    "contra": VoucherType.CONTRA,
}
# kind of bill, the group of the party's ledger, and the side the party line is on (+1 debit, -1 credit): a sale debits the
# customer, a purchase credits the supplier, a credit note credits the customer, a debit note debits the supplier.
_BILL = {
    VoucherType.SALES: (BillKind.SALES, G.DEBTOR, +1),
    VoucherType.CREDIT_NOTE: (BillKind.CREDIT_NOTE, G.DEBTOR, -1),
    VoucherType.PURCHASE: (BillKind.PURCHASE, G.CREDITOR, -1),
    VoucherType.DEBIT_NOTE: (BillKind.DEBIT_NOTE, G.CREDITOR, +1),
}
_ROUND_OFF = ("round off", "rounding", "round-off", "rounded off")


@dataclass(frozen=True)
class Facts:
    #: normal_name(ledger name) -> LedgerGroup value, for every ledger in the chart.
    groups: dict[str, str]
    #: normal_name of the ledgers that are bank accounts.
    bank_ledgers: frozenset[str]


@dataclass(frozen=True)
class BillFigures:
    kind: str
    party_ledger: str
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    igst_paise: int
    cess_paise: int
    #: Signed: positive when the voucher rounds up.
    round_off_paise: int
    total_paise: int


@dataclass(frozen=True)
class Planned:
    voucher: ParsedVoucher
    voucher_type: str
    entry_kind: str
    bill: BillFigures | None
    note: str = ""


@dataclass(frozen=True)
class Skip:
    voucher: ParsedVoucher
    reason: str


def plan_voucher(v: ParsedVoucher, facts: Facts) -> Planned | Skip:
    vtype = _TYPES.get(normal_name(v.tally_type))
    if vtype is None:
        return Skip(v, "This voucher type is not imported.")
    for line in v.lines:
        if normal_name(line.ledger) not in facts.groups:
            return Skip(v, f"The ledger {line.ledger!r} is not in the client's chart. Import the masters first.")
    if len(v.lines) < 2:
        return Skip(v, "The voucher has fewer than two lines.")
    if any(line.signed_paise == 0 for line in v.lines):
        return Skip(v, "The voucher has a line with no amount.")
    if sum(line.signed_paise for line in v.lines) != 0:
        return Skip(v, "The voucher does not balance.")

    if vtype in (VoucherType.PAYMENT, VoucherType.RECEIPT, VoucherType.CONTRA):
        if any(normal_name(line.ledger) in facts.bank_ledgers for line in v.lines):
            return Skip(v, "Bank vouchers are imported in a later release.")
        return Planned(v, vtype, EntryKind.JOURNAL, None)
    if vtype == VoucherType.JOURNAL:
        return Planned(v, vtype, EntryKind.JOURNAL, None)
    return _invoice(v, vtype, facts)


def _party_line(v: ParsedVoucher, facts: Facts, side: str):
    flagged = [line for line in v.lines if line.is_party]
    candidates = flagged or [line for line in v.lines if v.party and normal_name(line.ledger) == normal_name(v.party)]
    candidates = [line for line in candidates if facts.groups.get(normal_name(line.ledger)) == side]
    return candidates[0] if len(candidates) == 1 else None


def _invoice(v: ParsedVoucher, vtype: str, facts: Facts) -> Planned | Skip:
    kind, side, expected = _BILL[vtype]
    party = _party_line(v, facts, side)
    if party is None:
        # A cash sale, or a voucher with no single party: written as a plain voucher.
        return Planned(v, vtype, EntryKind.VOUCHER, None)
    if (party.signed_paise > 0) != (expected > 0):
        word = {VoucherType.SALES: "sale", VoucherType.PURCHASE: "purchase"}.get(vtype, vtype.lower())
        return Skip(v, f"The party line is on the wrong side for a {word}.")
    if not (v.number or v.reference):
        return Planned(v, vtype, EntryKind.VOUCHER, None, note="No invoice number, so no bill was made.")

    taxable = cgst = sgst = igst = cess = round_off = 0
    for line in v.lines:
        if line is party:
            continue
        key = normal_name(line.ledger)
        taxes = facts.groups[key] == G.DUTIES_AND_TAXES
        # Positive when the line adds to what the party carries: it sits on the side opposite the party's.
        amount = -line.signed_paise * expected
        if taxes and "cgst" in key:
            cgst += amount
        elif taxes and ("sgst" in key or "utgst" in key):
            sgst += amount
        elif taxes and "igst" in key:
            igst += amount
        elif taxes and "cess" in key:
            cess += amount
        elif key in _ROUND_OFF:
            round_off += amount
        else:
            taxable += amount
    total = abs(party.signed_paise)
    ties = taxable > 0 and min(cgst, sgst, igst, cess) >= 0 and taxable + cgst + sgst + igst + cess + round_off == total
    if not ties:
        return Planned(
            v, vtype, EntryKind.VOUCHER, None, note="The lines do not tie to a taxable value, tax and round-off, so no bill was made."
        )
    return Planned(v, vtype, EntryKind.VOUCHER, BillFigures(kind, party.ledger, taxable, cgst, sgst, igst, cess, round_off, total))
