"""Layouts that real statements arrived in and failed on.

Each case here started as a PDF a user could not upload. They are rebuilt with invented figures, since the
failure was in the shape of the document, not its contents.
"""

from __future__ import annotations

import datetime

import pytest

from banking.parsers import detect_parser, parse_statement
from banking.parsers.base import StatementParseError
from banking.parsers.columns import as_date
from banking.tests.layouts import document, layout

# A current account in overdraft: a narrow date column wraps "30-Mar-" / "2026" onto two lines, and a negative
# balance is printed as "-" then the figure on the next line.
OD_HEADER = [
    "S.no", "Transaction\nID", "Transaction\ndate", "Cheque No", "Description",
    "Withdrawal\n(Dr)", "Deposit\n(Cr)", "Available\nBalance",
]
OD_ROWS = [
    ["1", "S1000001", "30-Mar-\n2026", "", "UPI/SHOP/1", "", "10000.00", "-\n4164365.67"],
    ["2", "S1000002", "30-Mar-\n2026", "", "UPI/SHOP/2", "", "70000.00", "-\n4094365.67"],
    ["3", "S1000003", "31-Mar-\n2026", "", "NEFT/SUPPLIER", "5000.00", "", "-\n4099365.67"],
    ["4", "S1000004", "31-Mar-\n2026", "", "UPI/SHOP/3", "", "2157.00", "-\n4097208.67"],
]
OD_TEXT = "Account statement\nAccount name: TEST TRADERS Account type: Current Account\nIFSC code: ICIC0000001"


def test_a_date_wrapped_across_two_lines_is_still_a_date():
    assert as_date("30-Mar-\n2026") == datetime.date(2026, 3, 30)
    assert as_date("30/\n03/2026") == datetime.date(2026, 3, 30)
    assert as_date("30-Mar-2026") == datetime.date(2026, 3, 30)


def test_an_overdraft_statement_with_wrapped_dates_and_negative_balances_is_read():
    statement = parse_statement(document(OD_TEXT, [OD_HEADER, *OD_ROWS]))

    assert len(statement) == 4
    assert statement.transactions[0].date == datetime.date(2026, 3, 30)
    assert statement.transactions[-1].date == datetime.date(2026, 3, 31)
    # The chain is proved, not assumed: every row's balance follows from the one before it.
    running = statement.opening_balance_paise
    for txn in statement.transactions:
        running += txn.signed_paise
        assert running == txn.balance_paise
    assert statement.closing_balance_paise == -409720867


# A loan account: a DEBIT raises what is owed (disbursal, interest charged) and a CREDIT lowers it (an instalment).
LOAN_HEADER = ["TXN DATE", "VALUE DATE", "DESCRIPTION", "DEBIT", "CREDIT", "BALANCE"]
LOAN_ROWS = [
    ["07-Nov-2023", "07-Nov-2023", "LOAN DISBURSAL", "3145388.00", "", "3145388.00"],
    ["05-Dec-2023", "05-Dec-2023", "REGULAR INTEREST\nInterest Charged", "21969.00", "", "3167357.00"],
    ["06-Dec-2023", "06-Dec-2023", "Installment Payment By Xfer.", "", "21969.00", "3145388.00"],
    ["05-Jan-2024", "05-Jan-2024", "REGULAR INTEREST\nInterest Charged", "23538.00", "", "3168926.00"],
    ["05-Jan-2024", "05-Jan-2024", "Installment Payment By Xfer.", "", "26926.88", "3141999.12"],
]
LOAN_TEXT = "The Karur Vysya Bank Ltd\nLoan Account Statement\nAcc Type : DIGITAL HOME LOAN"


