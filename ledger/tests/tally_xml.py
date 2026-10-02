"""Synthetic Tally masters files for tests. No real data, and no real company.

The shapes follow what the import design remembers of Tally's export, which has
never been checked against a real file (see the UNVERIFIED marks in
``ledger/tally_parse.py``); a real sample may force changes here as well.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET

from openpyxl import Workbook


def ledger(name, parent, opening=None, *, alias=None, action=None):
    return {"name": name, "parent": parent, "opening": opening, "alias": alias, "action": action}


def group(name, parent):
    return {"name": name, "parent": parent}


def masters_tree(ledgers, groups=(), *, books_from=None, wrap="body") -> ET.Element:
    envelope = ET.Element("ENVELOPE")
    if wrap == "body":
        container = ET.SubElement(ET.SubElement(envelope, "BODY"), "DATA")
        if books_from:
            ET.SubElement(ET.SubElement(container, "COMPANY"), "BOOKSFROM").text = books_from
    else:
        container = ET.SubElement(ET.SubElement(envelope, "BODY"), "IMPORTDATA")
        container = ET.SubElement(container, "REQUESTDATA")
    holder = ET.SubElement(container, "TALLYMESSAGE")
    for g in groups:
        node = ET.SubElement(holder, "GROUP", {"NAME": g["name"]})
        ET.SubElement(node, "PARENT").text = g["parent"]
    for item in ledgers:
        attrs = {"NAME": item["name"]}
        if item["action"]:
            attrs["ACTION"] = item["action"]
        node = ET.SubElement(holder, "LEDGER", attrs)
        ET.SubElement(node, "PARENT").text = item["parent"]
        if item["opening"] is not None:
            ET.SubElement(node, "OPENINGBALANCE").text = item["opening"]
        if item["alias"]:
            names = ET.SubElement(ET.SubElement(node, "LANGUAGENAME.LIST"), "NAME.LIST")
            ET.SubElement(names, "NAME").text = item["name"]
            ET.SubElement(names, "NAME").text = item["alias"]
    return envelope


def masters_xml(ledgers, groups=(), *, encoding="utf-8", declaration=True, **kw) -> bytes:
    """``encoding`` is the real one; the declaration says the same, as Tally's does.

    ``utf-16`` gets a byte-order mark, ``utf-16-le`` and ``utf-16-be`` do not.
    """
    text = ET.tostring(masters_tree(ledgers, groups, **kw), encoding="unicode")
    if declaration:
        label = "UTF-16" if encoding.startswith("utf-16") else "UTF-8"
        text = f'<?xml version="1.0" encoding="{label}"?>\n{text}'
    return text.encode(encoding)


def csv_bytes(rows, *, encoding="utf-8") -> bytes:
    def quote(cell):
        text = "" if cell is None else str(cell)
        return '"' + text.replace('"', '""') + '"' if any(c in text for c in ',"\n') else text

    return "\r\n".join(",".join(quote(c) for c in row) for row in rows).encode(encoding)


def xlsx_bytes(rows, *, sheet_title="Ledgers") -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_title
    for row in rows:
        sheet.append(list(row))
    out = io.BytesIO()
    workbook.save(out)
    return out.getvalue()
