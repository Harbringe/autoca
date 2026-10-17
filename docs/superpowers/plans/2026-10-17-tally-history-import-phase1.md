# Import history from Tally, phase 1: vouchers and the screen

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A firm can upload a client's Tally masters and a Tally vouchers export, preview what would happen, confirm, and have the client's Sales, Purchase, Credit Note, Debit Note and Journal vouchers posted to the books exactly as Tally had them (with bills for invoices), and undo the whole run.

**Architecture:** A pure parser (`ledger/tally_vouchers.py`) turns the vouchers XML into `ParsedVouchers`. A pure planner (`ledger/tally_plan.py`) decides, per voucher, what is posted or why it is skipped. A service (`ledger/tally_voucher_import.py`) stages a preview in the existing `LedgerImportRun` table (new kind `VOUCHERS`) and, on confirm, writes each voucher in its own atomic block through a faithful writer, remembering the Tally GUID in a new `TallyVoucher` table so a re-run imports nothing twice and a run can be undone. An API route group and one web screen sit on top. Bank vouchers (Payment/Receipt/Contra on a bank ledger) and learning are phases 2 and 3 and are **not** in this plan.

**Tech Stack:** Django 5 / DRF / Postgres RLS, defusedxml, pytest (DB tests run in CI only), React 19, TanStack Query/Router, vitest.

**Spec:** `docs/superpowers/specs/2026-10-17-tally-history-import-design.md`

## Deviations from the spec (found while reading the code)

1. **Voucher numbers are not kept as `entry_no`.** `JournalEntry.entry_no` is an integer from `allocate_voucher_number`; Tally numbers are strings like `SI/12/2526/00099`. The Tally number is stored on `TallyVoucher.tally_number` and, for invoices, is the bill's `reference` (the invoice number). The entry gets the next number in AutoCA's own series.
2. **Faithful writer, not the billing planner.** `ledger.billing._post` rebuilds the lines from heads and tax and refuses heads that are bank, cash or party accounts. A history import must reproduce Tally's lines exactly, so `ledger/tally_voucher_import.py` writes the lines as they were and *derives* the bill's figures (taxable, CGST/SGST/IGST/cess, round-off, total) from them. `_post`'s duplicate key (`invoice_key`) and sign-off lock are reused.
3. **No existing writer for a plain journal voucher** (`EntryKind.JOURNAL` is never written outside tests); the faithful writer is the first.
4. **Bank vouchers wait for phase 2.** In phase 1 a Payment/Receipt/Contra voucher is skipped with the reason "bank and cash vouchers are imported in a later release" **only if one of its ledgers is a bank account**; otherwise it posts as a journal. The preview counts them loudly. Until phase 2 exists, a run is **partial books** and the screen says so.

## Global Constraints

- Money is whole paise (`int`), never float. Parse Tally amounts with `core.money.to_paise`, then negate once (Tally writes a debit as negative; the books are debit-positive).
- The file is hostile: `defusedxml` with DTD, entities and external references forbidden; illegal XML characters stripped as in `ledger.tally_parse._strip_illegal_xml`; size cap `settings.MAX_TALLY_IMPORT_BYTES`; counts and name lengths capped; names a spreadsheet would run as a formula (`= + - @`) skipped with a reason.
- Every table is firm-scoped with row-level security (`rls_operations`) and a composite foreign key keeping a row's client the same as its ledger's/entry's client, as in `ledger/migrations/0010_tally_import_security.py`.
- A voucher posts all-or-nothing. A voucher that does not balance, names a ledger not in the chart, is cancelled or optional, is outside the range, or clashes on invoice number is skipped with a reason and never partially written.
- The import refuses any date range that has an AutoCA posting for the client and any range inside `editing.locked_through(client.pk)`.
- Permission: `ledger.import` (firm admin, Senior CA) and `core.access.require_chart_import`, as the masters import.
- Real client data is never committed. All tests use synthetic XML built in `ledger/tests/tally_voucher_xml.py`.
- Files in this repo use CRLF; do not rewrite line endings of untouched lines.
- After changing any API, regenerate: `python manage.py spectacular --file web/openapi.yaml` then `npx openapi-typescript` as the repo's script does (CI fails if they differ).

## Review Focus

1. A sale to `Cash` (party ledger is not a debtor): posts as a plain voucher entry with no bill and no party, not an error.
2. The same GUID uploaded twice, or the same file after a partial failure: nothing doubles, and what was written before the failure stays.
3. A voucher whose lines do not sum to zero, or which has one line of nil amount: skipped, listed, books untouched.
4. A Tally number reused across voucher types or years (`1` for a Sales and `1` for a Journal): no collision on `entry_no`.
5. A file with two companies or a date range straddling a locked year: refused whole, with a message a person can act on.

---

## File Structure

| File | Responsibility |
|---|---|
| `ledger/tally_vouchers.py` (new) | Pure. Bytes to `ParsedVouchers`. No database. |
| `ledger/tally_plan.py` (new) | Pure. One `ParsedVoucher` plus the chart's facts to a `Planned` or a `Skip`. Derives bill figures. |
| `ledger/tally_voucher_import.py` (new) | `stage_vouchers`, `confirm_vouchers`, `undo_run`; the faithful writer. |
| `ledger/models.py` (modify) | `ImportKind.VOUCHERS`; `TallyVoucher`. |
| `ledger/migrations/0034_tally_vouchers.py`, `0035_tally_vouchers_security.py` (new) | Table, then RLS and the client keys. |
| `api/serializers/tally.py`, `api/views/tally.py`, `api/urls.py` (modify) | Upload kind, preview, confirm, undo. |
| `ledger/tests/tally_voucher_xml.py` (new) | Synthetic voucher XML builder. |
| `ledger/tests/test_tally_vouchers_parse.py`, `test_tally_plan.py`, `test_tally_voucher_import.py` (new) | Tests per layer. |
| `web/src/api/queries/tallyImport.ts`, `web/src/features/tally/TallyImportScreen.tsx` + test, `web/src/routes/_app/clients/$clientId/tally.tsx` (new) | The screen. |

---

### Task 1: Synthetic voucher XML builder and the parser

**Files:**
- Create: `ledger/tests/tally_voucher_xml.py`, `ledger/tally_vouchers.py`
- Test: `ledger/tests/test_tally_vouchers_parse.py`

**Interfaces:**
- Produces (`ledger/tally_vouchers.py`):
  ```python
  @dataclass(frozen=True)
  class VoucherLine:
      ledger: str            # as written, cleaned
      signed_paise: int      # debit positive (books' sign)
      is_party: bool         # ISPARTYLEDGER == Yes

  @dataclass(frozen=True)
  class ParsedVoucher:
      ordinal: int           # 1-based position of the VOUCHER element
      guid: str
      tally_type: str        # VOUCHERTYPENAME / VCHTYPE, as written
      number: str            # VOUCHERNUMBER, may be empty
      date: datetime.date
      party: str             # PARTYLEDGERNAME or ""
      narration: str
      reference: str         # REFERENCE or ""
      party_gstin: str       # PARTYGSTIN or ""
      own_gstin: str         # CMPGSTIN or ""
      lines: tuple[VoucherLine, ...]

  @dataclass
  class ParsedVouchers:
      company: str                       # SVCURRENTCOMPANY, "" if absent
      companies: set[str]                # every distinct company seen
      vouchers: list[ParsedVoucher]
      skipped: list[SkippedLine]         # reuse ledger.tally_parse.SkippedLine
      date_from: datetime.date | None
      date_to: datetime.date | None

  def parse_vouchers(data: bytes, filename: str, *, max_bytes: int) -> ParsedVouchers
  ```
  Raises `TallyParseError` / `TallyTooLargeError` (from `ledger.tally_parse`).
- Constants: `MAX_VOUCHERS = 200_000`, `MAX_LINES_PER_VOUCHER = 500`.

- [ ] **Step 1: Write the builder** `ledger/tests/tally_voucher_xml.py`

```python
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
```

- [ ] **Step 2: Write the failing parser tests** `ledger/tests/test_tally_vouchers_parse.py`

```python
"""Reading a Tally vouchers export: shape, signs, and what is refused."""

from __future__ import annotations

import datetime

import pytest

from ledger.tally_parse import TallyParseError, TallyTooLargeError
from ledger.tally_vouchers import parse_vouchers
from ledger.tests.tally_voucher_xml import line, voucher, vouchers_xml

MAX = 10 * 1024 * 1024


def sale(guid="g1", number="1", date="20250401", amount=1180.0):
    return voucher(
        guid=guid, vtype="Sales", number=number, date=date, party="Acme Traders", gstin="27ABCDE1234F1Z5",
        lines=[line("Acme Traders", amount, party=True), line("Sales", -1000.0), line("Output CGST", -90.0), line("Output SGST", -90.0)],
    )


def test_reads_a_sales_voucher_with_the_books_sign():
    parsed = parse_vouchers(vouchers_xml([sale()]), "sales.xml", max_bytes=MAX)
    assert len(parsed.vouchers) == 1
    v = parsed.vouchers[0]
    assert (v.guid, v.tally_type, v.number, v.date) == ("g1", "Sales", "1", datetime.date(2025, 4, 1))
    assert v.party == "Acme Traders" and v.party_gstin == "27ABCDE1234F1Z5"
    assert [(l.ledger, l.signed_paise, l.is_party) for l in v.lines] == [
        ("Acme Traders", 118000, True), ("Sales", -100000, False), ("Output CGST", -9000, False), ("Output SGST", -9000, False),
    ]
    assert parsed.company == "TEST CO" and parsed.date_from == parsed.date_to == datetime.date(2025, 4, 1)


def test_cancelled_and_optional_vouchers_are_skipped_with_a_reason():
    xml = vouchers_xml([sale("a"), voucher(guid="b", vtype="Sales", number="2", date="20250402", lines=[], cancelled=True),
                        voucher(guid="c", vtype="Journal", number="3", date="20250403", lines=[], optional=True)])
    parsed = parse_vouchers(xml, "v.xml", max_bytes=MAX)
    assert [v.guid for v in parsed.vouchers] == ["a"]
    assert {s.reason.split(".")[0] for s in parsed.skipped} == {"Cancelled in Tally", "Optional in Tally"}


def test_a_voucher_with_a_bad_date_or_no_guid_is_skipped_not_fatal():
    xml = vouchers_xml([sale("a"), sale("", number="9"), sale("z", date="2025-13-45")])
    parsed = parse_vouchers(xml, "v.xml", max_bytes=MAX)
    assert [v.guid for v in parsed.vouchers] == ["a"]
    assert len(parsed.skipped) == 2


def test_two_companies_are_recorded_so_the_import_can_refuse():
    one = vouchers_xml([sale("a")], company="ONE")
    two = vouchers_xml([sale("b")], company="TWO")
    merged = one.replace(b"</ENVELOPE>", b"") + two.split(b"<ENVELOPE>", 1)[1]
    with pytest.raises(TallyParseError):
        parse_vouchers(merged, "v.xml", max_bytes=MAX)  # not well-formed: two roots


def test_a_doctype_is_refused():
    bomb = b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><ENVELOPE>&a;</ENVELOPE>'
    with pytest.raises(TallyParseError):
        parse_vouchers(bomb, "v.xml", max_bytes=MAX)


def test_too_large_is_refused():
    with pytest.raises(TallyTooLargeError):
        parse_vouchers(b"<ENVELOPE>" + b" " * 100 + b"</ENVELOPE>", "v.xml", max_bytes=50)


def test_illegal_control_characters_do_not_break_the_file():
    xml = vouchers_xml([sale("a")]).replace(b"Acme Traders", b"Acme&#4; Traders", 1)
    parsed = parse_vouchers(xml, "v.xml", max_bytes=MAX)
    assert len(parsed.vouchers) == 1


def test_a_formula_looking_party_name_is_skipped():
    v = voucher(guid="f", vtype="Journal", number="1", date="20250401",
                lines=[line("=HYPERLINK(1)", 10.0), line("Cash", -10.0)])
    parsed = parse_vouchers(vouchers_xml([v]), "v.xml", max_bytes=MAX)
    assert parsed.vouchers == [] and "formula" in parsed.skipped[0].reason


def test_nothing_but_a_non_voucher_file_is_an_error():
    with pytest.raises(TallyParseError):
        parse_vouchers(b"<ENVELOPE><X/></ENVELOPE>", "v.xml", max_bytes=MAX)
```

