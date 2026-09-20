"""Resolving a counterparty to a party.

The tests that matter here are the ones about what the resolver *refuses* to
do. Recognising ``RAMESH TRADRS PVT`` as Ramesh Traders is the feature; never
deciding that on its own is the guarantee, and a regression in the second one
would look like the first one working better.
"""

from __future__ import annotations

import datetime

import pytest

from classify.models import AliasSource, Party, PartyAlias, PartyBankAccount
from classify.narration import normalise
from classify.parties import Kind, Signal, confirm_alias, remember_account, resolve
from core.db.session import firm_context
from core.provisioning import create_client, create_firm

pytestmark = pytest.mark.django_db


@pytest.fixture
def client_record():
    firm = create_firm("Party Resolution Test Firm")
    return create_client(firm, "Arjun Nair", datetime.date(2025, 4, 1))


def _party(client, name, **kw):
    return Party.objects.create(
        firm_id=client.firm_id, client=client, canonical_name=name, **kw
    )


# ---------------------------------------------------------------------------
# What resolves on its own
# ---------------------------------------------------------------------------


def test_an_account_number_already_seen_resolves_without_asking(client_record):
    with firm_context(client_record.firm_id):
        party = _party(client_record, "Ramesh Traders")
        remember_account(client_record, party, "918020031234567")

        found = resolve(
            client_record,
            counterparty="SOMETHING ELSE ENTIRELY",
            counterparty_account="918020031234567",
        )

    assert found.kind == Kind.AUTO
    assert found.signal == Signal.ACCOUNT_HASH
    assert found.party == party


def test_a_confirmed_spelling_resolves_without_asking(client_record):
    with firm_context(client_record.firm_id):
        party = _party(client_record, "Ramesh Traders")
        confirm_alias(client_record, party, "RAMESH TRADRS PVT")

        found = resolve(client_record, counterparty="ramesh  tradrs pvt")

    assert found.kind == Kind.AUTO
    assert found.signal == Signal.ALIAS_CONFIRMED
    assert found.party == party


def test_the_canonical_name_still_resolves_exactly(client_record):
    with firm_context(client_record.firm_id):
        party = _party(client_record, "Ramesh Traders")
        found = resolve(client_record, counterparty="RAMESH TRADERS")

    assert found.kind == Kind.AUTO
    assert found.signal == Signal.CANONICAL_NAME
    assert found.party == party


def test_the_clients_own_account_never_resolves_to_a_party(client_record):
    """A transfer between the client's own accounts is not a payment to anyone."""
    with firm_context(client_record.firm_id):
        party = _party(client_record, "Ramesh Traders")
        remember_account(client_record, party, "918020031234567")
        own = PartyBankAccount.hash_for("918020031234567", client_record.firm_id)

        found = resolve(
            client_record,
            counterparty="SELF",
            counterparty_account="918020031234567",
            own_accounts=(own,),
        )

    assert found.party is None
    assert found.kind == Kind.NEW


# ---------------------------------------------------------------------------
# What only ever suggests
# ---------------------------------------------------------------------------


def test_a_near_identical_name_is_suggested_and_never_resolved(client_record):
    """The boundary this module exists to hold.

    A one-character difference scores far above any threshold anyone would
    choose, and it still does not resolve. Merging two parties is a person's
    decision because the failure is silent.
    """
    with firm_context(client_record.firm_id):
        party = _party(client_record, "Ramesh Traders")
        found = resolve(client_record, counterparty="RAMESH TRADRS")

    assert found.kind == Kind.CANDIDATE
    assert found.party is None, "a similarity score must never resolve a party"
    assert [c.party for c in found.candidates] == [party]
    assert found.candidates[0].score > 0.9
    assert found.candidates[0].why


def test_an_unrelated_name_is_not_suggested_at_all(client_record):
    with firm_context(client_record.firm_id):
        _party(client_record, "Ramesh Traders")
        found = resolve(client_record, counterparty="MAHARASHTRA STATE ELECTRICITY")

    assert found.kind == Kind.NEW
    assert found.candidates == ()


def test_two_facts_that_disagree_go_to_a_person(client_record):
    """An account saying one party and a GSTIN saying another is not a tiebreak."""
    with firm_context(client_record.firm_id):
        by_account = _party(client_record, "Ramesh Traders")
        remember_account(client_record, by_account, "918020031234567")

        by_gstin = _party(client_record, "Ramesh Enterprises")
        by_gstin.set_gstin("27AAPFU0939F1ZV")
        by_gstin.save()

        found = resolve(
            client_record,
            counterparty="RAMESH",
            counterparty_account="918020031234567",
            gstin="27AAPFU0939F1ZV",
        )

    assert found.conflict is True
    assert found.kind == Kind.CANDIDATE
    assert found.party is None
    # The GSTIN is the stronger signal, so it is offered first -- but it is
    # still offered, not applied.
    assert [c.party for c in found.candidates] == [by_gstin, by_account]


