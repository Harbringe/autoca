"""Trial Balance, P&L and Balance Sheet, over a real statement's entries.

The arithmetic is simple; the two things worth defending are that the trial
balance actually balances (if it does not, something bypassed the journal) and
that every report says out loud when it was built from incomplete books.
"""

from __future__ import annotations

import datetime

import pytest

from banking.ingest import confirm_opening_balance
from banking.tests.support import ingest_fixture_statement
from classify.engine import classify_statement, review, review_queue
from classify.models import LedgerAccount, LedgerGroup
from classify.seeds import seed_client
from core.db.session import firm_context
from core.models import FirmMembership, Role, User
from core.provisioning import create_client, create_firm
from ledger.approval import approve
from ledger.reports import balance_sheet, profit_and_loss, render_trial_balance, trial_balance

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

FY = 2025

# The statement runs 01-04-2025 to 03-06-2026, so it straddles two financial
# years: 44 of its 54 rows fall in FY2025-26 and 10 in FY2026-27.
FY2025_ENTRIES = 44
FY2026_ENTRIES = 10

# The accountant's own Tally ledger for this account, FY2025-26, prints
# 54,20,836.96 debit and 44,95,705.00 credit. These are those figures.
BANK_DEBIT = 54_20_836_96
BANK_CREDIT = 44_95_705_00
OPENING = 1_24_189_43


@pytest.fixture
def firm():
    return create_firm("Reports Test Firm")


@pytest.fixture
def client(firm):
    return create_client(firm, "Arjun Nair", datetime.date(2025, 4, 1))


@pytest.fixture
def senior(firm):
    user = User.objects.create_user(email="ca@example.com", password="correct-horse-battery")
    with firm_context(firm.pk):
        return FirmMembership.objects.create(firm=firm, user=user, role=Role.SENIOR_CA)


@pytest.fixture
def books(client, senior):
    """A statement ingested, classified, and posted in full."""
    with firm_context(client.firm_id):
        result = ingest_fixture_statement(client)
        confirm_opening_balance(
            result.bank_account, balance_paise=OPENING, as_of=datetime.date(2025, 4, 1)
        )
        seed_client(client)
        classify_statement(result.statement)

        expenses = ledger(client, "Sundry Expenses", LedgerGroup.INDIRECT_EXPENSE)
        income = ledger(client, "Sundry Income", LedgerGroup.INDIRECT_INCOME)
        while True:
            row = review_queue(client).first()
            if row is None:
                break
            # Leave the seeded suggestions where they are; only place what
            # nothing claimed, so the report has more than two ledgers in it.
            if row.ledger is None:
                target = expenses if row.transaction.is_debit else income
                row = review(row, target, learn=False)[0]
            approve(row, membership=senior)
        yield result


def ledger(client, name, group):
    return LedgerAccount.objects.get_or_create(
        firm_id=client.firm_id, client=client, name=name, defaults={"group": group}
    )[0]


# ---------------------------------------------------------------------------
# Trial balance
# ---------------------------------------------------------------------------


def test_the_trial_balance_balances(client, books):
    """If it does not, something wrote to the books without going through a voucher."""
    report = trial_balance(client, FY)

    assert report.rows
    assert report.balances
    assert report.total_debit_paise == report.total_credit_paise


def test_the_bank_ledger_matches_the_accountants_own_tally_totals(client, books):
    """The strongest assertion available: their figures, independently reached.

    The accountant's Tally ledger for this account over FY2025-26 shows a debit
    total of 54,20,836.96 and a credit total of 44,95,705.00. This system parsed
    the same PDF, classified it differently, and posted its own vouchers -- and
    arrives at those totals to the paisa.
    """
    bank = next(r for r in trial_balance(client, FY).rows if r.name.startswith("Axis Bank"))

    assert bank.debit_paise == BANK_DEBIT
    assert bank.credit_paise == BANK_CREDIT
    assert bank.opening_paise == OPENING
    assert bank.net_paise == OPENING + BANK_DEBIT - BANK_CREDIT


def test_it_renders_in_the_shape_a_firm_already_reads(client, books):
    text = render_trial_balance(trial_balance(client, FY))

    assert "Particulars" in text
    assert "₹" in text
    assert "Total" in text


# ---------------------------------------------------------------------------
# Profit and loss
# ---------------------------------------------------------------------------


def test_profit_and_loss_separates_income_from_expenditure(client, books):
    report = profit_and_loss(client, FY)

    assert {row.name for row in report.income} == {"Sundry Income", "Bank Interest Received"}
    assert {row.name for row in report.expenses} == {"Sundry Expenses"}
    assert report.total_income_paise > 0
    assert report.total_expenses_paise > 0


def test_net_profit_is_income_less_expenditure(client, books):
    report = profit_and_loss(client, FY)

    assert report.net_profit_paise == report.total_income_paise - report.total_expenses_paise


def test_the_bank_account_is_not_in_the_profit_and_loss(client, books):
    """A bank balance is an asset, not income. Getting this wrong doubles turnover."""
    report = profit_and_loss(client, FY)
    names = {row.name for row in report.income} | {row.name for row in report.expenses}

    assert not any(name.startswith("Axis Bank") for name in names)