def test_a_loan_statement_is_read_with_its_balance_moving_the_other_way():
    statement = parse_statement(document(LOAN_TEXT, [LOAN_HEADER, *LOAN_ROWS]))

    assert statement.kind == "LOAN"
    assert statement.liability is True
    assert statement.opening_balance_paise == 0
    assert statement.closing_balance_paise == 314199912
    assert len(statement) == 5
    # Debit and credit are kept exactly as the statement prints them, so posting is unchanged.
    interest, instalment = statement.transactions[1], statement.transactions[2]
    assert (interest.debit_paise, interest.credit_paise) == (2196900, 0)
    assert (instalment.debit_paise, instalment.credit_paise) == (0, 2196900)


def test_the_same_table_without_a_loan_title_is_not_read_as_a_loan():
    """Loan polarity comes from the document's title and is never tried as a fallback. Otherwise a bank
    statement with swapped columns would pass the balance check and post backwards."""
    with pytest.raises(StatementParseError):
        parse_statement(document("Account statement\nAccount type: Savings",[LOAN_HEADER, *LOAN_ROWS]))


def test_a_loan_statement_whose_rows_do_not_tie_out_is_still_refused():
    broken = [*LOAN_ROWS[:3], ["05-Jan-2024", "05-Jan-2024", "REGULAR INTEREST", "23538.00", "", "1.00"], *LOAN_ROWS[4:]]
    with pytest.raises(StatementParseError):
        parse_statement(document(LOAN_TEXT, [LOAN_HEADER, *broken]))


def test_a_credit_card_statement_is_read_by_the_card_reader_not_as_a_bank_account():
    """A card has no running balance: it is proved against its printed previous balance and total due instead."""
    from banking.parsers.card import CardStatementParser

    parser = detect_parser(document("Credit Card Statement\nStatement date 05-Apr-2026", [OD_HEADER, *OD_ROWS]))

    assert isinstance(parser, CardStatementParser)


def test_a_bank_statement_that_merely_mentions_a_loan_is_not_refused():
    """The check reads the title at the top of the first page, not any word anywhere."""
    text = OD_TEXT + "\nNote: your home loan EMI is debited on the 5th of each month."
    assert len(parse_statement(document(text, [OD_HEADER, *OD_ROWS]))) == 4


@pytest.mark.parametrize("name", ["hdfc", "icici", "kotak", "sbi"])
def test_the_existing_bank_layouts_are_not_mistaken_for_loans(name):
    assert len(parse_statement(layout(name))) > 0


# A savings account whose balance column ends "Cr." (with a full stop), whose cheque numbers are digits, whose withdrawal and
# deposit sit in separate columns, and which has a cleared cheque reversed the same day. The full stop used to make the balance
# unreadable as money, so almost no row looked like a transaction and the statement was refused.
CR_DOT_HEADER = ["Tran Date", "Withdrawal", "Deposit", "Balance", "Alpha", "CHQ. NO.", "Narration", "Additional Info"]
CR_DOT_ROWS = [
    ["12-04-2025", "2.65", "", "12466467.30 Cr.", "", "", "SMS CHRG FOR:01-01-2025to31-03-2025", ""],
    ["14-05-2025", "200000.00", "", "12266467.30 Cr.", "IOC", "971320", "Cash Withdrawal At Br : TOWN", ""],
    ["14-05-2025", "6000000.00", "", "6266467.30 Cr.", "IOC", "971319", "PAYEE ONE", ""],
    ["29-08-2025", "", "2600000.00", "8866467.30 Cr.", "", "", "By CLEARING - TO121", ""],
    ["29-08-2025", "2600000.00", "", "6266467.30 Cr.", "", "", "REJECT:4:REQUIRED INFORMATION NOT", ""],
    ["31-12-2025", "", "1373224.00", "7639691.30 Cr.", "", "", "RTGS IN: SAMPLE", ""],
]
CR_DOT_TEXT = "Statement of Account No: 1000000000001\nIFSC Code: PUNB0000001\nStatement for Period : 01-04-2025 to 31-03-2026"


def test_a_balance_printed_with_cr_and_a_full_stop_is_read():
    from banking.parsers.columns import as_paise

    assert as_paise("12466467.30 Cr.") == 1246646730
    assert as_paise("1000.00 Dr.") == -100000
    assert as_paise("1000.00 Cr") == 100000


