"""The model queue: rows wait, and short calls read a few at a time (Q-1)."""

from __future__ import annotations

import datetime
import json
import time

import pytest
from django.core.cache import cache
from django.db import connection
from django.test.utils import CaptureQueriesContext

from banking.tests.support import ingest_fixture_statement
from classify.engine import classify_statement, review, unresolved_for
from classify.models import ClassificationMethod, LedgerAccount, LedgerGroup, ModelState, TransactionClassification
from classify.queue import MAX_ATTEMPTS, _pause_key, mark_waiting, process_next_batch, waiting_count
from classify.seeds import seed_client
from core.db.session import firm_context, get_current_firm_id
from core.provisioning import create_client, create_firm
from integrations.llm.base import LLMAdapter, LLMError, LLMRateLimited, LLMResponse
from integrations.registry import reset_adapter_cache

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


class QueueLLM(LLMAdapter):
    """Answers every row with one script, and records what the world looked like at the call."""

    calls = 0
    #: (firm context, savepoints open) at each call
    seen: list = []
    reply: dict = {}
    raises: Exception | None = None
    omit: set = set()
    during = None

    def __init__(self, **_ignored):
        pass

    def complete_json(self, system, user, *, max_tokens=2048):
        QueueLLM.calls += 1
        QueueLLM.seen.append((get_current_firm_id(), len(connection.savepoint_ids)))
        if QueueLLM.during:
            hook, QueueLLM.during = QueueLLM.during, None
            hook()
        if QueueLLM.raises:
            raise QueueLLM.raises
        prompt = json.loads(user)
        suggestions = []
        for row in prompt["transactions"]:
            if row["key"] in QueueLLM.omit:
                continue
            suggestions.append({"key": row["key"], "ledger": None, "confidence": 0, **QueueLLM.reply})
        return LLMResponse(text=json.dumps({"suggestions": suggestions}), model="queue")


@pytest.fixture
def llm(settings):
    settings.INTEGRATIONS = {**settings.INTEGRATIONS, "llm": f"{__name__}.QueueLLM"}
    reset_adapter_cache()
    QueueLLM.calls, QueueLLM.seen = 0, []
    QueueLLM.reply = {"ledger": "Electricity", "confidence": 0.6, "rationale": "Looks like a bill."}
    QueueLLM.raises, QueueLLM.omit, QueueLLM.during = None, set(), None
    yield QueueLLM
    reset_adapter_cache()


@pytest.fixture
def client():
    return create_client(create_firm("Queue Test Firm"), "Arjun Nair", datetime.date(2025, 4, 1))


def _books(client, *, name="Axis"):
    with firm_context(client.firm_id):
        statement = ingest_fixture_statement(client).statement
        seed_client(client)
        classify_statement(statement)
        LedgerAccount.objects.get_or_create(
            firm_id=client.firm_id, client=client, name="Electricity", group=LedgerGroup.INDIRECT_EXPENSE
        )
        mark_waiting(unresolved_for(client))
    return statement


@pytest.fixture
def queued(client):
    """A statement whose unresolved rows are waiting, with no firm context left open."""
    statement = _books(client)
    with firm_context(client.firm_id):
        assert waiting_count(client) >= 25
    return statement


def _states(client):
    with firm_context(client.firm_id):
        rows = TransactionClassification.objects.filter(transaction__bank_account__client=client).select_related("ledger")
        return {r.pk: r for r in rows}


def _by_state(client, state):
    return [r for r in _states(client).values() if r.model_state == state]


def test_a_batch_reads_ten_rows_and_applies_the_answers(client, queued, llm):
    with firm_context(client.firm_id):
        before = waiting_count(client)

    outcome = process_next_batch(client)

    assert (outcome.processed, outcome.suggested) == (10, 10)
    assert outcome.state == "working" and outcome.waiting == before - 10
    done = _by_state(client, ModelState.DONE)
    assert len(done) == 10
    assert all(r.method == ClassificationMethod.LLM and r.ledger.name == "Electricity" for r in done)
    assert all(r.model_attempts == 1 and r.model_claimed_until is None for r in done)


def test_the_model_is_never_called_inside_a_transaction_or_a_tenant_context(client, queued, llm):
    baseline = len(connection.savepoint_ids)

    process_next_batch(client)

    assert llm.calls == 1
    assert llm.seen == [(None, baseline)]


def test_a_call_asks_about_one_account_in_batches_of_at_most_fifteen(client, queued, llm):
    process_next_batch(client, max_rows=500)
    assert llm.calls == 1
    assert len(_by_state(client, ModelState.DONE)) == 15


def test_two_windows_never_read_the_same_row(client, queued, llm):
    """The second call runs while the first is out with the provider, holding its claim."""
    second = {}

    def other_window():
        with CaptureQueriesContext(connection) as queries:
            second["outcome"] = process_next_batch(client)
        second["sql"] = " ".join(q["sql"] for q in queries)

    llm.during = other_window
    first = process_next_batch(client)

    assert first.processed == 10 and second["outcome"].processed == 10
    assert "FOR UPDATE" in second["sql"] and "SKIP LOCKED" in second["sql"]
    done = _by_state(client, ModelState.DONE)
    assert len(done) == 20
    assert all(r.model_attempts == 1 for r in done)


