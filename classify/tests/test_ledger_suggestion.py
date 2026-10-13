"""A head the assistant had in mind but was not sure enough to open: kept on the row for a person, never created on its own."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.serializers.classify import ClassificationSerializer
from classify.engine import review_queue, unresolved_for
from classify.llm import recategorize, suggest_unresolved
from classify.models import (
    ClassificationMethod,
    LedgerAccount,
    LedgerGroup,
    LedgerStatus,
    TransactionClassification,
)
from classify.proposals import resolve_proposal, suggestion_for
from classify.standard_ledgers import SUGGESTABLE_GROUPS
from classify.tests.test_llm import ScriptedLLM, classified, client, scripted  # noqa: F401
from core.db.session import firm_context


def led(name, group=LedgerGroup.INDIRECT_EXPENSE, status=LedgerStatus.ACTIVE, pk=None):
    return SimpleNamespace(pk=pk or name, name=name, group=group, status=status)


# ---------------------------------------------------------------------------
# The vetting, which needs no database
# ---------------------------------------------------------------------------


def test_a_new_head_is_suggested_under_the_standard_spelling_and_group():
    spec = {"name": "dividend received", "group": "INDIRECT_INCOME"}
    assert suggestion_for(spec, known=[led("Electricity")]) == ("Dividend Received", "INDIRECT_INCOME")


@pytest.mark.parametrize("group", ["FIXED_ASSET", "STOCK", "CURRENT_ASSET", "BANK", "CASH", "SUSPENSE", "NOT_A_GROUP", ""])
def test_a_group_the_new_account_dialog_does_not_offer_is_not_suggested(group):
    assert suggestion_for({"name": "Some Head", "group": group}, known=[]) == ("", "")


def test_the_suggestable_groups_are_exactly_the_ones_the_dialog_offers():
    """``web/src/features/review/NewAccountDialog.tsx`` lists them (and a test there holds the same list)."""
    assert {str(g) for g in SUGGESTABLE_GROUPS} == {
        "INDIRECT_EXPENSE", "DIRECT_EXPENSE", "INDIRECT_INCOME", "DIRECT_INCOME", "CREDITOR", "DEBTOR", "LOAN",
        "DUTIES_AND_TAXES", "INVESTMENT", "CAPITAL",
    }


@pytest.mark.parametrize("name", ["", "ab", "P1A2B3C4D5 advances", "12", "A1"])
def test_an_unusable_name_is_not_suggested(name):
    assert suggestion_for({"name": name, "group": "INDIRECT_EXPENSE"}, known=[]) == ("", "")


def test_a_name_a_person_rejected_is_not_suggested_again():
    known = [led("Rent", status=LedgerStatus.REJECTED)]
    assert suggestion_for({"name": "Rent Paid", "group": "INDIRECT_EXPENSE"}, known=known) == ("", "")


def test_the_rows_own_bank_account_is_never_suggested():
    known = [led("Generic Bank A/c 5335", LedgerGroup.BANK)]
    assert suggestion_for({"name": "Generic Bank A/c 5335", "group": "INDIRECT_EXPENSE"}, known=known, excluded_names=("Generic Bank A/c 5335",)) == ("", "")


def test_an_idea_close_to_an_existing_ledger_is_kept_under_that_ledgers_own_name():
    known = [led("Dividend Received", LedgerGroup.INDIRECT_INCOME)]
    assert suggestion_for({"name": "Dividends Received", "group": "INDIRECT_INCOME"}, known=known) == ("Dividend Received", "INDIRECT_INCOME")


def test_the_ledger_the_row_already_sits_in_is_no_suggestion():
    here = led("Dividend Received", LedgerGroup.INDIRECT_INCOME, pk="x")
    assert suggestion_for({"name": "Dividend Received", "group": "INDIRECT_INCOME"}, known=[here], placed_in=here) == ("", "")


def test_the_create_path_keeps_its_original_order_of_checks():
    """A bad group on a name close to an existing ledger is still refused there, as it always was."""
    known = [led("Rent")]
    assert resolve_proposal(None, "Rent", "BANK", "why", known=known) is None
    assert resolve_proposal(None, "Rent", "INDIRECT_EXPENSE", "why", known=known) is known[0]


# ---------------------------------------------------------------------------
# Applied to rows: the threshold behaves exactly as before at and above it
# ---------------------------------------------------------------------------

def say(ledger, new_ledger=None, confidence=0.6):
    reply = {"ledger": ledger, "confidence": confidence, "rationale": "Closest I have.", "question": "Is this a dividend?"}
    if new_ledger:
        reply["new_ledger"] = new_ledger
    return {"*": reply}


DIVIDEND = {"name": "Dividend Received", "group": "INDIRECT_INCOME"}


@pytest.mark.django_db
@pytest.mark.usefixtures("fixture_adapters")
def test_below_the_bar_the_row_is_placed_in_the_closest_ledger_and_the_idea_is_kept_not_created(client, classified, scripted):
    scripted.script = say("Electricity", DIVIDEND, confidence=0.6)
    with firm_context(client.firm_id):
        before = unresolved_for(client).count()
        outcome = suggest_unresolved(client)

        assert outcome.proposed == 0
        assert not LedgerAccount.objects.filter(client=client, name="Dividend Received").exists()
        rows = review_queue(client).filter(ledger__name="Electricity", method=ClassificationMethod.LLM)
        assert rows.count() == before
        assert all(r.suggested_ledger_name == "Dividend Received" and r.suggested_ledger_group == "INDIRECT_INCOME" for r in rows)
        assert all(r.open_question for r in rows)


@pytest.mark.django_db
@pytest.mark.usefixtures("fixture_adapters")
def test_at_the_bar_with_no_ledger_it_is_created_as_it_always_was(client, classified, scripted):
    scripted.script = say(None, DIVIDEND, confidence=0.75)
    with firm_context(client.firm_id):
        outcome = suggest_unresolved(client)
        assert outcome.proposed == 1
        made = LedgerAccount.objects.get(client=client, name="Dividend Received")
        assert made.status == LedgerStatus.ACTIVE
        assert all(r.suggested_ledger_name == "" for r in TransactionClassification.objects.filter(ledger=made))


@pytest.mark.django_db
@pytest.mark.usefixtures("fixture_adapters")
def test_just_below_the_bar_with_no_ledger_nothing_is_created_and_the_row_waits_with_its_idea(client, classified, scripted):
    scripted.script = say(None, DIVIDEND, confidence=0.74)
    with firm_context(client.firm_id):
        before = unresolved_for(client).count()
        outcome = suggest_unresolved(client)
        assert outcome.proposed == 0
        assert not LedgerAccount.objects.filter(client=client, name="Dividend Received").exists()
        waiting = unresolved_for(client)
        assert waiting.count() == before
        assert all(r.suggested_ledger_name == "Dividend Received" for r in waiting)


@pytest.mark.django_db
@pytest.mark.usefixtures("fixture_adapters")
def test_above_the_bar_with_both_a_ledger_and_a_new_head_the_ledger_is_used_and_no_idea_is_kept(client, classified, scripted):
    scripted.script = say("Electricity", DIVIDEND, confidence=0.8)
    with firm_context(client.firm_id):
        suggest_unresolved(client)
        assert not LedgerAccount.objects.filter(client=client, name="Dividend Received").exists()
        assert all(r.suggested_ledger_name == "" for r in review_queue(client).filter(ledger__name="Electricity", method=ClassificationMethod.LLM))


@pytest.mark.django_db
@pytest.mark.usefixtures("fixture_adapters")
def test_a_rule_placed_row_never_gets_an_idea(client, classified, scripted):
    scripted.script = say("Electricity", DIVIDEND, confidence=0.6)
    with firm_context(client.firm_id):
        recategorize(client)
        rule_rows = review_queue(client).filter(method=ClassificationMethod.RULE)
        assert rule_rows.exists()
        assert all(r.suggested_ledger_name == "" for r in rule_rows)


@pytest.mark.django_db
@pytest.mark.usefixtures("fixture_adapters")
def test_a_head_that_cannot_be_opened_is_not_kept_as_an_idea(client, classified, scripted):
    scripted.script = say("Electricity", {"name": "Delivery Van", "group": "FIXED_ASSET"}, confidence=0.6)
    with firm_context(client.firm_id):
        suggest_unresolved(client)
        assert all(r.suggested_ledger_name == "" for r in review_queue(client).filter(method=ClassificationMethod.LLM))


@pytest.mark.django_db
@pytest.mark.usefixtures("fixture_adapters")
def test_the_api_shows_the_idea_only_while_the_row_is_the_assistants_and_a_person_decision_ends_it(client, classified, scripted):
    scripted.script = say("Electricity", DIVIDEND, confidence=0.6)
    with firm_context(client.firm_id):
        suggest_unresolved(client)
        rows = list(review_queue(client).filter(method=ClassificationMethod.LLM))
        shown = ClassificationSerializer(rows, many=True, context={}).data
        assert all(item["suggested_ledger"]["name"] == "Dividend Received" for item in shown)
        assert all(item["suggested_ledger"]["existing_ledger"] is None for item in shown)
        assert shown[0]["suggested_ledger"]["rows_sharing"] == len(rows) - 1

        # a person decides one row: the idea is gone from it, and from nowhere else
        row = rows[0]
        row.resolve(row.treatment, user=None)
        row.refresh_from_db()
        assert row.suggested_ledger_name == ""
        assert ClassificationSerializer(row, context={}).data["suggested_ledger"] is None
        others = ClassificationSerializer(rows[1:], many=True, context={}).data
        assert all(item["suggested_ledger"] is not None for item in others)


@pytest.mark.django_db
@pytest.mark.usefixtures("fixture_adapters")
def test_once_the_ledger_exists_the_api_says_the_row_can_be_placed_straight_into_it(client, classified, scripted):
    scripted.script = say("Electricity", DIVIDEND, confidence=0.6)
    with firm_context(client.firm_id):
        suggest_unresolved(client)
        made = LedgerAccount.objects.create(
            firm_id=client.firm_id, client=client, name="Dividend Received", group=LedgerGroup.INDIRECT_INCOME, status=LedgerStatus.ACTIVE,
        )
        rows = list(review_queue(client).filter(method=ClassificationMethod.LLM))
        shown = ClassificationSerializer(rows, many=True, context={}).data
        assert all(item["suggested_ledger"]["existing_ledger"] == made.pk for item in shown)
        assert all(item["suggested_ledger"]["existing_name"] == "Dividend Received" for item in shown)
