"""A credit-card statement is proved against its printed previous balance and total due."""

from __future__ import annotations

import datetime

import pytest

from banking.parsers import detect_parser, parse_statement
from banking.parsers.base import BalanceChainError, StatementParseError
from banking.parsers.card import CardStatementParser
from integrations.pdf.base import PdfDocument, PdfPage

TEXT = """HDFC BANK Credit Card Statement
Credit Card No: 4000 XXXX XXXX 1234
Statement Period: 01-09-2025 to 30-09-2025
Statement Date: 30-09-2025
"""

SUMMARY = [
    ["Previous Balance", "Purchases", "Payments", "Total Amount Due"],
    ["12,000.00", "8,500.00", "12,000.00", "8,500.00"],
]

SINGLE = [
    ["Date", "Transaction details", "Amount (Rs.)"],
    ["03-09-2025", "SWIGGY BENGALURU", "1,500.00"],
    ["10-09-2025", "PAYMENT RECEIVED - THANK YOU", "12,000.00 Cr"],
    ["14-09-2025", "AMAZON PAY INDIA", "5,000.00"],
    ["25-09-2025", "FUEL STATION PUNE", "2,000.00"],
]

SPLIT = [
    ["Date", "Description", "Debits", "Credits"],
    ["03-09-2025", "SWIGGY BENGALURU", "1,500.00", ""],
    ["10-09-2025", "PAYMENT RECEIVED", "", "12,000.00"],
    ["14-09-2025", "AMAZON PAY INDIA", "5,000.00", ""],
    ["25-09-2025", "FUEL STATION PUNE", "2,000.00", ""],
]


def doc(*tables, text=TEXT):
    return PdfDocument(
        engine="fixture", page_count=1, pages=(PdfPage(page_number=1, text=text, tables=tuple(tuple(tuple(r) for r in t) for t in tables)),)
    )


def test_a_card_statement_with_a_credit_suffix_is_read_and_proved():
    statement = parse_statement(doc(SUMMARY, SINGLE))

    assert statement.kind == "CARD" and statement.liability is True and statement.bank_code == "HDFC"
    assert statement.account_number == "4000XXXXXXXX1234"
    assert statement.opening_balance_paise == 12_000_00 and statement.closing_balance_paise == 8_500_00
    assert [t.debit_paise for t in statement.transactions] == [1_500_00, 0, 5_000_00, 2_000_00]
    assert [t.credit_paise for t in statement.transactions] == [0, 12_000_00, 0, 0]
    assert [t.balance_paise for t in statement.transactions] == [13_500_00, 1_500_00, 6_500_00, 8_500_00]
    assert statement.period_start == datetime.date(2025, 9, 1) and statement.period_end == datetime.date(2025, 9, 30)


def test_separate_debit_and_credit_columns_are_read_the_same_way():
    statement = parse_statement(doc(SUMMARY, SPLIT))

    assert statement.closing_balance_paise == 8_500_00
    assert statement.total_debit_paise == 8_500_00 and statement.total_credit_paise == 12_000_00


def test_a_dropped_row_fails_the_proof_and_nothing_is_imported():
    short = [SINGLE[0], *SINGLE[1:3], SINGLE[4]]

    with pytest.raises(BalanceChainError) as refused:
        parse_statement(doc(SUMMARY, short))

    assert "does not close" in str(refused.value)


def test_a_purchase_read_as_a_payment_fails_the_proof():
    wrong = [SINGLE[0], ["03-09-2025", "SWIGGY BENGALURU", "1,500.00 Cr"], *SINGLE[2:]]

    with pytest.raises(BalanceChainError):
        parse_statement(doc(SUMMARY, wrong))


def test_a_statement_without_its_summary_is_refused_and_says_what_is_missing():
    with pytest.raises(StatementParseError) as refused:
        parse_statement(doc(SINGLE))

    assert "previous balance" in str(refused.value)


def test_a_statement_without_a_card_number_is_refused():
    with pytest.raises(StatementParseError, match="card number"):
        parse_statement(doc(SUMMARY, SINGLE, text="HDFC BANK Credit Card Statement\nStatement Period: 01-09-2025 to 30-09-2025"))


def test_the_summary_box_is_not_mistaken_for_a_transaction():
    with_due_date = [["Payment Due Date", "Total Amount Due"], ["20-10-2025", "8,500.00"]]

    statement = parse_statement(doc(SUMMARY, with_due_date, SINGLE))

    assert len(statement) == 4


def test_the_title_chooses_the_card_reader_and_a_bank_statement_does_not_get_it():
    assert isinstance(detect_parser(doc(SUMMARY, SINGLE)), CardStatementParser)
