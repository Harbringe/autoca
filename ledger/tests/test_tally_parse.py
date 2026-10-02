"""The Tally masters parser: good files, damaged files, and hostile ones."""

from __future__ import annotations

import datetime
import io
import time
import zipfile

import pytest

from classify.models import LedgerGroup
from ledger import tally_parse
from ledger.tally_parse import (
    TallyParseError,
    TallyTooLargeError,
    normal_name,
    parse_masters,
    parse_opening,
    resolve_group,
)
from ledger.tests.tally_xml import csv_bytes, group, ledger, masters_xml, xlsx_bytes

LIMIT = 10 * 1024 * 1024


def parse(data, name="masters.xml"):
    return parse_masters(data, name, max_bytes=LIMIT)


# ---------------------------------------------------------------------------
# Amounts and the sign convention
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, paise",
    [
        ("-1500.00", 150_000),
        ("2500.50", -250_050),
        ("1,23,456.00 Dr", 12_345_600),
        ("1,23,456.00 Cr", -12_345_600),
        ("12,345.00 dr", 1_234_500),
        ("0.10", -10),
        ("", 0),
        (None, 0),
        ("0", 0),
    ],
)
def test_tally_negative_is_a_debit_and_the_result_is_debit_positive(text, paise):
    assert parse_opening(text) == paise


@pytest.mark.parametrize("text", ["12.345", "1e5", "NaN", "Infinity", "100 USD", "abc", "1.2.3", "-"])
def test_an_amount_that_is_not_exact_money_is_refused(text):
    with pytest.raises(ValueError):
        parse_opening(text)


def test_an_absurd_amount_is_refused():
    with pytest.raises(ValueError):
        parse_opening("9" * 30)


# ---------------------------------------------------------------------------
# XML
# ---------------------------------------------------------------------------


def sample_ledgers():
    return [
        ledger("HDFC Bank", "Bank Accounts", "-50000.00"),
        ledger("Acme & Sons", "Sundry Debtors", "1200.50", alias="ACME"),
        ledger("Rent", "Indirect Expenses"),
    ]


@pytest.mark.parametrize("wrap", ["body", "import"])
def test_it_reads_ledgers_wherever_the_export_nests_them(wrap):
    parsed = parse(masters_xml(sample_ledgers(), wrap=wrap))

    assert parsed.source_format == "xml"
    by_name = {item.name: item for item in parsed.ledgers}
    assert by_name["HDFC Bank"].opening_paise == 5_000_000
    assert by_name["HDFC Bank"].parent == "Bank Accounts"
    assert by_name["Acme & Sons"].opening_paise == -120_050
    assert by_name["Acme & Sons"].alias == "ACME"
    assert by_name["Rent"].opening_paise == 0
    assert not parsed.skipped


def test_the_books_from_date_is_read_when_the_file_has_one():
    parsed = parse(masters_xml(sample_ledgers(), books_from="20250401"))
    assert parsed.books_from == datetime.date(2025, 4, 1)
    assert parse(masters_xml(sample_ledgers())).books_from is None


@pytest.mark.parametrize("encoding", ["utf-8", "utf-16", "utf-16-le", "utf-16-be"])
def test_it_reads_utf8_and_utf16_with_or_without_a_byte_order_mark(encoding):
    parsed = parse(masters_xml([ledger("Café Ledger", "Indirect Expenses", "10.00")], encoding=encoding))
    assert [item.name for item in parsed.ledgers] == ["Café Ledger"]


def test_a_utf8_byte_order_mark_is_tolerated():
    data = b"\xef\xbb\xbf" + masters_xml(sample_ledgers())
    assert len(parse(data).ledgers) == 3


def test_characters_xml_forbids_are_removed_not_fatal():
    # Raw, and as numeric references (UNVERIFIED: Tally is remembered to write "&#4; Primary").
    data = masters_xml(
        [ledger("Plain", "Indirect Expenses")], [group("Odd Group", "@@4@@ Primary")], declaration=False
    ).replace(b"@@4@@", b"&#4;")
    data = data.replace(b"Plain", b"Pla\x07in")
    parsed = parse(data)
    assert parsed.ledgers[0].name == "Plain"
    assert parsed.groups[normal_name("Odd Group")].parent == "Primary"


def test_names_are_cleaned_and_a_bad_one_is_skipped_with_its_reason():
    ledgers = [
        ledger("  Spaced \t  Out  ", "Indirect Expenses"),
        ledger('=HYPERLINK("x")', "Indirect Expenses", "5.00"),
        ledger("-Minus", "Indirect Expenses"),
        ledger("x" * 300, "Indirect Expenses"),
        ledger("Zero​Width", "Indirect Expenses"),
        ledger("Fine", "Indirect Expenses", "12.345"),
        ledger("Good", "Indirect Expenses", "1.00"),
        ledger("Gone", "Indirect Expenses", action="Delete"),
    ]
    parsed = parse(masters_xml(ledgers))

    assert [item.name for item in parsed.ledgers] == ["Spaced Out", "Good"]
    reasons = " | ".join(s.reason for s in parsed.skipped)
    assert "formula" in reasons
    assert "longer than 255" in reasons
    assert "control characters" in reasons
    assert "exact amount" in reasons
    assert "deleted" in reasons
    assert len(parsed.skipped) == 6


