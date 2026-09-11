"""Ingestion: the path from uploaded bytes to rows, under a tenant context.

These run against real PostgreSQL with RLS in force, like the rest of the
firm-scoped suite. A test that passed on SQLite would be testing a database
that cannot express the isolation this system depends on.
"""

from __future__ import annotations

import datetime
import json
from decimal import Decimal

import pytest

from banking.ingest import ingest_statement
from banking.models import BankAccount, Statement, StatementTransaction
from banking.tests.conftest import FIXTURES
from core.db.session import firm_context
from core.provisioning import create_client, create_firm
from integrations.pdf.base import PdfDocument, PdfTextAdapter

pytestmark = pytest.mark.django_db

FIXTURE_JSON = json.loads(
    (FIXTURES / "axis_savings_statement.json").read_text(encoding="utf-8")
)


class FixturePdfAdapter(PdfTextAdapter):
    """Returns the captured statement regardless of the bytes handed to it.

    Ingestion is being tested here, not extraction, and the input bytes still
    matter: they are what the content hash and the stored object are built from.
    """

    def __init__(self, **_ignored):
        pass

    def extract(self, data: bytes) -> PdfDocument:
        return PdfDocument.from_dict(FIXTURE_JSON)


@pytest.fixture
def firm():
    return create_firm("Ingest Test Firm")


@pytest.fixture
def client(firm):
    return create_client(firm, "Ramesh Deshmukh", datetime.date(2025, 4, 1))


@pytest.fixture(autouse=True)
def _fixture_adapters(tmp_path, settings):
    settings.INTEGRATIONS = {
        **settings.INTEGRATIONS,
        "pdf": "banking.tests.test_ingest.FixturePdfAdapter",
        "storage": "integrations.storage.local.LocalStorageAdapter",
    }
    settings.INTEGRATION_OPTIONS = {
        **settings.INTEGRATION_OPTIONS,
        "pdf": {},
        "storage": {"root": str(tmp_path / "storage")},
    }
    from integrations.registry import reset_adapter_cache

    reset_adapter_cache()
    yield
    reset_adapter_cache()


def test_ingest_creates_the_account_statement_and_every_row(client):
    with firm_context(client.firm_id):
        result = ingest_statement(client=client, data=b"%PDF-1.4 axis", filename="axis.pdf")

        assert result.is_new
        assert result.rows_created == 54
        assert result.rows_already_present == 0

        account = result.bank_account
        assert account.bank_code == "AXIS"
        assert account.account_number == "911010000004321"
        assert account.ifsc == "UTIB0000318"

        statement = result.statement
        assert statement.period_start == datetime.date(2025, 4, 1)
        assert statement.opening_balance == Decimal("124189.43")
        assert statement.closing_balance == Decimal("603490.57")
        assert statement.transaction_count == 54
        assert StatementTransaction.objects.filter(statement=statement).count() == 54


def test_the_ledger_name_matches_tallys_convention(client):
    """Vouchers name this string on export; a near-miss creates a second ledger."""
    with firm_context(client.firm_id):
        result = ingest_statement(client=client, data=b"%PDF-1.4 axis")

        assert result.bank_account.ledger_name == "Axis Bank A/c 911010000004321"


def test_rows_keep_the_banks_own_figures(client):
    with firm_context(client.firm_id):
        ingest_statement(client=client, data=b"%PDF-1.4 axis")

        first = StatementTransaction.objects.order_by("row_number").first()
        assert first.value_date == datetime.date(2025, 4, 13)
        assert first.narration == "Sweep/VO000000087559330/19000014841287"
        assert first.debit == Decimal("250.00")
        assert first.credit == Decimal("0.00")
        assert first.balance == Decimal("123939.43")
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

        key = result.statement.storage_key
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
