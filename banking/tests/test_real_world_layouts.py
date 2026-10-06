"""Layouts that real statements arrived in and failed on.

Each case here started as a PDF a user could not upload. They are rebuilt with invented figures, since the
failure was in the shape of the document, not its contents.
"""

from __future__ import annotations

import datetime

import pytest

from banking.parsers import UnsupportedBankError, detect_parser, parse_statement
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


def test_a_credit_card_statement_is_refused_for_what_it_is():
    """Not read yet: a card has no running balance to prove against."""
    with pytest.raises(UnsupportedBankError, match="credit card"):
        detect_parser(document("Credit Card Statement\nStatement date 05-Apr-2026",[OD_HEADER, *OD_ROWS]))


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
