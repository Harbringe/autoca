"""Month end: does the ledger agree with the bank?

One subtraction that catches what every other check misses -- a row posted
twice, a correction reversed the wrong way, an entry approved against the wrong
account. It is also the check the firm already does by hand today, so it is the
one they will look at first.
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
from ledger.reconciliation import NoStatementError, check_balance, ledger_balance

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

OPENING = 1_24_189_43
CLOSING = 6_03_490_57


@pytest.fixture
def firm():
    return create_firm("Reconciliation Test Firm")


@pytest.fixture
def client(firm):
    return create_client(firm, "Arjun Nair", datetime.date(2025, 4, 1))


@pytest.fixture
def senior(firm):
    user = User.objects.create_user(email="ca@example.com", password="correct-horse-battery")
    with firm_context(firm.pk):
        return FirmMembership.objects.create(firm=firm, user=user, role=Role.SENIOR_CA)


@pytest.fixture
def account(client):
    """An ingested statement with its opening balance confirmed."""
    with firm_context(client.firm_id):
        result = ingest_fixture_statement(client)
        confirm_opening_balance(
            result.bank_account, balance_paise=OPENING, as_of=datetime.date(2025, 4, 1)
        )
        seed_client(client)
        classify_statement(result.statement)
        yield result.bank_account


def ledger(client, name, group=LedgerGroup.INDIRECT_EXPENSE):
    return LedgerAccount.objects.get_or_create(
        firm_id=client.firm_id, client=client, name=name, defaults={"group": group}
    )[0]


def approve_everything(client, senior):
    """Place every queued row in one bucket and post the lot."""
    suspense = ledger(client, "Suspense A/c", LedgerGroup.SUSPENSE)
    while True:
        row = review_queue(client).first()
        if row is None:
            return
        approve(review(row, suspense, learn=False)[0], membership=senior)


def test_a_fully_posted_period_reconciles(client, account, senior):
    """The books and the bank arrive at the same closing figure."""
    approve_everything(client, senior)

    check = check_balance(account, datetime.date(2026, 6, 3))

    assert check.statement_balance_paise == CLOSING
    assert check.ledger_balance_paise == CLOSING
    assert check.matches
    assert check.can_close


def test_an_unposted_period_does_not_reconcile_and_says_why(client, account, senior):
    """The commonest reason for a break is simply "not finished yet"."""
    check = check_balance(account, datetime.date(2026, 6, 3))

    assert not check.matches
    assert check.unapproved_count == 54
    assert not check.can_close
    assert "not posted" in check.explain() or "not been posted" in check.explain()
    assert "approved" not in check.explain()


def test_a_break_with_everything_posted_and_no_opening_balance_names_the_opening_balance(client, senior):
    with firm_context(client.firm_id):
        result = ingest_fixture_statement(client)
        seed_client(client)
        classify_statement(result.statement)
        approve_everything(client, senior)

        check = check_balance(result.bank_account, datetime.date(2026, 6, 3))

        assert not check.matches and check.unapproved_count == 0
        assert "opening balance has not been confirmed" in check.explain()
        assert "real break" not in check.explain()


def test_the_difference_is_reported_in_rupees(client, account, senior):
    check = check_balance(account, datetime.date(2026, 6, 3))

    assert check.difference_paise == OPENING - CLOSING
    assert "₹" in check.explain()


def test_a_partly_posted_period_cannot_be_closed(client, account, senior):
    """Reconciling is necessary but not sufficient -- outstanding work blocks close."""
    suspense = ledger(client, "Suspense A/c", LedgerGroup.SUSPENSE)
    row = review_queue(client).first()
    approve(review(row, suspense, learn=False)[0], membership=senior)

    check = check_balance(account, datetime.date(2026, 6, 3))

    assert not check.can_close
    assert check.unapproved_count == 53


def test_the_opening_balance_is_part_of_the_ledger_balance(client, account, senior):
    """A client onboarding mid-year has money this system never saw."""
    approve_everything(client, senior)
    assert ledger_balance(account, datetime.date(2026, 6, 3)) == CLOSING

    account.opening_balance_paise = 0
    account.save(update_fields=["opening_balance_paise"])

    assert ledger_balance(account, datetime.date(2026, 6, 3)) == CLOSING - OPENING


def test_reconciling_partway_through_a_statement_uses_that_days_balance(
    client, account, senior
):
    """The same figure the bank would print on a statement cut on that date."""
    approve_everything(client, senior)

    check = check_balance(account, datetime.date(2025, 4, 14))

    assert check.statement_balance_paise == 1_23_689_43  # after the second sweep
    assert check.matches


def test_a_date_no_statement_covers_is_refused(client, account):
    """Reconciling against nothing would silently "pass"."""
    with pytest.raises(NoStatementError, match="Upload the period first"):
        check_balance(account, datetime.date(2030, 1, 1))
