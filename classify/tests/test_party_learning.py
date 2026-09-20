"""What the system works out about *who* a payee is, and what it remembers.

Three promises, each with a test that would fail if it were quietly broken:

* a fact fills the party in; a resemblance only ever suggests;
* a person's decision teaches the spelling, so it is not asked twice;
* the model's opinion of who someone is has no more standing than a spelling
  similarity -- it is stored as a suggestion and never applied.
"""

from __future__ import annotations

import datetime
import json
import re

import pytest

from banking.tests.support import ingest_fixture_statement
from classify.engine import classify_statement, review
from classify.llm import suggest_unresolved
from classify.models import (
    LedgerAccount,
    LedgerGroup,
    Party,
    PartyAlias,
    TransactionClassification,
)
from classify.parties import Kind, PartyBook, Signal
from classify.seeds import seed_client
from classify.tests.test_llm import ScriptedLLM, scripted  # noqa: F401  (fixtures)
from classify.treatment import Treatment
from core.db.session import firm_context
from core.provisioning import create_client, create_firm

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


@pytest.fixture
def client():
    firm = create_firm("Party Learning Firm")
    return create_client(firm, "Arjun Nair", datetime.date(2025, 4, 1))


def _party(client, name):
    return Party.objects.create(firm_id=client.firm_id, client=client, canonical_name=name)


def _ledger(client, name="Electricity"):
    return LedgerAccount.objects.create(
        firm_id=client.firm_id, client=client, name=name, group=LedgerGroup.INDIRECT_EXPENSE
    )


def _row(client, needle):
    """The earliest row for a payee -- the statement has several for some."""
    return (
        TransactionClassification.objects.filter(
            firm_id=client.firm_id, counterparty__icontains=needle
        )
        .order_by("transaction__value_date")
        .first()
    )


# ---------------------------------------------------------------------------
# A fact fills the party in; a resemblance only suggests
# ---------------------------------------------------------------------------


def test_a_row_whose_payee_is_a_known_party_gets_that_party(client):
    with firm_context(client.firm_id):
        party = _party(client, "Godavari Restaurant")
        statement = ingest_fixture_statement(client).statement
        seed_client(client)
        classify_statement(statement)

        row = _row(client, "GODAVARI")

    assert row.party_resolution == Kind.AUTO
    assert row.party_id == party.pk


def test_a_row_whose_payee_only_looks_like_a_party_is_not_given_it(client):
    with firm_context(client.firm_id):
        party = _party(client, "Godavari Restaurants Pvt Ltd")
        statement = ingest_fixture_statement(client).statement
        seed_client(client)
        classify_statement(statement)

        row = _row(client, "GODAVARI")

    assert row.party_resolution == Kind.CANDIDATE
    assert row.party_id is None, "a resemblance must never set the party"
    assert row.party_candidates[0]["party"] == str(party.pk)
    assert row.party_candidates[0]["why"]


# ---------------------------------------------------------------------------
# A person's decision teaches the spelling
# ---------------------------------------------------------------------------


def test_placing_a_row_teaches_the_spelling_so_it_is_not_asked_twice(client):
    with firm_context(client.firm_id):
        party = _party(client, "Zerodha")
        statement = ingest_fixture_statement(client).statement
        seed_client(client)
        classify_statement(statement)
        row = _row(client, "ZERODHA BROKING LIMIT")
        assert row.party_resolution != Kind.AUTO

        review(row, Treatment(ledger=_ledger(client, "Brokerage"), party=party), learn=False)

        row.refresh_from_db()
        assert row.party_resolution == "CONFIRMED"
        assert PartyAlias.objects.filter(client=client, party=party).count() == 1

        again = PartyBook(client).resolve(counterparty="Zerodha Broking Limit")
    assert again.kind == Kind.AUTO
    assert again.signal == Signal.ALIAS_CONFIRMED
    assert again.party.pk == party.pk


