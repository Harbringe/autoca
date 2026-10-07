"""The assistant's queue through the API: the upload only queues, next-batch reads (Q-1)."""

from __future__ import annotations

import datetime
import json

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import DatabaseError, transaction

from api.tests.conftest import member, sign_in
from banking.tests.support import ingest_fixture_statement
from classify.engine import classify_statement, unresolved_for
from classify.models import ModelState, TransactionClassification
from classify.queue import BatchOutcome, mark_waiting
from classify.seeds import seed_client
from core.db.session import firm_context
from core.models import AuditLog, Role
from core.provisioning import create_client, create_firm
from integrations.llm.base import LLMAdapter, LLMResponse
from integrations.registry import reset_adapter_cache

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"


class Tripwire(LLMAdapter):
    """A model that fails the test if anything asks it a question."""

    calls = 0

    def __init__(self, **_ignored):
        pass

    def complete_json(self, system, user, *, max_tokens=2048):
        Tripwire.calls += 1
        prompt = json.loads(user)
        suggestions = [
            {"key": row["key"], "ledger": None, "confidence": 0, "rationale": "-"}
            for row in prompt["transactions"]
        ]
        return LLMResponse(text=json.dumps({"suggestions": suggestions}), model="tripwire")


@pytest.fixture
def model(settings):
    settings.INTEGRATIONS = {**settings.INTEGRATIONS, "llm": f"{__name__}.Tripwire"}
    reset_adapter_cache()
    Tripwire.calls = 0
    yield Tripwire
    reset_adapter_cache()


def _upload(http, client, data=b"%PDF-1.4 axis"):
    return http.post(
        f"{V1}/clients/{client.pk}/statements/upload/",
        {"file": SimpleUploadedFile("axis.pdf", data, content_type="application/pdf")},
        format="multipart",
    )


def _queued_books(client):
    with firm_context(client.firm_id):
        statement = ingest_fixture_statement(client).statement
        seed_client(client)
        classify_statement(statement)
        mark_waiting(unresolved_for(client))
    return statement


# ---------------------------------------------------------------------------
# The upload no longer asks the model
# ---------------------------------------------------------------------------


def test_the_upload_marks_unresolved_rows_as_waiting_and_never_calls_the_model(api, client_record, model):
    response = _upload(api, client_record)

    assert response.status_code == 202
    result = response.json()["result"]
    assert model.calls == 0
    assert result["waiting_for_assistant"] > 0
    assert not any(key.startswith("model_") for key in result)
    with firm_context(client_record.firm_id):
        waiting = TransactionClassification.objects.filter(model_state=ModelState.WAITING)
        assert waiting.count() == result["waiting_for_assistant"]
        assert all(row.ledger_id is None for row in waiting)


def test_sending_the_same_file_twice_is_the_same_job(api, client_record, model):
    first = _upload(api, client_record)
    second = _upload(api, client_record)

    assert first.status_code == 202 and second.status_code == 200
    assert second.json()["id"] == first.json()["id"]


def test_a_different_file_or_client_is_a_different_job(api, firm, client_record, model):
    other = create_client(firm, "Second Client", datetime.date(2025, 4, 1))
    a = _upload(api, client_record)
    b = _upload(api, client_record, data=b"%PDF-1.4 something else")
    c = _upload(api, other)

    assert len({a.json()["id"], b.json()["id"], c.json()["id"]}) == 3


def test_a_removed_statement_can_be_uploaded_again(api, client_record, model):
    first = _upload(api, client_record).json()
    removed = api.delete(f"{V1}/clients/{client_record.pk}/statements/{first['result']['statement']}/")
    assert removed.status_code == 200

    again = _upload(api, client_record)

    assert again.status_code == 202
    assert again.json()["id"] != first["id"]


# ---------------------------------------------------------------------------
# The manual button re-marks; it does not call
# ---------------------------------------------------------------------------


def test_asking_again_requeues_the_rows_and_calls_nothing(api, client_record, model):
    _queued_books(client_record)
    with firm_context(client_record.firm_id):
        TransactionClassification.objects.update(model_state=ModelState.DECLINED, model_attempts=3)

    response = api.post(f"{V1}/clients/{client_record.pk}/review-queue/suggest/")

    assert response.status_code == 202
    result = response.json()["result"]
    assert model.calls == 0 and result["waiting_for_assistant"] > 0
    summary = api.get(f"{V1}/clients/{client_record.pk}/review-queue/summary/").json()
    assert summary["assistant_waiting"] == result["waiting_for_assistant"]
    with firm_context(client_record.firm_id):
        assert TransactionClassification.objects.filter(model_attempts=3, ledger__isnull=True).count() == 0


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------


def test_next_batch_reads_a_batch_for_a_senior(api, client_record, model):
    _queued_books(client_record)

    response = api.post(f"{V1}/clients/{client_record.pk}/assistant/next-batch/")

    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 10 and body["state"] == "working" and body["reason"] == ""
    assert set(body) >= {"suggested", "declined", "waiting", "retry_after_seconds", "message"}
    assert model.calls == 1


