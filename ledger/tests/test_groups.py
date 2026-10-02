"""Every ledger group lands on one side of the books, and an unknown one says so.

The Balance Sheet used to treat any group it did not list as an asset as a
liability, so a Fixed Assets ledger imported from Tally would have been reported
as money owed. Nothing is a liability by omission now.
"""

from __future__ import annotations

import datetime

import pytest

from classify.models import LedgerAccount, LedgerGroup
from core.db.session import firm_context
from core.provisioning import create_client, create_firm
from ledger.reports import (
    ASSET_GROUPS,
    LIABILITY_GROUPS,
    PROFIT_AND_LOSS_GROUPS,
    balance_sheet,
    profit_and_loss,
    trial_balance,
)
from ledger.tests.support import make_ledger, post

pytestmark = pytest.mark.django_db

FY = 2025
DAY = datetime.date(2025, 6, 1)


@pytest.fixture
def client():
    firm = create_firm("Groups Firm")
    return create_client(firm, "Groups Client", datetime.date(2025, 4, 1))


def test_every_group_is_on_exactly_one_side():
    sides = [ASSET_GROUPS, LIABILITY_GROUPS, PROFIT_AND_LOSS_GROUPS, {LedgerGroup.SUSPENSE}]
    for group in LedgerGroup.values:
        homes = [i for i, side in enumerate(sides) if group in side]
        assert len(homes) == 1, f"{group} is on {len(homes)} sides of the books"


@pytest.mark.parametrize(
    "group",
    [
        LedgerGroup.FIXED_ASSET,
        LedgerGroup.STOCK,
        LedgerGroup.CURRENT_ASSET,
        LedgerGroup.LOAN_ADVANCE,
        LedgerGroup.DEPOSIT,
        LedgerGroup.MISC_EXPENDITURE,
    ],
)
def test_an_asset_group_lands_on_the_assets_side(client, group):
    with firm_context(client.firm_id):
        asset = make_ledger(client, "Thing owned", group)
        capital = make_ledger(client, "Owner's capital", LedgerGroup.CAPITAL)
        post(client, DAY, asset, capital, 5_000_00)
        sheet = balance_sheet(client, FY)

    assert [r.name for r in sheet.assets] == ["Thing owned"]
    assert [r.name for r in sheet.liabilities] == ["Owner's capital"]
    assert sheet.balances


@pytest.mark.parametrize(
    "group",
    [LedgerGroup.BANK_OD, LedgerGroup.PROVISION, LedgerGroup.RESERVES, LedgerGroup.CURRENT_LIABILITY],
)
def test_a_liability_group_lands_on_the_liabilities_side(client, group):
    with firm_context(client.firm_id):
        cash = make_ledger(client, "Cash-in-Hand", LedgerGroup.CASH)
        owed = make_ledger(client, "Owed", group)
        post(client, DAY, cash, owed, 2_000_00)
        sheet = balance_sheet(client, FY)

    assert [r.name for r in sheet.liabilities] == ["Owed"]
    assert sheet.balances


def test_sales_and_purchase_accounts_are_trading_accounts(client):
    with firm_context(client.firm_id):
        cash = make_ledger(client, "Cash-in-Hand", LedgerGroup.CASH)
        sales = make_ledger(client, "Sales", LedgerGroup.SALES)
        purchases = make_ledger(client, "Purchases", LedgerGroup.PURCHASE)
        post(client, DAY, cash, sales, 9_000_00)
        post(client, DAY, purchases, cash, 4_000_00)
        pnl = profit_and_loss(client, FY)
        sheet = balance_sheet(client, FY)

    assert [r.name for r in pnl.income] == ["Sales"]
    assert [r.name for r in pnl.expenses] == ["Purchases"]
    assert pnl.net_profit_paise == 5_000_00
    assert not [r for r in sheet.liabilities + sheet.assets if r.name in {"Sales", "Purchases"}]
    assert sheet.balances


def test_an_unknown_group_is_shown_apart_and_the_sheet_says_it_does_not_balance(client):
    with firm_context(client.firm_id):
        cash = make_ledger(client, "Cash-in-Hand", LedgerGroup.CASH)
        odd = make_ledger(client, "Odd one", LedgerGroup.CAPITAL)
        post(client, DAY, cash, odd, 1_000_00)
        LedgerAccount.objects.filter(pk=odd.pk).update(group="SOMETHING_NEW")
        sheet = balance_sheet(client, FY)
        tb = trial_balance(client, FY)

    assert [r.name for r in sheet.unclassified] == ["Odd one"]
    assert sheet.unclassified_paise == -1_000_00
    assert "Odd one" not in [r.name for r in sheet.liabilities]
    assert not sheet.balances
    assert tb.balances