def test_a_skipped_name_is_shown_without_control_characters():
    parsed = parse(masters_xml([ledger("Zero​Width", "Indirect Expenses")]))
    assert "​" not in parsed.skipped[0].name


def test_the_group_walk_stops_at_the_nearest_group_we_know():
    groups = {
        normal_name("Retail Customers"): tally_parse.MasterGroup("Retail Customers", "Sundry Debtors"),
        normal_name("Online"): tally_parse.MasterGroup("Online", "Retail Customers"),
        normal_name("Mine"): tally_parse.MasterGroup("Mine", "Primary"),
        normal_name("A"): tally_parse.MasterGroup("A", "B"),
        normal_name("B"): tally_parse.MasterGroup("B", "A"),
    }
    assert resolve_group("Online", groups).group == LedgerGroup.DEBTOR
    assert resolve_group("Online", groups).path == ("Online", "Retail Customers", "Sundry Debtors")
    assert resolve_group("sundry DEBTORS", groups).group == LedgerGroup.DEBTOR
    assert resolve_group("Fixed Assets", groups).group == LedgerGroup.FIXED_ASSET
    assert resolve_group("Mine", groups).group is None
    assert resolve_group("A", groups).group is None
    assert resolve_group("", groups).group is None
    assert resolve_group("Nowhere", groups).group is None


# ---------------------------------------------------------------------------
# Damaged and hostile files
# ---------------------------------------------------------------------------


def test_malformed_xml_is_a_plain_refusal():
    with pytest.raises(TallyParseError, match="not well-formed"):
        parse(b"<ENVELOPE><LEDGER NAME='x'></ENVELOPE>")


def test_an_empty_file_and_a_file_without_ledgers_are_refused():
    with pytest.raises(TallyParseError, match="empty"):
        parse(b"   \n")
    with pytest.raises(TallyParseError, match="No ledgers"):
        parse(b"<ENVELOPE><BODY/></ENVELOPE>")


def _bomb() -> bytes:
    entities = b'<!ENTITY lol "lol">' + b"".join(
        b'<!ENTITY lol%d "%s">' % (i, b"&lol%d;" % (i - 1) * 10 if i > 1 else b"&lol;" * 10)
        for i in range(1, 10)
    )
    return (
        b'<?xml version="1.0"?><!DOCTYPE lolz [' + entities + b"]>"
        b"<ENVELOPE><LEDGER NAME='x'><PARENT>&lol9;</PARENT></LEDGER></ENVELOPE>"
    )


def test_an_entity_bomb_is_refused_quickly_and_not_expanded():
    started = time.monotonic()
    with pytest.raises(TallyParseError, match="DTD or entities"):
        parse(_bomb())
    assert time.monotonic() - started < 2


def test_an_external_entity_is_refused_and_nothing_is_fetched(tmp_path):
    secret = tmp_path / "secret.txt"
    secret.write_text("TOP SECRET")
    data = (
        f'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY xxe SYSTEM "{secret.as_uri()}">]>'
        f"<ENVELOPE><LEDGER NAME='&xxe;'><PARENT>Bank Accounts</PARENT></LEDGER></ENVELOPE>"
    ).encode()
    with pytest.raises(TallyParseError) as caught:
        parse(data)
    assert "TOP SECRET" not in str(caught.value)


def test_a_dtd_with_no_entities_is_refused_too():
    with pytest.raises(TallyParseError, match="DTD or entities"):
        parse(b'<!DOCTYPE ENVELOPE SYSTEM "http://example.invalid/x.dtd"><ENVELOPE/>')


def test_a_file_over_the_limit_is_refused_before_it_is_read():
    with pytest.raises(TallyTooLargeError, match="MB"):
        parse_masters(b"<ENVELOPE>" + b" " * 2048 + b"</ENVELOPE>", "m.xml", max_bytes=1024)


def test_too_many_ledgers_is_refused(monkeypatch):
    monkeypatch.setattr(tally_parse, "MAX_LEDGERS", 3)
    many = [ledger(f"L{i}", "Indirect Expenses") for i in range(4)]
    with pytest.raises(TallyParseError, match="more than 3 ledgers"):
        parse(masters_xml(many))


