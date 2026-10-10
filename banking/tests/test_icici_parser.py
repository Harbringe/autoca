"""The ICICI e-statement layout: rows by position, remarks above and below, amount column for direction, same-day order by the
balances. Built from the real layout's measurements with made-up figures; no database."""

from __future__ import annotations

import datetime

import pytest

from banking.parsers import detect_parser, parse_statement
from banking.parsers.base import StatementParseError
from banking.parsers.icici import IciciStatementParser
from integrations.pdf.base import PdfDocument, PdfLine, PdfPage, PdfWord

TITLE = (
    "1\nStatement of Transactions in Saving Account no. 123456789012 in INR for the period March 26, 2026 - March 30, 2026\n"
    "ASHA TRADERS Your Base Branch: ICICI BANK LIMITED,\n"
)


def w(text, x0, x1=None):
    return PdfWord(text, x0, x1 if x1 is not None else x0 + 6 * len(text))


def header(top=217.0):
    return [
        PdfLine(top, (w("Transaction", 60.2, 107.8), w("Withdrawal", 399, 447), w("Deposit", 473.8, 504.2), w("Balance", 532.1, 563.9))),
        PdfLine(top + 5, (w("S", 23.5, 28.9), w("No.", 31.2, 44.5), w("Cheque", 122.4, 151.8), w("Number", 154.1, 185.6), w("Transaction", 247.1, 294.6), w("Remarks", 297, 331.9))),
        PdfLine(top + 10, (w("Date", 74.4, 93.6), w("Amount", 395.6, 427.3), w("(INR)", 429.6, 450.4), w("Amount", 461.6, 493.3), w("(INR)", 495.6, 516.4), w("(INR)", 537.6, 558.4))),
    ]


def money(text, column):
    """Right-aligned under its column: withdrawal ends at 453, deposit at 519, balance at 571."""
    edge = {"w": 453.0, "d": 519.0, "b": 571.0}[column]
    return w(text, edge - 6 * len(text), edge)


def row(top, sno, date, amount, column, balance, remark=""):
    words = [w(str(sno), 30.1, 34.9), w(date, 61.4, 103.6)]
    if remark:
        words.append(w(remark, 192.0))
    words += [money(amount, column), money(balance, "b")]
    return PdfLine(top, tuple(words))


def remark(top, text):
    return PdfLine(top, (w(text, 192.0),))


def doc(*pages):
    built = tuple(PdfPage(page_number=i + 1, text=(TITLE if i == 0 else "") + "\n".join(line.text for line in lines), lines=tuple(lines)) for i, lines in enumerate(pages))
    return PdfDocument(engine="test", page_count=len(built), pages=built)


PAGE1 = header() + [row(247, 1, "03.04.2025", "199.00", "w", "2051.70", "VSI/NETFLIX")]


def test_detected_by_its_title_and_header_and_not_by_a_layout_without_positions():
    document = doc(PAGE1)
    assert isinstance(detect_parser(document), IciciStatementParser)
    plain = PdfDocument(engine="t", page_count=1, pages=(PdfPage(page_number=1, text=TITLE + "Withdrawal Deposit Balance"),))
    assert not IciciStatementParser.detect(plain)


def test_remarks_belong_to_the_row_by_position_and_direction_comes_from_the_column():
    page = header() + [
        row(247, 1, "03.04.2025", "199.00", "w", "2051.70", "VSI/NETFLIX"),
        remark(262, "MMT/IMPS/AGALE"),
        row(267, 2, "05.04.2025", "1002.95", "w", "1048.75"),
        remark(272, "NILE/SBIN0000433"),
        remark(282, "UPI/8744070@paytm"),
        row(287, 3, "11.04.2025", "145.00", "d", "1193.75"),
        remark(292, "BANK"),
    ]
    parsed = parse_statement(doc(page))

    assert parsed.bank_code == "ICICI" and parsed.account_number == "123456789012" and parsed.account_holder == "ASHA TRADERS"
    first, second, third = parsed.transactions
    # row 1's remark is on its own line; the line 5 points above row 2's own line is row 2's head, and so on down the page
    assert (first.debit_paise, first.narration) == (199_00, "VSI/NETFLIX")
    assert second.narration == "MMT/IMPS/AGALE NILE/SBIN0000433"
    assert (third.credit_paise, third.narration) == (145_00, "UPI/8744070@paytm BANK")
    assert parsed.opening_balance_paise == 2250_70


def test_the_period_is_the_rows_when_the_printed_one_does_not_hold_them():
    parsed = parse_statement(doc(header() + [row(247, 1, "03.04.2025", "199.00", "w", "2051.70", "X"), row(267, 2, "30.03.2026", "1.00", "d", "2052.70", "Y")]))
    assert (parsed.period_start, parsed.period_end) == (datetime.date(2025, 4, 3), datetime.date(2026, 3, 30))


def test_same_day_rows_listed_out_of_balance_order_are_put_in_the_order_the_balances_prove():
    # 8,116.48 -> deposit 3,000 -> 11,116.48. Then the bank lists a +10,000 reversal before the -10,000 it reverses,
    # each carrying the balance it really had.
    page = header() + [
        row(247, 1, "12.07.2025", "3920.00", "w", "8116.48", "A"),
        row(267, 2, "14.07.2025", "3000.00", "d", "11116.48", "B"),
        row(287, 3, "14.07.2025", "10000.00", "d", "11116.48", "REVERSAL"),
        row(307, 4, "14.07.2025", "10000.00", "w", "1116.48", "ORIGINAL"),
    ]
    parsed = parse_statement(doc(page))

    assert [t.narration for t in parsed.transactions] == ["A", "B", "ORIGINAL", "REVERSAL"]
    assert parsed.closing_balance_paise == 11116_48


def test_a_row_that_no_order_can_explain_is_refused_not_forced():
    page = header() + [
        row(247, 1, "03.04.2025", "199.00", "w", "2051.70", "A"),
        row(267, 2, "05.04.2025", "10.00", "w", "9999.00", "B"),  # the balance does not follow
    ]
    with pytest.raises(StatementParseError, match="(?i)balance chain"):
        parse_statement(doc(page))


def test_a_row_tail_that_spills_onto_the_next_page_goes_back_to_its_row():
    page1 = header() + [row(247, 1, "03.04.2025", "199.00", "w", "2051.70", "FIRST"), remark(262, "PART TWO")]
    page2 = header() + [remark(232, "PART THREE"), row(247, 2, "05.04.2025", "1.00", "d", "2052.70", "SECOND")]
    parsed = parse_statement(doc(page1, page2))
    assert parsed.transactions[0].narration == "FIRST PART TWO PART THREE"
    assert parsed.transactions[1].narration == "SECOND"
