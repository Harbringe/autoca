"""Continuity across statements, and the opening balance a client starts from.

The balance chain proves nothing was lost *within* a statement. Nothing proves
it *between* statements, and a missing month does exactly the same damage. Both
gaps are surfaced rather than absorbed, because the alternative is books that
balance against a bank balance nobody reconciled.
"""

from __future__ import annotations

import datetime

import pytest

from banking.ingest import (
    StatementContinuityError,
    confirm_opening_balance,
    ingest_statement,
)
from banking.tests.support import ingest_fixture_statement
from core.db.session import firm_context
from core.provisioning import create_client, create_firm

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


@pytest.fixture
def client():
    firm = create_firm("Continuity Test Firm")
    return create_client(firm, "Ramesh Deshmukh", datetime.date(2025, 4, 1))


def test_the_first_statement_asks_for_an_opening_balance(client):
    """A client onboarding mid-year has history this system never saw.

    Starting them at zero, or silently at the statement's own opening line,
    misstates every balance from then on.
    """
    with firm_context(client.firm_id):
        result = ingest_fixture_statement(client)

        assert result.needs_opening_confirmation
        assert not result.bank_account.has_opening_balance


def test_confirming_the_opening_balance_records_it_with_its_date(client):
    with firm_context(client.firm_id):
        account = ingest_fixture_statement(client).bank_account

        confirm_opening_balance(
            account, balance_paise=1_24_189_43, as_of=datetime.date(2025, 4, 1)
        )
        account.refresh_from_db()

        assert account.has_opening_balance
        assert account.opening_balance_paise == 1_24_189_43
        assert account.opening_as_of == datetime.date(2025, 4, 1)


def test_a_missing_statement_period_is_a_blocking_error(client, monkeypatch):
    """The second statement must open where the first one closed."""
    from banking import ingest as ingest_module

    with firm_context(client.firm_id):
        ingest_fixture_statement(client, filename="first.pdf")

        # A later statement whose opening figure does not continue from the
        # closing figure of the one already on file.
        original = ingest_module.detect_parser

        def _shifted(document):
            parser = original(document)
            real_parse = parser.parse

            def parse(doc):
                import dataclasses

                parsed = real_parse(doc)
                return dataclasses.replace(
                    parsed,
                    period_start=datetime.date(2026, 8, 1),
                    period_end=datetime.date(2026, 9, 30),
                    transactions=(),
                    opening_balance_paise=9_99_999_00,
                    closing_balance_paise=9_99_999_00,
                    stated_total_debit_paise=None,
                    stated_total_credit_paise=None,
                )

            parser.parse = parse
            return parser

        monkeypatch.setattr(ingest_module, "detect_parser", _shifted)

        with pytest.raises(StatementContinuityError, match="period is missing"):
            ingest_statement(client=client, data=b"%PDF gap", filename="gap.pdf")


def test_a_gap_can_be_recorded_deliberately(client, monkeypatch):
    """Sometimes the earlier period genuinely is not available. Say so explicitly."""
    from banking import ingest as ingest_module

    with firm_context(client.firm_id):
        ingest_fixture_statement(client, filename="first.pdf")

        original = ingest_module.detect_parser

        def _shifted(document):
            parser = original(document)
            real_parse = parser.parse

            def parse(doc):
                import dataclasses

                parsed = real_parse(doc)
                return dataclasses.replace(
                    parsed,
                    period_start=datetime.date(2026, 8, 1),
                    period_end=datetime.date(2026, 9, 30),
                    transactions=(),
                    opening_balance_paise=9_99_999_00,
                    closing_balance_paise=9_99_999_00,
                    stated_total_debit_paise=None,
                    stated_total_credit_paise=None,
                )

            parser.parse = parse
            return parser

        monkeypatch.setattr(ingest_module, "detect_parser", _shifted)

        result = ingest_statement(
            client=client, data=b"%PDF gap", filename="gap.pdf", allow_gap=True
        )
        assert result.is_new


def test_a_continuing_statement_passes(client):
    """The same file re-ingested under a different name still lines up."""
    with firm_context(client.firm_id):
        ingest_fixture_statement(client, filename="first.pdf")
        again = ingest_fixture_statement(client, data=b"%PDF again", filename="second.pdf")

        assert again.is_new
        assert again.rows_created == 0  # every row was already known
