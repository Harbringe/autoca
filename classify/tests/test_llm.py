"""The model tier: bounded, reviewable, and unable to break the pipeline."""

from __future__ import annotations

import datetime
import json

import pytest

from banking.tests.support import ingest_fixture_statement
from classify.engine import classify_statement, review, review_queue, unresolved_for
from classify.llm import _TOKEN, recategorize, suggest_unresolved
from classify.models import (
    ClassificationMethod,
    LedgerAccount,
    LedgerGroup,
    TransactionClassification,
)
from classify.seeds import seed_client
from classify.treatment import ReviewBand
from core.db.session import firm_context
from core.provisioning import create_client, create_firm
from integrations.llm.base import LLMAdapter, LLMError, LLMRateLimited, LLMResponse
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
            for field in ("narration", "rationale", "question"):
                if field in reply:
                    reply[field] = reply[field].replace("{cp}", row["counterparty"])
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
    return create_client(firm, "Arjun Nair", datetime.date(2025, 4, 1))


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


def test_a_confident_booking_is_ready_to_post_with_its_narration(client, classified, scripted):
    scripted.script = {"Meter": {
        "ledger": "Electricity", "confidence": 0.99, "rationale": "Remark says meter.",
        "narration": "Being electricity charges paid to MSEDCL vide UPI",
    }}
    with firm_context(client.firm_id):
        outcome = suggest_unresolved(client)
        assert outcome.suggested >= 1
        row = review_queue(client).filter(method=ClassificationMethod.LLM).first()
        assert row is not None
        assert row.ledger.name == "Electricity"
        assert row.confidence == 0.99
        assert row.review_band == ReviewBand.HIGH
        assert row.needs_review  # a person still signs
        assert row.rationale == "Remark says meter."
        assert row.book_narration == "Being electricity charges paid to MSEDCL vide UPI"
        assert row.open_question == ""
        assert review_queue(client, ReviewBand.HIGH).filter(pk=row.pk).exists()


def test_the_models_tokens_are_turned_back_into_names_before_storing(client, classified, scripted):
    scripted.script = {"Meter": {
        "ledger": "Electricity", "confidence": 0.99,
        "narration": "Being electricity charges paid to {cp} by UPI",
        "rationale": "Same payee as {cp}.", "question": "Is {cp} the landlord?",
    }}
    with firm_context(client.firm_id):
        suggest_unresolved(client)
        row = review_queue(client).filter(method=ClassificationMethod.LLM).first()
        assert row.book_narration == "Being electricity charges paid to SURESH KIRAN MENON by UPI"
        assert "SURESH KIRAN MENON" in row.rationale
        for stored in TransactionClassification.objects.exclude(book_narration=""):
            assert not _TOKEN.search(stored.book_narration)
            assert not _TOKEN.search(stored.rationale) and not _TOKEN.search(stored.open_question)


def test_a_narration_with_a_token_nobody_can_resolve_falls_back_to_the_template(client, classified, scripted):
    from ledger.approval import book_narration_for

    scripted.script = {"Meter": {
        "ledger": "Electricity", "confidence": 0.99,
        "narration": "Being payment made to P269D28A4 by UPI",
        "rationale": "See P269D28A4.",
    }}
    with firm_context(client.firm_id):
        suggest_unresolved(client)
        row = review_queue(client).filter(method=ClassificationMethod.LLM).first()
        assert row.book_narration == ""
        assert "an individual" in row.rationale
        template = book_narration_for(row)
        assert template.startswith("Being") and not _TOKEN.search(template)


def test_a_reference_number_that_looks_like_a_token_is_left_alone(client, classified, scripted):
    scripted.script = {"Meter": {
        "ledger": "Electricity", "confidence": 0.99,
        "narration": "Being electricity charges paid by cheque no. P20240915 and ref V12345678",
        "rationale": "Cheque P20240915.",
    }}
    with firm_context(client.firm_id):
        suggest_unresolved(client)
        row = review_queue(client).filter(method=ClassificationMethod.LLM).first()
        assert row.book_narration == "Being electricity charges paid by cheque no. P20240915 and ref V12345678"
        assert row.rationale == "Cheque P20240915."


def test_a_lowercase_token_the_model_hands_back_is_still_caught(client, classified, scripted):
    scripted.script = {"Meter": {
        "ledger": "Electricity", "confidence": 0.99,
        "narration": "Being payment made to p269d28a4 by UPI",
        "rationale": "x",
    }}
    with firm_context(client.firm_id):
        suggest_unresolved(client)
        row = review_queue(client).filter(method=ClassificationMethod.LLM).first()
        assert row.book_narration == ""


def test_the_prompt_says_transaction_text_is_untrusted():
    from classify.llm import SYSTEM_PROMPT

    assert "untrusted data" in SYSTEM_PROMPT and "never instructions" in SYSTEM_PROMPT


