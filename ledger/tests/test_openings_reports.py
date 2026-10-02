"""Imported opening balances in the Trial Balance, P&L and Balance Sheet.

An opening is a starting position, not an entry, so these tests post nothing
for it. What they defend: it lands on the right side, the books still balance,
the part that does not balance is shown under Tally's own name for it, history
the opening already contains is not counted twice, and a bank account's opening
is never counted twice.
"""

from __future__ import annotations

import datetime

import pytest

from banking.models import BankAccount
from classify.models import LedgerGroup
from core.db.session import firm_context
from core.provisioning import create_client, create_firm
from ledger.models import LedgerOpening
from ledger.reports import balance_sheet, profit_and_loss, trial_balance
from ledger.tests.support import make_ledger, post

pytestmark = pytest.mark.django_db

START = datetime.date(2025, 4, 1)
DIFFERENCE = "Difference in opening balances"


@pytest.fixture
def client():
    firm = create_firm("Openings Firm")
    return create_client(firm, "Openings Client", START)


@pytest.fixture
def ctx(client):
    with firm_context(client.firm_id):
        yield


def opening(client, ledger, paise, year=2025):
    return LedgerOpening.objects.create(
        firm_id=client.firm_id, client=client, ledger=ledger, financial_year=year, signed_paise=paise
    )


def rows(report):
    return {r.name: r for r in report.rows}


def test_an_imported_asset_is_on_the_assets_side_and_balanced_openings_leave_no_difference(client, ctx):
    machinery = make_ledger(client, "Machinery", LedgerGroup.FIXED_ASSET)
    capital = make_ledger(client, "Capital", LedgerGroup.CAPITAL)
    opening(client, machinery, 1_000_00)
    opening(client, capital, -1_000_00)

    tb, sheet = trial_balance(client, 2025), balance_sheet(client, 2025)

    assert tb.balances and sheet.balances
    assert [(r.name, r.net_paise) for r in sheet.assets] == [("Machinery", 1_000_00)]
    assert [(r.name, r.net_paise) for r in sheet.liabilities] == [("Capital", -1_000_00)]
    assert DIFFERENCE not in rows(tb)


def test_openings_that_do_not_balance_show_as_the_difference_and_the_books_still_balance(client, ctx):
    opening(client, make_ledger(client, "Machinery", LedgerGroup.FIXED_ASSET), 1_000_00)
    opening(client, make_ledger(client, "Stock", LedgerGroup.STOCK), 500_00)

    tb, sheet = trial_balance(client, 2025), balance_sheet(client, 2025)

    assert rows(tb)[DIFFERENCE].net_paise == -1_500_00
    assert tb.balances and sheet.balances
    assert sheet.total_assets_paise == 1_500_00
    assert DIFFERENCE in [r.name for r in sheet.liabilities]


def test_an_opening_on_an_income_ledger_is_an_earlier_years_result_not_this_years(client, ctx):
    opening(client, make_ledger(client, "Sales", LedgerGroup.SALES), -9_000_00)
    opening(client, make_ledger(client, "Debtor", LedgerGroup.DEBTOR), 9_000_00)

    tb, pnl, sheet = trial_balance(client, 2025), profit_and_loss(client, 2025), balance_sheet(client, 2025)

    assert pnl.total_income_paise == 0 and pnl.net_profit_paise == 0
    assert rows(tb)["Profit & Loss A/c"].net_paise == -9_000_00
    assert DIFFERENCE not in rows(tb)
    assert tb.balances and sheet.balances


def test_the_opening_carries_into_later_years_with_what_was_posted_since(client, ctx):
    machinery = make_ledger(client, "Machinery", LedgerGroup.FIXED_ASSET)
    capital = make_ledger(client, "Capital", LedgerGroup.CAPITAL)
    opening(client, machinery, 1_000_00)
    post(client, datetime.date(2025, 6, 1), machinery, capital, 500_00)

    first, second = trial_balance(client, 2025), trial_balance(client, 2026)

    assert rows(first)["Machinery"].opening_paise == 1_000_00 and rows(first)["Machinery"].net_paise == 1_500_00
    assert rows(second)["Machinery"].opening_paise == 1_500_00
    assert first.balances and second.balances


def test_history_before_the_openings_year_is_not_counted_twice(client, ctx):
    machinery = make_ledger(client, "Machinery", LedgerGroup.FIXED_ASSET)
    capital = make_ledger(client, "Capital", LedgerGroup.CAPITAL)
    post(client, datetime.date(2025, 1, 15), machinery, capital, 700_00)
    opening(client, machinery, 1_000_00)

    tb = trial_balance(client, 2025)
    by_name = rows(tb)

    assert by_name["Machinery"].opening_paise == 1_000_00
    assert by_name["Capital"].opening_paise == -700_00
    assert by_name[DIFFERENCE].net_paise == -300_00
    assert tb.balances and balance_sheet(client, 2025).balances


def test_a_later_import_replaces_an_earlier_one(client, ctx):
    machinery = make_ledger(client, "Machinery", LedgerGroup.FIXED_ASSET)
    opening(client, machinery, 100_00, year=2025)
    opening(client, machinery, 150_00, year=2026)

    assert rows(trial_balance(client, 2025))["Machinery"].opening_paise == 100_00
    assert rows(trial_balance(client, 2026))["Machinery"].opening_paise == 150_00
    assert trial_balance(client, 2026).balances


def test_a_balance_that_the_bank_account_already_supplies_is_not_added_twice(client, ctx):
    ledger = make_ledger(client, "HDFC Bank", LedgerGroup.BANK)
    account = BankAccount(firm_id=client.firm_id, client=client, bank_code="HDFC", ledger_name="HDFC Bank")
    account.set_account_number("11112222333")
    account.save()

    # The import came first: the ledger holds an opening, and the bank confirms its own afterwards.
    opening(client, ledger, 5_000_00)
    assert rows(trial_balance(client, 2025))["HDFC Bank"].opening_paise == 5_000_00

    account.opening_balance_paise = 5_000_00
    account.opening_as_of = START
    account.save()

    tb = trial_balance(client, 2025)
    assert rows(tb)["HDFC Bank"].opening_paise == 5_000_00
    assert rows(tb)[DIFFERENCE].net_paise == -5_000_00
    assert tb.balances


def test_the_bank_accounts_figure_wins_when_the_two_differ(client, ctx):
    ledger = make_ledger(client, "HDFC Bank", LedgerGroup.BANK)
    account = BankAccount(
        firm_id=client.firm_id, client=client, bank_code="HDFC", ledger_name="hdfc  bank",
        opening_balance_paise=4_000_00, opening_as_of=START,
    )
    account.set_account_number("11112222444")
    account.save()
    opening(client, ledger, 9_000_00)

    assert rows(trial_balance(client, 2025))["hdfc  bank"].opening_paise == 4_000_00
    assert "HDFC Bank" not in rows(trial_balance(client, 2025))