- [ ] **Step 3: Run to verify they fail**

Run: `python -m pytest ledger/tests/test_tally_vouchers_parse.py -q`
Expected: collection error / `ModuleNotFoundError: ledger.tally_vouchers`. (These are pure tests; they run locally, no database.)

- [ ] **Step 4: Implement** `ledger/tally_vouchers.py`

```python
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

from core.money import to_paise
from ledger.tally_parse import (
    MAX_NAME_LENGTH,
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
    seen_voucher_element = False
    try:
        for _event, element in iterparse(
            io.BytesIO(text.encode("utf-8")), events=("end",), forbid_dtd=True, forbid_entities=True, forbid_external=True
        ):
            tag = _local(element.tag)
            if tag == "SVCURRENTCOMPANY":
                name = " ".join((element.text or "").split())
                if name:
                    parsed.companies.add(name)
                    parsed.company = parsed.company or name
            elif tag == "VOUCHER":
                seen_voucher_element = True
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
    if not seen_voucher_element:
        raise TallyParseError("No vouchers were found in this file. Export the vouchers (not the masters or a report) from Tally.")
    dates = [v.date for v in parsed.vouchers]
    if dates:
        parsed.date_from, parsed.date_to = min(dates), max(dates)
    return parsed


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
            amount = -to_paise(node.findtext("AMOUNT") or "0")
            lines.append(VoucherLine(name, amount, _yes(node, "ISPARTYLEDGER")))
        party_raw = (element.findtext("PARTYLEDGERNAME") or "").strip()
        party = clean_text(party_raw, what="party name") if party_raw else ""
    except _BadText as exc:
        return skip(str(exc))
    except (ValueError, ArithmeticError):
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
```

- [ ] **Step 5: Run to verify they pass**

Run: `python -m pytest ledger/tests/test_tally_vouchers_parse.py -q`
Expected: all pass. If `core.money.to_paise` rejects the plain decimal string, read `core/money.py` and adapt the call (it is used the same way in `tally_parse.parse_opening`); do not add a new money parser.

- [ ] **Step 6: Commit**

```bash
git add ledger/tally_vouchers.py ledger/tests/tally_voucher_xml.py ledger/tests/test_tally_vouchers_parse.py
git commit -m "Tally vouchers: read a vouchers export into parsed vouchers (pure, hostile-input safe)"
```

---

### Task 2: The planner (pure)

**Files:**
- Create: `ledger/tally_plan.py`
- Test: `ledger/tests/test_tally_plan.py`

**Interfaces:**
- Consumes: `ParsedVoucher`, `VoucherLine` (Task 1).
- Produces:
  ```python
  @dataclass(frozen=True)
  class Facts:
      """What the planner may know about the chart, as plain data (no ORM)."""
      groups: dict[str, str]        # normal_name(ledger name) -> LedgerGroup value, for ledgers in the chart
      bank_ledgers: frozenset[str]  # normal_name of ledgers whose group is BANK / BANK_OD

  @dataclass(frozen=True)
  class BillFigures:
      kind: str                     # a BillKind value: PURCHASE / SALES / DEBIT_NOTE / CREDIT_NOTE
      party_ledger: str             # the party line's ledger name
      taxable_paise: int; cgst_paise: int; sgst_paise: int; igst_paise: int; cess_paise: int
      round_off_paise: int          # signed, positive rounds up
      total_paise: int              # what the party's ledger carries

  @dataclass(frozen=True)
  class Planned:
      voucher: ParsedVoucher
      voucher_type: str             # a VoucherType value
      entry_kind: str               # EntryKind VOUCHER or JOURNAL
      bill: BillFigures | None

  @dataclass(frozen=True)
  class Skip:
      voucher: ParsedVoucher
      reason: str

  def plan_voucher(v: ParsedVoucher, facts: Facts) -> Planned | Skip
  ```

Rules the planner implements (each pinned by a test below):
1. Tally type -> `VoucherType`: `Sales`, `Purchase`, `Credit Note`, `Debit Note`, `Journal` map directly; `Payment`/`Receipt`/`Contra` map to the same-named type. Any other type name (a firm-specific type like `Delivery Note`, `Stock Journal`, `Rejections Out`) is **skipped** with "This voucher type is not imported."
2. A voucher with any line ledger whose `normal_name` is not in `facts.groups` is skipped: `"The ledger 'X' is not in the client's chart. Import the masters first."` (first missing name shown).
3. The lines must sum to exactly zero and there must be at least two lines, each non-zero; otherwise skipped "The voucher does not balance." / "has fewer than two lines".
4. Payment/Receipt/Contra with any line on a bank ledger: skipped `"Bank vouchers are imported in a later release."`; with no bank line: `entry_kind=JOURNAL`, no bill.
5. Journal: `entry_kind=JOURNAL`, no bill.
6. Sales/Purchase/Credit Note/Debit Note: `entry_kind=VOUCHER`. A bill is produced only when the party line's ledger is in group DEBTOR (sales, credit note) or CREDITOR (purchase, debit note) and a voucher number or reference exists; otherwise `bill=None` (a cash sale is a plain voucher). Figures: tax lines are those whose ledger `normal_name` contains `cgst`, `sgst`/`utgst`, `igst` or `cess` and whose group is DUTIES_AND_TAXES; a ledger named `round off`/`rounding` is the round-off; every other non-party line is a head and adds to `taxable_paise` (absolute value, so a head reversed inside the voucher nets). `total_paise` is `abs(party line)`. Sign check: for a purchase/debit note the party line is a credit (negative), for sales/credit note a debit (positive); a voucher against the grain (a purchase whose party is debited) is skipped "The party line is on the wrong side for a purchase."
7. A bill's `taxable + tax + round_off` must equal `total` (within 0); otherwise the voucher still posts as a plain voucher entry with `bill=None` and a note on the preview row (`bill_note`), because the books must match Tally even where the bill cannot be derived. (The note is returned via `Planned.note`.)

Add `note: str = ""` to `Planned`.

- [ ] **Step 1: Write the failing tests** `ledger/tests/test_tally_plan.py`

```python
"""Deciding what a parsed voucher becomes. Pure: no database."""

from __future__ import annotations

import datetime

from classify.models import LedgerGroup as G
from ledger.models import BillKind, EntryKind, VoucherType
from ledger.tally_parse import normal_name
from ledger.tally_plan import Facts, Planned, Skip, plan_voucher
from ledger.tally_vouchers import ParsedVoucher, VoucherLine

CHART = {
    "Acme Traders": G.DEBTOR, "Zed Supplies": G.CREDITOR, "Cash": G.CASH, "Bank One": G.BANK,
    "Sales": G.SALES, "Purchases": G.PURCHASE, "Output CGST": G.DUTIES_AND_TAXES, "Output SGST": G.DUTIES_AND_TAXES,
    "Input CGST": G.DUTIES_AND_TAXES, "Input SGST": G.DUTIES_AND_TAXES, "Round Off": G.INDIRECT_EXPENSE, "Rent": G.INDIRECT_EXPENSE,
}
FACTS = Facts(
    groups={normal_name(k): v for k, v in CHART.items()},
    bank_ledgers=frozenset({normal_name("Bank One")}),
)


def voucher(tally_type, lines, *, number="1", party="", reference=""):
    return ParsedVoucher(
        ordinal=1, guid="g", tally_type=tally_type, number=number, date=datetime.date(2025, 4, 1), party=party,
        narration="", reference=reference, party_gstin="", own_gstin="",
        lines=tuple(VoucherLine(n, p, ip) for n, p, ip in lines),
    )


def test_a_credit_sale_becomes_a_voucher_and_a_bill():
    v = voucher("Sales", [("Acme Traders", 118000, True), ("Sales", -100000, False), ("Output CGST", -9000, False), ("Output SGST", -9000, False)], party="Acme Traders")
    plan = plan_voucher(v, FACTS)
    assert isinstance(plan, Planned)
    assert (plan.voucher_type, plan.entry_kind) == (VoucherType.SALES, EntryKind.VOUCHER)
    b = plan.bill
    assert (b.kind, b.taxable_paise, b.cgst_paise, b.sgst_paise, b.total_paise, b.round_off_paise) == (BillKind.SALES, 100000, 9000, 9000, 118000, 0)


def test_round_off_is_signed_and_the_bill_still_ties():
    v = voucher("Purchase", [("Zed Supplies", -118000, True), ("Purchases", 99999, False), ("Input CGST", 9000, False), ("Input SGST", 9000, False), ("Round Off", 1, False)], party="Zed Supplies")
    b = plan_voucher(v, FACTS).bill
    assert (b.kind, b.taxable_paise, b.round_off_paise, b.total_paise) == (BillKind.PURCHASE, 99999, 1, 118000)


def test_a_cash_sale_is_a_plain_voucher_without_a_bill():
    v = voucher("Sales", [("Cash", 1000, True), ("Sales", -1000, False)], party="Cash")
    plan = plan_voucher(v, FACTS)
    assert isinstance(plan, Planned) and plan.bill is None and plan.entry_kind == EntryKind.VOUCHER


def test_a_bill_that_does_not_tie_posts_without_a_bill_and_says_why():
    v = voucher("Sales", [("Acme Traders", 118500, True), ("Sales", -100000, False), ("Output CGST", -9000, False), ("Output SGST", -9000, False)], party="Acme Traders")
    plan = plan_voucher(v, FACTS)
    assert isinstance(plan, Planned) and plan.bill is None and plan.note


def test_an_unbalanced_voucher_is_skipped():
    v = voucher("Journal", [("Rent", 1000, False), ("Cash", -900, False)])
    assert isinstance(plan_voucher(v, FACTS), Skip)


def test_a_missing_ledger_is_skipped_and_named():
    v = voucher("Journal", [("Rent", 1000, False), ("Mystery", -1000, False)])
    out = plan_voucher(v, FACTS)
    assert isinstance(out, Skip) and "Mystery" in out.reason


def test_a_payment_on_a_bank_ledger_waits_for_phase_two():
    v = voucher("Payment", [("Rent", 1000, False), ("Bank One", -1000, False)])
    out = plan_voucher(v, FACTS)
    assert isinstance(out, Skip) and "later release" in out.reason


def test_a_cash_payment_is_a_journal_entry():
    v = voucher("Payment", [("Rent", 1000, False), ("Cash", -1000, False)])
    plan = plan_voucher(v, FACTS)
    assert (plan.entry_kind, plan.voucher_type, plan.bill) == (EntryKind.JOURNAL, VoucherType.PAYMENT, None)


def test_an_unknown_voucher_type_is_skipped():
    v = voucher("Delivery Note", [("Rent", 1, False), ("Cash", -1, False)])
    assert isinstance(plan_voucher(v, FACTS), Skip)


def test_a_purchase_whose_party_is_debited_is_skipped():
    v = voucher("Purchase", [("Zed Supplies", 1000, True), ("Purchases", -1000, False)], party="Zed Supplies")
    assert isinstance(plan_voucher(v, FACTS), Skip)


def test_a_nil_or_single_line_voucher_is_skipped():
    assert isinstance(plan_voucher(voucher("Journal", [("Rent", 0, False), ("Cash", 0, False)]), FACTS), Skip)
    assert isinstance(plan_voucher(voucher("Journal", [("Rent", 0, False)]), FACTS), Skip)
```

