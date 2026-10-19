"""The ledgers every new client starts with, and Tally's predefined groups, checked against what Tally itself lists."""

from __future__ import annotations

import pytest

from classify.models import LedgerGroup
from classify.seeds import SEED_LEDGERS, STARTER_LEDGERS
from classify.standard_ledgers import STANDARD_LEDGERS
from ledger.reports import ASSET_GROUPS, LIABILITY_GROUPS, PROFIT_AND_LOSS_GROUPS
from ledger.tally_parse import TALLY_GROUPS, normal_name

# Every group of Tally's "List of Groups" (photographed) and of the List of Ledgers a demo company exports (Master.xlsx), as Tally spells
# them. "Profit & Loss A/c" is a ledger there and is computed here, so it is not a group of ours.
TALLY_PREDEFINED_GROUPS = [
    "Bank Accounts", "Bank OCC A/c", "Bank OD A/c", "Branch / Divisions", "Capital Account", "Cash-in-Hand", "Current Assets",
    "Current Liabilities", "Deposits (Asset)", "Direct Expenses", "Direct Incomes", "Duties & Taxes", "Expenses (Direct)",
    "Expenses (Indirect)", "Fixed Assets", "Income (Direct)", "Income (Indirect)", "Indirect Expenses", "Indirect Incomes",
    "Investments", "Loans & Advances (Asset)", "Loans (Liability)", "Misc. Expenses (ASSET)", "Provisions", "Purchase Accounts",
    "Reserves & Surplus", "Retained Earnings", "Sales Accounts", "Secured Loans", "Stock-in-Hand", "Sundry Creditors",
    "Sundry Debtors", "Suspense A/c", "Unsecured Loans",
]


@pytest.mark.parametrize("name", TALLY_PREDEFINED_GROUPS)
def test_every_predefined_tally_group_maps_to_one_of_ours(name):
    assert normal_name(name) in TALLY_GROUPS, f"{name!r} is not mapped"
    assert TALLY_GROUPS[normal_name(name)] in LedgerGroup.values


def test_the_starter_chart_is_sound():
    names = [name for name, _ in STARTER_LEDGERS]
    assert len(names) == len({normal_name(n) for n in names}), "a starter ledger is listed twice"
    seeded = {normal_name(name) for name, _ in SEED_LEDGERS}
    assert not seeded & {normal_name(n) for n in names}, "a starter ledger repeats one every client already gets"
    assert all(group in LedgerGroup.values for _, group in STARTER_LEDGERS)
    # No group-like name (those are groups, not ledgers) and no ledger the reports compute.
    assert not {normal_name(n) for n in names} & {"profit & loss a/c", "sundry debtors", "sundry creditors", "secured loans", "unsecured loans"}
    # A bank or cash ledger comes from a statement, and Suspense is a seed: never a starter.
    assert not [n for n, group in STARTER_LEDGERS if group in (LedgerGroup.BANK, LedgerGroup.CASH, LedgerGroup.SUSPENSE)]
    # Every group used lands on a side of the books.
    sides = ASSET_GROUPS | LIABILITY_GROUPS | PROFIT_AND_LOSS_GROUPS
    assert all(group in sides for _, group in STARTER_LEDGERS)


def test_a_starter_ledger_agrees_with_the_standard_names_a_proposal_is_steered_to():
    """Where both lists name a ledger, the proposal would be turned into the starter ledger, so the group may differ only by Tally's finer
    Sales and Purchase accounts (a proposal for "Sales" as an income is the same ledger)."""
    standard = {normal_name(n): g for n, g in STANDARD_LEDGERS}
    finer = {("Sales", LedgerGroup.SALES), ("Purchases", LedgerGroup.PURCHASE)}
    for name, group in STARTER_LEDGERS:
        if normal_name(name) in standard and standard[normal_name(name)] != group:
            assert (name, group) in finer, f"{name}: starter {group}, standard {standard[normal_name(name)]}"
