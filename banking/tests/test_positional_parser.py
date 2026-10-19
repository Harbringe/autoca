"""Statements whose rows are words in columns, not a ruled table (HDFC's e-statement is one), read by position.

Built from measurements of such a layout with made-up names and figures; no database and no real statement. The account
is an overdraft: its balance is negative and a deposit raises it, as a bank balance does.
"""

from __future__ import annotations

import datetime

import pytest

from banking.parsers import detect_parser, parse_statement
from banking.parsers.base import BalanceChainError, StatementParseError
from banking.parsers.generic import GenericStatementParser
from banking.parsers.positional import PositionalStatementParser
from integrations.pdf.base import PdfDocument, PdfLine, PdfPage, PdfWord

TITLE = "Statement of account\nStatement From : 01/04/2025 To : 30/04/2025\nAccountNo : 50200012345678 RTGS/NEFTIFSC: TEST0001234\n"

STEP = 17.2


def w(text, x0, x1=None):
    return PdfWord(text, x0, x1 if x1 is not None else x0 + 5.0 * len(text))


HEADER_AT = 233.6
HEADER = PdfLine(
    HEADER_AT,
    (w("Date", 40, 56), w("Narration", 144, 178), w("Chq./Ref.No.", 284, 328), w("ValueDt", 362, 392), w("WithdrawalAmt.", 405, 466), w("DepositAmt.", 491, 536), w("ClosingBalance", 564, 619)),
)
BOILERPLATE = PdfLine(120.0, (w("AccountBranch", 34), w(":", 100), w("TESTVILLE", 108)))


def money(text, column):
    """Right-aligned under its header, as the bank prints them."""
    edge = {"w": 470.0, "d": 548.0, "b": 627.0}[column]
    return PdfWord(text, edge - 5.5 * len(text), edge)


def row(top, date, narration, amount, column, balance, ref="000012345678"):
    return PdfLine(top, (w(date, 34), w(narration, 68), w(ref, 293), w(date, 362), money(amount, column), money(balance, "b")))


def more(top, text):
    return PdfLine(top, (w(text, 68),))


def summary(top, opening, drs, crs, debits, credits, closing):
    return [
        PdfLine(top, (w("STATEMENTSUMMARY", 68), w(":-", 192))),
        PdfLine(top + STEP, (w("OpeningBalance", 132), w("DrCount", 290), w("CrCount", 361), w("Debits", 425), w("Credits", 501), w("ClosingBal", 572))),
        PdfLine(top + 2 * STEP, (w(opening, 137), w(drs, 300), w(crs, 369), w(debits, 411), w(credits, 489), w(closing, 567))),
    ]


def doc(*pages, text=TITLE):
    built = tuple(
        PdfPage(page_number=i + 1, text=(text if i == 0 else "") + "\n".join(line.text for line in lines), lines=tuple(lines))
        for i, lines in enumerate(pages)
    )
    return PdfDocument(engine="test", page_count=len(built), pages=built)


def page1(*extra):
    t = HEADER_AT + STEP
    return [
        BOILERPLATE, HEADER,
        row(t, "01/04/25", "UPI-ASHA-9876543210@YBL", "1,000.00", "d", "-49,000.00"),
        more(t + STEP, "PAYMENTFROMPHONE"),
        row(t + 2 * STEP, "02/04/25", "NEFTDR-ACME", "2,500.50", "w", "-51,500.50"),
        more(t + 3 * STEP, "TRADERSLTD"),
        more(t + 4 * STEP, "REF77"),
        row(t + 5 * STEP, "03/04/25", "CASHDEPOSITBY-SELF", "10,000.00", "d", "-41,500.50"),
        *extra,
    ]


def page2(*extra):
    t = HEADER_AT + STEP
    return [
        BOILERPLATE, HEADER,
        more(t, "KHELI-TAIL"),
        more(t + STEP, "OFROW3"),
        row(t + 2 * STEP, "04/04/25", "ATMWDL", "500.00", "w", "-42,000.50"),
        *extra,
    ]


SUMMARY_OK = ("-50,000.00", "2", "2", "3,000.50", "11,000.00", "-42,000.50")


def statement(*pages, text=TITLE):
    return parse_statement(doc(*pages, text=text))


