"""The working a GSTR-3B return is filled from, for one month.

What the invoices give: outward taxable supplies (3.1(a), sales and credit notes that carry tax), reverse-charge inward supplies
(3.1(d)), input tax credit (4(A)(5), 4(A)(3)) and the tax liability. What no invoice holds is entered per month on the client
(``read_entries``): exempt, nil-rated, zero-rated and non-GST supplies (3.1(b), (c), (e) and 5), credit reversed (4(B)), interest and
late fee (5.1), and an opening credit where the month's carried-forward credit is to be put right.

Credit carries forward from April of the year, month by month. Within a month it is applied as the law orders (section 49A): IGST
credit against IGST, then CGST, then SGST; CGST credit against CGST, then IGST; SGST credit against SGST, then IGST; cess credit only
against cess. Reverse-charge tax, interest and late fee are paid in cash, never from credit. It writes nothing.
"""

from __future__ import annotations

import datetime
import re

from ledger.models import Bill, BillKind

HEADS = ("igst", "cgst", "sgst", "cess")
_AMOUNTS = (
    "zero_rated_paise", "exempt_paise", "non_gst_paise", "inward_exempt_paise", "late_fee_paise",
    *(f"{kind}_{h}_paise" for kind in ("itc_reversed", "interest", "opening_credit") for h in HEADS),
)
MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _amount(value) -> int:
    if value is None or isinstance(value, bool):
        return 0
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def read_entries(client, month: str) -> dict:
    """The month's entered figures, always in full shape; ``opening_credit_*`` is None where nothing was entered."""
    stored = (client.gst_return_entries or {}).get(month) if isinstance(client.gst_return_entries, dict) else None
    stored = stored if isinstance(stored, dict) else {}
    out = {key: _amount(stored.get(key)) for key in _AMOUNTS if not key.startswith("opening_credit")}
    for h in HEADS:
        key = f"opening_credit_{h}_paise"
        out[key] = _amount(stored[key]) if stored.get(key) is not None else None
    return out


def normalise_entries(body: dict) -> dict:
    out = {key: _amount(body.get(key)) for key in _AMOUNTS if not key.startswith("opening_credit")}
    for h in HEADS:
        key = f"opening_credit_{h}_paise"
        if body.get(key) is not None:
            out[key] = _amount(body.get(key))
    return out


def _zero() -> dict:
    return {"taxable_paise": 0, **{f"{h}_paise": 0 for h in HEADS}}


def _add(row: dict, bill: Bill, factor: int) -> None:
    row["taxable_paise"] += factor * bill.taxable_paise
    for head in HEADS:
        row[f"{head}_paise"] += factor * getattr(bill, f"{head}_paise")


def _bounds(month: str) -> tuple[datetime.date, datetime.date]:
    year, mon = (int(part) for part in month.split("-"))
    start = datetime.date(year, mon, 1)
    return start, (start.replace(day=28) + datetime.timedelta(days=4)).replace(day=1) - datetime.timedelta(days=1)


def _figures(client, month: str) -> dict:
    """The invoices' figures for one month, before any credit is applied."""
    start, end = _bounds(month)
    bills = Bill.objects.filter(
        firm_id=client.firm_id, client=client, bill_date__range=(start, end),
        kind__in=(BillKind.SALES, BillKind.CREDIT_NOTE, BillKind.PURCHASE, BillKind.DEBIT_NOTE),
    )
    outward, reverse, itc, itc_reverse = _zero(), _zero(), _zero(), _zero()
    untaxed = 0
    counts = {"sales": 0, "purchases": 0, "reverse_charge": 0}
    for bill in bills:
        tax = sum(getattr(bill, f"{h}_paise") for h in HEADS)
        if bill.kind in (BillKind.SALES, BillKind.CREDIT_NOTE):
            factor = 1 if bill.kind == BillKind.SALES else -1
            if tax:
                _add(outward, bill, factor)
            else:
                untaxed += factor * bill.taxable_paise
            counts["sales"] += 1
        elif bill.rcm:
            factor = 1 if bill.kind == BillKind.PURCHASE else -1
            _add(reverse, bill, factor)
            _add(itc_reverse, bill, factor)
            counts["reverse_charge"] += 1
        else:
            _add(itc, bill, 1 if bill.kind == BillKind.PURCHASE else -1)
            counts["purchases"] += 1
    return {"outward": outward, "reverse": reverse, "itc": itc, "itc_reverse": itc_reverse, "untaxed": untaxed, "counts": counts}