def test_resolving_writes_nothing(client_record):
    """It is asked speculatively, for rows nobody will review."""
    with firm_context(client_record.firm_id):
        _party(client_record, "Ramesh Traders")
        before = (Party.objects.count(), PartyAlias.objects.count(), PartyBankAccount.objects.count())

        resolve(client_record, counterparty="RAMESH TRADRS PVT", counterparty_account="918020031234567")
        resolve(client_record, counterparty="SOMEONE NEW")

        assert (
            Party.objects.count(),
            PartyAlias.objects.count(),
            PartyBankAccount.objects.count(),
        ) == before


# ---------------------------------------------------------------------------
# Remembering a decision
# ---------------------------------------------------------------------------


def test_a_spelling_confirmed_once_is_not_asked_again(client_record):
    with firm_context(client_record.firm_id):
        party = _party(client_record, "Ramesh Traders")

        first = resolve(client_record, counterparty="RAMESH TRADRS PVT")
        assert first.kind == Kind.CANDIDATE

        confirm_alias(client_record, party, "RAMESH TRADRS PVT", source=AliasSource.MANUAL)

        second = resolve(client_record, counterparty="RAMESH TRADRS PVT")

    assert second.kind == Kind.AUTO
    assert second.party == party


def test_confirming_the_same_spelling_twice_is_not_an_error(client_record):
    with firm_context(client_record.firm_id):
        party = _party(client_record, "Ramesh Traders")
        first = confirm_alias(client_record, party, "RAMESH TRADRS PVT")
        again = confirm_alias(client_record, party, "ramesh tradrs pvt")

    assert again is not None
    assert again.pk == first.pk


def test_a_spelling_claimed_by_another_party_is_refused_not_moved(client_record):
    """Reassigning a spelling would move one party's history onto another."""
    with firm_context(client_record.firm_id):
        ramesh = _party(client_record, "Ramesh Traders")
        suresh = _party(client_record, "Suresh Traders")
        confirm_alias(client_record, ramesh, "R TRADERS")

        refused = confirm_alias(client_record, suresh, "R TRADERS")

        assert refused is None
        assert PartyAlias.objects.get(alias_normalised=normalise("R TRADERS")).party_id == ramesh.pk


def test_one_spelling_cannot_mean_two_parties(client_record):
    """The constraint that makes alias resolution deterministic."""
    from django.db.utils import IntegrityError

    with firm_context(client_record.firm_id):
        ramesh = _party(client_record, "Ramesh Traders")
        suresh = _party(client_record, "Suresh Traders")
        PartyAlias.objects.create(
            firm_id=client_record.firm_id,
            client=client_record,
            party=ramesh,
            alias_normalised="RTRADERS",
            alias_display="R Traders",
        )
        with pytest.raises(IntegrityError):
            PartyAlias.objects.create(
                firm_id=client_record.firm_id,
                client=client_record,
                party=suresh,
                alias_normalised="RTRADERS",
                alias_display="R Traders",
            )


# ---------------------------------------------------------------------------
# Resemblance that ignores what carries no identity
# ---------------------------------------------------------------------------


def test_a_corporate_suffix_does_not_hide_a_resemblance(client_record):
    """"Pvt Ltd" says what kind of business it is, not which one."""
    with firm_context(client_record.firm_id):
        party = _party(client_record, "Ramesh Traders")
        found = resolve(client_record, counterparty="RAMESH TRADERS PVT LTD")

    assert found.kind == Kind.CANDIDATE
    assert found.candidates[0].party == party
    assert found.candidates[0].score >= 0.95


def test_the_same_words_in_another_order_are_still_suggested(client_record):
    with firm_context(client_record.firm_id):
        party = _party(client_record, "Ramesh Traders")
        found = resolve(client_record, counterparty="TRADERS RAMESH")

    assert found.kind == Kind.CANDIDATE
    assert found.candidates[0].party == party


def test_a_suffix_alone_does_not_make_two_businesses_alike(client_record):
    """Sharing "Pvt Ltd" must not count as sharing an identity."""
    with firm_context(client_record.firm_id):
        _party(client_record, "Ramesh Traders")
        found = resolve(client_record, counterparty="MAHESH ELECTRICALS PVT LTD")

    assert found.kind == Kind.NEW
