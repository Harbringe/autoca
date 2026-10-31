"""Tally's voucher-type master: which of Tally's own types each of a firm's voucher types is a copy of.

A firm makes its own voucher type ("GST SALE") by choosing a parent from Tally's list when it creates it, and that link is stored on the
voucher type, not on the vouchers. Reading the voucher-type export therefore says what each custom type counts as, so a person is not
asked. Nothing is written: the answer is a suggestion the person sees and may change before the vouchers are read again.

UNVERIFIED against a real file, like the ledger-list reader it borrows from: the export is read as ``VOUCHERTYPE`` elements with a NAME
and a ``PARENT``. A real sample may force changes here and in the test twin.
"""

from __future__ import annotations

import io
import json

from ledger.tally_parse import (
    TallyParseError,
    TallyTooLargeError,
    _decode,
    _element_name,
    _local,
    _strip_illegal_xml,
    normal_name,
)
from ledger.tally_plan import NO_ACCOUNTING_TYPES, STANDARD_TYPES
from ledger.tally_vouchers import _json_node

MAX_TYPES = 2000


def read_voucher_types(data: bytes, filename: str, *, max_bytes: int) -> dict[str, str]:
    """``{voucher type name: its parent's name}`` from a voucher-type export (.xml or .json)."""
    if len(data) > max_bytes:
        raise TallyTooLargeError(f"This file is {len(data) // (1024 * 1024)} MB, which is more than a list of voucher types can be.")
    name = (filename or "").lower()
    if not name.endswith((".xml", ".json")):
        raise TallyParseError("Upload the voucher types as an .xml or .json file exported from Tally.")
    try:
        text = _decode(data)
        elements = _json_elements(text) if text.lstrip().startswith("{") else _xml_elements(text)
        found: dict[str, str] = {}
        for element in elements:
            if len(found) >= MAX_TYPES:
                raise TallyParseError(f"This file has more than {MAX_TYPES:,} voucher types.")
            vtype, _aliases = _element_name(element)
            parent = (element.findtext("PARENT") or "").strip()
            if vtype and parent:
                found[vtype] = parent
    except (TallyParseError, TallyTooLargeError):
        raise
    except Exception as exc:  # noqa: BLE001 -- a hostile file must end as a refusal, never a 500
        raise TallyParseError("This file could not be read as a Tally voucher types export. Export the voucher types from Tally again.") from exc
    if not found:
        raise TallyParseError("No voucher types with a parent were found in this file. In Tally, export Masters > Voucher Types.")
    return found


def _xml_elements(text: str):
    from defusedxml.ElementTree import iterparse

    text = _strip_illegal_xml(text)
    if text.lstrip().startswith("<?xml"):
        text = text[text.find("?>") + 2 :]
    for _event, element in iterparse(io.BytesIO(text.encode("utf-8")), events=("end",), forbid_dtd=True, forbid_entities=True, forbid_external=True):
        if _local(element.tag) == "VOUCHERTYPE":
            yield element


def _json_elements(text: str):
    doc = json.loads(text, parse_constant=_refuse)
    messages = doc.get("tallymessage") if isinstance(doc, dict) else None
    if not isinstance(messages, list):
        raise TallyParseError("This JSON file is not a Tally export (it has no list of Tally messages).")
    for message in messages:
        meta = message.get("metadata") if isinstance(message, dict) else None
        kind = str(meta.get("type", "")).replace(" ", "").lower() if isinstance(meta, dict) else ""
        if kind == "vouchertype":
            yield _json_node("VOUCHERTYPE", message, 0)


def _refuse(_name):
    raise ValueError("not a number Tally writes")


def suggest_mapping(parents: dict[str, str]) -> dict[str, str]:
    """What each of the firm's own voucher types counts as: a standard type, or ``"none"``. Tally's own types, and any whose chain of
    parents ends in nothing we know (a reversing journal, say), are left out, so they are still asked about."""
    by_name = {normal_name(n): normal_name(p) for n, p in parents.items()}
    out: dict[str, str] = {}
    for name, parent in parents.items():
        key = normal_name(name)
        if key in STANDARD_TYPES or key in NO_ACCOUNTING_TYPES:
            continue
        current, seen = normal_name(parent), set()
        while current and current not in seen:
            seen.add(current)
            if current in STANDARD_TYPES:
                out[name] = current
                break
            if current in NO_ACCOUNTING_TYPES:
                out[name] = "none"
                break
            current = by_name.get(current, "")
    return out
