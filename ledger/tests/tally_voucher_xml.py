"""Synthetic Tally voucher exports for tests. No real company or client.

Shaped after the real "Import Data" voucher files Tally writes: ENVELOPE/BODY/IMPORTDATA/REQUESTDATA/TALLYMESSAGE/VOUCHER,
with LEDGERENTRIES.LIST children. Tally writes a debit as a negative AMOUNT and ISDEEMEDPOSITIVE=Yes.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET


def line(ledger, amount, *, party=False, bills=()):
    """``amount`` is in rupees, debit positive (the books' sign); the builder writes Tally's sign.

    ``bills`` are ``(name, billtype, rupees)`` bill allocations, e.g. ``("INV-1", "Agst Ref", 1180.0)``.
    """
    return {"ledger": ledger, "amount": amount, "party": party, "bills": bills}


def voucher(
    *, guid, vtype, number, date, lines, party="", narration="", reference="", gstin="", own_gstin="", cancelled=False, optional=False,
    items=(),
):
    return {
        "guid": guid, "vtype": vtype, "number": number, "date": date, "lines": lines, "party": party,
        "narration": narration, "reference": reference, "gstin": gstin, "own_gstin": own_gstin,
        "cancelled": cancelled, "optional": optional, "items": items,
    }


def vouchers_xml(vouchers, *, company="TEST CO") -> bytes:
    envelope = ET.Element("ENVELOPE")
    header = ET.SubElement(envelope, "HEADER")
    ET.SubElement(header, "TALLYREQUEST").text = "Import Data"
    body = ET.SubElement(envelope, "BODY")
    importdata = ET.SubElement(body, "IMPORTDATA")
    desc = ET.SubElement(ET.SubElement(importdata, "REQUESTDESC"), "STATICVARIABLES")
    ET.SubElement(desc, "SVCURRENTCOMPANY").text = company
    holder = ET.SubElement(ET.SubElement(importdata, "REQUESTDATA"), "TALLYMESSAGE")
    for v in vouchers:
        node = ET.SubElement(
            holder, "VOUCHER", {"VCHTYPE": v["vtype"], "ACTION": "Create", "OBJVIEW": "Accounting Voucher View"}
        )
        ET.SubElement(node, "DATE").text = v["date"]
        ET.SubElement(node, "GUID").text = v["guid"]
        ET.SubElement(node, "VOUCHERTYPENAME").text = v["vtype"]
        ET.SubElement(node, "VOUCHERNUMBER").text = v["number"]
        if v["party"]:
            ET.SubElement(node, "PARTYLEDGERNAME").text = v["party"]
        if v["gstin"]:
            ET.SubElement(node, "PARTYGSTIN").text = v["gstin"]
        if v["own_gstin"]:
            ET.SubElement(node, "CMPGSTIN").text = v["own_gstin"]
        if v["reference"]:
            ET.SubElement(node, "REFERENCE").text = v["reference"]
        if v["narration"]:
            ET.SubElement(node, "NARRATION").text = v["narration"]
        ET.SubElement(node, "ISCANCELLED").text = "Yes" if v["cancelled"] else "No"
        ET.SubElement(node, "ISOPTIONAL").text = "Yes" if v["optional"] else "No"
        # An item invoice: (stock item, ledger it is booked to, rupees with the books' sign), one allocation per item.
        for stock, ledger, rupees, *qty in v["items"]:
            stock_node = ET.SubElement(node, "ALLINVENTORYENTRIES.LIST")
            ET.SubElement(stock_node, "STOCKITEMNAME").text = stock
            if qty:
                ET.SubElement(stock_node, "BILLEDQTY").text = qty[0]
            ET.SubElement(stock_node, "AMOUNT").text = f"{-rupees:.2f}"
            alloc = ET.SubElement(stock_node, "ACCOUNTINGALLOCATIONS.LIST")
            ET.SubElement(alloc, "LEDGERNAME").text = ledger
            ET.SubElement(alloc, "AMOUNT").text = f"{-rupees:.2f}"
        for item in v["lines"]:
            entry = ET.SubElement(node, "LEDGERENTRIES.LIST")
            ET.SubElement(entry, "LEDGERNAME").text = item["ledger"]
            debit = item["amount"] > 0
            ET.SubElement(entry, "ISDEEMEDPOSITIVE").text = "Yes" if debit else "No"
            ET.SubElement(entry, "ISPARTYLEDGER").text = "Yes" if item["party"] else "No"
            ET.SubElement(entry, "AMOUNT").text = f"{-item['amount']:.2f}"
            for name, billtype, rupees in item["bills"]:
                alloc = ET.SubElement(entry, "BILLALLOCATIONS.LIST")
                ET.SubElement(alloc, "NAME").text = name
                ET.SubElement(alloc, "BILLTYPE").text = billtype
                ET.SubElement(alloc, "AMOUNT").text = f"{-rupees if debit else rupees:.2f}"
    return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)