def test_a_spelling_that_is_just_the_canonical_name_adds_no_alias(client):
    """Nothing to remember when the exact name already resolves."""
    with firm_context(client.firm_id):
        party = _party(client, "Godavari Restaurant")
        statement = ingest_fixture_statement(client).statement
        seed_client(client)
        classify_statement(statement)
        row = _row(client, "GODAVARI")

        review(row, Treatment(ledger=_ledger(client), party=party), learn=False)

        assert PartyAlias.objects.filter(client=client).count() == 0


# ---------------------------------------------------------------------------
# The model's opinion is a suggestion
# ---------------------------------------------------------------------------


def _guess(party, reason="same words as the known party"):
    return {
        "ledger": "Electricity",
        "confidence": 0.95,
        "party_guess": {"alias": party.alias_token, "reason": reason},
    }


def _ask_about_godavari(client, scripted, reply):  # noqa: F811
    with firm_context(client.firm_id):
        statement = ingest_fixture_statement(client).statement
        seed_client(client)
        classify_statement(statement)
        _ledger(client)
        # Created *after* the rows, so they are still NEW and the only thing
        # that can name this party is the model.
        party = _party(client, "Godavari Restaurants Pvt Ltd")
        scripted.script = {"GODAVARI": reply(party) if callable(reply) else reply}
        suggest_unresolved(client)
        return party, _row(client, "GODAVARI")


def test_a_model_guess_is_kept_as_a_suggestion_and_never_applied(client, scripted):  # noqa: F811
    party, row = _ask_about_godavari(client, scripted, _guess)

    assert row.party_id is None, "the model's guess must not set the party"
    assert row.party_resolution == Kind.CANDIDATE
    assert row.party_candidates[0]["party"] == str(party.pk)
    assert "MODEL" in row.party_candidates[0]["source"]


def test_a_guess_naming_an_alias_it_invented_is_ignored(client, scripted):  # noqa: F811
    _, row = _ask_about_godavari(
        client,
        scripted,
        {
            "ledger": "Electricity",
            "confidence": 0.95,
            "party_guess": {"alias": "V0000000000", "reason": "made up"},
        },
    )

    assert row.party_candidates == []
    assert row.party_resolution in ("", Kind.NEW)


def test_a_token_in_the_models_reason_is_turned_back_into_words(client, scripted):  # noqa: F811
    """A reviewer cannot read V3F9A1C2B0, and it must not reach a record."""
    _, row = _ask_about_godavari(
        client,
        scripted,
        lambda party: _guess(party, f"same payee as {party.alias_token} and P1A2B3C4D"),
    )

    reason = row.party_candidates[0]["why"]
    assert not re.search(r"\b[VP][0-9A-F]{8,10}\b", reason), reason
    assert "Godavari Restaurants Pvt Ltd" in reason
    assert "an individual" in reason


def test_a_party_already_established_is_not_overridden_by_a_guess(client, scripted):  # noqa: F811
    with firm_context(client.firm_id):
        known = _party(client, "Godavari Restaurant")
        other = _party(client, "Some Other Business")
        statement = ingest_fixture_statement(client).statement
        seed_client(client)
        classify_statement(statement)
        _ledger(client)
        scripted.script = {"*": {}, "GODAVARI": _guess(other)}
        suggest_unresolved(client)
        row = _row(client, "GODAVARI")

    assert row.party_resolution == Kind.AUTO
    assert row.party_id == known.pk
    assert all(c["party"] != str(other.pk) for c in row.party_candidates)


def test_business_names_reach_the_model_but_a_persons_name_never_does(client, scripted):  # noqa: F811
    with firm_context(client.firm_id):
        _party(client, "Godavari Restaurants Pvt Ltd")
        _party(client, "Suresh Kiran Menon")
        statement = ingest_fixture_statement(client).statement
        seed_client(client)
        classify_statement(statement)
        _ledger(client)
        scripted.script = {"*": {}}
        suggest_unresolved(client)

    listed = scripted.prompts[0]["known_parties"]
    names = {entry.get("name") for entry in listed}
    assert "Godavari Restaurants Pvt Ltd" in names
    assert "Suresh Kiran Menon" not in json.dumps(scripted.prompts[0])
    assert any("name" not in entry for entry in listed), "the person appears by alias alone"
