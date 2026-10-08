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
    assert _section(19, "PL.REV", row("Sales", LedgerGroup.SALES, -1)) == "Sale of products"
    assert _section(19, "PL.REV", row("Consulting Fees", LedgerGroup.DIRECT_INCOME, -1)) == "Sale of services"
    assert _section(19, "PL.REV", row("Export Incentive", LedgerGroup.SALES, -1)) == "Other operating revenue"
    assert _section(25, "PL.EXP", row("Office Rent", LedgerGroup.INDIRECT_EXPENSE, 1)) == "Rent"
    assert _section(25, "PL.EXP", row("Audit Fees", LedgerGroup.INDIRECT_EXPENSE, 1)) == "Payments to auditors"
    assert _section(25, "PL.EXP", row("Sundry", LedgerGroup.INDIRECT_EXPENSE, 1)) == "Miscellaneous expenses"
    assert _section(5, "NCL.BORR", row("Term Loan - HDFC Bank", LedgerGroup.LOAN, -1)) == "Long-term · Term loans from banks"
    assert _section(5, "CL.BORR", row("Cash Credit - SBI", LedgerGroup.LOAN, -1)) == "Short-term · Loans repayable on demand"
    assert _section(10, "CL.OTH", row("TDS Payable", LedgerGroup.DUTIES_AND_TAXES, -1)) == "TDS payable"
    assert _section(17, "CA.CASH", row("Cash", LedgerGroup.CASH, 1)) == "Cash on hand"
    assert _section(17, "CA.CASH", row("HDFC Current", LedgerGroup.BANK, 1)) == "Balances with banks"
    assert _section(9, "CL.PAY", row("Ravi Traders", LedgerGroup.CREDITOR, -1)) == ""


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
