"""The working a GSTR-1 return is filled from, for one month, taken from the booked sales invoices and credit notes.

Tables: 4 (B2B, to registered parties), 5 (B2C large: unregistered, inter-state, invoice over 2.5 lakh), 7 (B2C other, by rate and
inter/intra-state), 9B (credit notes, registered and unregistered), 8 (exempt, nil-rated and non-GST, from the month's entries on the
GSTR-3B working), 12 (HSN summary, from the item lines of the invoices that have them) and 13 (documents issued).

What the books do not record: the place of supply, so the B2C figures are by rate and by inter/intra-state, not by state; the HSN
summary covers only invoices with item lines; export, SEZ and e-commerce supplies are not told apart from other sales. It writes nothing.
"""

from __future__ import annotations

from collections import defaultdict

from ledger import gstr3b
from ledger.models import Bill, BillKind, InvoiceReading

HEADS = ("igst", "cgst", "sgst", "cess")
B2CL_LIMIT_PAISE = 2_50_000 * 100


def _tax(bill: Bill) -> int:
    return sum(getattr(bill, f"{h}_paise") for h in HEADS)


def _rate(bill: Bill) -> str:
    """The GST rate an invoice is at, as a plain number of percent: tax over taxable value, to the nearest half percent."""
    if not bill.taxable_paise:
        return "0"
    pct = round((bill.igst_paise + bill.cgst_paise + bill.sgst_paise) * 200 / bill.taxable_paise) / 2
    return f"{pct:g}"


def _row(bill: Bill, factor: int = 1) -> dict:
    return {
        "number": bill.reference, "date": bill.bill_date.isoformat(), "party": bill.party.canonical_name, "gstin": bill.party.gstin,
        "value_paise": factor * bill.total_paise, "taxable_paise": factor * bill.taxable_paise, "rate": _rate(bill),
        **{f"{h}_paise": factor * getattr(bill, f"{h}_paise") for h in HEADS},
    }


def _sum(rows: list[dict]) -> dict:
    return {key: sum(r[key] for r in rows) for key in ("value_paise", "taxable_paise", *(f"{h}_paise" for h in HEADS))}


def _hsn(client, bills: list[Bill]) -> tuple[list[dict], int]:
    from ledger.inventory import parse_quantity
    from ledger.invoice_intake import fields_of

    readings = {r.bill_id: r for r in InvoiceReading.objects.filter(firm_id=client.firm_id, client=client, bill_id__in=[b.pk for b in bills])}
    by_hsn: dict[tuple[str, str], dict] = defaultdict(lambda: {"quantity": 0, "taxable_paise": 0, **{f"{h}_paise": 0 for h in HEADS}})
    without = 0
    for bill in bills:
        reading = readings.get(bill.pk)
        lines = [line for line in ((fields_of(reading).get("items") or []) if reading else []) if line.get("amount_paise")]
        total = sum(line["amount_paise"] for line in lines)
        if not lines or not total:
            without += 1
            continue
        factor = 1 if bill.kind == BillKind.SALES else -1
        for line in lines:
            row = by_hsn[(str(line.get("hsn_sac") or "").strip() or "—", str(line.get("unit") or "").strip())]
            share = line["amount_paise"] / total
            quantity = parse_quantity(line.get("quantity"))
            row["quantity"] += factor * float(quantity or 0)
            row["taxable_paise"] += factor * line["amount_paise"]
            for h in HEADS:
                row[f"{h}_paise"] += factor * round(getattr(bill, f"{h}_paise") * share)
    out = [{"hsn": hsn, "unit": unit, **{k: (round(v, 3) if k == "quantity" else v) for k, v in row.items()}} for (hsn, unit), row in sorted(by_hsn.items())]
    return out, without


def _documents(bills: list[Bill], kind: str, label: str) -> dict | None:
    mine = [b for b in bills if b.kind == kind]
    if not mine:
        return None
    numbers = sorted(b.reference for b in mine)
    return {"label": label, "from": numbers[0], "to": numbers[-1], "count": len(mine)}


def build(client, month: str) -> dict:
    start, end = gstr3b._bounds(month)
    bills = list(
        Bill.objects.filter(
            firm_id=client.firm_id, client=client, bill_date__range=(start, end), kind__in=(BillKind.SALES, BillKind.CREDIT_NOTE),
        ).select_related("party").order_by("bill_date", "reference")
    )
    b2b, b2cl, b2cs_rows, cdn_reg, cdn_unreg, untaxed = [], [], [], [], [], []
    for bill in bills:
        registered = bool(bill.party.gstin)
        if not _tax(bill):
            untaxed.append(bill)
            continue
        if bill.kind == BillKind.CREDIT_NOTE:
            (cdn_reg if registered else cdn_unreg).append(_row(bill, -1))
        elif registered:
            b2b.append(_row(bill))
        elif bill.igst_paise and bill.total_paise > B2CL_LIMIT_PAISE:
            b2cl.append(_row(bill))
        else:
            b2cs_rows.append(bill)
    grouped: dict[tuple[str, str], dict] = {}
    for bill in b2cs_rows:
        key = ("Inter-state" if bill.igst_paise else "Intra-state", _rate(bill))
        row = grouped.setdefault(key, {"supply": key[0], "rate": key[1], "taxable_paise": 0, **{f"{h}_paise": 0 for h in HEADS}})
        row["taxable_paise"] += bill.taxable_paise
        for h in HEADS:
            row[f"{h}_paise"] += getattr(bill, f"{h}_paise")
    b2cs = sorted(grouped.values(), key=lambda r: (r["supply"], float(r["rate"])))

    entries = gstr3b.read_entries(client, month)
    hsn, without_items = _hsn(client, [b for b in bills if _tax(b)])
    in_tables = sum(r["taxable_paise"] for r in b2b + b2cl + b2cs) - sum(-r["taxable_paise"] for r in cdn_reg + cdn_unreg)
    three_b = gstr3b.build(client, month)["outward_taxable"]["taxable_paise"]
    documents = [
        d for d in (_documents(bills, BillKind.SALES, "Invoices for outward supply"), _documents(bills, BillKind.CREDIT_NOTE, "Credit notes")) if d
    ]
    return {
        "month": month,
        "b2b": {"rows": b2b, "total": _sum(b2b)},
        "b2cl": {"rows": b2cl, "total": _sum(b2cl)},
        "b2cs": {"rows": b2cs, "total": {key: sum(r[key] for r in b2cs) for key in ("taxable_paise", *(f"{h}_paise" for h in HEADS))}},
        "credit_notes_registered": {"rows": cdn_reg, "total": _sum(cdn_reg)},
        "credit_notes_unregistered": {"rows": cdn_unreg, "total": _sum(cdn_unreg)},
        "exempt_nil_non_gst": {
            "zero_rated_paise": entries["zero_rated_paise"], "exempt_paise": entries["exempt_paise"], "non_gst_paise": entries["non_gst_paise"],
            "untaxed_sales_paise": sum((1 if b.kind == BillKind.SALES else -1) * b.taxable_paise for b in untaxed),
        },
        "hsn": hsn,
        "hsn_bills_without_items": without_items,
        "documents": documents,
        "agrees_with_3b": in_tables == three_b,
        "taxable_in_tables_paise": in_tables,
        "taxable_in_3b_paise": three_b,
    }
