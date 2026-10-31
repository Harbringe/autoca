"""Reading a Tally vouchers export. Nothing here touches the database.

The same hostility rules as ``ledger.tally_parse`` (read its docstring first): defusedxml with DTDs, entities and external
references forbidden, illegal XML characters stripped, size and count caps, formula-looking names skipped with a reason.
A problem with one voucher skips that voucher with a reason and the file goes on; a problem with the file as a whole is
a :class:`TallyParseError` written for the person who uploaded it.

**Sign.** Tally writes a debit as a negative AMOUNT. ``core.money.to_paise`` reads that as Tally's sign, so each amount is
negated once here and leaves this module debit-positive, like the rest of the system.
"""

from __future__ import annotations

import datetime
import io
import json
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from core.money import MoneyError, to_paise
from ledger.tally_parse import (
    SkippedLine,
    TallyParseError,
    TallyTooLargeError,
    _BadText,
    _decode,
    _local,
    _strip_illegal_xml,
    _tally_date,
    clean_text,
)

MAX_VOUCHERS = 200_000
MAX_LINES_PER_VOUCHER = 500
MAX_NARRATION = 2_000
MAX_INVENTORY_ALLOCATIONS = 5_000
#: How deep a voucher may nest in a JSON export. A real one is about six levels; this only stops a hostile file.
MAX_JSON_DEPTH = 24
#: Where an item invoice keeps the sales or purchase head: inside each stock item, not among the voucher's own ledger lines.
_INVENTORY_TAGS = ("ALLINVENTORYENTRIES.LIST", "INVENTORYENTRIES.LIST", "INVENTORYENTRIESIN.LIST", "INVENTORYENTRIESOUT.LIST")


@dataclass(frozen=True)
class VoucherLine:
    ledger: str
    signed_paise: int
    is_party: bool
    #: Tally's bill allocations on this line: (bill name, "Agst Ref" / "New Ref" / "On Account" / "Advance", paise, always positive).
    bills: tuple[tuple[str, str, int], ...] = ()


@dataclass(frozen=True)
class VoucherItem:
    """One stock item line of an item invoice: what moved, how much, and what it was booked at."""

    name: str
    unit: str
    #: A decimal as text (a quantity has up to three places); the caller turns it into a ``Decimal``.
    quantity: str
    value_paise: int


@dataclass(frozen=True)
class ParsedVoucher:
    ordinal: int
    guid: str
    tally_type: str
    number: str
    date: datetime.date
    party: str
    narration: str
    reference: str
    party_gstin: str
    own_gstin: str
    lines: tuple[VoucherLine, ...]
    items: tuple[VoucherItem, ...] = ()


@dataclass
class ParsedVouchers:
    company: str = ""
    companies: set[str] = field(default_factory=set)
    vouchers: list[ParsedVoucher] = field(default_factory=list)
    skipped: list[SkippedLine] = field(default_factory=list)
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None


def parse_vouchers(data: bytes, filename: str, *, max_bytes: int) -> ParsedVouchers:
    if len(data) > max_bytes:
        raise TallyTooLargeError(f"This file is larger than {max_bytes // (1024 * 1024)} MB, which is more than an import takes.")
    name = filename.lower()
    if not name.endswith((".xml", ".json")):
        raise TallyParseError("A vouchers export must be a Tally XML file (.xml) or a Tally JSON file (.json).")
    text = _strip_illegal_xml(_decode(data))
    parsed = ParsedVouchers()
    ordinal = 0

    def take(element) -> None:
        nonlocal ordinal
        ordinal += 1
        if ordinal > MAX_VOUCHERS:
            raise TallyParseError(f"This file has more than {MAX_VOUCHERS:,} vouchers. Export a shorter period.")
        _read_voucher(element, ordinal, parsed)
        element.clear()

    if name.endswith(".json"):
        for element in _json_vouchers(text):
            take(element)
    else:
        _read_xml(text, parsed, take)
    if ordinal == 0:
        raise TallyParseError("No vouchers were found in this file. Export the vouchers (not the masters or a report) from Tally.")
    dates = [v.date for v in parsed.vouchers]
    if dates:
        parsed.date_from, parsed.date_to = min(dates), max(dates)
    return parsed


def _read_xml(text: str, parsed: ParsedVouchers, take) -> None:
    from defusedxml import DefusedXmlException
    from defusedxml.ElementTree import ParseError, iterparse

    try:
        for _event, element in iterparse(
            io.BytesIO(_without_declaration(text).encode("utf-8")),
            events=("end",),
            forbid_dtd=True,
            forbid_entities=True,
            forbid_external=True,
        ):
            tag = _local(element.tag)
            if tag == "SVCURRENTCOMPANY":
                name = " ".join((element.text or "").split())
                if name:
                    parsed.companies.add(name)
                    parsed.company = parsed.company or name
            elif tag == "VOUCHER":
                take(element)
    except DefusedXmlException as exc:
        raise TallyParseError(
            "This file contains definitions (a DTD or entities) that an export from Tally never has, so it was not read."
        ) from exc
    except ParseError as exc:
        raise TallyParseError("This file is not well-formed XML, so it cannot be read. Export the vouchers from Tally again.") from exc


