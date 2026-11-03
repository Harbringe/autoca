"""Drafts of the e-invoice (IRP) and e-way bill (bulk upload) JSON for a booked sales invoice or credit note.

The books hold the invoice's value and tax, the parties' names and GSTINs, the client's address as text and, where the invoice was read,
its item lines with HSN. They do not hold a structured address or pincode for either side, the transport details of the goods, or whether
the client's turnover brings it under e-invoicing. So these are drafts: the JSON is filled in as far as the books go, what is still
needed is listed under ``missing``, and a person supplies it before the file is uploaded. Nothing is sent to any portal.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

from gst.models import GstRegistration
from ledger.inventory import parse_quantity
from ledger.invoice_intake import fields_of
from ledger.models import Bill, BillKind, InvoiceReading

EWAY_THRESHOLD_PAISE = 50_000_00
EINVOICE_TURNOVER_NOTE = (
    "E-invoicing applies to a taxpayer whose aggregate turnover has been over Rs 5 crore in any year since 2017-18. The books cannot "
    "say that, so check it before using this."
)
DOC_TYPES = {BillKind.SALES: "INV", BillKind.CREDIT_NOTE: "CRN", BillKind.DEBIT_NOTE: "DBN"}


def _rs(paise: int) -> float:
    return float(Decimal(paise) / 100)


def _date(day: datetime.date) -> str:
    return day.strftime("%d/%m/%Y")


def _rate(taxable: int, igst: int, cgst: int, sgst: int) -> float:
    if not taxable:
        return 0.0
    return round((igst + cgst + sgst) * 200 / taxable) / 2


def _items(client, bill: Bill) -> tuple[list[dict], bool]:
    """The invoice's lines with the bill's tax spread over them by value; ``True`` when they came from the invoice itself."""
    reading = InvoiceReading.objects.filter(firm_id=client.firm_id, client=client, bill_id=bill.pk).first()
    lines = [line for line in ((fields_of(reading).get("items") or []) if reading else []) if line.get("amount_paise")]
    total = sum(line["amount_paise"] for line in lines)
    if not lines or not total:
        return [{"desc": "Goods or services as per the invoice", "hsn": "", "qty": None, "unit": "", "taxable": bill.taxable_paise}], False
    out, left = [], {"taxable": bill.taxable_paise}
    for i, line in enumerate(lines):
        last = i == len(lines) - 1
        taxable = left["taxable"] if last else round(bill.taxable_paise * line["amount_paise"] / total)
        left["taxable"] -= taxable
        out.append(
            {
                "desc": str(line.get("description") or "Item")[:300], "hsn": str(line.get("hsn_sac") or "").strip(),
                "qty": parse_quantity(line.get("quantity")), "unit": str(line.get("unit") or "").strip().upper()[:8], "taxable": taxable,
            }
        )
    return out, True


def _split(bill: Bill, items: list[dict]) -> list[dict]:
    """Each item's tax: the bill's tax by head, in proportion to the item's taxable value, the last item taking what is left."""
    left = {h: getattr(bill, f"{h}_paise") for h in ("igst", "cgst", "sgst", "cess")}
    for i, item in enumerate(items):
        last = i == len(items) - 1
        for h in left:
            share = left[h] if last else round(getattr(bill, f"{h}_paise") * item["taxable"] / bill.taxable_paise) if bill.taxable_paise else 0
            item[h] = share
            if not last:
                left[h] -= share
    return items


def _seller(client, bill: Bill):
    regs = list(GstRegistration.objects.filter(firm_id=client.firm_id, client=client, is_active=True))
    match = next((r for r in regs if r.gstin_hash == bill.own_gstin_hash), None) if bill.own_gstin_hash else None
    return match or (regs[0] if regs else None)