def test_a_statement_with_cr_dot_balances_and_a_same_day_reversal_is_read():
    statement = parse_statement(document(CR_DOT_TEXT, [CR_DOT_HEADER, *CR_DOT_ROWS]))

    assert len(statement) == 6
    running = statement.opening_balance_paise
    for txn in statement.transactions:
        running += txn.signed_paise
        assert running == txn.balance_paise
    assert statement.closing_balance_paise == 763969130


# ---------------------------------------------------------------------------
# Hardening: say where a table stops following its own balance; join wrapped narrations; ignore page totals.
# ---------------------------------------------------------------------------

PLAIN_HEADER = ["Date", "Narration", "Withdrawal", "Deposit", "Balance"]


def test_a_statement_that_cannot_be_proved_says_where_its_balance_stops_following_the_amounts():
    rows = [
        ["01-04-2025", "OPENING CREDIT", "", "1000.00", "1000.00"],
        ["02-04-2025", "RENT", "200.00", "", "800.00"],
        # A row was lost in extraction: this one says 100 out of 800 but the balance is 500.
        ["04-04-2025", "SHOP", "100.00", "", "500.00"],
        ["05-04-2025", "SALARY", "", "50.00", "550.00"],
    ]
    with pytest.raises(StatementParseError) as refused:
        parse_statement(document("Account statement", [PLAIN_HEADER, *rows]))

    message = str(refused.value)
    assert "breaks at transaction 3" in message and "04-04-2025" in message and "'SHOP'" in message
    assert "should be 700.00 but the statement shows 500.00" in message
    assert "missing, merged" in message


def test_a_narration_that_wraps_onto_its_own_row_is_joined_to_the_row_above():
    rows = [
        ["01-04-2025", "NEFT/SUPPLIER ONE", "", "1000.00", "1000.00"],
        ["", "REF 0042 FOR APRIL", "", "", ""],
        ["02-04-2025", "RENT", "200.00", "", "800.00"],
        ["03-04-2025", "SALARY", "", "50.00", "850.00"],
    ]
    statement = parse_statement(document("Account statement", [PLAIN_HEADER, *rows]))

    assert len(statement) == 3
    assert statement.transactions[0].narration == "NEFT/SUPPLIER ONE REF 0042 FOR APRIL"


def test_a_page_footer_is_not_taken_for_the_end_of_a_narration():
    rows = [
        ["01-04-2025", "NEFT/SUPPLIER ONE", "", "1000.00", "1000.00"],
        ["", "Page 1 of 3", "", "", ""],
        ["02-04-2025", "RENT", "200.00", "", "800.00"],
        ["03-04-2025", "SALARY", "", "50.00", "850.00"],
    ]
    statement = parse_statement(document("Account statement", [PLAIN_HEADER, *rows]))

    assert statement.transactions[0].narration == "NEFT/SUPPLIER ONE"


def test_page_totals_and_a_repeated_header_do_not_count_as_transactions():
    rows = [
        ["01-04-2025", "NEFT/SUPPLIER ONE", "", "1000.00", "1000.00"],
        ["02-04-2025", "RENT", "200.00", "", "800.00"],
        ["", "Page Total", "200.00", "1000.00", ""],
        PLAIN_HEADER,
        ["03-04-2025", "SALARY", "", "50.00", "850.00"],
    ]
    statement = parse_statement(document("Account statement", [PLAIN_HEADER, *rows]))

    assert len(statement) == 3 and statement.closing_balance_paise == 85000


@pytest.mark.parametrize(
    "text", ["12.04.2025", "12 April 2025", "12-April-2025", "12 Apr, 2025", "12/04/25", "12-Apr-25", "2025-04-12"]
)
def test_the_dates_banks_print_are_read(text):
    assert as_date(text) == datetime.date(2025, 4, 12)
