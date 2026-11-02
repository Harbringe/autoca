"""Does the GST on the invoices agree with the GST in the books?

Every sales and purchase invoice carries its tax by head (CGST, SGST, IGST, Cess) and posts it to an Input or Output ledger. Nothing
forces the two to stay together: a ledger edited by hand, a journal posted straight to a GST ledger, an invoice booked with the wrong
tax. This reads both for a financial year and names the difference per head, with the month-by-month working a 3B return starts from.
It writes nothing.

Reverse-charge purchases post to their own RCM ledgers and are left out of both sides, as the return treats them separately.
"""

from __future__ import annotations

import datetime
import re

from classify.models import LedgerGroup
from ledger.models import Bill, BillKind
from ledger.reports import _balances

HEADS = ("cgst", "sgst", "igst", "cess")
LABELS = {"cgst": "CGST", "sgst": "SGST", "igst": "IGST", "cess": "Cess"}
_LEDGER = re.compile(r"\b(input|output)\b.*\b(cgst|sgst|igst|cess)\b|\b(cgst|sgst|igst|cess)\b.*\b(input|output)\b", re.IGNORECASE)


def _side_and_head(name: str) -> tuple[str, str] | None:
    """``("output", "cgst")`` for "Output CGST @9%", or None for a ledger that is not an input/output GST ledger (RCM ones too)."""
    if "rcm" in name.lower() or "reverse" in name.lower() or not _LEDGER.search(name):
        return None
    lowered = name.lower()
    side = "input" if "input" in lowered else "output"
    head = next(h for h in HEADS if h in lowered)
    return side, head


def build(client, fy: int) -> dict:
    start, end = datetime.date(fy, 4, 1), datetime.date(fy + 1, 3, 31)
    bills = Bill.objects.filter(
        firm_id=client.firm_id, client=client, bill_date__range=(start, end), rcm=False,
        kind__in=(BillKind.SALES, BillKind.CREDIT_NOTE, BillKind.PURCHASE, BillKind.DEBIT_NOTE),
    )
    sign = {BillKind.SALES: ("output", 1), BillKind.CREDIT_NOTE: ("output", -1), BillKind.PURCHASE: ("input", 1), BillKind.DEBIT_NOTE: ("input", -1)}
    from_bills = {(s, h): 0 for s in ("output", "input") for h in HEADS}
    months: dict[str, dict] = {}
    for bill in bills:
        side, factor = sign[bill.kind]
        month = months.setdefault(
            bill.bill_date.strftime("%Y-%m"),
            {"month": bill.bill_date.strftime("%Y-%m"), "outward_taxable_paise": 0, "inward_taxable_paise": 0, **{f"output_{h}_paise": 0 for h in HEADS}, **{f"input_{h}_paise": 0 for h in HEADS}},
        )
        month[f"{'outward' if side == 'output' else 'inward'}_taxable_paise"] += factor * bill.taxable_paise
        for head in HEADS:
            amount = factor * getattr(bill, f"{head}_paise")
            from_bills[(side, head)] += amount
            month[f"{side}_{head}_paise"] += amount

    rows, _ = _balances(client, fy)
    in_books = {(s, h): 0 for s in ("output", "input") for h in HEADS}
    for row in rows:
        if row.group != LedgerGroup.DUTIES_AND_TAXES:
            continue
        found = _side_and_head(row.name)
        if found is None:
            continue
        side, head = found
        moved = row.credit_paise - row.debit_paise if side == "output" else row.debit_paise - row.credit_paise
        in_books[(side, head)] += moved

    heads = []
    for side in ("output", "input"):
        for head in HEADS:
            bills_paise, books_paise = from_bills[(side, head)], in_books[(side, head)]
            if not bills_paise and not books_paise:
                continue
            heads.append(
                {
                    "side": side, "head": LABELS[head], "invoices_paise": bills_paise, "books_paise": books_paise,
                    "difference_paise": books_paise - bills_paise,
                }
            )
    net = {
        "output_paise": sum(v for (s, _), v in from_bills.items() if s == "output"),
        "input_paise": sum(v for (s, _), v in from_bills.items() if s == "input"),
    }
    net["payable_paise"] = net["output_paise"] - net["input_paise"]
    return {
        "fy": fy,
        "agrees": all(h["difference_paise"] == 0 for h in heads),
        "heads": heads,
        "months": [months[k] for k in sorted(months)],
        "net": net,
    }