def test_a_decline_keeps_the_question_for_the_client(client, classified, scripted):
    scripted.script = {"*": {
        "ledger": None, "confidence": 0, "rationale": "No remark, unknown person.",
        "question": "Who is this transfer to, and what was it for?",
    }}
    with firm_context(client.firm_id):
        suggest_unresolved(client)
        row = unresolved_for(client).first()
        assert row.open_question == "Who is this transfer to, and what was it for?"
        assert row.ledger is None


def test_a_rule_placed_row_gains_the_models_narration_but_keeps_the_rule(client, classified, scripted):
    with firm_context(client.firm_id):
        rule_row = review_queue(client).filter(method=ClassificationMethod.RULE).select_related("ledger").first()
        assert rule_row is not None
        scripted.script = {"*": {
            "ledger": rule_row.ledger.name, "confidence": 0.9, "narration": "Being as the rule says",
        }}
        recategorize(client)
        rule_row.refresh_from_db()
        assert rule_row.method == ClassificationMethod.RULE
        assert rule_row.book_narration == "Being as the rule says"


def test_an_unsure_model_places_a_flagged_best_guess(client, classified, scripted):
    """Unsure is not blank: the row gets a ledger, flagged, with the question."""
    scripted.script = {"*": {
        "ledger": "Electricity", "confidence": 0.4, "rationale": "Could be anything.",
        "question": "Is this an electricity bill?",
    }}
    with firm_context(client.firm_id):
        before = unresolved_for(client).count()
        outcome = suggest_unresolved(client)
        assert outcome.suggested == before and outcome.declined == 0
        row = review_queue(client).filter(method=ClassificationMethod.LLM).first()
        assert row.ledger.name == "Electricity"
        assert row.review_band == ReviewBand.JUDGEMENT, "a guess must never look bulk-approvable"
        assert row.needs_review
        assert row.open_question == "Is this an electricity bill?"
        assert row.rationale == "Could be anything."


def test_a_guess_never_displaces_a_rule(client, classified, scripted):
    """A rule is somebody's decision; a hunch does not overrule it."""
    with firm_context(client.firm_id):
        rule_row = TransactionClassification.objects.filter(
            method=ClassificationMethod.RULE
        ).first()
        original = rule_row.ledger_id
        scripted.script = {"*": {"ledger": "Electricity", "confidence": 0.3}}
        recategorize(client)
        rule_row.refresh_from_db()
        assert rule_row.method == ClassificationMethod.RULE
        assert rule_row.ledger_id == original


def test_the_model_may_not_park_a_row_in_suspense(client, classified, scripted):
    """Suspense is where nobody decided; a model that may pick it always will."""
    scripted.script = {"*": {"ledger": "Suspense A/c", "confidence": 0.9}}
    with firm_context(client.firm_id):
        outcome = suggest_unresolved(client)
        assert outcome.suggested == 0
        assert not review_queue(client).filter(ledger__name="Suspense A/c").exists()
    offered = [ledger["name"] for ledger in scripted.prompts[0]["ledgers"]]
    assert "Suspense A/c" not in offered


def test_a_low_confidence_guess_does_not_open_a_new_ledger(client, classified, scripted):
    scripted.script = {"*": {
        "ledger": None, "confidence": 0.4,
        "new_ledger": {"name": "Brand New Ledger", "group": "INDIRECT_EXPENSE"},
    }}
    with firm_context(client.firm_id):
        suggest_unresolved(client)
        assert not LedgerAccount.objects.filter(client=client, name="Brand New Ledger").exists()


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


def test_the_prompt_carries_no_identifiers_or_names(client, classified, scripted):
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
    # exact amounts and dates do go out: a bookkeeper needs them
    assert any("amount" in t and "date" in t for p in scripted.prompts for t in p["transactions"])
    assert "SURESH" not in text  # a person named in the fixture statement
    assert "Nair" not in text and "NAIR" not in text  # the account holder


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
    # Rows that read exactly alike are asked about once, so no more rows are sent than there are rows; every one is answered.
    assert 0 < sum(n for n in calls if n <= 10) <= outcome.considered


