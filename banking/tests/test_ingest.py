"""Ingestion: the path from uploaded bytes to rows, under a tenant context.

These run against real PostgreSQL with RLS in force, like the rest of the
firm-scoped suite. A test that passed on SQLite would be testing a database
that cannot express the isolation this system depends on.
"""

from __future__ import annotations

import datetime

import pytest

from banking.ingest import ingest_statement
from banking.models import BankAccount, Statement, StatementTransaction
from core.db.session import firm_context
from core.provisioning import create_client, create_firm
from documents.models import Document

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


@pytest.fixture
def firm():
    return create_firm("Ingest Test Firm")


@pytest.fixture
def client(firm):
    return create_client(firm, "Arjun Nair", datetime.date(2025, 4, 1))


def test_ingest_creates_the_account_statement_and_every_row(client):
    with firm_context(client.firm_id):
        result = ingest_statement(client=client, data=b"%PDF-1.4 axis", filename="axis.pdf")

        assert result.is_new
        assert result.rows_created == 54
        assert result.rows_already_present == 0

        account = result.bank_account
        assert account.bank_code == "AXIS"
        assert account.account_number == "900000000000001"
        assert account.ifsc == "UTIB0000001"
        assert account.account_last4 == "0001"

        statement = result.statement
        assert statement.period_start == datetime.date(2025, 4, 1)
        assert statement.opening_balance_paise == 1_24_189_43
        assert statement.closing_balance_paise == 6_03_490_57
        assert statement.transaction_count == 54
        assert StatementTransaction.objects.filter(statement=statement).count() == 54


def test_the_ledger_name_matches_tallys_convention(client):
    """Vouchers name this string on export; a near-miss creates a second ledger."""
    with firm_context(client.firm_id):
        result = ingest_statement(client=client, data=b"%PDF-1.4 axis")

        assert result.bank_account.ledger_name == "Axis Bank A/c 0001"


def test_two_accounts_ending_alike_do_not_share_a_ledger(client):
    """Sharing one would merge two accounts' books; the second falls back to its full number."""
    with firm_context(client.firm_id):
        first = ingest_statement(client=client, data=b"%PDF-1.4 axis").bank_account
        twin = BankAccount(firm_id=client.firm_id, client=client, bank_code="AXIS")
        twin.set_account_number("922020000000001")
        twin.save()

        assert twin.ledger_name == "Axis Bank A/c 922020000000001"
        assert twin.ledger_name != first.ledger_name


def test_renaming_the_bank_ledger_carries_its_entries(client):
    from classify.models import LedgerAccount
    from classify.seeds import LedgerRenameError, contra_ledger_for, rename_account_ledger

    with firm_context(client.firm_id):
        account = ingest_statement(client=client, data=b"%PDF-1.4 axis").bank_account
        ledger = contra_ledger_for(account)

        rename_account_ledger(account, "Axis Bank Current A/c")

        ledger.refresh_from_db()
        assert ledger.name == "Axis Bank Current A/c"
        assert contra_ledger_for(account).pk == ledger.pk
        assert LedgerAccount.objects.filter(client=client, name="Axis Bank A/c 0001").count() == 0

        LedgerAccount.objects.create(firm_id=client.firm_id, client=client, name="Taken")
        with pytest.raises(LedgerRenameError):
            rename_account_ledger(account, "Taken")


def test_rows_keep_the_banks_own_figures(client):
    with firm_context(client.firm_id):
        ingest_statement(client=client, data=b"%PDF-1.4 axis")

        first = StatementTransaction.objects.order_by("row_number").first()
        assert first.value_date == datetime.date(2025, 4, 13)
        assert first.narration == "Sweep/VO000000012345678/19000000000001"
        assert first.debit_paise == 250_00
        assert first.credit_paise == 0
        assert first.balance_paise == 1_23_939_43
        assert first.branch_code == "318"


def test_the_same_file_twice_is_the_same_statement(client):
    """Re-uploading is a user action, not a user error: no duplicate, no exception."""
    with firm_context(client.firm_id):
        first = ingest_statement(client=client, data=b"%PDF-1.4 axis", filename="axis.pdf")
        second = ingest_statement(client=client, data=b"%PDF-1.4 axis", filename="axis-copy.pdf")

        assert not second.is_new
        assert second.statement.pk == first.statement.pk
        assert Statement.objects.count() == 1
        assert StatementTransaction.objects.count() == 54


def test_an_overlapping_period_does_not_double_up_the_rows(client):
    """A client sends Apr-Sep in October and Apr-Mar in April. Every year.

    The files differ, so both are ingested as statements; the transactions they
    share are recognised and written once.
    """
    with firm_context(client.firm_id):
        ingest_statement(client=client, data=b"%PDF-1.4 axis", filename="part.pdf")
        again = ingest_statement(client=client, data=b"%PDF-1.4 axis full year", filename="full.pdf")

        assert again.is_new
        assert again.rows_created == 0
        assert again.rows_already_present == 54
        assert Statement.objects.count() == 2
        assert StatementTransaction.objects.count() == 54


def test_the_original_file_is_kept_as_evidence(client):
    """The parse is derived. The PDF is what a client or an assessing officer sees."""
    from integrations.registry import get_storage

    with firm_context(client.firm_id):
        result = ingest_statement(client=client, data=b"%PDF-1.4 axis", filename="axis.pdf")

        key = result.document.storage_key
        assert key.startswith(f"firms/{client.firm_id}/")
        assert get_storage().get(key) == b"%PDF-1.4 axis"


def test_a_second_firm_cannot_see_the_first_firms_statements(client):
    other = create_firm("Other Firm")

    with firm_context(client.firm_id):
        ingest_statement(client=client, data=b"%PDF-1.4 axis")

    with firm_context(other.pk):
        assert BankAccount.objects.count() == 0
        assert Statement.objects.count() == 0
        assert StatementTransaction.objects.count() == 0
        assert Document.objects.count() == 0
