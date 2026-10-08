"""Where a ledger sits on the ICAI-format statements, worked out each year from its group, its name and the sign of its balance."""

from __future__ import annotations

import pytest

from classify.models import LedgerGroup
from ledger.nce import LINES, _place
from ledger.reports import LedgerBalance


def row(name, group, net):
    """A ledger with a closing position of ``net`` (debits positive)."""
    return LedgerBalance(name=name, group=group, debit_paise=max(net, 0), credit_paise=max(-net, 0))


@pytest.mark.parametrize(
    ("name", "group", "net", "line"),
    [
        ("Ravi Traders", LedgerGroup.CREDITOR, -500, "CL.PAY"),
        ("Ravi Traders", LedgerGroup.CREDITOR, 500, "CA.LOANS"),  # we paid more than we owed: an advance, an asset
        ("Acme Ltd", LedgerGroup.DEBTOR, 900, "CA.REC"),
        ("Acme Ltd", LedgerGroup.DEBTOR, -900, "CL.OTH"),  # a customer's advance is a liability
        ("HDFC Bank", LedgerGroup.BANK, 100, "CA.CASH"),
        ("HDFC Bank", LedgerGroup.BANK, -100, "CL.BORR"),  # overdrawn
        ("Cash", LedgerGroup.CASH, 100, "CA.CASH"),
        ("TDS Payable", LedgerGroup.DUTIES_AND_TAXES, -50, "CL.OTH"),
        ("TDS Receivable", LedgerGroup.CURRENT_ASSET, 50, "CA.OTH"),
        ("Term Loan - SBI", LedgerGroup.LOAN, -9000, "NCL.BORR"),
        ("Cash Credit - SBI", LedgerGroup.LOAN, -9000, "CL.BORR"),
        ("Laptops", LedgerGroup.FIXED_ASSET, 70000, "NCA.PPE"),
        ("Tally Software", LedgerGroup.FIXED_ASSET, 7000, "NCA.INTANG"),
        ("Partners Capital", LedgerGroup.CAPITAL, -100000, "EQ.CAP"),
        ("Sales", LedgerGroup.SALES, -1000, "PL.REV"),
        ("Interest Received", LedgerGroup.INDIRECT_INCOME, -10, "PL.OTH"),
        ("Purchases", LedgerGroup.PURCHASE, 600, "PL.COGS"),
        ("Salary", LedgerGroup.INDIRECT_EXPENSE, 200, "PL.EMP"),
        ("Interest on Term Loan", LedgerGroup.INDIRECT_EXPENSE, 30, "PL.FIN"),
        ("Depreciation", LedgerGroup.INDIRECT_EXPENSE, 20, "PL.DEP"),
        ("Partners' Remuneration", LedgerGroup.INDIRECT_EXPENSE, 100, "PL.PREM"),
        ("Provision for Income Tax", LedgerGroup.INDIRECT_EXPENSE, 40, "PL.TAXC"),
        ("Bank Charges", LedgerGroup.INDIRECT_EXPENSE, 5, "PL.EXP"),
        ("Profit & Loss A/c", LedgerGroup.CAPITAL, -300, "EQ.RES"),
        ("Difference in opening balances", LedgerGroup.CAPITAL, -300, "EQ.CAP"),
    ],
)
def test_a_ledger_lands_on_the_line_its_group_name_and_balance_say(name, group, net, line):
    assert _place(row(name, group, net)) == line


def test_the_same_party_lands_on_different_lines_in_different_years():
    """Lent money one year (a debit balance), borrowed the next (a credit): an asset, then a liability."""
    assert _place(row("Related Party", LedgerGroup.CREDITOR, 800)) == "CA.LOANS"
    assert _place(row("Related Party", LedgerGroup.CREDITOR, -800)) == "CL.PAY"


def test_a_ledgers_own_line_overrides_everything():
    assert _place(row("Mystery", LedgerGroup.INDIRECT_EXPENSE, 10), override="PL.FIN") == "PL.FIN"
    assert _place(row("Mystery", LedgerGroup.INDIRECT_EXPENSE, 10), override="not-a-line") == "PL.EXP"


def test_every_line_has_a_side_and_the_notes_the_format_numbers():
    assert {d.side for d in LINES.values()} == {"L", "A", "PI", "PE"}
    assert LINES["CL.PAY"].note == 9 and LINES["PL.EXP"].note == 25 and LINES["EQ.CAP"].note == 3


