"""Layouts that real statements arrived in and failed on.

Each case here started as a PDF a user could not upload. They are rebuilt with invented figures, since the
failure was in the shape of the document, not its contents.
"""

from __future__ import annotations

import datetime

import pytest

from banking.parsers import UnsupportedBankError, detect_parser, parse_statement
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


@pytest.mark.parametrize(
    ("title", "kind"),
    [
        ("The Karur Vysya Bank Ltd\nLoan Account Statement\nBranch : TEST", "loan"),
        ("HOME LOAN STATEMENT\nAccount No : 1", "loan"),
        ("Credit Card Statement\nStatement date 05-Apr-2026", "credit card"),
    ],
)
def test_a_loan_or_credit_card_statement_is_refused_for_what_it_is(title, kind):
    """Its balance moves the other way from a bank account's, so reading it as one would post every row backwards.
    Say so, instead of the misleading "download it again"."""
    with pytest.raises(UnsupportedBankError, match=kind):
        detect_parser(document(title, [OD_HEADER, *OD_ROWS]))


def test_a_bank_statement_that_merely_mentions_a_loan_is_not_refused():
    """The check reads the title at the top of the first page, not any word anywhere."""
    text = OD_TEXT + "\nNote: your home loan EMI is debited on the 5th of each month."
    assert len(parse_statement(document(text, [OD_HEADER, *OD_ROWS]))) == 4


@pytest.mark.parametrize("name", ["hdfc", "icici", "kotak", "sbi"])
def test_the_existing_bank_layouts_are_not_mistaken_for_loans(name):
    assert len(parse_statement(layout(name))) > 0
