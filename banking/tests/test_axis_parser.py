"""The Axis parser, against a real statement's layout.

Every assertion here is a figure the bank printed. If the parser ever drifts,
these fail with the specific row that moved rather than with a count.
"""

from __future__ import annotations

import datetime
from decimal import Decimal

import pytest

from banking.parsers import UnsupportedBankError, detect_parser, parse_statement
from banking.parsers.axis import AxisStatementParser
from banking.parsers.base import (
    NoTextLayerError,
    StatementParseError,
    collapse_whitespace,
    parse_amount,
    parse_date,
)
from integrations.pdf.base import PdfDocument, PdfPage


def test_detects_an_axis_statement(axis_document):
    assert isinstance(detect_parser(axis_document), AxisStatementParser)


def test_reads_the_account_header(axis_document):
    statement = parse_statement(axis_document)

    assert statement.bank_code == "AXIS"
    assert statement.account_number == "911010000004321"
    assert statement.ifsc == "UTIB0000318"
    assert statement.period_start == datetime.date(2025, 4, 1)
    assert statement.period_end == datetime.date(2026, 6, 3)


def test_reads_every_row_and_the_statement_balances(axis_document):
    """The whole point: 54 rows that reproduce the bank's own arithmetic.

    Constructing ``ParsedStatement`` already proved the chain; these assertions
    pin the figures so a parse that balances at the wrong scale still fails.
    """
    statement = parse_statement(axis_document)

    assert len(statement) == 54
    assert statement.opening_balance == Decimal("124189.43")
    assert statement.closing_balance == Decimal("603490.57")
    assert statement.total_debit == Decimal("4941572.00")
    assert statement.total_credit == Decimal("5420873.14")
    assert statement.stated_total_debit == statement.total_debit
    assert statement.stated_total_credit == statement.total_credit


def test_summary_rows_are_not_transactions(axis_document):
    """OPENING BALANCE, TRANSACTION TOTAL and CLOSING BALANCE sit in the table."""
    narrations = [t.narration.upper() for t in parse_statement(axis_document).transactions]

    assert not [n for n in narrations if "BALANCE" in n and "CREDIT BALANCE REFUND" not in n]
    assert not [n for n in narrations if "TRANSACTION TOTAL" in n]


def test_debit_and_credit_come_from_separate_columns(axis_document):
    """The column the amount sits in is the only thing that says which way it went.

    Row 1 is a 250.00 sweep out; row 3 is a 350,000.00 RTGS in. Flattened to
    text these are indistinguishable, which is why the extractor returns cells.
    """
    rows = parse_statement(axis_document).transactions

    assert rows[0].is_debit
    assert rows[0].debit == Decimal("250.00")
    assert rows[0].credit == Decimal("0.00")

    assert not rows[2].is_debit
    assert rows[2].credit == Decimal("350000.00")
    assert rows[2].signed_amount == Decimal("350000.00")


def test_narration_keeps_its_content_and_loses_its_line_wrapping(axis_document):
    """The wrap position is a column-width artefact; the text is the payload."""
    rows = parse_statement(axis_document).transactions
    wrapped = next(r for r in rows if r.narration.startswith("RTGS/"))

    assert "\n" not in wrapped.narration
    assert wrapped.narration.startswith("RTGS/HDFCR52025050266560113/DR")
    assert wrapped.narration.endswith("BANK///Self//OP")


def test_the_table_continues_across_a_page_without_repeating_its_header(axis_document):
    """Page 2 carries no header row. Losing it would drop 32 rows silently."""
    statement = parse_statement(axis_document)
    second_page_rows = [t for t in statement.transactions if t.date.year == 2026]

    assert len(second_page_rows) > 25
    assert statement.transactions[-1].date == datetime.date(2026, 6, 3)


def test_cheque_and_branch_columns_are_carried_through(axis_document):
    cheque_rows = [t for t in parse_statement(axis_document).transactions if t.cheque_number]

    assert {r.cheque_number for r in cheque_rows} == {"331809", "331810", "331811", "331812"}
    assert all(r.branch_code for r in parse_statement(axis_document).transactions)


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_scan_is_refused_rather_than_parsed_to_zero_rows():
    """A scanned PDF extracts to empty strings, not to an error.

    Without this check the pipeline's happy path would accept a scan, find no
    transactions, and file a statement that says the client did nothing all year.
    """
    scan = PdfDocument(engine="test", page_count=1, pages=(PdfPage(page_number=1, text=""),))

    with pytest.raises(NoTextLayerError, match="no text layer"):
        detect_parser(scan)


def test_an_unrecognised_bank_is_refused():
    other = PdfDocument(
        engine="test",
        page_count=1,
        pages=(PdfPage(page_number=1, text="Statement of account, Some Other Bank"),),
    )

    with pytest.raises(UnsupportedBankError):
        detect_parser(other)


def test_a_row_with_an_amount_but_no_date_is_refused_not_skipped(axis_document):
    """Skipping it would break the chain further down, where it is harder to read."""
    page = axis_document.pages[0]
    table = list(page.tables[0])
    broken = list(table[3])
    broken[0] = ""
    table[3] = tuple(broken)

    damaged = PdfDocument(
        engine="test",
        page_count=1,
        pages=(PdfPage(page_number=1, text=page.text, tables=(tuple(table),)),),
    )

    with pytest.raises(StatementParseError, match="no readable date"):
        parse_statement(damaged)


# ---------------------------------------------------------------------------
# Cell-level helpers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("250.00", Decimal("250.00")),
        ("4,941,572.00", Decimal("4941572.00")),
        ("1,00,000.00", Decimal("100000.00")),  # lakh grouping
        ("7403.75", Decimal("7403.75")),
        ("1,234.00 Cr", Decimal("1234.00")),
        ("1,234.00 Dr", Decimal("-1234.00")),
        ("", None),
        ("   ", None),
        ("-", None),
        (None, None),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


def test_parse_amount_refuses_a_cell_that_is_not_money():
    """A non-money cell means the column mapping is wrong. Fail here, not later."""
    with pytest.raises(StatementParseError, match="Not a money value"):
        parse_amount("Sweep/VO000000087559330")


def test_dates_are_day_first():
    """03-06-2026 is 3 June, not 6 March. The other reading reorders a whole FY."""
    assert parse_date("03-06-2026") == datetime.date(2026, 6, 3)
    assert parse_date("13-04-2025") == datetime.date(2025, 4, 13)
    assert parse_date("not a date") is None


def test_collapse_whitespace_joins_wrapped_lines():
    assert collapse_whitespace("SB:911\nInt.Pd:01-04-2025  to 30-\n06-2025") == (
        "SB:911 Int.Pd:01-04-2025 to 30- 06-2025"
    )