- [ ] **Step 2: Run to verify they fail**

Run: `python -m pytest ledger/tests/test_tally_plan.py -q`
Expected: `ModuleNotFoundError: ledger.tally_plan`.

- [ ] **Step 3: Implement** `ledger/tally_plan.py`

```python
"""What a parsed Tally voucher becomes in the books. Pure: the chart arrives as :class:`Facts`, never the ORM.

The lines are **never rebuilt**. The books must equal Tally's, so a voucher is written with exactly the lines it had and the
bill's figures are *derived* from them. Where they cannot be derived (the lines do not tie to a taxable value, tax and
round-off), the voucher is still written -- the money is right -- and the bill is left out with a note.
"""

from __future__ import annotations

from dataclasses import dataclass

from classify.models import LedgerGroup as G
from ledger.models import BillKind, EntryKind, VoucherType
from ledger.tally_parse import normal_name
from ledger.tally_vouchers import ParsedVoucher

_TYPES = {
    "sales": VoucherType.SALES,
    "purchase": VoucherType.PURCHASE,
    "credit note": VoucherType.CREDIT_NOTE,
    "debit note": VoucherType.DEBIT_NOTE,
    "journal": VoucherType.JOURNAL,
    "payment": VoucherType.PAYMENT,
    "receipt": VoucherType.RECEIPT,
    "contra": VoucherType.CONTRA,
}
_BILL = {
    VoucherType.SALES: (BillKind.SALES, G.DEBTOR, +1),
    VoucherType.CREDIT_NOTE: (BillKind.CREDIT_NOTE, G.DEBTOR, -1),
    VoucherType.PURCHASE: (BillKind.PURCHASE, G.CREDITOR, -1),
    VoucherType.DEBIT_NOTE: (BillKind.DEBIT_NOTE, G.CREDITOR, +1),
}
# The party line's sign the books expect: a sale debits the customer, a purchase credits the supplier. A credit note
# credits the customer; a debit note debits the supplier.
_EXPECTED_SIGN = {
    VoucherType.SALES: +1, VoucherType.CREDIT_NOTE: -1, VoucherType.PURCHASE: -1, VoucherType.DEBIT_NOTE: +1,
}
_ROUND_OFF = ("round off", "rounding", "round-off", "rounded off")


@dataclass(frozen=True)
class Facts:
    groups: dict[str, str]
    bank_ledgers: frozenset[str]


@dataclass(frozen=True)
class BillFigures:
    kind: str
    party_ledger: str
    taxable_paise: int
    cgst_paise: int
    sgst_paise: int
    igst_paise: int
    cess_paise: int
    round_off_paise: int
    total_paise: int


@dataclass(frozen=True)
class Planned:
    voucher: ParsedVoucher
    voucher_type: str
    entry_kind: str
    bill: BillFigures | None
    note: str = ""


@dataclass(frozen=True)
class Skip:
    voucher: ParsedVoucher
    reason: str


def plan_voucher(v: ParsedVoucher, facts: Facts) -> Planned | Skip:
    vtype = _TYPES.get(normal_name(v.tally_type))
    if vtype is None:
        return Skip(v, "This voucher type is not imported.")
    for line in v.lines:
        if normal_name(line.ledger) not in facts.groups:
            return Skip(v, f"The ledger {line.ledger!r} is not in the client's chart. Import the masters first.")
    if len(v.lines) < 2:
        return Skip(v, "The voucher has fewer than two lines.")
    if any(line.signed_paise == 0 for line in v.lines):
        return Skip(v, "The voucher has a line with no amount.")
    if sum(line.signed_paise for line in v.lines) != 0:
        return Skip(v, "The voucher does not balance.")

    if vtype in (VoucherType.PAYMENT, VoucherType.RECEIPT, VoucherType.CONTRA):
        if any(normal_name(line.ledger) in facts.bank_ledgers for line in v.lines):
            return Skip(v, "Bank vouchers are imported in a later release.")
        return Planned(v, vtype, EntryKind.JOURNAL, None)
    if vtype == VoucherType.JOURNAL:
        return Planned(v, vtype, EntryKind.JOURNAL, None)

    return _invoice(v, vtype, facts)


def _party_line(v: ParsedVoucher, facts: Facts, side: str):
    flagged = [l for l in v.lines if l.is_party]
    candidates = flagged or [l for l in v.lines if normal_name(l.ledger) == normal_name(v.party)]
    candidates = [l for l in candidates if facts.groups.get(normal_name(l.ledger)) == side]
    return candidates[0] if len(candidates) == 1 else None


def _invoice(v: ParsedVoucher, vtype: str, facts: Facts) -> Planned | Skip:
    kind, side, _ = _BILL[vtype]
    expected = _EXPECTED_SIGN[vtype]
    party = _party_line(v, facts, side)
    if party is None:
        return Planned(v, vtype, EntryKind.VOUCHER, None)  # a cash sale, or a voucher with no single party: a plain voucher
    if (party.signed_paise > 0) != (expected > 0):
        word = {VoucherType.SALES: "sale", VoucherType.PURCHASE: "purchase"}.get(vtype, vtype.lower())
        return Skip(v, f"The party line is on the wrong side for a {word}.")
    if not (v.number or v.reference):
        return Planned(v, vtype, EntryKind.VOUCHER, None, note="No invoice number, so no bill was made.")

    taxable = cgst = sgst = igst = cess = 0
    round_off = 0
    for line in v.lines:
        if line is party:
            continue
        key = normal_name(line.ledger)
        group = facts.groups[key]
        # Money against the party's grain is a head, tax or round-off; the sign tells which way it moves the total.
        amount = -line.signed_paise * expected  # positive when it adds to what the party carries
        if group == G.DUTIES_AND_TAXES and "cgst" in key:
            cgst += amount
        elif group == G.DUTIES_AND_TAXES and ("sgst" in key or "utgst" in key):
            sgst += amount
        elif group == G.DUTIES_AND_TAXES and "igst" in key:
            igst += amount
        elif group == G.DUTIES_AND_TAXES and "cess" in key:
            cess += amount
        elif key in _ROUND_OFF:
            round_off += amount
        else:
            taxable += amount
    total = abs(party.signed_paise)
    if min(taxable, cgst, sgst, igst, cess) < 0 or taxable <= 0 or taxable + cgst + sgst + igst + cess + round_off != total:
        return Planned(v, vtype, EntryKind.VOUCHER, None, note="The lines do not tie to a taxable value, tax and round-off, so no bill was made.")
    return Planned(v, vtype, EntryKind.VOUCHER, BillFigures(kind, party.ledger, taxable, cgst, sgst, igst, cess, round_off, total))
```

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest ledger/tests/test_tally_plan.py -q`
Expected: all pass. (`LedgerGroup.CASH`, `.BANK`, `.DEBTOR`, `.CREDITOR`, `.SALES`, `.PURCHASE`, `.DUTIES_AND_TAXES`, `.INDIRECT_EXPENSE` all exist, verified in `ledger/tally_parse.py`'s `TALLY_GROUPS`.)

- [ ] **Step 5: Commit**

```bash
git add ledger/tally_plan.py ledger/tests/test_tally_plan.py
git commit -m "Tally vouchers: decide what a voucher becomes (entry kind, bill figures, or a reason to skip), as a pure planner"
```

---

### Task 3: The link table and the migration

**Files:**
- Modify: `ledger/models.py` (add `ImportKind.VOUCHERS`; add `TallyVoucher`)
- Create: `ledger/migrations/0034_tally_vouchers.py`, `ledger/migrations/0035_tally_vouchers_security.py`
- Test: `ledger/tests/test_tally_voucher_import.py` (first test only; extended in Task 4)

**Interfaces:**
- Produces:
  ```python
  class TallyVoucher(UUIDModel, FirmScopedModel):
      client = FK(Client, CASCADE, related_name="tally_vouchers")
      run = FK(LedgerImportRun, null=True, SET_NULL, related_name="vouchers")
      guid = CharField(max_length=100)
      tally_type = CharField(max_length=64)
      tally_number = CharField(max_length=64, blank=True)
      entry = OneToOneField(JournalEntry, PROTECT, related_name="tally_voucher")
      # Meta: db_table "ledger_tally_voucher"; UniqueConstraint(firm, client, guid, name="uniq_tally_guid_per_client")
  ```
- `ImportKind.VOUCHERS = "VOUCHERS", "Vouchers"`; `LedgerImportRun.kind` max_length is 16 (fits).

- [ ] **Step 1: Write the failing test** (append to a new `ledger/tests/test_tally_voucher_import.py`)

```python
"""Staging and applying a Tally vouchers import: posting, idempotence, locks, refusals, undo, isolation."""

from __future__ import annotations

import datetime

import pytest
from django.db import IntegrityError, transaction

from core.db.session import firm_context
from core.provisioning import create_client, create_firm
from ledger.models import ImportKind, TallyVoucher

pytestmark = pytest.mark.django_db

