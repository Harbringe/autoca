"""Checking the posted books against Tally's own trial balance.

The accountant exports the trial balance from Tally for the same period and company; each ledger's closing balance there is compared with
ours. Differences are shown and never fixed: they are what the accountant investigates before signing the move off.

UNVERIFIED against a real file, like the other Tally readers: the export is read as ``DSPACCNAME/DSPDISPNAME`` (the ledger) followed by
``DSPACCINFO`` holding the closing debit (``DSPCLDRAMT/DSPCLDRAMTA``) and credit (``DSPCLCRAMT/DSPCLCRAMTA``), and the JSON twin of the
same names in lower case. Tally's sign convention for these is not relied on: each amount is taken as a size and the debit side is
the one in ``DSPCLDRAMTA``. A real sample may force changes here and in the test twin.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass

from core.money import to_paise
from ledger.tally_parse import (
    TallyParseError,
    TallyTooLargeError,
    _decode,
    _local,
    _strip_illegal_xml,
    normal_name,
)

MAX_LEDGERS = 50_000


@dataclass(frozen=True)
class Difference:
    name: str
    tally_paise: int  # closing balance, debit positive
    ours_paise: int


def read_trial_balance(data: bytes, filename: str, *, max_bytes: int) -> dict[str, int]:
    """``{ledger name: closing balance in paise, debit positive}`` from a Tally trial balance export (.xml or .json)."""
    if len(data) > max_bytes:
        raise TallyTooLargeError(f"This file is {len(data) // (1024 * 1024)} MB, which is more than a trial balance can be.")
    if not (filename or "").lower().endswith((".xml", ".json")):
        raise TallyParseError("Upload the trial balance as an .xml or .json file exported from Tally.")
    try:
        text = _decode(data)
        names, infos = _json_parts(text) if text.lstrip().startswith("{") else _xml_parts(text)
        if len(names) != len(infos):
            raise TallyParseError("This file's ledgers and balances do not pair up, so it is not read as a Tally trial balance.")
        if len(names) > MAX_LEDGERS:
            raise TallyParseError(f"This file has more than {MAX_LEDGERS:,} ledgers.")
        out: dict[str, int] = {}
        for name, (debit, credit) in zip(names, infos, strict=True):
            out[name] = out.get(name, 0) + abs(_paise(debit)) - abs(_paise(credit))
    except (TallyParseError, TallyTooLargeError):
        raise
    except Exception as exc:  # noqa: BLE001 -- a hostile file must end as a refusal, never a 500
        raise TallyParseError("This file could not be read as a Tally trial balance. Export the trial balance from Tally again.") from exc
    if not out:
        raise TallyParseError("No ledgers were found in this file. In Tally, export the Trial Balance report as XML or JSON.")
    return out


def _paise(text) -> int:
    cleaned = str(text or "").replace(",", "").strip()
    return to_paise(cleaned) if cleaned else 0


def _xml_parts(text: str):
    from defusedxml.ElementTree import iterparse

    text = _strip_illegal_xml(text)
    if text.lstrip().startswith("<?xml"):
        text = text[text.find("?>") + 2 :]
    names: list[str] = []
    infos: list[tuple[str, str]] = []
    for _event, element in iterparse(io.BytesIO(text.encode("utf-8")), events=("end",), forbid_dtd=True, forbid_entities=True, forbid_external=True):
        tag = _local(element.tag)
        if tag == "DSPACCNAME":
            names.append((element.findtext("DSPDISPNAME") or element.text or "").strip())
        elif tag == "DSPACCINFO":
            infos.append((element.findtext("DSPCLDRAMT/DSPCLDRAMTA") or "", element.findtext("DSPCLCRAMT/DSPCLCRAMTA") or ""))
    return names, infos


def _json_parts(text: str):
    def refuse(_name):
        raise ValueError("not a number Tally writes")

    doc = json.loads(text, parse_constant=refuse)
    names = [str(n).strip() for n in _find(doc, "dspdispname")]
    infos = []
    for info in _find(doc, "dspaccinfo"):
        debit = next(iter(_find(info, "dspcldramta")), "")
        credit = next(iter(_find(info, "dspclcramta")), "")
        infos.append((debit, credit))
    return names, infos


def _find(obj, key: str):
    """Every value stored under ``key``, anywhere in the document, in document order."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == key:
                if isinstance(v, list):
                    yield from v
                else:
                    yield v
            else:
                yield from _find(v, key)
    elif isinstance(obj, list):
        for item in obj:
            yield from _find(item, key)


def compare(client, financial_year: int, tally: dict[str, int]) -> tuple[list[Difference], int]:
    """Where Tally's closing balances and ours differ, biggest difference first, and how many ledgers agree.

    Names are matched the way the importer matches them (case, spacing and Unicode form ignored). A ledger on one side only is a
    difference against zero.
    """
    from ledger.reports import trial_balance

    ours: dict[str, tuple[str, int]] = {}
    for row in trial_balance(client, financial_year).rows:
        key = normal_name(row.name)
        shown, total = ours.get(key, (row.name, 0))
        ours[key] = (shown, total + row.closing_debit_paise - row.closing_credit_paise)
    theirs: dict[str, tuple[str, int]] = {}
    for name, paise in tally.items():
        key = normal_name(name)
        shown, total = theirs.get(key, (name, 0))
        theirs[key] = (shown, total + paise)

    differences: list[Difference] = []
    matched = 0
    for key in sorted(set(ours) | set(theirs)):
        our_name, our_paise = ours.get(key, ("", 0))
        their_name, their_paise = theirs.get(key, ("", 0))
        if our_paise == their_paise:
            matched += 1 if (key in ours and key in theirs) else 0
            continue
        differences.append(Difference(their_name or our_name, tally_paise=their_paise, ours_paise=our_paise))
    differences.sort(key=lambda d: abs(d.tally_paise - d.ours_paise), reverse=True)
    return differences, matched