from ledger.nce import _partners, _section, _unit, normalise_settings  # noqa: E402


def test_a_note_lists_each_ledger_under_its_sub_head():
    assert _section(19, "PL.REV", row("Sales", LedgerGroup.SALES, -1))[0] == "Sale of products"
    assert _section(19, "PL.REV", row("Consulting Fees", LedgerGroup.DIRECT_INCOME, -1))[0] == "Sale of services"
    assert _section(19, "PL.REV", row("Export Incentive", LedgerGroup.SALES, -1))[0] == "Other operating revenue"
    assert _section(25, "PL.EXP", row("Office Rent", LedgerGroup.INDIRECT_EXPENSE, 1))[0] == "Rent"
    assert _section(25, "PL.EXP", row("Audit Fees", LedgerGroup.INDIRECT_EXPENSE, 1))[0] == "Payments to auditors"
    assert _section(25, "PL.EXP", row("Sundry", LedgerGroup.INDIRECT_EXPENSE, 1))[0] == "Miscellaneous expenses"
    assert _section(5, "NCL.BORR", row("Term Loan - HDFC Bank", LedgerGroup.LOAN, -1))[0] == "Long-term · Term loans from banks"
    assert _section(5, "CL.BORR", row("Cash Credit - SBI", LedgerGroup.LOAN, -1))[0] == "Short-term · Loans repayable on demand"
    assert _section(10, "CL.OTH", row("TDS Payable", LedgerGroup.DUTIES_AND_TAXES, -1))[0] == "TDS payable"
    assert _section(17, "CA.CASH", row("Cash", LedgerGroup.CASH, 1))[0] == "Cash on hand"
    assert _section(17, "CA.CASH", row("HDFC Current", LedgerGroup.BANK, 1))[0] == "Balances with banks"
    assert _section(9, "CL.PAY", row("Ravi Traders", LedgerGroup.CREDITOR, -1))[0] == ""


def test_rounding_goes_to_the_nearest_unit_away_from_zero_at_the_half():
    assert _unit(12_345_67, 100) == 12_345_67
    assert _unit(12_345_67, 100_000) == 12_000_00
    assert _unit(12_500_00, 100_000) == 13_000_00
    assert _unit(-12_500_00, 100_000) == -13_000_00
    assert _unit(49_99, 100_000) == 0


def test_saved_settings_are_cleaned_whatever_was_stored():
    cleaned = normalise_settings({"rounding": "parsecs", "about": 7, "years": {"2025": {"partners": [{"name": " ", "share_bp": 1}, {"name": "A", "share_bp": 99_999, "opening_paise": -5}]}, "x": "y"}})
    assert cleaned["rounding"] == "rupees" and cleaned["about"] == "7"
    assert cleaned["years"]["2025"]["partners"] == [
        {"name": "A", "share_bp": 10_000, "opening_paise": 0, "introduced_paise": 0, "remuneration_paise": 0, "interest_paise": 0, "withdrawals_paise": 0}
    ]
    assert normalise_settings(None)["years"] == {}


def test_a_profit_is_split_to_the_paisa_with_the_leftover_going_to_the_first_partner():
    settings = normalise_settings({"years": {"2025": {"partners": [{"name": "A", "share_bp": 3333}, {"name": "B", "share_bp": 3333}, {"name": "C", "share_bp": 3334}]}}})
    rows = _partners(settings, 2025, 100, {})
    assert sum(r.profit_share_paise for r in rows) == 100


import datetime  # noqa: E402

from ledger.nce import _tally, suggest_size  # noqa: E402
from ledger.nce_ageing import add_months, is_over_six_months, split_by_age  # noqa: E402


def test_size_follows_the_icai_criteria_and_the_two_answers_only_a_person_can_give():
    assert suggest_size(100 * 10_000_000 * 100, 10 * 10_000_000 * 100)[0] == "msme"
    assert suggest_size(251 * 10_000_000 * 100, 0)[0] == "large"
    assert suggest_size(0, 51 * 10_000_000 * 100)[0] == "large"
    assert suggest_size(0, 0, bank_or_insurer=True)[0] == "large"
    assert suggest_size(0, 0, non_msme_group=True)[0] == "large"