FY = 2025
START = datetime.date(2025, 4, 1)


@pytest.fixture
def firm():
    return create_firm("Voucher Firm")


@pytest.fixture
def client(firm):
    return create_client(firm, "Voucher Client", START)


def test_the_link_table_is_one_row_per_guid_per_client(firm, client):
    assert ImportKind.VOUCHERS == "VOUCHERS"
    names = {c.name for c in TallyVoucher._meta.constraints}
    assert "uniq_tally_guid_per_client" in names
```

- [ ] **Step 2: Run to verify it fails**

Run: `python -m pytest ledger/tests/test_tally_voucher_import.py -q`
Expected: `ImportError: cannot import name 'TallyVoucher'`. (DB tests do not run locally; this one only needs the import and `_meta`, but `pytestmark django_db` needs a database. If the local test database times out as it has before, run it in CI by pushing nothing yet: instead run `python -c "import django, os; os.environ['DJANGO_SETTINGS_MODULE']='config.settings.test'; django.setup(); from ledger.models import ImportKind"` to check the import, and rely on CI for the DB run.)

- [ ] **Step 3: Add the model** to `ledger/models.py`, after `LedgerOpening`

```python
class TallyVoucher(UUIDModel, FirmScopedModel):
    """A voucher that came from Tally, and the entry it became.

    It is what makes a second upload of the same file import nothing (one row per Tally GUID per client) and what lets a
    whole run be undone. The Tally number is a string and is kept here, because ``JournalEntry.entry_no`` is AutoCA's own
    integer series.
    """

    client = models.ForeignKey(Client, on_delete=models.CASCADE, related_name="tally_vouchers")
    run = models.ForeignKey(LedgerImportRun, null=True, blank=True, on_delete=models.SET_NULL, related_name="vouchers")
    guid = models.CharField(max_length=100)
    tally_type = models.CharField(max_length=64)
    tally_number = models.CharField(max_length=64, blank=True)
    entry = models.OneToOneField(JournalEntry, on_delete=models.PROTECT, related_name="tally_voucher")

    class Meta:
        db_table = "ledger_tally_voucher"
        constraints = [
            models.UniqueConstraint(fields=["firm", "client", "guid"], name="uniq_tally_guid_per_client"),
        ]
        indexes = [models.Index(fields=["firm", "client", "run"], name="idx_tally_voucher_run")]
```

and add to `ImportKind`:

```python
    VOUCHERS = "VOUCHERS", "Vouchers"
```

- [ ] **Step 4: Generate the migration** and rename it

Run: `python manage.py makemigrations ledger -n tally_vouchers`
Expected: creates `ledger/migrations/0034_tally_vouchers.py` (number may differ; use the next number after `0033_stock_items_security`). Open it, and as in `0009_tally_import_tables.py` put `*ddl_tenant_context_operations()` first in `operations` (import it from `core.db.rls`).

- [ ] **Step 5: Write the security migration** `ledger/migrations/0035_tally_vouchers_security.py`

```python
"""Tenant isolation for the Tally voucher links, and the client boundary inside a firm.

A link names an entry and a run; both must belong to the link's own client, checked by composite foreign keys, as in
0010. Additive only: constraints on a table this release creates.
"""

from django.db import migrations

from core.db.rls import ddl_tenant_context_operations, rls_operations

FORWARD = [
    "ALTER TABLE ledger_tally_voucher ADD CONSTRAINT tally_voucher_run_same_client "
    "FOREIGN KEY (client_id, run_id) REFERENCES ledger_import_run (client_id, id) "
    "ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;",
    "ALTER TABLE ledger_tally_voucher ADD CONSTRAINT tally_voucher_entry_same_client "
    "FOREIGN KEY (client_id, entry_id) REFERENCES ledger_journal_entry (client_id, id) "
    "ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;",
]
REVERSE = [
    "ALTER TABLE ledger_tally_voucher DROP CONSTRAINT tally_voucher_entry_same_client;",
    "ALTER TABLE ledger_tally_voucher DROP CONSTRAINT tally_voucher_run_same_client;",
]


class Migration(migrations.Migration):
    dependencies = [("ledger", "0034_tally_vouchers")]

    operations = [
        *ddl_tenant_context_operations(),
        migrations.RunSQL(sql=FORWARD, reverse_sql=REVERSE),
        *rls_operations("ledger_tally_voucher"),
    ]
```

The entry key needs a unique `(client_id, id)` on `ledger_journal_entry`. Check first: `grep -rn "client_id, id" ledger/migrations/0004*`. If that constraint already exists (migration 0004 makes journal lines stay in one client's books, so it very likely does), keep the SQL above. If it does not, add `"ALTER TABLE ledger_journal_entry ADD CONSTRAINT uniq_entry_client_id UNIQUE (client_id, id);"` to `FORWARD` (and its drop to `REVERSE`) before the entry key.

- [ ] **Step 6: Check the migrations apply and the model matches**

Run: `python manage.py makemigrations --check --dry-run` → "No changes detected".
Run (CI covers the apply): `python manage.py migrate --plan | tail -5` lists both new migrations.

- [ ] **Step 7: Run the test, commit**

Run: `python -m pytest ledger/tests/test_tally_voucher_import.py -q` (CI if the local DB times out)
Expected: pass.

```bash
git add ledger/models.py ledger/migrations/0034_tally_vouchers.py ledger/migrations/0035_tally_vouchers_security.py ledger/tests/test_tally_voucher_import.py
git commit -m "Tally vouchers: a link table (one row per Tally GUID per client) with row-level security and client-boundary keys"
```

---

### Task 4: Staging a preview

**Files:**
- Create: `ledger/tally_voucher_import.py`
- Modify: `ledger/tests/test_tally_voucher_import.py`

**Interfaces:**
- Consumes: `parse_vouchers`, `plan_voucher`, `Facts`, `Planned`, `Skip`, `LedgerImportRun`, `ImportKind.VOUCHERS`, `editing.locked_through`, `core.access.require_chart_import`.
- Produces:
  ```python
  def stage_vouchers(client, membership, user, *, data: bytes, filename: str,
                     date_from: datetime.date | None = None, date_to: datetime.date | None = None
                     ) -> tuple[LedgerImportRun, bool]   # (run, reused)
  ```
  The run has `kind=VOUCHERS`, `financial_year` = the FY of its earliest voucher, `counts` = `{"vouchers": n, "will_post": n, "will_make_bill": n, "skipped": n, "by_type": {...}, "bank_waiting": n, "date_from": "...", "date_to": "..."}`, and `rows` = one dict per voucher: `{"ordinal", "guid", "type", "number", "date", "party", "total_paise", "action": "post"|"skip", "bill": bool, "reason": str, "note": str}`. `chart_stamp` is `ledger.tally_import.chart_stamp(client, fy)`.
- Raises: `TallyImportError` (from `ledger.tally_import`) for: more than one company in the file; a date range containing any `JournalEntry` for the client; a range reaching `locked_through`.

- [ ] **Step 1: Write failing tests** (append)

```python
from core.models import Client, FirmMembership, Role, User
from ledger.tally_import import TallyImportError
from ledger.tally_voucher_import import stage_vouchers
from ledger.tests.support import make_ledger, post
from ledger.tests.tally_voucher_xml import line, voucher, vouchers_xml
from classify.models import LedgerGroup as G


def member(firm, role, email):
    user = User.objects.create_user(email=email, password="correct-horse-battery")
    with firm_context(firm.pk):
        return FirmMembership.objects.create(firm=firm, user=user, role=role)


@pytest.fixture
def senior(firm, client):
    membership = member(firm, Role.SENIOR_CA, "lead@example.test")
    with firm_context(firm.pk):
        Client.objects.filter(pk=client.pk).update(lead=membership)
    client.lead = membership
    return membership


@pytest.fixture
def chart(firm, client):
    with firm_context(firm.pk):
        for name, group in [("Acme Traders", G.DEBTOR), ("Sales", G.SALES), ("Output CGST", G.DUTIES_AND_TAXES),
                            ("Output SGST", G.DUTIES_AND_TAXES), ("Cash", G.CASH), ("Rent", G.INDIRECT_EXPENSE), ("Bank One", G.BANK)]:
            make_ledger(client, name, group)
        yield


def sale(guid="g1", number="1", date="20250401"):
    return voucher(guid=guid, vtype="Sales", number=number, date=date, party="Acme Traders",
                   lines=[line("Acme Traders", 1180.0, party=True), line("Sales", -1000.0), line("Output CGST", -90.0), line("Output SGST", -90.0)])


def stage(client, senior, vouchers, **kw):
    return stage_vouchers(client, senior, senior.user, data=vouchers_xml(vouchers), filename="v.xml", **kw)


def test_preview_counts_and_writes_only_the_run(firm, client, senior, chart):
    bad = voucher(guid="g2", vtype="Journal", number="2", date="20250402", lines=[line("Rent", 10.0), line("Ghost", -10.0)])
    bank = voucher(guid="g3", vtype="Payment", number="3", date="20250403", lines=[line("Rent", 10.0), line("Bank One", -10.0)])
    run, reused = stage(client, senior, [sale(), bad, bank])
    assert reused is False
    assert run.kind == "VOUCHERS" and run.status == "PREVIEW" and run.financial_year == FY
    assert run.counts["vouchers"] == 3 and run.counts["will_post"] == 1 and run.counts["will_make_bill"] == 1
    assert run.counts["skipped"] == 2 and run.counts["bank_waiting"] == 1
    reasons = {r["guid"]: r["reason"] for r in run.rows if r["action"] == "skip"}
    assert "Ghost" in reasons["g2"] and "later release" in reasons["g3"]
    from ledger.models import JournalEntry
    assert JournalEntry.objects.filter(client=client).count() == 0


def test_the_same_file_is_the_same_preview(firm, client, senior, chart):
    first, _ = stage(client, senior, [sale()])
    second, reused = stage(client, senior, [sale()])
    assert reused is True and second.pk == first.pk


def test_a_range_with_postings_is_refused(firm, client, senior, chart):
    post(client, datetime.date(2025, 4, 5), make_ledger(client, "Rent", G.INDIRECT_EXPENSE), make_ledger(client, "Cash", G.CASH), 100)
    with pytest.raises(TallyImportError):
        stage(client, senior, [sale(date="20250401"), sale("g9", "9", "20250410")])


def test_two_companies_are_refused(firm, client, senior, chart):
    data = vouchers_xml([sale()], company="ONE").replace(b"</REQUESTDESC>", b"<STATICVARIABLES><SVCURRENTCOMPANY>TWO</SVCURRENTCOMPANY></STATICVARIABLES></REQUESTDESC>")
    with pytest.raises(TallyImportError):
        stage_vouchers(client, senior, senior.user, data=data, filename="v.xml")


