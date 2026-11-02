"""Tally's stock-item master: each product with its unit, HSN, GST rate and opening stock.

Read from a ``STOCKITEM`` export (.xml, or .json written the same way). Nothing is written here: the rows go to the preview, and
``ledger.tally_stock_import`` writes the ones a person accepts.

UNVERIFIED against a real file, like the other masters readers: the unit is ``BASEUNITS``; the opening is ``OPENINGBALANCE`` ("40 Nos", or
"12.500 Box = 150 Nos" for a compound unit, of which the first quantity is kept) and ``OPENINGVALUE`` (Tally writes stock held as a negative);
the HSN is the first ``HSNCODE`` and the GST rate the ``Integrated Tax`` rate, or the Central and State rates added. A real sample may force
changes here and in the test twin.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from ledger.inventory import parse_quantity
from ledger.tally_parse import (
    TallyParseError,
    TallyTooLargeError,
    _decode,
    _element_name,
    _local,
    _strip_illegal_xml,
    normal_name,
)
from ledger.tally_vouchers import _json_node

MAX_ITEMS = 50_000


@dataclass(frozen=True)
class StockRow:
    name: str
    unit: str
    hsn_sac: str
    gst_rate: Decimal | None
    opening_qty: Decimal
    opening_value_paise: int


def read_stock_items(data: bytes, filename: str, *, max_bytes: int) -> list[StockRow]:
    """The items of a stock-item export, in file order; an item named twice (in any case) is read once."""
    if len(data) > max_bytes:
        raise TallyTooLargeError(f"This file is {len(data) // (1024 * 1024)} MB, which is more than a list of stock items can be.")
    name = (filename or "").lower()
    if not name.endswith((".xml", ".json")):
        raise TallyParseError("Upload the stock items as an .xml or .json file exported from Tally.")
    rows: list[StockRow] = []
    seen: set[str] = set()
    try:
        text = _decode(data)
        elements = _json_elements(text) if text.lstrip().startswith("{") else _xml_elements(text)
        for element in elements:
            if len(rows) >= MAX_ITEMS:
                raise TallyParseError(f"This file has more than {MAX_ITEMS:,} stock items.")
            item, _aliases = _element_name(element)
            key = normal_name(item)
            if not item or key in seen:
                continue
            seen.add(key)
            rows.append(_row(item, element))
    except (TallyParseError, TallyTooLargeError):
        raise
    except Exception as exc:  # noqa: BLE001 -- a hostile file must end as a refusal, never a 500
        raise TallyParseError("This file could not be read as a Tally stock items export. Export the stock items from Tally again.") from exc
    if not rows:
        raise TallyParseError("No stock items were found in this file. In Tally, export Masters > Stock Items.")
    return rows


def _row(name: str, element) -> StockRow:
    return StockRow(
        name=" ".join(name.split())[:200],
        unit=" ".join((element.findtext("BASEUNITS") or "").split())[:16],
        hsn_sac=_hsn(element),
        gst_rate=_rate(element),
        opening_qty=_opening_qty(element.findtext("OPENINGBALANCE")),
        opening_value_paise=_paise(element.findtext("OPENINGVALUE")),
    )


def _hsn(element) -> str:
    for node in element.iter():
        if _local(node.tag) in ("HSNCODE", "HSN") and (node.text or "").strip():
            return "".join((node.text or "").split())[:8]
    return ""


def _rate(element) -> Decimal | None:
    heads: dict[str, Decimal] = {}
    for block in element.iter():
        if _local(block.tag) != "RATEDETAILS.LIST":
            continue
        head = (block.findtext("GSTRATEDUTYHEAD") or "").strip().lower()
        try:
            value = Decimal((block.findtext("GSTRATE") or "").strip())
        except InvalidOperation:
            continue
        if head and head not in heads and 0 <= value <= 100:
            heads[head] = value
    if "integrated tax" in heads:
        return heads["integrated tax"]
    if "central tax" in heads and "state tax" in heads:
        return heads["central tax"] + heads["state tax"]
    return None


def _opening_qty(text: str | None) -> Decimal:
    first = (text or "").split("=")[0]
    return parse_quantity(first) or Decimal(0)


def _paise(text: str | None) -> int:
    """Tally writes stock held as a negative amount; the register wants what it is worth, whatever the sign."""
    try:
        return abs(int((Decimal((text or "0").strip().replace(",", "") or "0") * 100).to_integral_value()))
    except InvalidOperation:
        return 0


def _xml_elements(text: str):
    from defusedxml.ElementTree import iterparse

    text = _strip_illegal_xml(text)
    if text.lstrip().startswith("<?xml"):
        text = text[text.find("?>") + 2 :]
    for _event, element in iterparse(io.BytesIO(text.encode("utf-8")), events=("end",), forbid_dtd=True, forbid_entities=True, forbid_external=True):
        if _local(element.tag) == "STOCKITEM":
            yield element


def _json_elements(text: str):
    doc = json.loads(text, parse_constant=_refuse)
    messages = doc.get("tallymessage") if isinstance(doc, dict) else None
    if not isinstance(messages, list):
        raise TallyParseError("This JSON file is not a Tally export (it has no list of Tally messages).")
    for message in messages:
        meta = message.get("metadata") if isinstance(message, dict) else None
        kind = str(meta.get("type", "")).replace(" ", "").lower() if isinstance(meta, dict) else ""
        if kind == "stockitem":
            yield _json_node("STOCKITEM", message, 0)


def _refuse(_name):
    raise ValueError("not a number Tally writes")