def test_next_batch_is_for_people_who_may_classify(firm, client_record, model):
    _queued_books(client_record)
    reader = sign_in(member(firm, Role.READ_ONLY, "ro@example.test").user)

    denied = reader.post(f"{V1}/clients/{client_record.pk}/assistant/next-batch/")

    assert denied.status_code == 403
    assert model.calls == 0


def test_next_batch_does_not_reach_another_firms_client(api, model):
    other = create_client(create_firm("Someone Else"), "Not Yours", datetime.date(2025, 4, 1))
    _queued_books(other)

    response = api.post(f"{V1}/clients/{other.pk}/assistant/next-batch/")

    assert response.status_code == 404
    assert model.calls == 0
    with firm_context(other.firm_id):
        assert not TransactionClassification.objects.exclude(model_state=ModelState.WAITING).exclude(
            model_state__isnull=True
        ).exists()


def test_next_batch_validates_its_body(api, client_record, model):
    response = api.post(f"{V1}/clients/{client_record.pk}/assistant/next-batch/", {"max_rows": 500}, format="json")
    assert response.status_code == 400


def test_next_batch_needs_a_signed_in_member(client_record):
    from rest_framework.test import APIClient

    response = APIClient().post(f"{V1}/clients/{client_record.pk}/assistant/next-batch/")
    assert response.status_code in (401, 403)


def test_a_poll_that_did_nothing_leaves_no_audit_row_and_a_batch_leaves_one(api, firm, client_record, model):
    def audited():
        with firm_context(firm.pk):
            return list(AuditLog.objects.filter(path__contains="next-batch"))

    api.post(f"{V1}/clients/{client_record.pk}/assistant/next-batch/")  # nothing waiting
    assert audited() == []

    _queued_books(client_record)
    api.post(f"{V1}/clients/{client_record.pk}/assistant/next-batch/")

    rows = audited()
    assert len(rows) == 1 and rows[0].status_code == 200


# ---------------------------------------------------------------------------
# The middleware opt-out is narrow and still isolated
# ---------------------------------------------------------------------------


def test_an_opted_out_view_is_refused_by_the_database_outside_its_own_context(
    api, firm, client_record, monkeypatch
):
    """Outside a firm_context the view has no tenant at all; inside, only its own firm's rows."""
    other = create_client(create_firm("Other Firm"), "Other Client", datetime.date(2025, 4, 1))
    _queued_books(other)
    _queued_books(client_record)
    seen = {}

    def probe(client, *, max_rows=None):
        with pytest.raises(DatabaseError, match="tenant context missing"), transaction.atomic():
            list(TransactionClassification.objects.all()[:1])
        with firm_context(client.firm_id):
            seen["visible_firms"] = set(TransactionClassification.objects.values_list("firm_id", flat=True))
            seen["other_rows"] = TransactionClassification.objects.filter(firm_id=other.firm_id).count()
        return BatchOutcome(0, 0, 0, 0, "idle", None, "", "probe")

    monkeypatch.setattr("api.views.assistant.process_next_batch", probe)

    response = api.post(f"{V1}/clients/{client_record.pk}/assistant/next-batch/")

    assert response.status_code == 200
    assert seen["visible_firms"] == {firm.pk} and seen["other_rows"] == 0


def test_only_the_marked_view_is_opted_out(api, client_record):
    """An ordinary view is still inside the request-wide context, so a plain query works."""
    _queued_books(client_record)

    response = api.get(f"{V1}/clients/{client_record.pk}/review-queue/summary/")

    assert response.status_code == 200
    assert response.json()["assistant_waiting"] > 0


def test_the_marker_is_explicit_not_a_path_pattern():
    from api.views.assistant import NextBatchView
    from api.views.classify import ReviewQueueViewSet

    assert NextBatchView.opens_own_firm_context is True
    assert not getattr(ReviewQueueViewSet, "opens_own_firm_context", False)


# ---------------------------------------------------------------------------
# The worker: the same call, with nobody's page open
# ---------------------------------------------------------------------------


def test_the_worker_reads_waiting_rows_without_any_request(client_record, model, monkeypatch):
    from classify.management.commands import run_assistant
    from classify.management.commands.run_assistant import tick

    # The platform view that lists firms exists only where the superadmin SQL has been applied.
    monkeypatch.setattr(run_assistant, "firm_ids", lambda: [client_record.firm_id])
    _queued_books(client_record)

    read = tick()

    assert read > 0 and model.calls > 0
    with firm_context(client_record.firm_id):
        assert TransactionClassification.objects.filter(model_attempts__gt=0).exists()


def test_the_worker_has_nothing_to_do_when_nothing_waits(client_record, model, monkeypatch):
    from classify.management.commands import run_assistant
    from classify.management.commands.run_assistant import tick

    monkeypatch.setattr(run_assistant, "firm_ids", lambda: [client_record.firm_id])

    assert tick() == 0 and model.calls == 0


def test_the_summary_says_why_the_assistant_is_not_reading(api, client_record, model):
    from classify.queue import _pause

    _pause(client_record.firm_id, seconds=120, reason="rate_limit")

    summary = api.get(f"{V1}/clients/{client_record.pk}/review-queue/summary/").json()

    assert summary["assistant_reason"] == "rate_limit" and 100 <= summary["assistant_retry_seconds"] <= 120
