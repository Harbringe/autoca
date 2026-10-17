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
from dataclasses import dataclass, field

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


@dataclass(frozen=True)
class VoucherLine:
    ledger: str
    signed_paise: int
    is_party: bool
    #: Tally's bill allocations on this line: (bill name, "Agst Ref" / "New Ref" / "On Account" / "Advance", paise, always positive).
    bills: tuple[tuple[str, str, int], ...] = ()


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
    if not filename.lower().endswith(".xml"):
        raise TallyParseError("A vouchers export must be a Tally XML file (.xml).")
    from defusedxml import DefusedXmlException
    from defusedxml.ElementTree import ParseError, iterparse

    text = _strip_illegal_xml(_decode(data))
    parsed = ParsedVouchers()
    ordinal = 0
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
                ordinal += 1
                if ordinal > MAX_VOUCHERS:
                    raise TallyParseError(f"This file has more than {MAX_VOUCHERS:,} vouchers. Export a shorter period.")
                _read_voucher(element, ordinal, parsed)
                element.clear()
    except DefusedXmlException as exc:
        raise TallyParseError(
            "This file contains definitions (a DTD or entities) that an export from Tally never has, so it was not read."
        ) from exc
    except ParseError as exc:
        raise TallyParseError("This file is not well-formed XML, so it cannot be read. Export the vouchers from Tally again.") from exc
    if ordinal == 0:
        raise TallyParseError("No vouchers were found in this file. Export the vouchers (not the masters or a report) from Tally.")
    dates = [v.date for v in parsed.vouchers]
    if dates:
        parsed.date_from, parsed.date_to = min(dates), max(dates)
    return parsed


def _without_declaration(text: str) -> str:
    """The text was decoded already; a declaration naming another encoding would make the parser misread it."""
    if text.lstrip().startswith("<?xml"):
        end = text.find("?>")
        if end != -1:
            return text[end + 2 :]
    return text


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
        )
    )
