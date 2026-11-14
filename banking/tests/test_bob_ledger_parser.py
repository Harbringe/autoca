"""Bank of Baroda's branch ledger print (REP31), a one-row statement with no IFSC printed, and matching an account to a Tally
ledger by its digits. Made-up names and figures in the real layouts; no database."""

from __future__ import annotations

import datetime

import pytest

from banking.ingest import account_digits_tail, ledger_names_account
from banking.parsers import detect_parser, parse_statement
from banking.parsers.base import StatementParseError
from banking.parsers.bob import BankOfBarodaParser
from banking.parsers.bob_ledger import BankOfBarodaLedgerParser
from integrations.pdf.base import PdfDocument, PdfPage

SETTINGS_PAGE = """Transaction Details Page 1 of 2
21-10-2026 15:29:31 BANK OF BARODA, SAMPLE BRANCH Page 1
REP31 Customer Account Ledger Print
Acct Range : 12340100000999 to 12340100000999
Period : 01-04-2026 to 21-10-2026
"""
ROWS_PAGE = """21-10-2026 15:29:31 BANK OF BARODA SAMPLE BRANCH Page 2
Transaction Details Page 2 of 2
REP31 Customer Account Ledger Report from 01-04-2026 to 21-10-2026
Account No : 12340100000999 INR TEST PERSON ONE
Opening Balance : 1,000.00Cr
GL. Value Tran Id Instrmnt Particulars Transaction Transaction Balance
Date Date Number Debit Amount Credit Amount
02-04-2026 01-04-2026 S11111111 UPI/1/11:06:05/UPI/sample@bank 600.00 400.00Cr
02-04-2026 02-04-2026 U22222222 NEFT-SAMPLE CUSTOMER 1,250.50 1,650.50Cr
03-04-2026 03-04-2026 C33333333 000123 SAMPLE SUPPLIER CHQ 2,000.00 349.50Dr
Page Total Credit : 1,250.50
Page Total Debit : 2,600.00
Closing Balance : 349.50Dr
Total Credit : 1,250.50
Total Debit : 2,600.00
************* 2 pages printed. End of Report*************
"""


def _doc(*texts):
    pages = tuple(PdfPage(page_number=i + 1, text=t) for i, t in enumerate(texts))
    return PdfDocument(engine="test", page_count=len(pages), pages=pages)


def test_the_branch_ledger_print_is_recognised():
    assert isinstance(detect_parser(_doc(SETTINGS_PAGE, ROWS_PAGE)), BankOfBarodaLedgerParser)


def test_rows_are_proved_from_the_printed_opening_to_the_printed_closing():
    statement = parse_statement(_doc(SETTINGS_PAGE, ROWS_PAGE))
    assert statement.account_number == "12340100000999"
    assert statement.account_holder == "TEST PERSON ONE"
    assert (statement.period_start, statement.period_end) == (datetime.date(2026, 4, 1), datetime.date(2026, 10, 21))
    assert statement.opening_balance_paise == 100000 and statement.closing_balance_paise == -34950
    assert [(t.debit_paise, t.credit_paise) for t in statement.transactions] == [(60000, 0), (0, 125050), (200000, 0)]
    assert statement.transactions[2].cheque_number == "000123"
    assert statement.transactions[0].date == datetime.date(2026, 4, 2)  # the GL (posting) date, as the report is ordered


def test_a_missing_page_is_refused_because_the_closing_does_not_agree():
    short = ROWS_PAGE.replace("03-04-2026 03-04-2026 C33333333 000123 SAMPLE SUPPLIER CHQ 2,000.00 349.50Dr\n", "")
    with pytest.raises(StatementParseError, match="closing balance"):
        parse_statement(_doc(SETTINGS_PAGE, short))


def test_a_row_that_does_not_move_the_balance_by_its_amount_is_refused():
    wrong = ROWS_PAGE.replace("1,250.50 1,650.50Cr", "1,250.50 1,600.50Cr")
    with pytest.raises(StatementParseError, match="balance moved"):
        parse_statement(_doc(SETTINGS_PAGE, wrong))


ONE_ROW = """Main Account Holder Name :SAMPLE TRADERS Address :
Customer Id: Account No: 123XXXXXXXX458
Branch Name: SAMPLE BRANCH MICR Code:
IFSC Code: Nominee Reg: Yes
Your Account Statement as on 28/09/2026 Statement Period from 01/04/2025 to 28/09/2026
Statement of transactions in Current Account 123XXXXXXXX458 in INR for the period 01/04/2025 - 28/09/2026
TRAN DATE VALUE DATE NARRATION CHQ.NO. WITHDRAWAL(DR) DEPOSIT(CR) BALANCE(INR)
17/06/2025 17/06/2025 LEDGER FOLIO CHARGES - CA 147.50 8,088.92Cr
28/09/2026 10:33 Contact-Us@18005700 Page 1 of 1
"""


def test_a_one_row_statement_with_no_ifsc_printed_is_still_read():
    document = _doc(ONE_ROW)
    assert isinstance(detect_parser(document), BankOfBarodaParser)
    statement = parse_statement(document)
    assert len(statement.transactions) == 1
    assert statement.transactions[0].debit_paise == 14750
    assert statement.opening_balance_paise == 823642 and statement.closing_balance_paise == 808892


@pytest.mark.parametrize(
    "ledger, number, matches",
    [
        ("Test Bank CA A/c 12340200001458", "123XXXXXXXX458", True),  # masked: the digits it shows end the ledger's number
        ("Test Bank CC 691", "XXX691", True),
        ("Test Bank SB A/c 12340100000190", "12340100000190", True),
        ("Test Bank SB A/c 12340100000190", "12340200001458", False),
        ("Test OD A/c 50200104940014", "50200104943559", False),  # same bank, different account
        ("Test Bank CC 691", "12345691", True),  # a ledger named after the last digits only
        ("Rent", "12345691", False),
    ],
)
def test_an_account_finds_its_tally_ledger_by_its_digits(ledger, number, matches):
    assert ledger_names_account(ledger, number) is matches


def test_the_shown_digits_are_the_ones_after_the_mask():
    assert account_digits_tail("979XXXXXXXX458") == "458"
    assert account_digits_tail("97940100000190") == "0190"
    assert account_digits_tail("XX") == ""
