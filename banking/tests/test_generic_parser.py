"""Reading a statement from a bank nobody wrote a parser for.

The claim under test: column roles can be inferred and then *proved*, so the
system works with whatever bank a client happens to use rather than only the
ones someone anticipated. The proof is the statement's own running balance --
a wrong mapping does not almost-work, it fails on the first row.
"""

from __future__ import annotations

import datetime

import pytest

from banking.parsers import detect_parser, parse_statement
from banking.parsers.axis import AxisStatementParser
from banking.parsers.base import StatementParseError
from banking.parsers.columns import ColumnInferenceError, infer_columns
from banking.parsers.generic import GenericStatementParser
from banking.tests.layouts import LAYOUTS, document, layout

#: Movements per layout -- brought-forward and carried-forward lines are
#: balances, not transactions, and must not be counted as either.
EXPECTED_ROWS = {"hdfc": 5, "icici": 5, "kotak": 4, "sbi": 5}


@pytest.mark.parametrize("name", sorted(LAYOUTS))
def test_every_layout_parses(name):
    """Four banks, four different arrangements, no bank-specific code."""
    statement = parse_statement(layout(name))

    assert len(statement) == EXPECTED_ROWS[name]
    assert statement.bank_code == "GENERIC"


@pytest.mark.parametrize("name", ["hdfc", "icici", "kotak"])
def test_a_brought_forward_line_is_a_balance_not_a_transaction(name):
    """It carries a date and a balance and no amount. Counting it inflates nothing
    and misstates everything: the opening figure would be applied twice."""
    statement = parse_statement(layout(name))
    narrations = [t.narration.upper() for t in statement.transactions]

    assert not any("BALANCE" in n or n in {"B/F", "C/F"} for n in narrations)


@pytest.mark.parametrize("name", sorted(LAYOUTS))
def test_every_layout_ties_out(name):
    """Constructing ParsedStatement is the proof; this pins that it happened."""
    statement = parse_statement(layout(name))
    running = statement.opening_balance_paise

    for txn in statement.transactions:
        running += txn.signed_paise
        assert running == txn.balance_paise
    assert running == statement.closing_balance_paise


def test_withdrawal_and_deposit_columns_are_told_apart(name="hdfc"):
    """HDFC writes Withdrawal before Deposit. Swapping them inverts the books."""
    rows = parse_statement(layout(name)).transactions

    swiggy = next(r for r in rows if "SWIGGY" in r.narration)
    salary = next(r for r in rows if "ACME" in r.narration)

    assert swiggy.is_debit
    assert swiggy.debit_paise == 450_00
    assert not salary.is_debit
    assert salary.credit_paise == 1_20_000_00


def test_a_single_amount_column_with_a_direction_flag_is_read(name="kotak"):
    """Kotak carries one Amount column and a Dr/Cr flag beside it."""
    rows = parse_statement(layout(name)).transactions

    outgoing = next(r for r in rows if "RAJESH KUMAR" in r.narration)
    incoming = next(r for r in rows if "REFUND" in r.narration)

    assert outgoing.is_debit
    assert outgoing.debit_paise == 15_000_00
    assert not incoming.is_debit
    assert incoming.credit_paise == 2_500_00


def test_a_table_with_no_header_row_still_parses(name="sbi"):
    """Some net-banking exports drop the header. The arithmetic does not need it."""
    statement = parse_statement(layout(name))
    rows = statement.transactions

    assert len(rows) == 5
    assert rows[0].credit_paise == 3_500_00
    assert next(r for r in rows if "ATM WDL" in r.narration).debit_paise == 6_000_00


def test_interleaved_columns_do_not_confuse_it(name="icici"):
    """ICICI puts a serial number, two dates and a cheque column in the way."""
    rows = parse_statement(layout(name)).transactions

    salary = next(r for r in rows if "SALARY" in r.narration)
    assert salary.credit_paise == 85_000_00
    assert rows[0].narration.startswith("UPI/410123456789")


def test_the_narration_column_is_found_among_the_noise(name="icici"):
    """It takes no part in the sums, so it is the one thing arithmetic cannot vouch for."""
    rows = parse_statement(layout(name)).transactions

    assert all(len(r.narration) > 5 for r in rows)
    assert not any(r.narration.isdigit() for r in rows)


def test_the_period_is_read_from_the_header_text(name="hdfc"):
    statement = parse_statement(layout(name))

    assert statement.period_start == datetime.date(2025, 4, 1)
    assert statement.period_end == datetime.date(2025, 4, 30)


def test_the_account_number_and_ifsc_are_read_generically(name="icici"):
    statement = parse_statement(layout(name))

    assert statement.account_number == "004501234567"
    assert statement.ifsc == "ICIC0000045"


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_a_mapping_that_does_not_reproduce_the_balances_is_refused():
    """The safety property. A tampered amount breaks the chain, so nothing parses."""
    text, table = LAYOUTS["hdfc"]
    broken = [list(row) for row in table]
    broken[3][5] = "1,20,000.01"  # one paisa out on the deposit

    with pytest.raises(StatementParseError, match="reproduces its own running balance"):
        parse_statement(document(text, broken))


def test_a_table_that_is_not_a_statement_is_refused():
    """A summary table of dates and figures is not a transaction table."""
    table = [
        ["Quarter", "Opened", "Closed"],
        ["01-04-2025", "12", "9"],
        ["01-07-2025", "15", "11"],
        ["01-10-2025", "8", "14"],
    ]
    with pytest.raises(StatementParseError):
        parse_statement(document("Branch performance summary", table))


def test_a_document_with_no_table_at_all_is_refused():
    from integrations.pdf.base import PdfDocument, PdfPage

    prose = PdfDocument(
        engine="t",
        page_count=1,
        pages=(PdfPage(page_number=1, text="Dear customer, your statement is attached."),),
    )
    from banking.parsers import UnsupportedBankError

    with pytest.raises(UnsupportedBankError, match="looks like a transaction table"):
        detect_parser(prose)


def test_inference_needs_more_than_one_numeric_column():
    with pytest.raises(ColumnInferenceError, match="at least an amount and a running balance"):
        infer_columns(None, [["01-04-2025", "Something", "100.00"]] * 3)


def test_inference_needs_a_date():
    with pytest.raises(ColumnInferenceError, match="reads as a date"):
        infer_columns(None, [["Something", "100.00", "900.00"]] * 3)


# ---------------------------------------------------------------------------
# The two tiers
# ---------------------------------------------------------------------------


def test_a_dedicated_parser_wins_when_it_recognises_the_document(axis_document):
    """Axis has a real parser; it should be used rather than the generic path."""
    assert isinstance(detect_parser(axis_document), AxisStatementParser)


def test_the_generic_parser_reads_the_axis_statement_too(axis_document):
    """The fallback has to be good enough that the dedicated one is an optimisation.

    Same real 54-row statement, read without knowing anything about Axis.
    """
    statement = GenericStatementParser().parse(axis_document)

    assert len(statement) == 54
    assert statement.opening_balance_paise == 1_24_189_43
    assert statement.closing_balance_paise == 6_03_490_57
    assert statement.total_debit_paise == 49_41_572_00
    assert statement.total_credit_paise == 54_20_873_14


def test_the_two_tiers_agree_on_the_real_statement(axis_document):
    """Where both can read a file, they must read it identically."""
    dedicated = AxisStatementParser().parse(axis_document)
    generic = GenericStatementParser().parse(axis_document)

    assert [(t.date, t.signed_paise, t.balance_paise) for t in dedicated.transactions] == [
        (t.date, t.signed_paise, t.balance_paise) for t in generic.transactions
    ]
