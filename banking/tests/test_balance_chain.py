"""The arithmetic gate, attacked directly.

Every test here takes a statement that parsed correctly and breaks it the way a
parser bug would, then asserts the result cannot be constructed. The point is
that no caller has to remember to validate: there is no unvalidated
``ParsedStatement`` for a caller to hold.
"""

from __future__ import annotations

import dataclasses
import datetime

import pytest

from banking.parsers import parse_statement
from banking.parsers.base import (
    BalanceChainError,
    ParsedStatement,
    ParsedTransaction,
    StatementParseError,
)


def _statement(**overrides) -> ParsedStatement:
    """A two-row statement that balances, unless an override breaks it."""
    defaults = {
        "bank_code": "AXIS",
        "account_number": "911010000004321",
        "period_start": datetime.date(2025, 4, 1),
        "period_end": datetime.date(2026, 3, 31),
        "opening_balance_paise": 1000_00,
        "closing_balance_paise": 1150_00,
        "transactions": (
            ParsedTransaction(
                row_number=1,
                date=datetime.date(2025, 4, 13),
                narration="Sweep/VO000000087559330",
                debit_paise=250_00,
                balance_paise=750_00,
            ),
            ParsedTransaction(
                row_number=2,
                date=datetime.date(2025, 5, 2),
                narration="NEFT/MB/AXOMB20402110637",
                credit_paise=400_00,
                balance_paise=1150_00,
            ),
        ),
    }
    return ParsedStatement(**(defaults | overrides))


def test_a_correct_statement_constructs():
    assert len(_statement()) == 2


def test_a_dropped_row_is_caught(axis_document):
    """The commonest PDF bug: a row lost at a page break."""
    good = parse_statement(axis_document)
    without_row_thirty = good.transactions[:29] + good.transactions[30:]

    with pytest.raises(BalanceChainError, match="Balance chain broke at row"):
        dataclasses.replace(good, transactions=without_row_thirty)


def test_a_debit_read_as_a_credit_is_caught():
    """A flipped column keeps the amount and inverts its effect. Nothing else notices."""
    flipped = ParsedTransaction(
        row_number=1,
        date=datetime.date(2025, 4, 13),
        narration="Sweep/VO000000087559330",
        credit_paise=250_00,  # was a debit
        balance_paise=750_00,
    )

    with pytest.raises(BalanceChainError, match="row 1"):
        _statement(transactions=(flipped,), closing_balance_paise=750_00)


def test_a_duplicated_row_is_caught():
    rows = _statement().transactions

    with pytest.raises(BalanceChainError):
        _statement(transactions=(rows[0], rows[0], rows[1]))


def test_a_missing_final_page_is_named_as_such():
    """Truncation at the end breaks only the closing figure, so it gets its own message."""
    rows = _statement().transactions

    with pytest.raises(BalanceChainError, match="does not close"):
        _statement(transactions=rows[:1])


def test_footer_totals_catch_a_compensating_pair_of_errors():
    """Two errors that cancel keep the chain intact. The printed totals do not."""
    with pytest.raises(BalanceChainError, match="Debit total mismatch"):
        _statement(stated_total_debit_paise=300_00)

    with pytest.raises(BalanceChainError, match="Credit total mismatch"):
        _statement(stated_total_credit_paise=500_00)


def test_a_date_outside_the_period_is_caught():
    """The signature of a day/month swap, which silently reorders the year."""
    rows = _statement().transactions
    strayed = dataclasses.replace(rows[0], date=datetime.date(2024, 4, 13))

    with pytest.raises(StatementParseError, match="outside the statement period"):
        _statement(transactions=(strayed, rows[1]))


def test_a_row_cannot_hold_both_a_debit_and_a_credit():
    with pytest.raises(StatementParseError, match="both the debit and credit"):
        ParsedTransaction(
            row_number=1,
            date=datetime.date(2025, 4, 13),
            narration="x",
            debit_paise=1_00,
            credit_paise=1_00,
            balance_paise=0,
        )


def test_a_row_must_hold_an_amount():
    """A zero-value row is a summary line the parser failed to recognise."""
    with pytest.raises(StatementParseError, match="no amount in either column"):
        ParsedTransaction(
            row_number=1,
            date=datetime.date(2025, 4, 13),
            narration="TRANSACTION TOTAL",
            balance_paise=0,
        )


def test_direction_is_never_carried_by_a_sign():
    with pytest.raises(StatementParseError, match="negative amount"):
        ParsedTransaction(
            row_number=1,
            date=datetime.date(2025, 4, 13),
            narration="x",
            debit_paise=-1_00,
            balance_paise=0,
        )