def test_only_the_leads_and_admins_may_stage(firm, client, chart):
    junior = member(firm, Role.CA_ASSISTANT if hasattr(Role, "CA_ASSISTANT") else Role.SENIOR_CA, "other@example.test")
    with pytest.raises(Exception):
        stage_vouchers(client, junior, junior.user, data=vouchers_xml([sale()]), filename="v.xml")
```

If `Role.CA_ASSISTANT` does not exist, replace that line with a role that is not allowed `ledger.import` (look at `core/rbac.py`); the intent is "a member who is not the client's lead or a firm administrator is refused by `_require_rights`".

- [ ] **Step 2: Run to verify they fail**

Run (CI; or locally if the DB works): `python -m pytest ledger/tests/test_tally_voucher_import.py -q`
Expected: `ModuleNotFoundError: ledger.tally_voucher_import`.

- [ ] **Step 3: Implement** `ledger/tally_voucher_import.py` (staging half)

```python
"""Bringing a client's Tally vouchers in, exactly as Tally had them.

Same shape as ``ledger.tally_import``: staging is mutable and the books are not. ``stage_vouchers`` reads the file, plans
every voucher, and writes one :class:`~ledger.models.LedgerImportRun` -- a preview, nothing else. ``confirm_vouchers`` (below)
writes each voucher in its own transaction. Nothing here logs a name; the run records counts and who.
"""

from __future__ import annotations

import datetime
import hashlib

from django.conf import settings
from django.utils import timezone

from classify.models import LedgerAccount, LedgerGroup
from core.fy import financial_year
from ledger import editing
from ledger.models import ImportKind, ImportStatus, JournalEntry, LedgerImportRun
from ledger.tally_import import PREVIEW_LIFETIME, TallyImportError, _refuse_if_locked, _require_rights, chart_stamp
from ledger.tally_parse import normal_name
from ledger.tally_plan import Facts, Planned, plan_voucher
from ledger.tally_vouchers import parse_vouchers

_BANKS = (LedgerGroup.BANK, LedgerGroup.BANK_OD)


def _facts(client) -> Facts:
    rows = list(LedgerAccount.objects.filter(firm_id=client.firm_id, client=client).values_list("name", "group"))
    groups = {}
    for name, group in rows:
        groups.setdefault(normal_name(name), group)
    banks = frozenset(normal_name(n) for n, g in rows if g in _BANKS)
    return Facts(groups=groups, bank_ledgers=banks)


def stage_vouchers(client, membership, user, *, data: bytes, filename: str, date_from=None, date_to=None):
    _require_rights(membership, client)
    digest = hashlib.sha256(data).hexdigest()
    parsed = parse_vouchers(data, filename, max_bytes=settings.MAX_TALLY_IMPORT_BYTES)
    if len(parsed.companies) > 1:
        raise TallyImportError("This file has vouchers from more than one company. Export one company at a time.")
    vouchers = [v for v in parsed.vouchers if (date_from is None or v.date >= date_from) and (date_to is None or v.date <= date_to)]
    if not vouchers:
        raise TallyImportError("There are no vouchers to import in this file for that period.")
    first, last = min(v.date for v in vouchers), max(v.date for v in vouchers)
    year = financial_year(first)

    through = editing.locked_through(client.pk)
    if through is not None and first <= through:
        raise TallyImportError(
            f"The books are signed off through {through:%d-%m-%Y}, so vouchers dated from {first:%d-%m-%Y} cannot be imported."
        )
    if JournalEntry.objects.filter(client=client, entry_date__gte=first, entry_date__lte=last).exists():
        raise TallyImportError(
            f"This client already has entries between {first:%d-%m-%Y} and {last:%d-%m-%Y}. History can only be imported "
            f"into a period with nothing posted."
        )
    _refuse_if_locked(client, year)

    stamp = chart_stamp(client, year)
    existing = LedgerImportRun.objects.filter(
        firm_id=client.firm_id, client=client, kind=ImportKind.VOUCHERS, file_sha256=digest, status=ImportStatus.PREVIEW,
        chart_stamp=stamp, expires_at__gt=timezone.now(),
    ).first()
    if existing is not None:
        return existing, True

    facts = _facts(client)
    rows, counts = [], {"vouchers": 0, "will_post": 0, "will_make_bill": 0, "skipped": 0, "bank_waiting": 0, "by_type": {}}
    for v in vouchers:
        plan = plan_voucher(v, facts)
        counts["vouchers"] += 1
        counts["by_type"][v.tally_type] = counts["by_type"].get(v.tally_type, 0) + 1
        total = sum(l.signed_paise for l in v.lines if l.signed_paise > 0)
        row = {"ordinal": v.ordinal, "guid": v.guid, "type": v.tally_type, "number": v.number, "date": v.date.isoformat(),
               "party": v.party, "total_paise": total, "action": "post", "bill": False, "reason": "", "note": ""}
        if isinstance(plan, Planned):
            counts["will_post"] += 1
            row["bill"] = plan.bill is not None
            row["note"] = plan.note
            counts["will_make_bill"] += 1 if plan.bill else 0
        else:
            row["action"], row["reason"] = "skip", plan.reason
            counts["skipped"] += 1
            counts["bank_waiting"] += 1 if "later release" in plan.reason else 0
        rows.append(row)
    for s in parsed.skipped:
        counts["skipped"] += 1
        rows.append({"ordinal": s.ordinal, "guid": "", "type": "", "number": s.name, "date": "", "party": "", "total_paise": 0,
                     "action": "skip", "bill": False, "reason": s.reason, "note": ""})
    counts["date_from"], counts["date_to"] = first.isoformat(), last.isoformat()

    run = LedgerImportRun.objects.create(
        firm_id=client.firm_id, client=client, kind=ImportKind.VOUCHERS, financial_year=year, uploaded_by=user,
        file_sha256=digest, source_format="xml", include_openings=False, books_from=first, counts=counts, rows=rows,
        chart_stamp=stamp, expires_at=timezone.now() + PREVIEW_LIFETIME,
    )
    return run, False
```

`_refuse_if_locked(client, year)` and `_require_rights` are the masters importer's private helpers (`ledger/tally_import.py:645,650`); importing them is deliberate so both importers share one rule. If their signatures differ from `(membership, client)` / `(client, financial_year)`, adapt the calls to match the file.

- [ ] **Step 4: Run to verify they pass**

Run: `python -m pytest ledger/tests/test_tally_voucher_import.py -q` (CI)
Expected: pass.

- [ ] **Step 5: Commit**

```bash
git add ledger/tally_voucher_import.py ledger/tests/test_tally_voucher_import.py
git commit -m "Tally vouchers: stage a preview (counts, per-voucher action and reason); refuse a period with postings, a locked year, or two companies"
```

---

### Task 5: Confirm: the faithful writer

**Files:**
- Modify: `ledger/tally_voucher_import.py`, `ledger/tests/test_tally_voucher_import.py`

**Interfaces:**
- Consumes: Task 4's run; `ledger.approval.allocate_voucher_number`; `ledger.billing.party_ledger_for`, `invoice_key`, `supplier_identity` (from `core.identity`); `Party`, `PartyRole`, `Bill`, `JournalEntry`, `JournalLine.build`, `EntryMarker`.
- Produces:
  ```python
  def confirm_vouchers(run: LedgerImportRun, membership, user) -> LedgerImportRun
  ```
  Idempotent: confirming a CONFIRMED run returns it. `run.result` = `{"posted": n, "bills": n, "skipped": n, "failed": [{"guid","reason"}...]}`. Raises `TallyRunStaleError` when the chart changed since the preview.

Behaviour:
1. `_require_rights`; refuse if the run is not VOUCHERS or is DISCARDED/expired (`TallyImportError`); `TallyRunStaleError` if `chart_stamp(client, fy) != run.chart_stamp`.
2. Re-parse is **not** possible (no file kept), so the preview rows must carry everything needed. **Add to each `post` row** the planned data: `"lines": [[ledger_name, signed_paise], ...]`, `"voucher_type"`, `"entry_kind"`, `"narration"`, `"gstin"`, `"own_gstin"`, `"reference"`, and `"bill": {BillFigures as dict} | None`. Update Task 4's row builder to include them (the rows already hold only what the import needs; no file is kept, as with the masters run). Add a test in Task 4's file that a staged row carries `lines`.
3. For each `post` row, in order of date then ordinal, in `transaction.atomic()`:
   - skip if a `TallyVoucher` with that guid exists for the client (already imported);
   - `through = editing.locked_through`; if the date is inside it, record as failed;
   - resolve ledgers by `normal_name` against a dict built once;
   - create the `JournalEntry` (`entry_no=allocate_voucher_number(client, financial_year(date), voucher_type)`, `entry_kind`, `narration` = Tally narration or `f"{type} {number} (from Tally)"`, `approved_by=user`, `approved_at=now`, `marker=EntryMarker.NONE`);
   - create the lines with `JournalLine.build(entry=..., ledger_account=..., direction=DR if signed>0 else CR, amount_paise=abs(signed))`; the party line also gets `party=` (below);
   - when `bill` is not None: find or create the `Party` (`canonical_name` = the party ledger's name; `role` CUSTOMER for sales/credit note, VENDOR for purchase/debit note; GSTIN set with `set_gstin` if present and valid-looking), link the ledger (`party.ledger = that ledger` only if it has no party yet), create the `Bill` with the derived figures, `booked_on=date`, `financial_year`, `invoice_key = invoice_key(client.firm_id, identity, reference)` where `reference = number or reference` (max 64) and `identity` is built as in `_post` (`supplier_identity(party.gstin, party.pk)` for purchases/debit notes, `supplier_identity(own_gstin, client.pk)` for sales/credit notes), `own_gstin_hash` as in `_post`, `due_date=None`, `document=None`;
   - create `TallyVoucher(entry=..., guid, tally_type, tally_number, run)`.
   - A bill that hits `uniq_bill_per_invoice` (the same invoice number twice in a year) is **not** a failure of the voucher: create the entry without the bill, and add the reason to `failed` as a note "bill not made: duplicate invoice number".
   - Any other exception: that voucher is rolled back (its own savepoint), listed in `failed` with the reason; the run goes on.
4. Mark the run CONFIRMED with `confirmed_by`, `confirmed_at`, and `result`.

- [ ] **Step 1: Failing tests**

```python
from ledger.models import Bill, JournalEntry, JournalLine, TallyVoucher
from ledger.tally_voucher_import import confirm_vouchers


