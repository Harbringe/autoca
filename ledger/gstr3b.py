"""The working a GSTR-3B return is filled from, for one month, taken from the booked invoices.

Table 3.1(a): outward taxable supplies (sales less credit notes). Table 3.1(d): inward supplies on reverse charge. Table 4: input tax
credit on purchases less debit notes (4(A)(5)) and on reverse-charge purchases (4(A)(3)). Table 6.1: tax payable, which is the output
tax and the reverse-charge tax less the credit.

Not covered, because the books do not record it: zero-rated and exempt supplies, nil-rated and non-GST inward supplies, ITC that is
reversed or ineligible, interest and late fee, and credit already carried forward. A person adds those before filing. It writes nothing.
"""

from __future__ import annotations

import datetime

from ledger.models import Bill, BillKind

HEADS = ("igst", "cgst", "sgst", "cess")


def _zero() -> dict:
    return {"taxable_paise": 0, **{f"{h}_paise": 0 for h in HEADS}}


def _add(row: dict, bill: Bill, factor: int) -> None:
    row["taxable_paise"] += factor * bill.taxable_paise
    for head in HEADS:
        row[f"{head}_paise"] += factor * getattr(bill, f"{head}_paise")


def build(client, month: str) -> dict:
    """``month`` is ``YYYY-MM``."""
    year, mon = (int(part) for part in month.split("-"))
    start = datetime.date(year, mon, 1)
    end = (start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)
    bills = Bill.objects.filter(
        firm_id=client.firm_id, client=client, bill_date__range=(start, end),
        kind__in=(BillKind.SALES, BillKind.CREDIT_NOTE, BillKind.PURCHASE, BillKind.DEBIT_NOTE),
    )
    outward, reverse, itc, itc_reverse = _zero(), _zero(), _zero(), _zero()
    counts = {"sales": 0, "purchases": 0, "reverse_charge": 0}
    for bill in bills:
        if bill.kind in (BillKind.SALES, BillKind.CREDIT_NOTE):
            _add(outward, bill, 1 if bill.kind == BillKind.SALES else -1)
            counts["sales"] += 1
        elif bill.rcm:
            _add(reverse, bill, 1 if bill.kind == BillKind.PURCHASE else -1)
            _add(itc_reverse, bill, 1 if bill.kind == BillKind.PURCHASE else -1)
            counts["reverse_charge"] += 1
        else:
            _add(itc, bill, 1 if bill.kind == BillKind.PURCHASE else -1)
            counts["purchases"] += 1
    payable = {f"{h}_paise": outward[f"{h}_paise"] + reverse[f"{h}_paise"] - itc[f"{h}_paise"] - itc_reverse[f"{h}_paise"] for h in HEADS}
    return {
        "month": month,
        "outward_taxable": outward,
        "inward_reverse_charge": reverse,
        "itc_all_other": itc,
        "itc_reverse_charge": itc_reverse,
        "payable": payable,
        "counts": counts,
        "not_covered": [
            "Zero-rated, exempt and nil-rated supplies",
            "ITC reversed or ineligible",
            "Interest and late fee",
            "Credit carried forward from earlier months",
        ],
    }