def test_the_type_is_decided_from_the_bytes_not_the_name():
    pdf = b"%PDF-1.7\n\x00\x01\x02 binary " * 20
    with pytest.raises(TallyParseError):
        parse(pdf, "masters.xml")
    with pytest.raises(TallyParseError, match="not XLSX"):
        parse(masters_xml(sample_ledgers()), "masters.xlsx")
    with pytest.raises(TallyParseError, match="not XML"):
        parse(csv_bytes([["Ledger", "Group"], ["Rent", "Indirect Expenses"]]), "masters.xml")
    with pytest.raises(TallyParseError, match=r"\.xml, \.xlsx or \.csv"):
        parse(masters_xml(sample_ledgers()), "masters.exe")


def test_a_workbook_that_is_a_zip_bomb_is_refused(monkeypatch):
    monkeypatch.setattr(tally_parse, "MAX_XLSX_UNPACKED_BYTES", 1000)
    data = xlsx_bytes([["Ledger", "Group"], ["Rent", "Indirect Expenses"]])
    with pytest.raises(TallyParseError, match="too large once unpacked"):
        parse(data, "m.xlsx")


def test_a_zip_that_is_not_a_workbook_is_a_refusal_not_a_crash():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("hello.txt", "hi")
    with pytest.raises(TallyParseError):
        parse(buffer.getvalue(), "m.xlsx")


# ---------------------------------------------------------------------------
# Spreadsheets
# ---------------------------------------------------------------------------

TABLE = [
    ["Tally list of accounts"],
    [],
    ["Ledger", "Group", "Opening Balance"],
    ["HDFC Bank", "Bank Accounts", "50,000.00 Dr"],
    ["Acme", "Sundry Debtors", "1,200.50 Cr"],
    ["Rent", "Indirect Expenses", None],
    ["", "", ""],
    ["Odd amount", "Indirect Expenses", "12.345 Dr"],
]


@pytest.mark.parametrize("kind", ["csv", "xlsx"])
def test_a_flat_list_of_accounts_is_read_from_a_spreadsheet_or_csv(kind):
    data = csv_bytes(TABLE) if kind == "csv" else xlsx_bytes(TABLE)
    parsed = parse(data, f"accounts.{kind}")

    assert parsed.source_format == kind
    assert [(i.name, i.parent, i.opening_paise) for i in parsed.ledgers] == [
        ("HDFC Bank", "Bank Accounts", 5_000_000),
        ("Acme", "Sundry Debtors", -120_050),
        ("Rent", "Indirect Expenses", 0),
    ]
    assert len(parsed.skipped) == 1


def test_a_csv_name_that_would_run_as_a_formula_or_holds_control_characters_is_skipped():
    parsed = parse(
        csv_bytes(
            [
                ["Ledger", "Group", "Opening Balance"],
                ["=cmd|' /C calc'!A0", "Indirect Expenses", "1.00 Dr"],
                ["@SUM(A1)", "Indirect Expenses", "1.00 Dr"],
                ["Bad\x07Name", "Indirect Expenses", "1.00 Dr"],
                ["Fine", "Indirect Expenses", "1.00 Dr"],
            ]
        ),
        "a.csv",
    )
    assert [i.name for i in parsed.ledgers] == ["Fine"]
    assert len(parsed.skipped) == 3


def test_a_side_column_and_separate_debit_and_credit_columns_are_understood():
    sided = parse(
        csv_bytes(
            [
                ["Name", "Under", "Opening", "Dr/Cr"],
                ["A", "Sundry Debtors", "10.00", "Dr"],
                ["B", "Sundry Creditors", "20.00", "Cr"],
            ]
        ),
        "a.csv",
    )
    assert [i.opening_paise for i in sided.ledgers] == [1000, -2000]

    split = parse(
        xlsx_bytes(
            [
                ["Particulars", "Group", "Debit", "Credit"],
                ["A", "Sundry Debtors", 10, None],
                ["B", "Sundry Creditors", None, 20.5],
            ]
        ),
        "a.xlsx",
    )
    assert [i.opening_paise for i in split.ledgers] == [1000, -2050]


def test_an_excel_float_with_noise_is_refused_rather_than_rounded():
    parsed = parse(
        xlsx_bytes([["Ledger", "Group", "Opening Balance"], ["A", "Sundry Debtors", 0.1 + 0.2 + 1e-4]]),
        "a.xlsx",
    )
    assert not parsed.ledgers
    assert "two decimals" in parsed.skipped[0].reason


def test_a_csv_in_utf16_is_read():
    parsed = parse(csv_bytes([["Ledger", "Group"], ["Café", "Sundry Debtors"]], encoding="utf-16"), "a.csv")
    assert parsed.ledgers[0].name == "Café"


def test_a_table_without_a_ledger_column_is_refused():
    with pytest.raises(TallyParseError, match="Ledger"):
        parse(csv_bytes([["Foo", "Bar"], ["1", "2"]]), "a.csv")