def draft(client, bill: Bill, details: dict | None = None) -> dict:
    """``{"eligible", "note", "e_invoice": {"json", "missing"}, "eway_bill": {"json", "missing", "required"}}`` for one bill."""
    details = details or {}
    if bill.kind not in DOC_TYPES:
        return {"eligible": False, "note": "E-invoices and e-way bills are for sales invoices, credit notes and debit notes.", "e_invoice": None, "eway_bill": None}
    party = bill.party
    reg = _seller(client, bill)
    seller_gstin = reg.gstin if reg else ""
    buyer_gstin = party.gstin
    items, from_invoice = _items(client, bill)
    items = _split(bill, items)
    doc_type = DOC_TYPES[bill.kind]
    seller_state = (seller_gstin[:2] if seller_gstin else "")
    buyer_state = buyer_gstin[:2] if buyer_gstin else ""

    missing = []
    if not seller_gstin:
        missing.append("The client's GSTIN: no active GST registration is recorded.")
    if not buyer_gstin:
        missing.append(f"{party.canonical_name} has no GSTIN: e-invoices are for supplies to registered businesses.")
    if not (details.get("seller_address") or client.address):
        missing.append("The client's address.")
    if not details.get("seller_pin"):
        missing.append("The client's pincode.")
    if not details.get("seller_place"):
        missing.append("The client's place (city or town).")
    if not details.get("buyer_address"):
        missing.append(f"{party.canonical_name}'s address.")
    if not details.get("buyer_pin"):
        missing.append(f"{party.canonical_name}'s pincode.")
    if not details.get("buyer_place"):
        missing.append(f"{party.canonical_name}'s place (city or town).")
    if not from_invoice:
        missing.append("Item lines with HSN codes: the invoice has none read, so the draft has one line.")
    elif any(not i["hsn"] for i in items):
        missing.append("An HSN code on every item line.")

    total_tax = sum(getattr(bill, f"{h}_paise") for h in ("igst", "cgst", "sgst", "cess"))
    ei_items = []
    for n, item in enumerate(items, 1):
        qty = float(item["qty"]) if item["qty"] else 1
        ei_items.append(
            {
                "SlNo": str(n), "PrdDesc": item["desc"], "IsServc": "N", "HsnCd": item["hsn"], "Qty": qty, "Unit": item["unit"] or "OTH",
                "UnitPrice": round(_rs(item["taxable"]) / qty, 3), "TotAmt": _rs(item["taxable"]), "AssAmt": _rs(item["taxable"]),
                "GstRt": _rate(item["taxable"], item["igst"], item["cgst"], item["sgst"]),
                "IgstAmt": _rs(item["igst"]), "CgstAmt": _rs(item["cgst"]), "SgstAmt": _rs(item["sgst"]), "CesAmt": _rs(item["cess"]),
                "TotItemVal": _rs(item["taxable"] + item["igst"] + item["cgst"] + item["sgst"] + item["cess"]),
            }
        )
    e_invoice = {
        "Version": "1.1",
        "TranDtls": {"TaxSch": "GST", "SupTyp": "B2B", "RegRev": "Y" if bill.rcm else "N", "IgstOnIntra": "N"},
        "DocDtls": {"Typ": doc_type, "No": bill.reference, "Dt": _date(bill.bill_date)},
        "SellerDtls": {
            "Gstin": seller_gstin, "LglNm": client.name, "TrdNm": client.trade_name or client.name,
            "Addr1": (details.get("seller_address") or client.address or "")[:100], "Loc": details.get("seller_place", ""),
            "Pin": details.get("seller_pin", ""), "Stcd": seller_state,
        },
        "BuyerDtls": {
            "Gstin": buyer_gstin, "LglNm": party.canonical_name, "Pos": buyer_state, "Addr1": details.get("buyer_address", ""),
            "Loc": details.get("buyer_place", ""), "Pin": details.get("buyer_pin", ""), "Stcd": buyer_state,
        },
        "ItemList": ei_items,
        "ValDtls": {
            "AssVal": _rs(bill.taxable_paise), "CgstVal": _rs(bill.cgst_paise), "SgstVal": _rs(bill.sgst_paise), "IgstVal": _rs(bill.igst_paise),
            "CesVal": _rs(bill.cess_paise), "RndOffAmt": _rs(bill.round_off_paise), "TotInvVal": _rs(bill.taxable_paise + total_tax + bill.round_off_paise),
        },
    }

    required = bill.kind == BillKind.SALES and bill.total_paise > EWAY_THRESHOLD_PAISE
    eway_missing = []
    if not details.get("distance_km"):
        eway_missing.append("The distance in km.")
    if not details.get("vehicle_no") and not details.get("transporter_id"):
        eway_missing.append("A vehicle number, or the transporter's id to give it later.")
    eway_missing += [m for m in missing if any(word in m for word in ("pincode", "GSTIN", "place"))]
    mode = {"ROAD": 1, "RAIL": 2, "AIR": 3, "SHIP": 4}.get(str(details.get("mode", "ROAD")).upper(), 1)
    eway_items = [
        {
            "productName": i["desc"][:100], "productDesc": i["desc"][:100], "hsnCode": int(i["hsn"]) if i["hsn"].isdigit() else "",
            "quantity": float(i["qty"]) if i["qty"] else 1, "qtyUnit": i["unit"] or "OTH", "taxableAmount": _rs(i["taxable"]),
            "sgstRate": _rate(i["taxable"], 0, 0, i["sgst"]) if i["sgst"] else 0, "cgstRate": _rate(i["taxable"], 0, i["cgst"], 0) if i["cgst"] else 0,
            "igstRate": _rate(i["taxable"], i["igst"], 0, 0) if i["igst"] else 0, "cessRate": 0,
        }
        for i in items
    ]
    eway = {
        "version": "1.0.0621",
        "billLists": [
            {
                "userGstin": seller_gstin, "supplyType": "O", "subSupplyType": 1, "docType": {"INV": "INV", "CRN": "CNT", "DBN": "OTH"}[doc_type],
                "docNo": bill.reference, "docDate": _date(bill.bill_date),
                "fromGstin": seller_gstin, "fromTrdName": client.name, "fromAddr1": (details.get("seller_address") or client.address or "")[:120],
                "fromPlace": details.get("seller_place", ""), "fromPincode": details.get("seller_pin", ""), "fromStateCode": int(seller_state or 0), "actFromStateCode": int(seller_state or 0),
                "toGstin": buyer_gstin, "toTrdName": party.canonical_name, "toAddr1": details.get("buyer_address", ""), "toPlace": details.get("buyer_place", ""),
                "toPincode": details.get("buyer_pin", ""), "toStateCode": int(buyer_state or 0), "actToStateCode": int(buyer_state or 0),
                "totalValue": _rs(bill.taxable_paise), "cgstValue": _rs(bill.cgst_paise), "sgstValue": _rs(bill.sgst_paise), "igstValue": _rs(bill.igst_paise),
                "cessValue": _rs(bill.cess_paise), "totInvValue": _rs(bill.taxable_paise + total_tax + bill.round_off_paise),
                "transMode": mode, "transDistance": str(details.get("distance_km", 0)), "transporterName": details.get("transporter_name", ""),
                "transporterId": details.get("transporter_id", ""), "vehicleNo": str(details.get("vehicle_no", "")).replace(" ", "").upper(), "vehicleType": "R",
                "itemList": eway_items,
            }
        ],
    }
    return {
        "eligible": True,
        "note": EINVOICE_TURNOVER_NOTE,
        "e_invoice": {"json": e_invoice, "missing": missing},
        "eway_bill": {"json": eway, "missing": eway_missing, "required": required},
    }