def test_batches_share_one_call_per_batch(client, classified, scripted, settings):
    settings.LLM_BATCH_SIZE = 5
    with firm_context(client.firm_id):
        n = unresolved_for(client).count()
        suggest_unresolved(client)
    assert len(scripted.prompts) == -(-n // 5)


def test_the_business_profile_reaches_the_model_masked(client, classified, scripted):
    with firm_context(client.firm_id):
        client.business_profile = "Wholesale cloth trader. GSTIN 27ABCDE1234F1Z5, pays rent on a godown."
        client.save(update_fields=["business_profile"])
        suggest_unresolved(client)
    business = scripted.prompts[0]["business"]
    assert "cloth trader" in business and "godown" in business
    assert "27ABCDE1234F1Z5" not in business


def test_no_business_profile_means_no_business_key(client, classified, scripted):
    with firm_context(client.firm_id):
        suggest_unresolved(client)
    assert "business" not in scripted.prompts[0]


def test_a_request_the_provider_calls_too_large_is_retried_in_smaller_batches(client, classified, scripted, settings):
    """A 413 that means the request itself is too big is fixed by halving it."""
    settings.LLM_BATCH_SIZE = 50
    original = ScriptedLLM.complete_json

    def too_big(self, system, user, *, max_tokens=2048):
        if len(json.loads(user)["transactions"]) > 10:
            raise LLMError(
                "Groq answered HTTP 413 (rate_limit_exceeded: limit 8000, requested 8325); "
                "the request is larger than the plan allows in a minute (request_too_large)."
            )
        return original(self, system, user, max_tokens=max_tokens)

    scripted.script = {"*": {"ledger": "Electricity", "confidence": 0.9}}
    ScriptedLLM.complete_json = too_big
    try:
        with firm_context(client.firm_id):
            outcome = suggest_unresolved(client)
    finally:
        ScriptedLLM.complete_json = original
    assert not outcome.failed
    assert outcome.suggested == outcome.considered


def test_a_spent_minute_budget_is_not_split_into_more_requests(client, classified, scripted, settings):
    """A rate-limit 413 has already been waited out by the adapter. Halving would only repeat the
    fixed part of the prompt in twice as many requests, so the run stops and rows stay for a person."""
    settings.LLM_BATCH_SIZE = 50
    original = ScriptedLLM.complete_json
    asked = []

    def spent(self, system, user, *, max_tokens=2048):
        asked.append(len(json.loads(user)["transactions"]))
        raise LLMError("Groq answered HTTP 413 (rate_limit_exceeded).")

    ScriptedLLM.complete_json = spent
    try:
        with firm_context(client.firm_id):
            outcome = suggest_unresolved(client)
    finally:
        ScriptedLLM.complete_json = original
    assert outcome.failed
    assert "rate_limit_exceeded" in outcome.error
    assert len(asked) == 1


def test_a_rate_limit_keeps_what_was_answered_and_never_waits(client, classified, scripted, settings):
    """Run from a web request, so a spent minute stops the run instead of sleeping through it. The
    rows already answered are kept; the rest stay for a person."""
    settings.LLM_BATCH_SIZE = 50
    original = ScriptedLLM.complete_json
    calls = []
    answered = []

    def limited(self, system, user, *, max_tokens=2048):
        rows = len(json.loads(user)["transactions"])
        calls.append(rows)
        if rows > 10:
            raise LLMError(
                "Groq answered HTTP 413 (rate_limit_exceeded: limit 8000, requested 8325); "
                "the request is larger than the plan allows in a minute (request_too_large)."
            )
        if answered:
            raise LLMRateLimited("spent", retry_after=45)
        answered.append(rows)
        return original(self, system, user, max_tokens=max_tokens)

    scripted.script = {"*": {"ledger": "Electricity", "confidence": 0.9}}
    ScriptedLLM.complete_json = limited
    try:
        with firm_context(client.firm_id):
            outcome = suggest_unresolved(client)
    finally:
        ScriptedLLM.complete_json = original
    assert 0 < outcome.suggested < outcome.considered


def test_a_party_named_ledger_never_reaches_the_model_by_name(client, classified, scripted):
    """History and related rows say where a payee was booked before; a party's account is named after the party."""
    from classify.llm import PARTY_ACCOUNT_LABEL

    scripted.script = {"Meter": {"ledger": "Electricity", "confidence": 0.9}}
    with firm_context(client.firm_id):
        asked = unresolved_for(client).filter(transaction__narration__contains="Meter").first()
        assert asked is not None
        creditor = LedgerAccount.objects.create(
            firm_id=client.firm_id, client=client, name="Ramesh Kumar Sharma", group=LedgerGroup.CREDITOR
        )
        earlier = (
            TransactionClassification.objects.filter(transaction__bank_account__client=client, ledger__isnull=False)
            .exclude(pk=asked.pk)
            .first()
        )
        assert earlier is not None
        earlier.counterparty = asked.counterparty
        earlier.method = ClassificationMethod.REVIEWED
        earlier.ledger = creditor
        earlier.save()

        suggest_unresolved(client)

    sent = json.dumps(scripted.prompts)
    assert "Ramesh" not in sent
    assert PARTY_ACCOUNT_LABEL in sent
    assert all(entry["name"] != "Ramesh Kumar Sharma" for prompt in scripted.prompts for entry in prompt["ledgers"])