def test_six_months_are_counted_from_the_due_date_or_failing_that_the_bill_date():
    day = datetime.date
    assert add_months(day(2025, 8, 31), 6) == day(2026, 2, 28)
    assert is_over_six_months(day(2025, 9, 30), day(2025, 9, 1), day(2026, 3, 31)) is True
    assert is_over_six_months(day(2025, 10, 1), day(2025, 9, 1), day(2026, 3, 31)) is False
    assert is_over_six_months(None, day(2025, 9, 30), day(2026, 3, 31)) is True  # no due date: the bill's own date
    under, over = split_by_age([(None, day(2025, 4, 1), 300), (day(2026, 2, 1), day(2026, 1, 1), 200), (None, day(2025, 4, 2), 0)], day(2026, 3, 31))
    assert (under, over) == (200, 300)


def test_every_ledger_is_rounded_before_anything_is_added():
    rows = [row("A", LedgerGroup.SALES, -149_00), row("B", LedgerGroup.SALES, -149_00), row("C", LedgerGroup.SALES, -149_00)]
    totals, parts = _tally(rows, {}, unit=10_000)  # hundreds
    assert totals["PL.REV"] == 3 * 100_00  # each 149 became 100, not 447 -> 400
    assert [p for _, p in parts["PL.REV"]] == [100_00] * 3


def test_a_ledger_pinned_to_a_sub_head_goes_there_and_a_catch_all_is_a_guess():
    from ledger.nce import _section

    sundry = row("Sundry", LedgerGroup.INDIRECT_EXPENSE, 1)
    assert _section(25, "PL.EXP", sundry) == ("Miscellaneous expenses", True)
    assert _section(25, "PL.EXP", sundry, pinned="Rent") == ("Rent", False)
    assert _section(25, "PL.EXP", sundry, pinned="Not a sub-head") == ("Miscellaneous expenses", True)
    assert _section(25, "PL.EXP", row("Office Rent", LedgerGroup.INDIRECT_EXPENSE, 1)) == ("Rent", False)
    loan = row("Friend", LedgerGroup.LOAN, -1)
    assert _section(5, "NCL.BORR", loan, pinned="Loans and advances from related parties") == ("Long-term · Loans and advances from related parties", False)


from ledger import depreciation  # noqa: E402
from ledger.nce_assets import AssetFacts, block_for  # noqa: E402


def facts(kind, cost, put_to_use, disposed_on=None, life=10):
    terms = depreciation.AssetTerms(cost_paise=cost, put_to_use=put_to_use, method="SLM", life_years=life, disposed_on=disposed_on)
    return AssetFacts(kind, cost, put_to_use, disposed_on, tuple(depreciation.schedule(terms, through_year=2030)))


def test_the_block_rolls_forward_from_one_year_to_the_next():
    day = datetime.date
    machine = facts("Plant and machinery", 10_00_000_00, day(2024, 4, 1))
    bought = facts("Plant and machinery", 5_00_000_00, day(2025, 10, 1))
    sold = facts("Vehicles", 4_00_000_00, day(2023, 4, 1), disposed_on=day(2025, 6, 30), life=4)

    now = block_for([machine, bought, sold], 2025)

    plant = now["Plant and machinery"]
    assert (plant.gross_open, plant.additions, plant.deductions, plant.gross_close) == (10_00_000_00, 5_00_000_00, 0, 15_00_000_00)
    assert plant.dep_open == 1_00_000_00  # one full year of the first machine
    assert plant.dep_close == plant.dep_open + plant.dep_year
    assert plant.net_close == plant.gross_close - plant.dep_close
    car = now["Vehicles"]
    assert (car.gross_open, car.deductions, car.gross_close) == (4_00_000_00, 4_00_000_00, 0)
    assert car.dep_close == 0 and car.net_close == 0  # what was charged on it leaves with it
    assert car.dep_deductions == car.dep_open + car.dep_year


def test_the_net_block_at_the_start_of_a_year_is_the_end_of_the_one_before():
    asset = facts("Plant and machinery", 10_00_000_00, datetime.date(2024, 4, 1))
    assert block_for([asset], 2025)["Plant and machinery"].net_close < block_for([asset], 2024)["Plant and machinery"].net_close
    assert block_for([asset], 2025)["Plant and machinery"].gross_open == block_for([asset], 2024)["Plant and machinery"].gross_close
    assert block_for([asset], 2025)["Plant and machinery"].dep_open == block_for([asset], 2024)["Plant and machinery"].dep_close
