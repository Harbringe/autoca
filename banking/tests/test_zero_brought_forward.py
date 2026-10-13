"""A statement that prints "brought forward 0.00" whatever the account owed.

SBI prints this on its cash credit and Kisan Credit Card accounts when the extract starts part-way through the account's life.
The first row then does not follow from the printed opening, but its own balance leads through every row after it. The opening is
worked back from the first row, flagged, and a printed opening that is not zero is never overridden. The figures are invented.
"""

from __future__ import annotations

import pytest

from banking.parsers import parse_statement
from banking.parsers.base import BalanceChainError, StatementParseError
from banking.tests.layouts import document

TEXT = """STATE BANK OF INDIA
STATEMENT OF ACCOUNT
Account No : 12345678901
Product : EB-MSME-CC
IFSC Code : SBIN0001234
"""

HEADER = ["Post Date", "Value Date", "Description", "Cheque No/Reference", "Debit", "Credit", "Balance"]


def table(brought_forward: str, rows: list[list[str]]):
    return [HEADER, ["", "", "BROUGHT FORWARD", "", "", "", brought_forward], *rows]


# An overdraft: the balance is negative (DR). Opening is really 31,00,000.00 DR, so a credit of 3,70,000.00 leaves 27,30,000.00 DR.
ROWS = [
    ["04-04-2025", "04-04-2025", "CASH DEPOSIT SELF", "", "", "3,70,000.00", "27,30,000.00 DR"],
    ["06-04-2025", "06-04-2025", "DEP TFR UPI/CR/1", "", "", "50,000.00", "26,80,000.00 DR"],
    ["08-04-2025", "08-04-2025", "REMT THRU CHQ RTGS", "268862", "10,00,000.00", "", "36,80,000.00 DR"],
    ["09-04-2025", "09-04-2025", "DEP TFR UPI/CR/2", "", "", "80,000.00", "36,00,000.00 DR"],
]


def parse(brought_forward: str, rows=ROWS):
    return parse_statement(document(TEXT, table(brought_forward, rows)))


def test_a_printed_zero_that_the_first_row_contradicts_is_worked_back_from_that_row():
    statement = parse("0.00")

    assert statement.opening_inferred is True
    # 27,30,000.00 DR before the 3,70,000.00 credit means 31,00,000.00 DR to begin with
    assert statement.opening_balance_paise == -3_100_000_00
    assert statement.closing_balance_paise == -3_600_000_00
    assert len(statement) == 4


def test_a_printed_opening_that_leads_to_the_first_row_is_left_alone():
    statement = parse("31,00,000.00 DR")

    assert statement.opening_inferred is False
    assert statement.opening_balance_paise == -3_100_000_00


def test_a_printed_opening_that_is_not_zero_and_does_not_lead_to_the_first_row_is_still_refused():
    """It may mean a row was lost, so it is not smoothed over."""
    with pytest.raises((BalanceChainError, StatementParseError)):
        parse("12,00,000.00 DR")


def test_a_zero_is_not_trusted_over_a_chain_that_breaks_later():
    """If a later row does not follow from the one before, the first row's balance proves nothing, and the statement is refused."""
    broken = [list(r) for r in ROWS]
    broken[2][6] = "36,90,000.00 DR"  # the RTGS row no longer follows
    with pytest.raises((BalanceChainError, StatementParseError)):
        parse("0.00", broken)


def test_a_statement_that_really_opens_at_zero_is_not_flagged():
    rows = [
        ["04-04-2025", "04-04-2025", "CASH DEPOSIT SELF", "", "", "1,00,000.00", "1,00,000.00"],
        ["06-04-2025", "06-04-2025", "ATM WITHDRAWAL", "", "10,000.00", "", "90,000.00"],
        ["09-04-2025", "09-04-2025", "UPI/DR/1", "", "5,000.00", "", "85,000.00"],
    ]
    statement = parse("0.00", rows)

    assert statement.opening_inferred is False
    assert statement.opening_balance_paise == 0
