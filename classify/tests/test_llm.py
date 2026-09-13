"""The model tier: bounded, reviewable, and unable to break the pipeline."""

from __future__ import annotations

import datetime
import json

import pytest

from banking.tests.support import ingest_fixture_statement
from classify.engine import classify_statement, review, review_queue, unresolved_for
from classify.llm import LLM_CONFIDENCE_CAP, recategorize, suggest_unresolved
from classify.models import ClassificationMethod, LedgerAccount, LedgerGroup, TransactionClassification
from classify.seeds import seed_client
from classify.treatment import ReviewBand
from core.db.session import firm_context
from core.provisioning import create_client, create_firm
from integrations.llm.base import LLMAdapter, LLMError, LLMResponse
from integrations.registry import reset_adapter_cache

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


class ScriptedLLM(LLMAdapter):
    """Answers from a script keyed on the ledger it should pick, and records prompts."""

    prompts: list[dict] = []
    script: dict = {}
    fail_with: str = ""

    def __init__(self, **_ignored):
        pass

    def complete_json(self, system, user, *, max_tokens=2048):
        if ScriptedLLM.fail_with:
            raise LLMError(ScriptedLLM.fail_with)
        prompt = json.loads(user)
        ScriptedLLM.prompts.append(prompt)
        suggestions = []
        for row in prompt["transactions"]:
            reply = dict(ScriptedLLM.script.get("*", {}))
            for needle, override in ScriptedLLM.script.items():
                if needle != "*" and needle in row["narration"]:
                    reply = dict(override)
            reply.setdefault("ledger", None)
            reply.setdefault("confidence", 0)
            reply["key"] = row["key"]
            suggestions.append(reply)
        return LLMResponse(text=json.dumps({"suggestions": suggestions}), model="scripted")


@pytest.fixture
def scripted(settings):
    settings.INTEGRATIONS = {**settings.INTEGRATIONS, "llm": f"{__name__}.ScriptedLLM"}
    reset_adapter_cache()
    ScriptedLLM.prompts = []
    ScriptedLLM.script = {}
    ScriptedLLM.fail_with = ""
    yield ScriptedLLM
    reset_adapter_cache()


@pytest.fixture
def client():
    firm = create_firm("LLM Test Firm")
    return create_client(firm, "Ramesh Deshmukh", datetime.date(2025, 4, 1))


@pytest.fixture
def classified(client):
    with firm_context(client.firm_id):
        statement = ingest_fixture_statement(client).statement
        seed_client(client)
        classify_statement(statement)
        LedgerAccount.objects.create(
            firm_id=client.firm_id, client=client, name="Electricity", group=LedgerGroup.INDIRECT_EXPENSE
        )
        LedgerAccount.objects.create(
            firm_id=client.firm_id, client=client, name="Investments", group=LedgerGroup.INVESTMENT
        )
        yield statement


def test_without_a_provider_nothing_happens(client, classified):
    with firm_context(client.firm_id):
        before = unresolved_for(client).count()
        outcome = suggest_unresolved(client)
        assert outcome.suggested == 0 and not outcome.failed
        assert unresolved_for(client).count() == before


def test_a_confident_suggestion_lands_in_the_advised_band_never_high(client, classified, scripted):
    scripted.script = {"Meter": {"ledger": "Electricity", "confidence": 0.99, "rationale": "Remark says meter."}}
    with firm_context(client.firm_id):
        outcome = suggest_unresolved(client)
        assert outcome.suggested >= 1
        row = review_queue(client).filter(method=ClassificationMethod.LLM).first()
        assert row is not None
        assert row.ledger.name == "Electricity"
        assert row.confidence == LLM_CONFIDENCE_CAP
        assert row.review_band == ReviewBand.ADVISED
        assert row.needs_review
        assert row.rationale == "Remark says meter."
        # and it is not in the bulk-approvable set
        assert not review_queue(client, ReviewBand.HIGH).filter(pk=row.pk).exists()


def test_an_unsure_model_does_not_place_the_row(client, classified, scripted):
    scripted.script = {"*": {"ledger": "Electricity", "confidence": 0.4, "rationale": "Could be anything."}}
    with firm_context(client.firm_id):
        before = unresolved_for(client).count()
        outcome = suggest_unresolved(client)
        assert outcome.suggested == 0
        assert outcome.declined == before
        assert unresolved_for(client).count() == before
        assert unresolved_for(client).first().rationale == "Could be anything."


def test_an_invented_ledger_is_discarded(client, classified, scripted):
    scripted.script = {"*": {"ledger": "Miscellaneous Expenses", "confidence": 0.95}}
    with firm_context(client.firm_id):
        outcome = suggest_unresolved(client)
        assert outcome.suggested == 0
        assert not LedgerAccount.objects.filter(client=client, name="Miscellaneous Expenses").exists()