def test_a_window_that_finds_only_claimed_rows_is_told_to_come_back(client, queued, llm):
    with firm_context(client.firm_id):
        TransactionClassification.objects.filter(model_state=ModelState.WAITING).update(
            model_state=ModelState.CLAIMED,
            model_claimed_until=datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30),
        )

    outcome = process_next_batch(client)

    # Someone else is reading the rest: not idle, and not worth calling the provider for.
    assert outcome.processed == 0 and outcome.state == "working" and outcome.retry_after_seconds
    assert llm.calls == 0


def test_a_lapsed_claim_is_picked_up_again(client, queued, llm):
    with firm_context(client.firm_id):
        TransactionClassification.objects.filter(model_state=ModelState.WAITING).update(
            model_state=ModelState.CLAIMED,
            model_claimed_until=datetime.datetime.now(datetime.UTC) - datetime.timedelta(seconds=1),
            model_attempts=1,
        )
    outcome = process_next_batch(client)
    assert outcome.processed == 10
    assert all(r.model_attempts == 2 for r in _by_state(client, ModelState.DONE))


def test_a_rate_limit_releases_the_rows_uncounted_and_pauses(client, queued, llm):
    llm.raises = LLMRateLimited("slow down", retry_after=40)
    with firm_context(client.firm_id):
        before = waiting_count(client)

    outcome = process_next_batch(client)

    assert (outcome.state, outcome.reason, outcome.retry_after_seconds) == ("paused", "rate_limit", 40)
    assert outcome.waiting == before
    assert not _by_state(client, ModelState.CLAIMED)
    assert all(r.model_attempts == 0 for r in _states(client).values())

    # While paused a poll costs nothing: the provider is not asked again.
    again = process_next_batch(client)
    assert llm.calls == 1
    assert again.state == "paused" and 1 <= again.retry_after_seconds <= 40


def test_the_daily_limit_pauses_without_asking_the_provider_again(client, queued, llm):
    llm.raises = LLMRateLimited("tokens per day", retry_after=7200, daily=True)

    outcome = process_next_batch(client)
    again = process_next_batch(client)

    assert llm.calls == 1
    assert outcome.reason == again.reason == "daily_limit"
    assert "today's allowance" in outcome.message and str(outcome.waiting) in outcome.message
    assert again.retry_after_seconds > 3000


def test_a_row_the_model_cannot_answer_is_left_for_a_person_after_three_tries(client, queued, llm):
    llm.raises = LLMError("Groq answered HTTP 500.")
    retries = []
    for _ in range(MAX_ATTEMPTS):
        retries.append(process_next_batch(client).retry_after_seconds)
        entry = cache.get(_pause_key(client.firm_id))
        cache.set(_pause_key(client.firm_id), {**entry, "until": 0})  # waited out; the strikes are remembered

    assert retries == [30, 60, 120]
    declined = _by_state(client, ModelState.DECLINED)
    assert len(declined) == 10
    assert all(r.model_attempts == 3 and r.rationale and r.ledger_id is None for r in declined)

    llm.raises = None
    outcome = process_next_batch(client)
    assert outcome.processed == 10
    assert not {r.pk for r in declined} & {r.pk for r in _by_state(client, ModelState.DONE)}


def test_a_provider_failure_is_a_pause_and_leaves_the_rows_waiting(client, queued, llm):
    llm.raises = LLMError("Groq could not be reached.")

    outcome = process_next_batch(client)

    assert (outcome.state, outcome.reason) == ("paused", "provider_down")
    assert len(_by_state(client, ModelState.WAITING)) == outcome.waiting
    assert all(r.model_attempts <= 1 for r in _states(client).values())


def test_a_row_the_reply_leaves_out_goes_back_to_waiting(client, queued, llm):
    llm.omit = {"r1"}

    outcome = process_next_batch(client)

    assert outcome.processed == 10 and outcome.suggested == 9
    again = [r for r in _by_state(client, ModelState.WAITING) if r.model_attempts == 1]
    assert len(again) == 1


def test_a_row_the_model_looks_at_and_declines_is_left_alone(client, queued, llm):
    llm.reply = {"ledger": None, "confidence": 0, "rationale": "No signal."}

    outcome = process_next_batch(client)

    assert (outcome.suggested, outcome.declined) == (0, 10)
    declined = _by_state(client, ModelState.DECLINED)
    assert len(declined) == 10 and all(r.rationale == "No signal." for r in declined)