def test_rows_come_from_where_the_words_sit_and_the_summary_proves_them():
    parsed = statement(page1(), page2(*summary(HEADER_AT + 8 * STEP, *SUMMARY_OK)))
    assert [t.row_number for t in parsed.transactions] == [1, 2, 3, 4]
    first, second, third, fourth = parsed.transactions
    assert (first.credit_paise, first.debit_paise, first.balance_paise) == (100000, 0, -4900000)
    assert (second.debit_paise, second.balance_paise) == (250050, -5150050)
    assert (third.credit_paise, fourth.debit_paise) == (1000000, 50000)
    assert first.cheque_number == "000012345678"
    assert parsed.opening_balance_paise == -5000000 and parsed.closing_balance_paise == -4200050
    assert (parsed.total_debit_paise, parsed.total_credit_paise) == (300050, 1100000)
    assert parsed.kind == "BANK" and not parsed.liability
    assert parsed.account_number == "50200012345678" and parsed.ifsc == "TEST0001234"
    assert (parsed.period_start, parsed.period_end) == (datetime.date(2025, 4, 1), datetime.date(2025, 4, 30))


def test_a_wrapped_narration_is_joined_and_the_top_of_the_next_page_is_the_end_of_the_last_row():
    parsed = statement(page1(), page2(*summary(HEADER_AT + 8 * STEP, *SUMMARY_OK)))
    assert parsed.transactions[0].narration == "UPI-ASHA-9876543210@YBL PAYMENTFROMPHONE"
    assert parsed.transactions[1].narration == "NEFTDR-ACME TRADERSLTD REF77"
    assert parsed.transactions[2].narration == "CASHDEPOSITBY-SELF KHELI-TAIL OFROW3"
    assert parsed.transactions[3].narration == "ATMWDL"


def test_a_footer_set_well_below_the_last_row_is_not_its_narration():
    footer = PdfLine(HEADER_AT + 12 * STEP, (w("Thisisacomputergeneratednote", 68),))
    parsed = statement(page1(), page2(footer, *summary(HEADER_AT + 14 * STEP, *SUMMARY_OK)))
    assert parsed.transactions[3].narration == "ATMWDL"


def test_without_a_printed_summary_the_balances_alone_prove_it():
    parsed = statement(page1(), page2())
    assert len(parsed) == 4
    assert parsed.opening_balance_paise == -5000000  # worked back from the first row
    assert parsed.closing_balance_paise == -4200050


def test_a_summary_that_disagrees_with_the_rows_is_refused():
    wrong_count = ("-50,000.00", "3", "2", "3,000.50", "11,000.00", "-42,000.50")
    with pytest.raises(StatementParseError, match="3 debits"):
        statement(page1(), page2(*summary(HEADER_AT + 8 * STEP, *wrong_count)))
    wrong_total = ("-50,000.00", "2", "2", "3,001.50", "11,000.00", "-42,000.50")
    with pytest.raises(BalanceChainError, match="Debit total"):
        statement(page1(), page2(*summary(HEADER_AT + 8 * STEP, *wrong_total)))


def test_an_amount_read_under_the_wrong_column_breaks_the_balance_chain_and_is_refused():
    t = HEADER_AT + STEP
    # Row 2's withdrawal sits under Deposit. With no printed opening, row 1 sets the starting point, so the break shows at row 2.
    swapped = [BOILERPLATE, HEADER, row(t, "01/04/25", "UPI-ASHA", "1,000.00", "d", "-49,000.00"), row(t + STEP, "02/04/25", "NEFTDR", "2,500.50", "d", "-51,500.50"), row(t + 2 * STEP, "03/04/25", "CASH", "10,000.00", "d", "-41,500.50")]
    with pytest.raises(BalanceChainError, match="row 2"):
        statement(swapped)
    # With the opening printed, even the first row is held to it.
    first_swapped = [BOILERPLATE, HEADER, row(t, "01/04/25", "UPI-ASHA", "1,000.00", "w", "-49,000.00"), row(t + STEP, "02/04/25", "NEFTDR", "2,500.50", "w", "-51,500.50"), row(t + 2 * STEP, "03/04/25", "CASH", "10,000.00", "d", "-41,500.50"), *summary(t + 6 * STEP, "-50,000.00", "2", "1", "3,500.50", "10,000.00", "-41,500.50")]
    with pytest.raises(BalanceChainError, match="row 1"):
        statement(first_swapped)


def test_a_row_dropped_from_the_middle_is_refused():
    page = page1()
    del page[4]  # the second row's line: its figures are gone, the third row's balance no longer follows
    with pytest.raises(StatementParseError):
        statement(page, page2())


