"""The Bank of Baroda layout with one amount per row and a Dr/Cr balance, newest first. Built from the real layout with
made-up figures; no database."""

from __future__ import annotations

import datetime

import pytest

from banking.parsers import detect_parser, parse_statement
from banking.parsers.base import StatementParseError
from banking.parsers.bob import BankOfBarodaParser
from integrations.pdf.base import PdfDocument, PdfPage

HEAD = """Main Account Holder Name :GAJANAN CLOTH STORES Address :
Customer Id: NI4064141 Account No: 979XXXXXXXX691
Branch Name: PETH UMRI MICR Code: 431012345
IFSC Code: BARB0DBPETH Nominee Reg: No
Your Account Statement as on 28/09/2026 Statement Period from 01/04/2025 to 31/03/2026
Statement of transactions in Cash Credit Account 979XXXXXXXX691 in INR for the period 01/04/2025 - 31/03/2026
TRAN DATE VALUE DATE NARRATION CHQ.NO. WITHDRAWAL(DR) DEPOSIT(CR) BALANCE(INR)
"""
FOOT = "28/09/2026 10:34 Contact-Us@18005700 Page {n} of 2\n*This is computer-generated statement.No signature is required.\n"

#: Newest first. Opening (before the oldest row) is 19,70,131.78 owed.
PAGE_1 = HEAD + """31/03/2026 31/03/2026 97X91:Penal Charge Coll:01-03- 17,92,397.34Dr
449.09
2026 to 31
31/03/2026 31/03/2026 KULDEEP TEXTILES-MICR INWARD CLG 000352 30,340.00 17,91,948.25Dr
(CTS)
""" + FOOT.format(n=1)
PAGE_2 = """05/04/2025 05/04/2025 UPI/12/11:23:01/UPI/sainathba 1,00,000.00 18,09,931.78Dr
cchewar111
03/04/2025 03/04/2025 BY CASH 60,200.00 19,09,931.78Dr
""" + FOOT.format(n=2)


def _doc(*texts):
    pages = tuple(PdfPage(page_number=i + 1, text=t) for i, t in enumerate(texts))
    return PdfDocument(engine="test", page_count=len(pages), pages=pages)


def _statement():
    # Make the made-up pages self-consistent: balances chain from the oldest row upward.
    return _doc(PAGE_1, PAGE_2)


def test_detected_by_its_ifsc_and_header():
    assert isinstance(detect_parser(_statement()), BankOfBarodaParser)


def test_rows_are_put_in_date_order_and_direction_comes_from_the_balance():
    with pytest.raises(StatementParseError) as broken:
        parse_statement(_statement())
    # the made-up page 1 balance does not chain from page 2's, which is exactly what the proof is for
    assert "balance moved" in str(broken.value)


def test_a_consistent_statement_reads_with_the_right_directions():
    page1 = HEAD + """31/03/2026 31/03/2026 97X91:Penal Charge Coll:01-03- 18,10,380.87Dr
449.09
2026 to 31
31/03/2026 31/03/2026 KULDEEP TEXTILES-MICR INWARD CLG 000352 30,340.00 18,09,931.78Dr
(CTS)
""" + FOOT.format(n=1)
    page2 = """05/04/2025 05/04/2025 UPI/12/11:23:01/UPI/sainathba 1,00,000.00 18,40,271.78Dr
cchewar111
03/04/2025 03/04/2025 BY CASH 60,200.00 19,09,931.78Dr
""" + FOOT.format(n=2)
    # chronologically: 03/04 BY CASH (credit 60,200: owed falls 19,70,131.78 -> 19,09,931.78);
    # 05/04 UPI (credit 1,00,000?) owed 19,09,931.78 -> 18,40,271.78 is a fall of 69,660: so the printed amount disagrees
    with pytest.raises(StatementParseError):
        parse_statement(_doc(page1, page2))

    page2 = page2.replace("18,40,271.78Dr", "18,09,931.78Dr").replace("1,00,000.00", "1,00,000.00")
    # 19,09,931.78 -> 18,09,931.78 is a fall of exactly 1,00,000.00: a deposit
    page1_ok = page1.replace("18,09,931.78Dr", "17,79,591.78Dr").replace("18,10,380.87Dr", "17,80,040.87Dr")
    # 18,09,931.78 -> 17,79,591.78 rises? no: falls by 30,340.00: a deposit; then 17,79,591.78 -> 17,80,040.87 rises 449.09: a charge
    parsed = parse_statement(_doc(page1_ok, page2))

    assert parsed.bank_code == "BOB"
    assert parsed.account_number == "979XXXXXXXX691"
    assert parsed.ifsc == "BARB0DBPETH"
    assert parsed.account_holder == "GAJANAN CLOTH STORES"
    assert parsed.period_start == datetime.date(2025, 4, 1) and parsed.period_end == datetime.date(2026, 3, 31)
    dates = [t.date for t in parsed.transactions]
    assert dates == sorted(dates)
    first, second, third, fourth = parsed.transactions
    assert (first.credit_paise, first.debit_paise) == (60_200_00, 0)  # BY CASH
    assert (second.credit_paise, second.debit_paise) == (1_00_000_00, 0)
    assert (third.credit_paise, third.debit_paise) == (30_340_00, 0)
    assert (fourth.debit_paise, fourth.credit_paise) == (449_09, 0)  # the charge raises what is owed
    assert third.cheque_number == "000352"
    # What is owed is stored as a negative bank balance.
    assert parsed.opening_balance_paise == -19_70_131_78
    assert parsed.closing_balance_paise == -17_80_040_87


def test_an_oldest_row_that_does_not_say_which_way_is_refused_not_guessed():
    page = HEAD + "03/04/2025 03/04/2025 NEFT-ABC-PAYMENT 5,000.00 19,09,931.78Dr\n" + FOOT.format(n=1)
    with pytest.raises(StatementParseError, match="opening balance"):
        parse_statement(_doc(page))