def test_confirm_posts_exactly_the_tally_lines_and_makes_the_bill(firm, client, senior, chart):
    run, _ = stage(client, senior, [sale()])
    done = confirm_vouchers(run, senior, senior.user)
    assert done.status == "CONFIRMED" and done.result["posted"] == 1 and done.result["bills"] == 1
    entry = JournalEntry.objects.get(client=client)
    assert entry.voucher_type == "Sales" and entry.entry_kind == "VOUCHER"
    got = sorted((l.ledger_account.name, l.signed_paise) for l in entry.lines.select_related("ledger_account"))
    assert got == sorted([("Acme Traders", 118000), ("Sales", -100000), ("Output CGST", -9000), ("Output SGST", -9000)])
    bill = Bill.objects.get(client=client)
    assert (bill.kind, bill.reference, bill.taxable_paise, bill.cgst_paise, bill.total_paise, bill.entry_id) == ("SALES", "1", 100000, 9000, 118000, entry.pk)
    assert bill.party.canonical_name == "Acme Traders" and bill.party.ledger.name == "Acme Traders"
    assert TallyVoucher.objects.get(client=client).guid == "g1"


def test_a_second_confirm_and_a_second_upload_post_nothing_more(firm, client, senior, chart):
    run, _ = stage(client, senior, [sale()])
    confirm_vouchers(run, senior, senior.user)
    again = confirm_vouchers(run, senior, senior.user)
    assert again.status == "CONFIRMED" and JournalEntry.objects.filter(client=client).count() == 1


def test_a_cash_sale_posts_with_no_bill_and_no_party(firm, client, senior, chart):
    v = voucher(guid="c1", vtype="Sales", number="5", date="20250402", party="Cash", lines=[line("Cash", 500.0, party=True), line("Sales", -500.0)])
    run, _ = stage(client, senior, [v])
    confirm_vouchers(run, senior, senior.user)
    assert JournalEntry.objects.filter(client=client).count() == 1 and Bill.objects.filter(client=client).count() == 0


def test_a_journal_posts_as_a_journal_entry(firm, client, senior, chart):
    v = voucher(guid="j1", vtype="Journal", number="7", date="20250403", lines=[line("Rent", 100.0), line("Cash", -100.0)], narration="Rent for April")
    run, _ = stage(client, senior, [v])
    confirm_vouchers(run, senior, senior.user)
    e = JournalEntry.objects.get(client=client)
    assert (e.entry_kind, e.voucher_type, e.narration) == ("JOURNAL", "Journal", "Rent for April")


def test_the_same_tally_number_in_two_types_does_not_collide(firm, client, senior, chart):
    j = voucher(guid="j1", vtype="Journal", number="1", date="20250403", lines=[line("Rent", 100.0), line("Cash", -100.0)])
    run, _ = stage(client, senior, [sale(number="1"), j])
    confirm_vouchers(run, senior, senior.user)
    assert JournalEntry.objects.filter(client=client).count() == 2


def test_a_duplicate_invoice_number_posts_the_entry_without_a_second_bill(firm, client, senior, chart):
    run, _ = stage(client, senior, [sale("g1", "1"), sale("g2", "1", "20250402")])
    done = confirm_vouchers(run, senior, senior.user)
    assert JournalEntry.objects.filter(client=client).count() == 2 and Bill.objects.filter(client=client).count() == 1
    assert any("duplicate" in f["reason"].lower() for f in done.result["failed"])


def test_a_changed_chart_makes_the_preview_stale(firm, client, senior, chart):
    from ledger.tally_import import TallyRunStaleError
    run, _ = stage(client, senior, [sale()])
    make_ledger(client, "A new ledger", G.INDIRECT_EXPENSE)
    with pytest.raises(TallyRunStaleError):
        confirm_vouchers(run, senior, senior.user)


def test_a_signed_off_date_is_not_posted(firm, client, senior, chart, monkeypatch):
    run, _ = stage(client, senior, [sale()])
    monkeypatch.setattr("ledger.editing.locked_through", lambda client_id: datetime.date(2025, 4, 30))
    done = confirm_vouchers(run, senior, senior.user)
    assert done.result["posted"] == 0 and done.result["failed"]


def test_another_firm_cannot_see_or_confirm_the_run(firm, client, senior, chart):
    run, _ = stage(client, senior, [sale()])
    other = create_firm("Other Firm")
    from ledger.models import LedgerImportRun
    with firm_context(other.pk):
        assert LedgerImportRun.objects.filter(pk=run.pk).count() == 0
```

- [ ] **Step 2: Run to verify they fail**

Run (CI): `python -m pytest ledger/tests/test_tally_voucher_import.py -q`
Expected: `ImportError: cannot import name 'confirm_vouchers'`.

- [ ] **Step 3: Update Task 4's row builder** to carry the plan. In `stage_vouchers`, replace the `if isinstance(plan, Planned):` block's row updates with:

```python
        if isinstance(plan, Planned):
            counts["will_post"] += 1
            row["bill"] = plan.bill is not None
            row["note"] = plan.note
            row["voucher_type"], row["entry_kind"] = plan.voucher_type, plan.entry_kind
            row["lines"] = [[l.ledger, l.signed_paise] for l in v.lines]
            row["party_line"] = next((l.ledger for l in v.lines if l.is_party), v.party)
            row["narration"], row["reference"] = v.narration, v.reference
            row["gstin"], row["own_gstin"] = v.party_gstin, v.own_gstin
            row["figures"] = dataclasses.asdict(plan.bill) if plan.bill else None
            counts["will_make_bill"] += 1 if plan.bill else 0
```

(add `import dataclasses` at the top). A run's `rows` JSON for a very large file is large; `MAX_VOUCHERS = 200_000` bounds it, and `TallyImportDetailSerializer` must not return `lines`/`figures` to the browser (Task 7 trims them).

- [ ] **Step 4: Implement `confirm_vouchers`** (append to `ledger/tally_voucher_import.py`)

```python
import dataclasses  # at the top with the other imports

from django.db import IntegrityError, transaction

from classify.models import Party, PartyRole
from core.crypto import blind_index, normalise_gstin  # use the same imports ledger/billing.py uses for these two names
from core.identity import invoice_key, supplier_identity  # as in ledger/billing.py
from ledger.approval import allocate_voucher_number
from ledger.models import Bill, BillKind, Direction, EntryMarker, JournalLine, TallyVoucher
from ledger.tally_import import TallyRunStaleError


def confirm_vouchers(run: LedgerImportRun, membership, user) -> LedgerImportRun:
    client = run.client
    _require_rights(membership, client)
    if run.kind != ImportKind.VOUCHERS:
        raise TallyImportError("This is not a vouchers import.")
    if run.status == ImportStatus.CONFIRMED:
        return run
    if run.status != ImportStatus.PREVIEW or run.expires_at <= timezone.now():
        raise TallyImportError("This preview has expired. Upload the file again.")
    if chart_stamp(client, run.financial_year) != run.chart_stamp:
        raise TallyRunStaleError("The client's ledgers changed since this preview was made. Upload the file again.")

    ledgers = {normal_name(l.name): l for l in LedgerAccount.objects.filter(firm_id=client.firm_id, client=client)}
    done = set(TallyVoucher.objects.filter(firm_id=client.firm_id, client=client).values_list("guid", flat=True))
    result = {"posted": 0, "bills": 0, "skipped": 0, "failed": []}
    todo = sorted((r for r in run.rows if r["action"] == "post"), key=lambda r: (r["date"], r["ordinal"]))
    for row in todo:
        if row["guid"] in done:
            result["skipped"] += 1
            continue
        try:
            with transaction.atomic():
                made_bill = _write(client, user, run, row, ledgers)
        except _Refused as exc:
            result["failed"].append({"guid": row["guid"], "reason": str(exc)})
            continue
        except Exception:  # one voucher must not stop the rest; its own savepoint has rolled back
            result["failed"].append({"guid": row["guid"], "reason": "The voucher could not be written."})
            continue
        result["posted"] += 1
        result["bills"] += 1 if made_bill else 0
        if made_bill is None:
            result["failed"].append({"guid": row["guid"], "reason": "Posted, but no bill was made: a duplicate invoice number."})
    run.status = ImportStatus.CONFIRMED
    run.result = result
    run.confirmed_by, run.confirmed_at = user, timezone.now()
    run.save(update_fields=["status", "result", "confirmed_by", "confirmed_at"])
    return run


class _Refused(Exception):
    """A rule stopped this one voucher. The message is shown against it."""


def _write(client, user, run, row, ledgers) -> bool | None:
    """Write one voucher. Returns True when a bill was made, False when none was meant, None when a bill clashed."""
    date = datetime.date.fromisoformat(row["date"])
    through = editing.locked_through(client.pk)
    if through is not None and date <= through:
        raise _Refused(f"The books are signed off through {through:%d-%m-%Y}.")
    year = financial_year(date)
    entry = JournalEntry.objects.create(
        firm_id=client.firm_id, client=client, entry_no=allocate_voucher_number(client, year, row["voucher_type"]),
        financial_year=year, entry_date=date, voucher_type=row["voucher_type"], entry_kind=row["entry_kind"],
        narration=row["narration"] or f"{row['type']} {row['number']} (from Tally)".strip(),
        approved_by=user, approved_at=timezone.now(), marker=EntryMarker.NONE,
    )
    figures = row.get("figures")
    party = _party_for(client, row, ledgers) if figures else None
    lines = []
    for name, signed in row["lines"]:
        ledger = ledgers[normal_name(name)]
        is_party = party is not None and normal_name(name) == normal_name(figures["party_ledger"])
        lines.append(JournalLine.build(
            entry=entry, ledger_account=ledger, party=party if is_party else None,
            direction=Direction.DEBIT if signed > 0 else Direction.CREDIT, amount_paise=abs(signed),
        ))
    JournalLine.objects.bulk_create(lines)
    TallyVoucher.objects.create(
        firm_id=client.firm_id, client=client, run=run, guid=row["guid"], tally_type=row["type"],
        tally_number=row["number"], entry=entry,
    )
    if not figures:
        return False
    return _bill(client, party, entry, row, figures, date, year)


def _party_for(client, row, ledgers) -> Party:
    figures = row["figures"]
    ledger = ledgers[normal_name(figures["party_ledger"])]
    existing = Party.objects.filter(firm_id=client.firm_id, client=client, ledger=ledger).first()
    if existing is not None:
        return existing
    customer = figures["kind"] in (BillKind.SALES, BillKind.CREDIT_NOTE)
    party, _ = Party.objects.get_or_create(
        firm_id=client.firm_id, client=client, canonical_name=ledger.name,
        defaults={"role": PartyRole.CUSTOMER if customer else PartyRole.VENDOR},
    )
    if party.ledger_id is None and not Party.objects.filter(ledger=ledger).exists():
        party.ledger = ledger
    if row.get("gstin") and not party.gstin:
        party.set_gstin(row["gstin"])
    party.save()
    return party