def _json_vouchers(text: str):
    """The vouchers of a Tally JSON export, each as the same element tree the XML export would give.

    Tally's JSON is its XML written as objects: every tag in lower case, a repeated block (``LEDGERENTRIES.LIST``) a list of
    objects, a flag a real boolean, and a ``metadata`` object holding the voucher's attributes (``VCHTYPE``, ``ACTION``). Building
    the same elements means one reader for both, so a JSON file cannot be read differently from its XML twin. Nothing is parsed
    by a library that resolves anything: ``json`` only makes dicts, and NaN and runaway nesting are refused.
    """

    def refuse_constant(_name):
        raise ValueError("not a number Tally writes")

    try:
        doc = json.loads(text, parse_constant=refuse_constant)
        messages = doc.get("tallymessage") if isinstance(doc, dict) else None
        if not isinstance(messages, list):
            raise TallyParseError("This JSON file is not a Tally vouchers export (it has no list of Tally messages). Export the vouchers from Tally again.")
        for message in messages:
            kind = message.get("metadata") if isinstance(message, dict) else None
            if isinstance(kind, dict) and str(kind.get("type", "")).strip().lower() == "voucher":
                yield _json_node("VOUCHER", message, 0)
    except (ValueError, RecursionError) as exc:
        raise TallyParseError("This file is not well-formed JSON, or it nests far deeper than a Tally export does, so it cannot be read. Export the vouchers from Tally again.") from exc


def _json_node(tag: str, obj: dict, depth: int):
    if depth > MAX_JSON_DEPTH:
        raise ValueError("nested too deeply")
    node = ET.Element(tag)
    for key, value in obj.items():
        name = str(key).upper()
        if key == "metadata":
            if isinstance(value, dict):
                node.attrib.update({str(a).upper(): _json_text(b) for a, b in value.items()})
            continue
        if isinstance(value, dict):
            node.append(_json_node(name, value, depth + 1))
        elif isinstance(value, list):
            _json_list(node, name, value, depth)
        elif value is not None:
            ET.SubElement(node, name).text = _json_text(value)
    return node


def _json_list(node, name: str, items: list, depth: int) -> None:
    """A list is a repeated block (objects) or a typed value: ``[{"metadata": true, "type": "Number"}, "-1"]``."""
    typed = [i for i in items if not (isinstance(i, dict) and i.get("metadata") is True)]
    if typed and all(isinstance(i, dict) for i in typed):
        for item in typed:
            node.append(_json_node(name + ".LIST", item, depth + 1))
    elif typed and len(typed) < len(items):  # a typed value: ``[{"metadata": true, ...}, "-1"]``
        ET.SubElement(node, name).text = "\n".join(_json_text(i) for i in typed if not isinstance(i, dict | list))
    elif typed:  # plain strings: the same tag repeated, as the XML has it (an alias list, an address)
        for item in typed:
            if not isinstance(item, dict | list):
                ET.SubElement(node, name).text = _json_text(item)


def _json_text(value) -> str:
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value)


def _without_declaration(text: str) -> str:
    """The text was decoded already; a declaration naming another encoding would make the parser misread it."""
    if text.lstrip().startswith("<?xml"):
        end = text.find("?>")
        if end != -1:
            return text[end + 2 :]
    return text


# A number, then whatever follows it. One way to split, and DOTALL, so a text that no longer fits cannot make the matcher try them all.
_QUANTITY = re.compile(r"^(\d[\d,]*(?:\.\d+)?|\.\d+)\s*(.*)$", re.DOTALL)
#: A quantity is a few characters ("1,200.500 Kgs = 1 Nos"); anything longer is cut before matching, whatever the file says.
MAX_QUANTITY_TEXT = 64


def _quantity(text: str) -> tuple[str, str] | None:
    """``600 BOX`` -> ("600", "BOX"); ``1,200.500 Kgs = 1 Nos`` -> ("1200.500", "Kgs"). None when there is no usable number."""
    match = _QUANTITY.match(" ".join((text or "").split())[:MAX_QUANTITY_TEXT])
    if not match:
        return None
    number = match.group(1).replace(",", "")
    try:
        if Decimal(number) <= 0:
            return None
    except InvalidOperation:
        return None
    return number, " ".join(match.group(2).split("=")[0].split())[:16]


