"""Synthetic Tally voucher exports for tests. No real company or client.

Shaped after the real "Import Data" voucher files Tally writes: ENVELOPE/BODY/IMPORTDATA/REQUESTDATA/TALLYMESSAGE/VOUCHER,
with LEDGERENTRIES.LIST children. Tally writes a debit as a negative AMOUNT and ISDEEMEDPOSITIVE=Yes.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET


def line(ledger, amount, *, party=False):
    """``amount`` is in rupees, debit positive (the books' sign); the builder writes Tally's sign."""
    return {"ledger": ledger, "amount": amount, "party": party}


def voucher(
    *, guid, vtype, number, date, lines, party="", narration="", reference="", gstin="", own_gstin="", cancelled=False, optional=False
):
    return {
        "guid": guid, "vtype": vtype, "number": number, "date": date, "lines": lines, "party": party,
        "narration": narration, "reference": reference, "gstin": gstin, "own_gstin": own_gstin,
        "cancelled": cancelled, "optional": optional,
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
        for item in v["lines"]:
            entry = ET.SubElement(node, "LEDGERENTRIES.LIST")
            ET.SubElement(entry, "LEDGERNAME").text = item["ledger"]
            debit = item["amount"] > 0
            ET.SubElement(entry, "ISDEEMEDPOSITIVE").text = "Yes" if debit else "No"
            ET.SubElement(entry, "ISPARTYLEDGER").text = "Yes" if item["party"] else "No"
            ET.SubElement(entry, "AMOUNT").text = f"{-item['amount']:.2f}"
    return ET.tostring(envelope, encoding="utf-8", xml_declaration=True)