def test_the_amount_and_balance_may_sit_on_a_later_line_of_the_row():
    t = HEADER_AT + STEP
    amounts = PdfLine(t + STEP, (money("1,000.00", "d"), money("-49,000.00", "b")))
    first = PdfLine(t, (w("01/04/25", 34), w("UPI-ASHA", 68), w("000012345678", 293), w("01/04/25", 362)))
    rest = [row(t + 2 * STEP, "02/04/25", "NEFTDR", "2,500.50", "w", "-51,500.50"), row(t + 3 * STEP, "03/04/25", "CASH", "10,000.00", "d", "-41,500.50")]
    parsed = statement([BOILERPLATE, HEADER, first, amounts, *rest])
    assert [t.credit_paise or t.debit_paise for t in parsed.transactions] == [100000, 250050, 1000000]


def test_a_date_written_in_words_is_read():
    t = HEADER_AT + STEP

    def dated(top, day, narration, amount, column, balance):
        return PdfLine(top, (w(day, 34, 44), w("Apr", 46, 60), w("2025", 62, 82), w(narration, 90), money(amount, column), money(balance, "b")))

    parsed = statement([BOILERPLATE, HEADER, dated(t, "01", "UPI-ASHA", "1,000.00", "d", "-49,000.00"), dated(t + STEP, "02", "NEFTDR", "2,500.50", "w", "-51,500.50"), dated(t + 2 * STEP, "03", "CASH", "10,000.00", "d", "-41,500.50")])
    assert parsed.transactions[0].date == datetime.date(2025, 4, 1) and parsed.transactions[0].narration == "UPI-ASHA"


def test_a_row_a_day_past_the_printed_period_is_the_banks_own_and_stretches_the_period_but_a_month_past_is_refused():
    t = HEADER_AT + STEP
    next_day = [BOILERPLATE, HEADER, row(t, "30/04/25", "A", "1,000.00", "d", "-49,000.00"), row(t + STEP, "30/04/25", "B", "1,000.00", "d", "-48,000.00"), row(t + 2 * STEP, "01/05/25", "INTEREST", "143.00", "w", "-48,143.00")]
    parsed = statement(next_day)
    assert parsed.period_end == datetime.date(2025, 5, 1)
    far = [BOILERPLATE, HEADER, row(t, "30/04/25", "A", "1,000.00", "d", "-49,000.00"), row(t + STEP, "30/04/25", "B", "1,000.00", "d", "-48,000.00"), row(t + 2 * STEP, "01/06/25", "LATE", "143.00", "w", "-48,143.00")]
    with pytest.raises(StatementParseError, match="outside the statement period"):
        statement(far)


def test_a_loan_statement_by_its_title_is_read_as_what_is_owed():
    t = HEADER_AT + STEP
    # Owed rises with a debit: 5,00,000 owed, 25,000 interest debited, 10,000 repaid.
    loan = [BOILERPLATE, HEADER, row(t, "01/04/25", "INTEREST", "25,000.00", "w", "525,000.00"), row(t + STEP, "02/04/25", "EMI", "10,000.00", "d", "515,000.00"), row(t + 2 * STEP, "03/04/25", "EMI", "10,000.00", "d", "505,000.00")]
    document = doc(loan, text="Loan Account Statement\nStatement From : 01/04/2025 To : 30/04/2025\n")
    parser = detect_parser(document)
    assert isinstance(parser, PositionalStatementParser) and parser.liability
    parsed = parser.parse(document)
    assert parsed.kind == "LOAN" and parsed.liability
    assert (parsed.opening_balance_paise, parsed.closing_balance_paise) == (50000000, 50500000)


def test_it_claims_only_what_the_table_reader_does_not():
    positional = doc(page1(), page2())
    assert isinstance(detect_parser(positional), PositionalStatementParser)
    assert not GenericStatementParser.detect(positional)
    # No word positions (a fixture or a source that gives none): nothing to read, so nothing claimed.
    plain = PdfDocument(engine="t", page_count=1, pages=(PdfPage(page_number=1, text=TITLE + "Date Narration Withdrawal Deposit Balance"),))
    assert not PositionalStatementParser.detect(plain)


def test_a_page_with_no_transaction_rows_is_not_a_statement():
    prose = [PdfLine(100.0 + i * STEP, (w("Branchperformancesummary", 34), w(str(i), 300))) for i in range(5)]
    assert not PositionalStatementParser.detect(doc(prose))
