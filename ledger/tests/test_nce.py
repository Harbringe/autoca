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