def _bill(client, party, entry, row, f, date, year) -> bool | None:
    purchase = f["kind"] in (BillKind.PURCHASE, BillKind.DEBIT_NOTE)
    reference = (row["number"] or row["reference"])[:64]
    identity = supplier_identity(party.gstin, party.pk) if purchase else supplier_identity(row.get("own_gstin", ""), client.pk)
    own = normalise_gstin(row.get("own_gstin", ""))
    try:
        with transaction.atomic():
            Bill.objects.create(
                firm_id=client.firm_id, client=client, party=party, kind=f["kind"],
                direction=Direction.CREDIT if f["kind"] in (BillKind.PURCHASE, BillKind.CREDIT_NOTE) else Direction.DEBIT,
                reference=reference, bill_date=date, booked_on=date, financial_year=year,
                taxable_paise=f["taxable_paise"], cgst_paise=f["cgst_paise"], sgst_paise=f["sgst_paise"],
                igst_paise=f["igst_paise"], cess_paise=f["cess_paise"], round_off_paise=f["round_off_paise"],
                total_paise=f["total_paise"], entry=entry, invoice_key=invoice_key(client.firm_id, identity, reference),
                own_gstin_hash=blind_index(own, client.firm_id, CRYPTO_PURPOSE) if own else "",
            )
    except IntegrityError:
        return None
    return True
```

The two `core.crypto`/`CRYPTO_PURPOSE` imports are placeholders for the exact names `ledger/billing.py` imports for `blind_index`, `normalise_gstin` and `CRYPTO_PURPOSE`. Open the import block at the top of `ledger/billing.py` and copy those three import lines verbatim. Do the same for `invoice_key`/`supplier_identity` (`core.identity`).

- [ ] **Step 5: Run to verify they pass**

Run (CI): `python -m pytest ledger/tests/test_tally_voucher_import.py -q`
Expected: all pass. The balance trigger (`0003_balance_trigger_tenant_context`) rejects an unbalanced entry at commit; the planner already guarantees balance, so a trigger failure here is a bug in line building.

- [ ] **Step 6: Commit**

```bash
git add ledger/tally_voucher_import.py ledger/tests/test_tally_voucher_import.py
git commit -m "Tally vouchers: confirm writes each voucher with Tally's own lines, makes the bill from them, and remembers the GUID so a re-run adds nothing"
```

---

### Task 6: Undo a run

**Files:**
- Modify: `ledger/tally_voucher_import.py`, `ledger/tests/test_tally_voucher_import.py`

**Interfaces:**
- Produces: `def undo_run(run: LedgerImportRun, membership, user) -> LedgerImportRun`. Removes every entry the run wrote (bill first, then entry, using the same sequence as `ledger.billing.remove_bill`'s tail: `record_change(... REMOVED ...)`, `bill.delete()`, `entry.lines.all().delete()`, `entry.delete()`), after deleting its `TallyVoucher`. The run becomes `DISCARDED` with `result["undone"] = n`. Refuses with `TallyImportError` when any bill of the run has an allocation (a payment applied) or any entry is locked (`editing.require_editable`) or the run is not CONFIRMED.

- [ ] **Step 1: Failing tests**

```python
from ledger.tally_voucher_import import undo_run


def test_undo_removes_everything_the_run_wrote(firm, client, senior, chart):
    run, _ = stage(client, senior, [sale()])
    confirm_vouchers(run, senior, senior.user)
    undone = undo_run(run, senior, senior.user)
    assert undone.status == "DISCARDED"
    assert JournalEntry.objects.filter(client=client).count() == 0
    assert Bill.objects.filter(client=client).count() == 0 and TallyVoucher.objects.filter(client=client).count() == 0


def test_after_undo_the_same_file_can_be_imported_again(firm, client, senior, chart):
    run, _ = stage(client, senior, [sale()])
    confirm_vouchers(run, senior, senior.user)
    undo_run(run, senior, senior.user)
    run2, _ = stage(client, senior, [sale()])
    assert confirm_vouchers(run2, senior, senior.user).result["posted"] == 1


def test_undo_is_refused_once_a_payment_is_applied(firm, client, senior, chart):
    from ledger.billing import allocate
    run, _ = stage(client, senior, [sale()])
    confirm_vouchers(run, senior, senior.user)
    bill = Bill.objects.get(client=client)
    pay = post(client, datetime.date(2025, 4, 20), make_ledger(client, "Cash", G.CASH), bill.party.ledger, 118000)
    allocate(pay.lines.get(ledger_account=bill.party.ledger), amount_paise=118000, bill=bill)
    with pytest.raises(TallyImportError):
        undo_run(run, senior, senior.user)
    assert JournalEntry.objects.filter(client=client, voucher_type="Sales").count() == 1


def test_undo_of_an_unconfirmed_run_is_refused(firm, client, senior, chart):
    run, _ = stage(client, senior, [sale()])
    with pytest.raises(TallyImportError):
        undo_run(run, senior, senior.user)
```

- [ ] **Step 2: Run to verify they fail** (CI) — `ImportError: undo_run`.

- [ ] **Step 3: Implement**

```python
from ledger.models import ChangeAction


def undo_run(run: LedgerImportRun, membership, user) -> LedgerImportRun:
    client = run.client
    _require_rights(membership, client)
    if run.kind != ImportKind.VOUCHERS or run.status != ImportStatus.CONFIRMED:
        raise TallyImportError("Only an applied vouchers import can be undone.")
    with transaction.atomic():
        links = list(
            TallyVoucher.objects.select_for_update().filter(firm_id=client.firm_id, client=client, run=run).select_related("entry")
        )
        for link in links:
            entry = link.entry
            editing.require_editable(entry)
            bill = Bill.objects.filter(entry=entry).first()
            if bill is not None and bill.allocations.exists():
                raise TallyImportError(
                    f"Invoice {bill.reference!r} has a payment or adjustment applied to it, so this import cannot be undone. "
                    f"Release the payment first."
                )
        for link in links:
            entry = JournalEntry.objects.select_for_update().get(pk=link.entry_id)
            editing.record_change(entry, ChangeAction.REMOVED, actor=user, before=editing.snapshot(entry), note="Tally import undone")
            Bill.objects.filter(entry=entry).delete()
            link.delete()
            entry.lines.all().delete()
            entry.delete()
        run.status = ImportStatus.DISCARDED
        run.result = {**run.result, "undone": len(links)}
        run.save(update_fields=["status", "result"])
    return run
```

`editing.require_editable` raises `EntryLockedError` for a signed-off entry; let it propagate (the API maps it). If `record_change` or `snapshot` need other arguments, read `ledger/editing.py:86-130` and follow `remove_bill`'s tail exactly.

- [ ] **Step 4: Run to verify they pass** (CI) and commit

```bash
git add ledger/tally_voucher_import.py ledger/tests/test_tally_voucher_import.py
git commit -m "Tally vouchers: undo a whole run (refused once a payment is applied or a date is signed off)"
```

---

### Task 7: API routes

**Files:**
- Modify: `api/views/tally.py`, `api/serializers/tally.py`, `api/urls.py` (check where `TallyImportViewSet` is registered)
- Test: `api/tests/test_tally_vouchers_api.py` (follow the existing masters API tests: `grep -rln "tally-imports" api/tests`)

**Interfaces:**
- Consumes: `stage_vouchers`, `confirm_vouchers`, `undo_run`.
- Produces routes under `clients/{id}/tally-imports/`:
  - `POST vouchers/` (multipart `file`, optional `date_from`, `date_to`) -> 201 preview / 200 reused. Body: the run with `rows` trimmed to `{ordinal, type, number, date, party, total_paise, action, bill, reason, note}` (never `lines`, `figures`, `gstin`).
  - `POST {id}/confirm-vouchers/` -> 200 run with `result`.
  - `POST {id}/undo/` -> 200 run.
  - Errors: `TallyImportError` -> 409 `tally_rule`; `TallyRunStaleError` -> 409 `tally_run_stale`; `TallyParseError` -> 422; `TallyTooLargeError` -> 413; `EntryLockedError` -> 409 `entry_locked`. These mappings already exist for the masters routes (find them with `grep -rn "TallyRunStaleError" api`); extend the same handler, do not duplicate it.

- [ ] **Step 1: Write failing API tests** modelled on the existing masters API tests (copy their fixtures and `client.post` style). Cover: 201 on upload; 200 on the same file; rows contain no `lines`; confirm posts; confirm twice is 200; a non-lead member gets 403; another firm's run is 404; a doctype file is 422; undo returns the run `DISCARDED`.

- [ ] **Step 2: Run to verify they fail** — 404 on the new routes.

- [ ] **Step 3: Implement** in `api/views/tally.py` (add to `TallyImportViewSet`)

```python
    @extend_schema(
        summary="Upload a Tally vouchers export and preview importing it",
        description=(
            "Reads the vouchers and returns a **preview**; nothing is posted. Each voucher is `post` or `skip` with a reason "
            "(a ledger not in the chart, unbalanced, cancelled, a bank voucher that waits for a later release...). "
            "Refused with `409 tally_rule` when the period already has postings for the client, and `409 entry_locked` when it "
            "reaches a signed-off date. The same file with the chart unchanged returns the existing preview with **200**."
        ),
        request=TallyVouchersUploadSerializer,
        responses={200: TallyVoucherRunSerializer, 201: TallyVoucherRunSerializer, **_ERRORS, 409: TallyErrorSerializer,
                   413: TallyErrorSerializer, 422: TallyErrorSerializer},
    )
    @action(detail=False, methods=["post"], url_path="vouchers")
    def vouchers(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        payload = TallyVouchersUploadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        upload = payload.validated_data["file"]
        data = upload.read(settings.MAX_TALLY_IMPORT_BYTES + 1)
        run, reused = stage_vouchers(
            client, request.membership, request.user, data=data, filename=os.path.basename(upload.name),
            date_from=payload.validated_data.get("date_from"), date_to=payload.validated_data.get("date_to"),
        )
        return Response(TallyVoucherRunSerializer(run).data, status=status.HTTP_200_OK if reused else status.HTTP_201_CREATED)

    @extend_schema(summary="Post a previewed Tally vouchers import", request=None, responses={200: TallyVoucherRunSerializer, **_ERRORS, 409: TallyErrorSerializer})
    @action(detail=True, methods=["post"], url_path="confirm-vouchers")
    def confirm_vouchers_action(self, request, client_id=None, pk=None):
        client, runs = self._runs(request, client_id)
        run = confirm_vouchers(get_object_or_404(runs, pk=pk), request.membership, request.user)
        return Response(TallyVoucherRunSerializer(run).data)

    @extend_schema(summary="Undo an applied Tally vouchers import", request=None, responses={200: TallyVoucherRunSerializer, **_ERRORS, 409: TallyErrorSerializer})
    @action(detail=True, methods=["post"], url_path="undo")
    def undo(self, request, client_id=None, pk=None):
        client, runs = self._runs(request, client_id)
        run = undo_run(get_object_or_404(runs, pk=pk), request.membership, request.user)
        return Response(TallyVoucherRunSerializer(run).data)
```

Add imports (`from rest_framework.decorators import action`, the two new serializers, `stage_vouchers, confirm_vouchers, undo_run`). In `api/serializers/tally.py` add:

```python
class TallyVouchersUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)