# ---------------------------------------------------------------------------
# Balance sheet
# ---------------------------------------------------------------------------


def test_the_balance_sheet_carries_the_bank_as_an_asset(client, books):
    report = balance_sheet(client, FY)

    assert any(row.name.startswith("Axis Bank") for row in report.assets)


def test_assets_equal_liabilities_plus_profit(client, books):
    report = balance_sheet(client, FY)

    assert report.balances


def test_suspense_is_reported_separately(client, senior):
    """A balance sheet with a suspense figure is one with a question on it."""
    with firm_context(client.firm_id):
        result = ingest_fixture_statement(client)
        seed_client(client)
        classify_statement(result.statement)
        suspense = ledger(client, "Suspense A/c", LedgerGroup.SUSPENSE)
        row = (
            review_queue(client)
            .filter(ledger__isnull=True, transaction__value_date__year=2025)
            .first()
        )
        approve(review(row, suspense, learn=False)[0], membership=senior)

        report = balance_sheet(client, FY)
        assert report.suspense_paise != 0
        assert not any(r.name == "Suspense A/c" for r in report.liabilities)


# ---------------------------------------------------------------------------
# The footer
# ---------------------------------------------------------------------------


def test_a_report_over_complete_books_says_so(client, books):
    footer = trial_balance(client, FY).footer

    assert footer.is_complete
    assert footer.pending_review == 0
    assert footer.entry_count == FY2025_ENTRIES
    assert "INCOMPLETE" not in footer.caption()


def test_a_report_over_unreviewed_data_says_so_loudly(client, senior):
    """A firm must not hand a client an incomplete report without knowing."""
    with firm_context(client.firm_id):
        result = ingest_fixture_statement(client)
        seed_client(client)
        classify_statement(result.statement)

        footer = trial_balance(client, FY).footer

        assert not footer.is_complete
        assert footer.pending_review == FY2025_ENTRIES
        assert "INCOMPLETE" in footer.caption()
        assert f"{FY2025_ENTRIES} transaction(s)" in footer.caption()


def test_the_footer_names_the_financial_year_the_indian_way(client, books):
    footer = trial_balance(client, FY).footer

    assert footer.fy_label == "2025-26"
    assert footer.period_start == datetime.date(2025, 4, 1)
    assert footer.period_end == datetime.date(2026, 3, 31)


def test_each_financial_year_reports_only_its_own_entries(client, books):
    """This statement straddles 31 March, which is where FY bugs live.

    A report that swept both years together would overstate the client's income
    by a quarter, and the mistake would be invisible in either year alone.
    """
    this_year = trial_balance(client, FY)
    next_year = trial_balance(client, FY + 1)

    assert this_year.footer.entry_count == FY2025_ENTRIES
    assert next_year.footer.entry_count == FY2026_ENTRIES
    assert this_year.footer.entry_count + next_year.footer.entry_count == 54
    assert this_year.balances and next_year.balances


# ---------------------------------------------------------------------------
# Opening balances and carrying forward
# ---------------------------------------------------------------------------


def test_the_confirmed_opening_balance_is_in_the_books(client, books):
    """The bank's closing figure in the balance sheet is what the bank itself printed."""
    report = balance_sheet(client, FY)
    bank = next(r for r in report.assets if r.name.startswith("Axis Bank"))
    difference = next(r for r in report.liabilities if r.name == "Difference in opening balances")

    assert bank.opening_paise == OPENING
    assert difference.net_paise == -OPENING
    assert report.balances
    assert trial_balance(client, FY).balances


def test_the_bank_closing_matches_month_end_reconciliation(client, books):
    from ledger.reconciliation import ledger_balance

    bank_row = next(r for r in trial_balance(client, FY).rows if r.name.startswith("Axis Bank"))
    assert bank_row.net_paise == ledger_balance(books.bank_account, datetime.date(2026, 3, 31))


def test_the_next_year_carries_balances_and_last_years_result_forward(client, books):
    this_year = trial_balance(client, FY)
    next_year = trial_balance(client, FY + 1)
    last_pl = profit_and_loss(client, FY)

    bank_now = next(r for r in this_year.rows if r.name.startswith("Axis Bank"))
    bank_next = next(r for r in next_year.rows if r.name.startswith("Axis Bank"))
    assert bank_next.opening_paise == bank_now.net_paise

    brought_forward = next(r for r in next_year.rows if r.name == "Profit & Loss A/c")
    assert brought_forward.net_paise == -last_pl.net_profit_paise

    income_next = [r for r in next_year.rows if r.is_profit_and_loss]
    assert all(r.opening_paise == 0 for r in income_next)
    assert next_year.balances
    assert balance_sheet(client, FY + 1).balances


def test_without_a_confirmed_opening_there_is_no_difference_line(client, senior):
    with firm_context(client.firm_id):
        result = ingest_fixture_statement(client)
        seed_client(client)
        classify_statement(result.statement)
        row = review_queue(client).filter(ledger__isnull=False).first()
        approve(row, membership=senior)

        names = {r.name for r in trial_balance(client, FY).rows}
        assert "Difference in opening balances" not in names