def test_a_provider_failure_is_reported_not_raised(client, classified, scripted):
    scripted.fail_with = "Groq answered HTTP 503."
    with firm_context(client.firm_id):
        before = unresolved_for(client).count()
        outcome = suggest_unresolved(client)
        assert outcome.failed and "503" in outcome.error
        assert unresolved_for(client).count() == before


def test_the_prompt_carries_no_identifiers_or_exact_amounts(client, classified, scripted):
    scripted.script = {}
    with firm_context(client.firm_id):
        suggest_unresolved(client)
        rows = classified.transactions.all()
    text = json.dumps(scripted.prompts)
    for row in rows:
        # reference numbers and account numbers from the real narrations
        for token in row.narration.split("/"):
            if token.isdigit() and len(token) >= 9:
                assert token not in text
        assert str(row.amount_paise) not in text
    assert "MADHUKAR" not in text  # a person named in the fixture statement
    assert "Deshmukh" not in text and "DESHMUKH" not in text  # the account holder


def test_recategorize_keeps_an_agreeing_rule_and_flags_a_disagreement(client, classified, scripted):
    with firm_context(client.firm_id):
        rule_rows = list(
            review_queue(client).filter(method=ClassificationMethod.RULE).select_related("ledger")
        )
        assert rule_rows
        chosen = rule_rows[0].ledger.name
        agreeing = [r.pk for r in rule_rows if r.ledger.name == chosen]
        disagreeing = [r.pk for r in rule_rows if r.ledger.name != chosen]
        scripted.script = {"*": {"ledger": chosen, "confidence": 0.9, "rationale": "Model view."}}

        outcome = recategorize(client)

        for row in TransactionClassification.objects.filter(pk__in=agreeing):
            assert row.method == ClassificationMethod.RULE
            assert row.rationale == "Model view."
        for row in TransactionClassification.objects.filter(pk__in=disagreeing):
            assert row.method == ClassificationMethod.LLM
            assert row.review_band == ReviewBand.ADVISED and row.needs_review
        assert outcome.confirmed == len(agreeing)
        assert not review_queue(client).filter(method=ClassificationMethod.UNRESOLVED).exists()


def test_recategorize_never_touches_a_persons_decision(client, classified, scripted):
    scripted.script = {"*": {"ledger": "Investments", "confidence": 0.95}}
    with firm_context(client.firm_id):
        row = unresolved_for(client).first()
        electricity = LedgerAccount.objects.get(client=client, name="Electricity")
        review(row, electricity, learn=False)

        recategorize(client)

        row.refresh_from_db()
        assert row.method == ClassificationMethod.REVIEWED
        assert row.ledger == electricity


def test_the_model_can_never_place_a_row_in_its_own_bank_ledger(client, classified, scripted):
    own = classified.bank_account.ledger_name
    scripted.script = {"*": {"ledger": own, "confidence": 0.95}}
    with firm_context(client.firm_id):
        seed_client(client)
        outcome = suggest_unresolved(client)
        assert outcome.suggested == 0
        assert not review_queue(client).filter(ledger__name=own).exists()
    offered = {ledger["name"] for prompt in scripted.prompts for ledger in prompt["ledgers"]}
    assert own not in offered


def test_a_stale_model_suggestion_is_withdrawn_when_the_model_declines(client, classified, scripted):
    scripted.script = {"*": {"ledger": "Electricity", "confidence": 0.9}}
    with firm_context(client.firm_id):
        suggest_unresolved(client)
        assert review_queue(client).filter(method=ClassificationMethod.LLM).exists()
        scripted.script = {"*": {"ledger": None, "confidence": 0, "rationale": "No signal."}}
        recategorize(client)
        assert not review_queue(client).filter(method=ClassificationMethod.LLM).exists()


def test_a_cut_off_reply_is_retried_in_smaller_batches(client, classified, scripted, settings):
    settings.LLM_BATCH_SIZE = 50
    calls = []
    original = ScriptedLLM.complete_json

    def truncating(self, system, user, *, max_tokens=2048):
        rows = len(json.loads(user)["transactions"])
        calls.append(rows)
        if rows > 10:
            raise LLMError("Groq answered HTTP 400 (json_validate_failed).")
        return original(self, system, user, max_tokens=max_tokens)

    scripted.script = {"*": {"ledger": "Electricity", "confidence": 0.9}}
    ScriptedLLM.complete_json = truncating
    try:
        with firm_context(client.firm_id):
            outcome = suggest_unresolved(client)
    finally:
        ScriptedLLM.complete_json = original
    assert not outcome.failed
    assert outcome.suggested == outcome.considered
    assert calls[0] > 10
    assert sum(n for n in calls if n <= 10) == outcome.considered


def test_batches_share_one_call_per_batch(client, classified, scripted, settings):
    settings.LLM_BATCH_SIZE = 5
    with firm_context(client.firm_id):
        n = unresolved_for(client).count()
        suggest_unresolved(client)
    assert len(scripted.prompts) == -(-n // 5)
