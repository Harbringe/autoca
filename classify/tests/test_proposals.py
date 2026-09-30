"""Ledgers the model opens: live at once, and a CA can rename or merge them."""

from __future__ import annotations

import pytest

from classify.engine import review_queue, unresolved_for
from classify.llm import recategorize, suggest_unresolved
from classify.models import ClassificationMethod, LedgerAccount, LedgerGroup, LedgerStatus
from classify.proposals import ProposalError, accept, merge, reject
from classify.tests.test_llm import ScriptedLLM, classified, client, scripted  # noqa: F401
from classify.treatment import ReviewBand
from core.db.session import firm_context

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def propose(name, group="INDIRECT_EXPENSE", confidence=0.9):
    return {"*": {"ledger": None, "new_ledger": {"name": name, "group": group}, "confidence": confidence, "rationale": "Looks like it."}}


def test_a_missing_ledger_is_proposed_and_the_rows_suggested_into_it(client, classified, scripted):
    scripted.script = propose("Rent")
    with firm_context(client.firm_id):
        before = unresolved_for(client).count()
        outcome = suggest_unresolved(client)

        rent = LedgerAccount.objects.get(client=client, name="Rent")
        assert rent.status == LedgerStatus.ACTIVE
        assert rent.proposal_reason == "Looks like it."
        assert outcome.proposed == 1
        rows = review_queue(client).filter(ledger=rent)
        assert rows.count() == before
        assert all(r.method == ClassificationMethod.LLM and r.review_band == ReviewBand.HIGH for r in rows)


def test_a_near_duplicate_of_an_existing_ledger_uses_that_ledger(client, classified, scripted):
    scripted.script = propose("Electricity Expenses")
    with firm_context(client.firm_id):
        outcome = suggest_unresolved(client)
        assert outcome.proposed == 0
        assert not LedgerAccount.objects.filter(client=client, name="Electricity Expenses").exists()
        assert review_queue(client).filter(ledger__name="Electricity").exists()


def test_a_name_a_ca_rejected_is_not_proposed_again(client, classified, scripted):
    scripted.script = propose("Rent Paid")
    with firm_context(client.firm_id):
        LedgerAccount.objects.create(
            firm_id=client.firm_id, client=client, name="Rent", group=LedgerGroup.INDIRECT_EXPENSE,
            status=LedgerStatus.REJECTED, is_active=False,
        )
        before = unresolved_for(client).count()
        outcome = suggest_unresolved(client)
        assert outcome.proposed == 0
        assert unresolved_for(client).count() == before
        assert not LedgerAccount.objects.filter(client=client, name="Rent Paid").exists()


def test_bank_cash_and_suspense_ledgers_cannot_be_proposed(client, classified, scripted):
    for group in ("BANK", "CASH", "SUSPENSE"):
        scripted.script = propose(f"Mystery {group}", group=group)
        with firm_context(client.firm_id):
            suggest_unresolved(client)
            assert not LedgerAccount.objects.filter(client=client, name=f"Mystery {group}").exists()


def test_a_ledger_named_after_a_person_token_is_refused(client, classified, scripted):
    scripted.script = propose("Advances - P1A2B3C4D5")
    with firm_context(client.firm_id):
        before = unresolved_for(client).count()
        outcome = suggest_unresolved(client)
        assert outcome.proposed == 0
        assert unresolved_for(client).count() == before
        assert not LedgerAccount.objects.filter(client=client, name__startswith="Advances").exists()


def test_a_standard_name_takes_the_standard_spelling(client, classified, scripted):
    scripted.script = propose("telephone and internet")
    with firm_context(client.firm_id):
        suggest_unresolved(client)
        assert LedgerAccount.objects.filter(client=client, name="Telephone & Internet", status=LedgerStatus.ACTIVE).exists()


def test_a_proposal_never_displaces_a_rule_placement(client, classified, scripted):
    scripted.script = propose("Rent")
    with firm_context(client.firm_id):
        rule_rows = list(review_queue(client).filter(method=ClassificationMethod.RULE).values_list("pk", "ledger_id"))
        assert rule_rows
        recategorize(client)
        for pk, ledger_id in rule_rows:
            row = review_queue(client).get(pk=pk)
            assert row.method == ClassificationMethod.RULE and row.ledger_id == ledger_id


def _proposed(client, name):
    """A ledger still in the PROPOSED state from before ledgers went live at once."""
    return LedgerAccount.objects.create(
        firm_id=client.firm_id, client=client, name=name,
        group=LedgerGroup.INDIRECT_EXPENSE, status=LedgerStatus.PROPOSED,
    )


def test_accept_can_rename_to_match_tally(client, classified, scripted):
    with firm_context(client.firm_id):
        rent = _proposed(client, "Rent")
        row = unresolved_for(client).first()
        row.ledger = rent
        row.method = ClassificationMethod.LLM
        row.save(update_fields=["ledger", "method"])
        accept(rent, name="Office Rent")
        rent.refresh_from_db()
        assert rent.status == LedgerStatus.ACTIVE and rent.name == "Office Rent"
        assert review_queue(client).filter(ledger=rent, method=ClassificationMethod.LLM).exists()


def test_accept_refuses_a_name_the_client_already_has(client, classified, scripted):
    with firm_context(client.firm_id):
        rent = _proposed(client, "Rent")
        with pytest.raises(ProposalError, match="Merge"):
            accept(rent, name="Electricity")


def test_merge_moves_the_rows_and_removes_the_models_ledger(client, classified, scripted):
    scripted.script = propose("Rent")
    with firm_context(client.firm_id):
        suggest_unresolved(client)
        rent = LedgerAccount.objects.get(client=client, name="Rent")
        assert rent.status == LedgerStatus.ACTIVE  # live, but nothing posted: still mergeable
        electricity = LedgerAccount.objects.get(client=client, name="Electricity")
        count = rent.classifications.count()
        assert merge(rent, electricity) == count
        assert not LedgerAccount.objects.filter(pk=rent.pk).exists()
        assert review_queue(client).filter(ledger=electricity).count() >= count


def test_reject_returns_the_rows_to_the_queue_and_remembers_the_name(client, classified, scripted):
    with firm_context(client.firm_id):
        rent = _proposed(client, "Rent")
        rows = list(unresolved_for(client)[:3])
        for row in rows:
            row.ledger = rent
            row.method = ClassificationMethod.LLM
            row.save(update_fields=["ledger", "method"])
        before = unresolved_for(client).count() + len(rows)
        assert reject(rent) == len(rows)
        rent.refresh_from_db()
        assert rent.status == LedgerStatus.REJECTED
        assert unresolved_for(client).count() == before
        with pytest.raises(ProposalError):
            accept(rent)


def test_a_token_is_refused_in_any_case_and_no_standard_name_trips_the_check():
    from classify.proposals import _ALIAS_TOKEN
    from classify.standard_ledgers import STANDARD_LEDGERS

    for token in ("P3F9A1C2B0", "p3f9a1c2b0", "Rent v3f9a1c2b0", "V0000000000"):
        assert _ALIAS_TOKEN.search(token), token
    assert not [name for name, _ in STANDARD_LEDGERS if _ALIAS_TOKEN.search(name)]
    assert not _ALIAS_TOKEN.search("Vehicle Expenses")


def test_a_lowercase_token_cannot_become_a_ledger_name(client, classified, scripted):
    scripted.script = propose("Paid to p3f9a1c2b0")
    with firm_context(client.firm_id):
        outcome = suggest_unresolved(client)
        assert outcome.proposed == 0
        assert not LedgerAccount.objects.filter(client=client, name__icontains="p3f9a1c2b0").exists()
