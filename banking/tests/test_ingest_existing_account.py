"""A statement for an account the client already has (set up from Tally, or saved with its number masked) goes to that account, and
a statement whose opening the books already disagree with says so. Real PostgreSQL, like the rest of the ingest tests."""

from __future__ import annotations

import datetime

import pytest

from banking.ingest import ingest_statement, numbers_name_one_account
from banking.models import BankAccount
from core.db.session import firm_context
from core.provisioning import create_client, create_firm

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

#: The fixture statement (``b"%PDF-1.4 axis"``) is account 900000000000001, from 01-04-2025, opening 1,24,189.43.
AXIS = b"%PDF-1.4 axis"


@pytest.fixture
def client():
    firm = create_firm("Existing Account Firm")
    return create_client(firm, "Sample Traders", datetime.date(2025, 4, 1))


def _account(client, number, *, code="BANK", ledger="Sample Bank SB A/c", opening=None):
    account = BankAccount(firm_id=client.firm_id, client=client, bank_code=code, ledger_name=ledger)
    account.set_account_number(number)
    if opening is not None:
        account.opening_balance_paise, account.opening_as_of = opening, datetime.date(2025, 3, 31)
    account.save()
    return account


def test_the_same_number_under_another_bank_code_is_the_same_account(client):
    with firm_context(client.firm_id):
        existing = _account(client, "900000000000001", ledger="Sample Bank SB A/c 900000000000001")
        result = ingest_statement(client=client, data=AXIS)
        assert result.bank_account.pk == existing.pk
        assert BankAccount.objects.filter(client=client).count() == 1


def test_an_account_saved_with_a_masked_number_takes_the_statement_that_prints_it_in_full(client):
    with firm_context(client.firm_id):
        existing = _account(client, "XXXXXXXXXXX0001", ledger="Sample Bank CA A/c 0001")
        assert ingest_statement(client=client, data=AXIS).bank_account.pk == existing.pk


def test_two_accounts_that_could_both_be_it_are_not_guessed_between(client):
    with firm_context(client.firm_id):
        _account(client, "XXXXXXXXXXX0001", ledger="First A/c")
        _account(client, "XXXX0001", ledger="Second A/c")
        result = ingest_statement(client=client, data=AXIS)
        assert result.bank_account.ledger_name not in ("First A/c", "Second A/c")


def test_a_statement_that_does_not_start_where_the_books_are_says_so(client):
    with firm_context(client.firm_id):
        _account(client, "900000000000001", code="AXIS", ledger="Sample Bank SB A/c", opening=1_00_000_00)
        result = ingest_statement(client=client, data=AXIS)
        assert result.books_balance_before_paise == 1_00_000_00  # the books, against the statement's 1,24,189.43


def test_a_statement_that_starts_where_the_books_are_says_nothing(client):
    with firm_context(client.firm_id):
        _account(client, "900000000000001", code="AXIS", ledger="Sample Bank SB A/c", opening=1_24_189_43)
        assert ingest_statement(client=client, data=AXIS).books_balance_before_paise is None


def test_with_no_confirmed_opening_the_books_cannot_disagree(client):
    with firm_context(client.firm_id):
        assert ingest_statement(client=client, data=AXIS).books_balance_before_paise is None


@pytest.mark.parametrize(
    "saved, printed, same",
    [
        ("97940200001458", "979XXXXXXXX458", True),
        ("XXX691", "12340000691", True),
        ("97940100000190", "97940100000190", True),
        ("97940100000190", "979XXXXXXXX458", False),
        ("XXX458", "XXX691", False),
        ("12345", "123456", False),
    ],
)
def test_masked_and_full_numbers(saved, printed, same):
    assert numbers_name_one_account(saved, printed) is same