def test_a_person_who_places_a_row_while_the_model_is_asked_is_not_overwritten(client, queued, llm):
    picked = {}

    def person():
        with firm_context(client.firm_id):
            row = TransactionClassification.objects.filter(model_state=ModelState.CLAIMED).first()
            ledger = LedgerAccount.objects.create(
                firm_id=client.firm_id, client=client, name="Rent Paid", group=LedgerGroup.INDIRECT_EXPENSE
            )
            review(row, ledger, learn=False)
            picked["row"], picked["ledger"] = row.pk, ledger.pk

    llm.during = person
    process_next_batch(client)

    with firm_context(client.firm_id):
        row = TransactionClassification.objects.get(pk=picked["row"])
    assert row.method == ClassificationMethod.REVIEWED and row.ledger_id == picked["ledger"]
    assert row.model_state == ModelState.DONE


def test_the_assistants_sure_answers_are_posted_when_the_batch_is_applied(client, queued, llm):
    from ledger.models import JournalEntry

    llm.reply = {"ledger": "Electricity", "confidence": 0.97, "rationale": "A bill.", "narration": "Being electricity charges paid"}

    outcome = process_next_batch(client)

    assert outcome.auto_posted > 0
    with firm_context(client.firm_id):
        assert JournalEntry.objects.filter(client=client, marker="AI_POSTED").count() == outcome.auto_posted


def test_the_model_never_sees_a_person_when_reading_a_batch(client, queued, llm):
    prompts = []
    original = QueueLLM.complete_json

    def spy(self, system, user, *, max_tokens=2048):
        prompts.append(user)
        return original(self, system, user, max_tokens=max_tokens)

    QueueLLM.complete_json = spy
    try:
        process_next_batch(client)
    finally:
        QueueLLM.complete_json = original
    assert "ARJUN" not in prompts[0].upper()
    assert "Arjun" not in prompts[0]


def test_the_stub_answers_idle_and_leaves_every_row_as_it_was(client, queued, settings):
    settings.INTEGRATIONS = {**settings.INTEGRATIONS, "llm": "integrations.llm.stub.StubLLMAdapter"}
    reset_adapter_cache()
    with firm_context(client.firm_id):
        before = waiting_count(client)

    outcome = process_next_batch(client)

    assert (outcome.state, outcome.reason, outcome.processed) == ("idle", "assistant_off", 0)
    assert outcome.waiting == before
    assert len(_by_state(client, ModelState.WAITING)) == before
    reset_adapter_cache()


def test_nothing_waiting_is_idle(client, llm):
    _books(client)
    with firm_context(client.firm_id):
        TransactionClassification.objects.update(model_state=ModelState.DONE)

    outcome = process_next_batch(client)

    assert (outcome.state, outcome.processed, outcome.waiting) == ("idle", 0, 0)
    assert llm.calls == 0


def test_marking_leaves_a_row_another_window_is_reading(client, queued, llm):
    with firm_context(client.firm_id):
        row = TransactionClassification.objects.filter(model_state=ModelState.WAITING).first()
        row.model_state = ModelState.CLAIMED
        row.model_claimed_until = datetime.datetime.now(datetime.UTC) + datetime.timedelta(seconds=30)
        row.model_attempts = 2
        row.save()
        mark_waiting(unresolved_for(client))
        row.refresh_from_db()
        assert row.model_state == ModelState.CLAIMED and row.model_attempts == 2
        # ...and a declined one starts afresh.
        TransactionClassification.objects.filter(pk=row.pk).update(model_state=ModelState.DECLINED)
        mark_waiting(unresolved_for(client))
        row.refresh_from_db()
        assert row.model_state == ModelState.WAITING and row.model_attempts == 0


def test_another_firms_rows_are_not_touched(client, queued, llm):
    other = create_client(create_firm("Other Firm"), "Meera Rao", datetime.date(2025, 4, 1))
    _books(other)

    process_next_batch(client)

    with firm_context(other.firm_id):
        rows = list(TransactionClassification.objects.all())
        assert rows and all(r.firm_id == other.firm_id for r in rows)
        waiting = [r for r in rows if r.model_state == ModelState.WAITING]
        assert waiting and all(r.model_attempts == 0 for r in waiting)


def test_new_ledgers_the_model_opens_are_capped_per_hour_not_per_batch(client, queued, llm):
    from classify.llm import MAX_PROPOSALS_PER_RUN

    with firm_context(client.firm_id):
        for n in range(MAX_PROPOSALS_PER_RUN):
            LedgerAccount.objects.create(
                firm_id=client.firm_id, client=client, name=f"Opened {n} Ledger",
                group=LedgerGroup.INDIRECT_EXPENSE, proposal_reason="model",
            )
    llm.reply = {
        "ledger": None, "confidence": 0.9, "rationale": "Needs a head.",
        "new_ledger": {"name": "Brand New Head", "group": "INDIRECT_EXPENSE"},
    }

    outcome = process_next_batch(client)

    assert outcome.proposed == 0
    with firm_context(client.firm_id):
        assert not LedgerAccount.objects.filter(client=client, name="Brand New Head").exists()


def test_the_pause_lives_in_the_cache_one_key_per_firm(client, queued, llm):
    llm.raises = LLMRateLimited("slow", retry_after=30)
    process_next_batch(client)
    entry = cache.get(_pause_key(client.firm_id))
    assert entry["reason"] == "rate_limit" and entry["until"] > time.time()
