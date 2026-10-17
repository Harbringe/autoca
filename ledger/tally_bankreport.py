"""Reading a Tally bank ledger report: the "ledger vouchers" view of one bank ledger, exported as XML.

It is one-sided: each row is the bank ledger's own side of a voucher -- the date, the other ledger, Tally's voucher type, the number, the
narration (for a bank-fed ledger, the bank's own text) and the amount. A voucher that touched several other ledgers shows the other side
as "(as per details)"; a one-sided report cannot say what those were, so such a row is left out, with the reason, rather than guessed.

Nothing here touches the database. The same hostility rules as ``ledger.tally_parse``: defusedxml with DTDs and entities refused, illegal
characters stripped, size and row caps, formula-looking names skipped with a reason.

**Sign.** Tally prints a debit as a negative amount. As in ``ledger.tally_vouchers`` it is negated once here, so ``signed_paise`` is the bank
ledger's side in the books' own sign: positive is money into the account.
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
    clean_text,
)

MAX_ROWS = 200_000

#: Tally's short voucher-type names in this report, and what they are called everywhere else.
VOUCHER_TYPES = {"rcpt": "Receipt", "pymt": "Payment", "cntr": "Contra", "jrnl": "Journal", "sale": "Sales", "purc": "Purchase"}
#: What Tally prints where one voucher touched several other ledgers.
AS_PER_DETAILS = "(as per details)"


@dataclass(frozen=True)
class BankReportRow:
    ordinal: int
    date: datetime.date
    #: The other ledger of the voucher.
    counter: str
    narration: str
    voucher_type: str
    number: str
    #: The bank ledger's side, books' sign: positive is money in.
    signed_paise: int


@dataclass
class ParsedBankReport:
    rows: list[BankReportRow] = field(default_factory=list)
    skipped: list[SkippedLine] = field(default_factory=list)
    date_from: datetime.date | None = None
    date_to: datetime.date | None = None


def looks_like_bank_report(data: bytes) -> bool:
    """A cheap look at the start of a file: this report is a flat run of DSPVCHDATE elements, a voucher export is not."""
    head = data[:4000].decode("utf-8", "ignore") if data[:2] not in (b"\xff\xfe", b"\xfe\xff") else data[:8000].decode("utf-16", "ignore")
    return "<DSPVCHDATE>" in head


def parse_bank_report(data: bytes, filename: str, *, max_bytes: int) -> ParsedBankReport:
    if len(data) > max_bytes:
        raise TallyTooLargeError(f"This file is larger than {max_bytes // (1024 * 1024)} MB, which is more than an import takes.")
    if not filename.lower().endswith(".xml"):
        raise TallyParseError("A bank report must be a Tally XML file (.xml).")
    from defusedxml import DefusedXmlException
    from defusedxml.ElementTree import ParseError, iterparse

    text = _strip_illegal_xml(_decode(data))
    if text.lstrip().startswith("<?xml"):
        text = text[text.find("?>") + 2 :]
    parsed = ParsedBankReport()
    current: dict[str, str] = {}
    ordinal = 0
    try:
        for _event, element in iterparse(
            io.BytesIO(text.encode("utf-8")), events=("end",), forbid_dtd=True, forbid_entities=True, forbid_external=True
        ):
            tag = _local(element.tag)
            if not tag.startswith("DSP"):
                continue
            current[tag] = element.text or ""
            if tag == "DSPEXPLVCHNUMBER":  # the last element of a row
                ordinal += 1
                if ordinal > MAX_ROWS:
                    raise TallyParseError(f"This report has more than {MAX_ROWS:,} rows. Export a shorter period.")
                _read_row(current, ordinal, parsed)
                current = {}
    except DefusedXmlException as exc:
        raise TallyParseError(
            "This file contains definitions (a DTD or entities) that an export from Tally never has, so it was not read."
        ) from exc
    except ParseError as exc:
        raise TallyParseError("This file is not well-formed XML, so it cannot be read. Export the report from Tally again.") from exc
    if ordinal == 0:
        raise TallyParseError("No rows were found in this file. Export a ledger's vouchers (the bank ledger's report) from Tally.")
    dates = [r.date for r in parsed.rows]
    if dates:
        parsed.date_from, parsed.date_to = min(dates), max(dates)
    return parsed


def _read_row(raw: dict[str, str], ordinal: int, parsed: ParsedBankReport) -> None:
    number = raw.get("DSPEXPLVCHNUMBER", "").replace("(No. :", "").replace(")", "").strip()[:64]

    def skip(reason: str) -> None:
        parsed.skipped.append(SkippedLine(ordinal=ordinal, name=number, reason=reason))

    try:
        date = datetime.datetime.strptime(raw.get("DSPVCHDATE", "").strip(), "%d-%b-%y").date()
    except ValueError:
        return skip("The row's date could not be read.")
    counter = " ".join(raw.get("DSPVCHLEDACCOUNT", "").split())
    if counter.lower() == AS_PER_DETAILS:
        return skip("Tally shows several ledgers on this voucher, which a bank report does not list. Import the vouchers export for it.")
    try:
        counter = clean_text(counter, what="ledger name")
    except _BadText as exc:
        return skip(str(exc))
    voucher_type = VOUCHER_TYPES.get(raw.get("DSPVCHTYPE", "").strip().lower())
    if voucher_type is None:
        return skip("This voucher type is not imported.")
    debit, credit = raw.get("DSPVCHDRAMT", "").strip(), raw.get("DSPVCHCRAMT", "").strip()
    try:
        signed = -to_paise(debit) if debit else (-to_paise(credit) if credit else 0)
    except (MoneyError, ValueError, ArithmeticError):
        return skip("The row's amount could not be read.")
    if signed == 0:
        return skip("The row has no amount.")
    narration = " ".join(raw.get("DSPVCHGROUPN", "").split())[:1000]
    parsed.rows.append(BankReportRow(ordinal, date, counter, narration, voucher_type, number, signed))