def _inventory(element) -> tuple[list[VoucherLine], tuple[VoucherItem, ...]]:
    """The accounting side and the stock side of an item invoice.

    A voucher entered with items lists the party and the taxes among its ledger lines, but the head the goods are booked to
    (Purchases, Sales) only appears inside the items, as each item's allocation to a ledger; those are added up per ledger.
    The items themselves -- name, quantity, unit, value -- are what the stock register is built from.
    """
    totals: dict[str, int] = {}
    items: list[VoucherItem] = []
    seen = 0
    for tag in _INVENTORY_TAGS:
        for item in element.findall(tag):
            for alloc in item.findall("ACCOUNTINGALLOCATIONS.LIST"):
                seen += 1
                if seen > MAX_INVENTORY_ALLOCATIONS:
                    raise _BadText(f"The voucher has more than {MAX_INVENTORY_ALLOCATIONS} item lines.")
                name = clean_text(alloc.findtext("LEDGERNAME"), what="ledger name")
                totals[name] = totals.get(name, 0) - to_paise((alloc.findtext("AMOUNT") or "0").strip() or "0")
            quantity = _quantity(item.findtext("BILLEDQTY") or item.findtext("ACTUALQTY") or "")
            stock = " ".join((item.findtext("STOCKITEMNAME") or "").split())[:200]
            if quantity and stock:
                try:
                    value = abs(to_paise((item.findtext("AMOUNT") or "0").strip() or "0"))
                except (MoneyError, ValueError, ArithmeticError):
                    value = 0
                items.append(VoucherItem(stock, quantity[1], quantity[0], value))
    return [VoucherLine(name, paise, False) for name, paise in totals.items() if paise], tuple(items)


def _bills(node) -> tuple[tuple[str, str, int], ...]:
    """The bill references on one ledger line. A reference that cannot be read is dropped; it only decides what a payment settles."""
    found = []
    for item in node.findall("BILLALLOCATIONS.LIST")[:MAX_LINES_PER_VOUCHER]:
        name = " ".join((item.findtext("NAME") or "").split())[:64]
        kind = " ".join((item.findtext("BILLTYPE") or "").split())[:20]
        try:
            paise = abs(to_paise((item.findtext("AMOUNT") or "0").strip() or "0"))
        except (MoneyError, ValueError, ArithmeticError):
            continue
        if name and paise:
            found.append((name, kind, paise))
    return tuple(found)


def _yes(element, tag) -> bool:
    return (element.findtext(tag) or "").strip().lower() == "yes"


def _read_voucher(element, ordinal: int, parsed: ParsedVouchers) -> None:
    number = " ".join((element.findtext("VOUCHERNUMBER") or "").split())[:64]

    def skip(reason: str) -> None:
        parsed.skipped.append(SkippedLine(ordinal=ordinal, name=number, reason=reason))

    if (element.get("ACTION") or "").strip().lower() == "delete" or _yes(element, "ISDELETED"):
        return skip("Deleted in Tally.")
    if _yes(element, "ISCANCELLED"):
        return skip("Cancelled in Tally.")
    if _yes(element, "ISOPTIONAL"):
        return skip("Optional in Tally (not part of the books).")
    guid = (element.findtext("GUID") or "").strip()
    if not guid or len(guid) > 100:
        return skip("The voucher has no identifier, so a second import could not tell it was already imported.")
    date = _tally_date(element.findtext("DATE"))
    if date is None:
        return skip("The voucher's date could not be read.")
    tally_type = " ".join((element.findtext("VOUCHERTYPENAME") or element.get("VCHTYPE") or "").split())[:64]
    if not tally_type:
        return skip("The voucher has no type.")
    nodes = element.findall("LEDGERENTRIES.LIST") + element.findall("ALLLEDGERENTRIES.LIST")
    if len(nodes) > MAX_LINES_PER_VOUCHER:
        return skip(f"The voucher has more than {MAX_LINES_PER_VOUCHER} ledger lines.")
    lines: list[VoucherLine] = []
    try:
        for node in nodes:
            name = clean_text(node.findtext("LEDGERNAME"), what="ledger name")
            amount = -to_paise((node.findtext("AMOUNT") or "0").strip() or "0")
            lines.append(VoucherLine(name, amount, _yes(node, "ISPARTYLEDGER"), _bills(node)))
        stock_lines, items = _inventory(element)
        lines.extend(stock_lines)
        party_raw = (element.findtext("PARTYLEDGERNAME") or "").strip()
        party = clean_text(party_raw, what="party name") if party_raw else ""
    except _BadText as exc:
        return skip(str(exc))
    except (MoneyError, ValueError, ArithmeticError):
        return skip("An amount in the voucher could not be read.")
    parsed.vouchers.append(
        ParsedVoucher(
            ordinal=ordinal,
            guid=guid,
            tally_type=tally_type,
            number=number,
            date=date,
            party=party,
            narration=" ".join((element.findtext("NARRATION") or "").split())[:MAX_NARRATION],
            reference=" ".join((element.findtext("REFERENCE") or "").split())[:64],
            party_gstin=(element.findtext("PARTYGSTIN") or "").strip().upper()[:15],
            own_gstin=(element.findtext("CMPGSTIN") or "").strip().upper()[:15],
            lines=tuple(lines),
            items=items,
        )
    )