_ROW_KEYS = ("ordinal", "type", "number", "date", "party", "total_paise", "action", "bill", "reason", "note")


class TallyVoucherRunSerializer(serializers.ModelSerializer):
    rows = serializers.SerializerMethodField()

    class Meta:
        model = LedgerImportRun
        fields = ["id", "kind", "status", "financial_year", "counts", "rows", "result", "expires_at", "created_at", "confirmed_at"]

    def get_rows(self, run) -> list[dict]:
        return [{k: r.get(k) for k in _ROW_KEYS} for r in run.rows]
```

Use `extend_schema_field` on `get_rows` the way the existing detail serializer does for its `rows`, so the schema is typed. Make sure the viewset's `required_permission = "ledger.import"` covers the new actions (it applies class-wide).

- [ ] **Step 4: Regenerate the schema and types**, run the tests

Run: `python manage.py spectacular --file web/openapi.yaml` then the repo's TypeScript generation (`cd web && npm run gen:api` or the command in `web/package.json`; check `grep -n openapi web/package.json`).
Run: `python -m pytest api/tests/test_tally_vouchers_api.py api/tests/test_tally_import_api.py -q` (CI)
Expected: pass; `git status` shows `web/openapi.yaml` and `web/src/api/schema.d.ts` changed.

- [ ] **Step 5: Commit**

```bash
git add api web/openapi.yaml web/src/api/schema.d.ts
git commit -m "Tally vouchers: upload and preview, confirm, and undo over the API (rows trimmed to what the screen shows)"
```

---

### Task 8: The screen

**Files:**
- Create: `web/src/api/queries/tallyImport.ts`, `web/src/features/tally/TallyImportScreen.tsx`, `web/src/features/tally/TallyImportScreen.test.tsx`, `web/src/routes/_app/clients/$clientId/tally.tsx`
- Modify: the client's sub-navigation where `masters`/`ledgers` links are listed (find with `grep -rn "'/masters'\|masters" web/src/features/shell web/src/routes/_app/clients | head`) to add "Import from Tally".

**Interfaces:**
- Consumes: the routes of Task 7 through `raw.post` (see `useUploadInvoice` in `web/src/api/queries/bills.ts` for the FormData pattern and `V1`).
- Produces (`tallyImport.ts`):
  ```ts
  export type VoucherRunRow = { ordinal: number; type: string; number: string; date: string; party: string; total_paise: number; action: 'post' | 'skip'; bill: boolean; reason: string; note: string }
  export type VoucherRun = { id: string; status: 'PREVIEW' | 'CONFIRMED' | 'DISCARDED'; financial_year: number; counts: Record<string, any>; rows: VoucherRunRow[]; result: { posted?: number; bills?: number; skipped?: number; failed?: { guid: string; reason: string }[]; undone?: number }; expires_at: string }
  export function useStageVouchers(clientId: string)   // mutation: ({ file }) => VoucherRun
  export function useConfirmVouchers(clientId: string) // mutation: (runId) => VoucherRun
  export function useUndoVouchers(clientId: string)    // mutation: (runId) => VoucherRun
  ```
  Each success invalidates the client's data with `useInvalidateClient(clientId)` as `useUploadInvoice` does.

Screen behaviour (states): (1) **Upload**: a file input accepting `.xml` and a short help paragraph naming the Tally export ("Export > Vouchers, in XML format"; marked as needing the user's confirmation for their Tally version). (2) **Preview**: counts (vouchers, will post, bills, skipped), the date range, by-type chips; a prominent notice when `counts.bank_waiting > 0`: "N bank vouchers are not imported yet; the bank ledger will be incomplete until the next release"; a table of skipped vouchers with reasons (paged with `lib/pageSizes.ts` section `rules`-style; add section `tallyPreview`), a "Post N vouchers" button disabled when `will_post === 0`. (3) **Done**: posted/bills/failed counts, failed reasons, and an "Undo this import" button with a confirm step. Errors (`tally_rule`, `entry_locked`, parse errors) show the server's message in an alert; nothing is swallowed.

- [ ] **Step 1: Write the failing component test** `TallyImportScreen.test.tsx`, following `PartiesRules.component.test.tsx` for the render helper and query-client wrapper:

```tsx
// Renders the screen with the three mutations mocked. Pins: upload shows the preview; the bank notice appears; Post is
// disabled at zero; confirming shows the result; an API error message is shown as written.
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
// ...use the same providers/helper imports as PartiesRules.component.test.tsx

const post = vi.fn()
vi.mock('@/api/client', async (orig) => ({ ...(await orig<typeof import('@/api/client')>()), raw: { post: (...a: unknown[]) => post(...a), get: vi.fn() } }))

const preview = {
  id: 'r1', status: 'PREVIEW', financial_year: 2025, expires_at: '2099-01-01T00:00:00Z', result: {},
  counts: { vouchers: 3, will_post: 1, will_make_bill: 1, skipped: 2, bank_waiting: 1, by_type: { Sales: 1, Payment: 1, Journal: 1 }, date_from: '2025-04-01', date_to: '2025-04-03' },
  rows: [
    { ordinal: 2, type: 'Journal', number: '2', date: '2025-04-02', party: '', total_paise: 1000, action: 'skip', bill: false, reason: "The ledger 'Ghost' is not in the client's chart. Import the masters first.", note: '' },
    { ordinal: 3, type: 'Payment', number: '3', date: '2025-04-03', party: '', total_paise: 1000, action: 'skip', bill: false, reason: 'Bank vouchers are imported in a later release.', note: '' },
  ],
}

describe('TallyImportScreen', () => {
  beforeEach(() => { post.mockReset() })

  it('uploads a file, shows the preview and the bank notice', async () => {
    post.mockResolvedValueOnce(preview)
    // render(<TallyImportScreen clientId="c1" />) inside the providers
    // await userEvent.upload(screen.getByLabelText(/vouchers file/i), new File(['<x/>'], 'v.xml', { type: 'text/xml' }))
    // expect(await screen.findByText(/1 bank voucher/i)).toBeInTheDocument()
    // expect(screen.getByText(/Ghost/)).toBeInTheDocument()
  })
})
```

Replace the commented lines with real code using the helper that `PartiesRules.component.test.tsx` uses to render with providers; the test must have real assertions for: preview counts, bank notice, skip reasons, disabled Post at zero, confirm result, and a rejected upload showing the server message.

- [ ] **Step 2: Run to verify it fails**

Run: `cd web && npx vitest run src/features/tally -q`
Expected: cannot resolve `TallyImportScreen`.

- [ ] **Step 3: Implement** `tallyImport.ts`, `TallyImportScreen.tsx`, the route file (copy `routes/_app/clients/$clientId/masters.tsx` for the `createFileRoute` shape, path `/_app/clients/$clientId/tally`), and the navigation entry. Use existing UI primitives (`components/ui`), the `formatInr` helper used elsewhere for rupee display, and the page-size hook pattern from `MastersScreen.tsx` for the skipped table. Regenerate the route tree if the project requires it (`grep -n "routeTree" web/package.json web/vite.config.ts`).

- [ ] **Step 4: Run to verify it passes and the whole web suite is green**

Run: `cd web && npx vitest run -q && npx tsc --noEmit && npm run lint`
Expected: pass.

- [ ] **Step 5: Check it in the browser** against local live mode (`scripts\run-live.ps1`, web at localhost:5173) with a **synthetic** file produced by `ledger/tests/tally_voucher_xml.py` (write it to the scratchpad, never into the repo): upload, preview, confirm on a scratch client, undo. Report what was seen.

- [ ] **Step 6: Commit**

```bash
git add web/src
git commit -m "Tally vouchers: the Import from Tally screen (upload, preview with skipped reasons and the bank-voucher notice, post, undo)"
```

---

### Task 9: Hardening, docs and memory

**Files:**
- Modify: `docs/ARCHITECTURE.md` (a short "Tally history import" section), `docs/superpowers/specs/2026-10-17-tally-history-import-design.md` (record the deviations above), memory `todo-import-client-ledgers-from-tally.md` and `MEMORY.md`.
- Test: `ledger/tests/test_tally_voucher_security.py`

- [ ] **Step 1: Security tests**: (a) an entity bomb and a 100k-deep nested file are refused fast (no memory blow-up; assert the call returns an error within a second); (b) a voucher with 501 lines is skipped; (c) a narration with control characters is stored cleaned; (d) a firm-B user cannot confirm firm-A's run by id (404); (e) the run's `rows` JSON never contains a GSTIN in the API response; (f) CSV/formula-looking party name is skipped (parser test exists; add the API-level one).
- [ ] **Step 2: Run** `python -m pytest ledger api -q -n 4 --dist loadfile` in CI and confirm green.
- [ ] **Step 3: Update the docs and the memory note**: record that phase 1 exists, what is not imported (bank vouchers, inventory lines, stock), the deviations, and that the export steps in the screen's help are unconfirmed.
- [ ] **Step 4: Commit**

```bash
git add docs ledger/tests/test_tally_voucher_security.py
git commit -m "Tally vouchers: security tests, architecture note, and the spec updated with what the code taught"
```

---

## Self-review

- **Spec coverage.** Inputs/hostility: Task 1. Mapping (sales/purchase/notes -> entry + bill, journal, cash vouchers as journal, skips with reasons): Task 2 and 5. GUID idempotence and link: Tasks 3 and 5. Refusals (postings in range, lock, two companies): Task 4. Preview/confirm/undo and the screen: Tasks 4-8. Safety/RLS/client keys: Task 3. Security tests: Task 9. **Not in this plan, by design:** bank vouchers as statement rows (phase 2), learning (phase 3), inventory lines (open question 2: ignored in phase 1), opening-balance reconciliation (open question 6: masters screen already handles openings; a screen for it is still missing, see below).
- **Gap found:** the **masters** half of the screen (upload masters, resolve conflicts, confirm) has a backend but no UI, and phase 1 vouchers *require* the masters to be applied first (a missing ledger skips the voucher). The screen in Task 8 therefore needs a second step "Import the chart first". That is a sizeable piece (conflict resolution UI) and is **Task 10, not yet written**: it should be added before this plan is executed, or phase 1 launches with "apply the chart with the existing API" as a stated limitation. Raised with the user in the handoff.
- **Placeholders.** Three spots tell the implementer to copy exact import lines or a helper from a named file (`ledger/billing.py` imports in Task 5; the render helper in Task 8; Task 3's `(client_id, id)` unique check). Each names the file and what to copy; none is a "TBD".
- **Types.** `Facts`, `Planned`, `Skip`, `BillFigures` (Task 2) are used unchanged in Tasks 4-5; row keys written in Task 4 (`lines`, `figures`, `party_line`, `voucher_type`, `entry_kind`, `narration`, `reference`, `gstin`, `own_gstin`) are the ones Task 5 reads; `VoucherRunRow` (Task 8) matches `_ROW_KEYS` (Task 7).