def _apply_credit(liability: dict, credit: dict) -> tuple[dict, dict, dict]:
    """``(paid by credit, still to pay, credit left)`` per head, in the order section 49A sets."""
    liability, credit = dict(liability), dict(credit)
    paid = dict.fromkeys(HEADS, 0)

    def use(pay_head: str, from_head: str) -> None:
        amount = min(liability[pay_head], credit[from_head])
        liability[pay_head] -= amount
        credit[from_head] -= amount
        paid[pay_head] += amount

    for pay_head, sources in (("igst", ("igst", "cgst", "sgst")), ("cgst", ("cgst", "igst")), ("sgst", ("sgst", "igst")), ("cess", ("cess",))):
        for source in sources:
            use(pay_head, source)
    return paid, liability, credit


def _month_result(client, month: str, carry_in: dict) -> dict:
    f = _figures(client, month)
    e = read_entries(client, month)
    opening = {h: (e[f"opening_credit_{h}_paise"] if e[f"opening_credit_{h}_paise"] is not None else carry_in[h]) for h in HEADS}
    credit = {h: opening[h] + f["itc"][f"{h}_paise"] + f["itc_reverse"][f"{h}_paise"] - e[f"itc_reversed_{h}_paise"] for h in HEADS}
    # A reversal can exceed what there is: the shortfall is not negative credit, it is tax to pay.
    short = {h: max(-credit[h], 0) for h in HEADS}
    credit = {h: max(credit[h], 0) for h in HEADS}
    liability = {h: max(f["outward"][f"{h}_paise"], 0) for h in HEADS}
    paid, left_to_pay, credit_left = _apply_credit(liability, credit)
    cash = {h: left_to_pay[h] + max(f["reverse"][f"{h}_paise"], 0) + short[h] + e[f"interest_{h}_paise"] for h in HEADS}
    return {
        "figures": f, "entries": e, "opening_credit": opening, "credit_available": credit,
        "liability": liability, "paid_by_credit": paid, "paid_in_cash": cash, "carry_forward": credit_left,
    }


def build(client, month: str) -> dict:
    """``month`` is ``YYYY-MM``. Credit is carried from April of that year."""
    year, mon = (int(part) for part in month.split("-"))
    fy_start = year if mon >= 4 else year - 1
    carry = dict.fromkeys(HEADS, 0)
    result = None
    for m in (4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3):
        label = f"{fy_start if m >= 4 else fy_start + 1}-{m:02d}"
        result = _month_result(client, label, carry)
        carry = result["carry_forward"]
        if label == month:
            break
    assert result is not None
    f, e = result["figures"], result["entries"]
    untaxed_entered = e["zero_rated_paise"] + e["exempt_paise"] + e["non_gst_paise"]
    return {
        "month": month,
        "outward_taxable": f["outward"],
        "zero_rated_paise": e["zero_rated_paise"],
        "exempt_nil_paise": e["exempt_paise"],
        "non_gst_outward_paise": e["non_gst_paise"],
        "inward_reverse_charge": f["reverse"],
        "inward_exempt_paise": e["inward_exempt_paise"],
        "itc_all_other": f["itc"],
        "itc_reverse_charge": f["itc_reverse"],
        "itc_reversed": {f"{h}_paise": e[f"itc_reversed_{h}_paise"] for h in HEADS},
        "opening_credit": {f"{h}_paise": result["opening_credit"][h] for h in HEADS},
        "liability": {f"{h}_paise": result["liability"][h] for h in HEADS},
        "paid_by_credit": {f"{h}_paise": result["paid_by_credit"][h] for h in HEADS},
        "paid_in_cash": {f"{h}_paise": result["paid_in_cash"][h] for h in HEADS},
        "interest": {f"{h}_paise": e[f"interest_{h}_paise"] for h in HEADS},
        "late_fee_paise": e["late_fee_paise"],
        "carry_forward": {f"{h}_paise": result["carry_forward"][h] for h in HEADS},
        "untaxed_sales_paise": f["untaxed"],
        "untaxed_unexplained_paise": max(f["untaxed"] - untaxed_entered, 0),
        "counts": f["counts"],
        "entries": e,
    }
