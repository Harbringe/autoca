"""A statement upload read by the worker instead of inside the request (core/jobqueue.py, banking/upload_jobs.py).

The behaviour that matters: the request only records and stages the file; a worker reads it and gives the result the inline path always
gave; a worker that lost its job leaves nothing behind; a crashed one is noticed and its job retried a bounded number of times; and what
a person is told while waiting is true.
"""

from __future__ import annotations

import datetime
import uuid
from datetime import timedelta

import pytest
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

import banking.upload_jobs  # noqa: F401 -- registers the statement reader with the queue
from banking.models import Statement, StatementTransaction
from core import jobqueue
from core.db.session import firm_context
from core.jobs import enqueue_job
from core.models import Job, JobStatus
from core.provisioning import create_client, create_firm
from integrations.registry import get_storage
from ledger.models import JournalEntry

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"
PDF = b"%PDF-1.4 axis"


@pytest.fixture(autouse=True)
def background(settings):
    settings.STATEMENT_UPLOAD_MODE = "background"
    cache.clear()


class QuietBeat:
    """The heartbeat without its thread: a test's uncommitted data cannot be seen from a second connection."""

    said: list[str] = []

    def __init__(self, claim):
        self.claim = claim
        self.lost = False
        QuietBeat.said = []

    def start(self):
        pass

    def stop(self):
        pass

    def say(self, words):
        QuietBeat.said.append(words)


def upload(api, client, data: bytes = PDF, name: str = "axis.pdf", **extra):
    return api.post(
        f"{V1}/clients/{client.pk}/statements/upload/",
        {"file": SimpleUploadedFile(name, data, content_type="application/pdf"), **extra},
        format="multipart",
    )


def work():
    return jobqueue.run_once("test-reader", heartbeat_factory=QuietBeat)


def counts(firm):
    with firm_context(firm.pk):
        return {
            "statements": Statement.objects.count(),
            "rows": StatementTransaction.objects.count(),
            "entries": JournalEntry.objects.count(),
        }


def only_job(firm):
    with firm_context(firm.pk):
        return Job.objects.get()


def strip_ids(result: dict) -> dict:
    return {k: v for k, v in result.items() if k not in {"statement", "bank_account"}}


# ---------------------------------------------------------------------------
# Accepting
# ---------------------------------------------------------------------------


def test_accepting_an_upload_records_and_stages_it_and_reads_nothing(api, firm, client_record):
    response = upload(api, client_record)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "PENDING" and body["message"] == jobqueue.WAITING_WORDS
    assert body["result"] == {} and body["queue_ahead"] == 0
    job = only_job(firm)
    assert job.staged_at is not None and job.staged_key.startswith(f"firms/{firm.pk}/clients/{client_record.pk}/uploads/")
    assert get_storage().get(job.staged_key) == PDF
    assert counts(firm) == {"statements": 0, "rows": 0, "entries": 0}


def test_the_same_file_while_it_waits_is_the_same_job_and_one_staged_file(api, firm, client_record):
    first = upload(api, client_record).json()
    again = upload(api, client_record)

    assert again.status_code == 200 and again.json()["id"] == first["id"]
    with firm_context(firm.pk):
        assert Job.objects.count() == 1


def test_a_password_upload_is_read_in_the_request_and_nothing_is_staged(api, firm, client_record):
    body = upload(api, client_record, password="not-kept").json()

    assert body["status"] != "PENDING"
    with firm_context(firm.pk):
        assert not Job.objects.filter(status=JobStatus.PENDING).exists()
        assert not Job.objects.exclude(staged_key="").exists()


def test_when_the_file_cannot_be_stored_no_job_is_left_behind(api, firm, client_record, monkeypatch):
    def refuse(*_a, **_k):
        raise OSError("storage is down")

    monkeypatch.setattr(type(get_storage()), "put", refuse)
    with pytest.raises(OSError):
        upload(api, client_record)
    with firm_context(firm.pk):
        assert Job.objects.count() == 0


def test_a_request_that_died_before_its_file_arrived_is_replaced_by_the_next_upload(api, firm, client_record):
    first = upload(api, client_record).json()
    with firm_context(firm.pk):
        Job.objects.filter(pk=first["id"]).update(staged_at=None, created_at=timezone.now() - timedelta(minutes=5))

    second = upload(api, client_record)

    assert second.status_code == 202 and second.json()["id"] != first["id"]
    with firm_context(firm.pk):
        assert Job.objects.count() == 1 and Job.objects.get().staged_at is not None


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def test_a_worker_pass_gives_the_result_the_inline_path_gives(api, firm, client_record, settings):
    other = create_client(firm, "Inline Client", datetime.date(2025, 4, 1))
    settings.STATEMENT_UPLOAD_MODE = "inline"
    inline = upload(api, other).json()
    settings.STATEMENT_UPLOAD_MODE = "background"
    queued = upload(api, client_record).json()

    assert work() == "succeeded"
    done = api.get(f"{V1}/jobs/{queued['id']}/").json()

    assert inline["status"] == "SUCCEEDED" and done["status"] == "SUCCEEDED"
    assert done["progress"] == 100 and done["error"] == "" and done["error_code"] == ""
    assert strip_ids(done["result"]) == strip_ids(inline["result"])
    assert done["result"]["rows_created"] == 54
    with firm_context(firm.pk):
        assert Statement.objects.filter(bank_account__client=client_record).count() == 1
        assert Statement.objects.filter(bank_account__client=other).count() == 1


def test_progress_is_told_at_stage_boundaries(api, client_record):
    upload(api, client_record)
    work()

    assert QuietBeat.said[0] == "Reading the PDF"
    assert "Saving the rows" in QuietBeat.said and "Posting what the rules are sure of" in QuietBeat.said


def test_the_staged_file_is_deleted_after_the_job_is_final(api, firm, client_record):
    upload(api, client_record)
    key = only_job(firm).staged_key
    work()

    assert not get_storage().exists(key) and only_job(firm).staged_key == ""


def test_the_same_file_after_it_was_read_returns_the_original_and_queues_nothing(api, firm, client_record):
    first = upload(api, client_record).json()
    work()
    again = upload(api, client_record)

    assert again.status_code == 200 and again.json()["id"] == first["id"] and again.json()["status"] == "SUCCEEDED"
    assert work() is None


def test_a_file_that_cannot_be_read_fails_the_job_with_the_same_words_and_code_as_inline(api, firm, client_record, settings):
    from integrations.registry import reset_adapter_cache

    settings.INTEGRATIONS = {**settings.INTEGRATIONS, "pdf": "integrations.pdf.pdfplumber_text.PdfPlumberAdapter"}
    reset_adapter_cache()
    garbage = b"%PDF-1.7 followed by nothing a PDF parser can read"
    other = create_client(firm, "Inline Client", datetime.date(2025, 4, 1))
    settings.STATEMENT_UPLOAD_MODE = "inline"
    inline = upload(api, other, garbage, "notes.pdf").json()
    settings.STATEMENT_UPLOAD_MODE = "background"
    queued = upload(api, client_record, garbage, "notes.pdf").json()

    assert work() == "failed"
    done = api.get(f"{V1}/jobs/{queued['id']}/").json()

    assert done["status"] == "FAILED" and done["error_code"] == inline["error_code"] == "unreadable_file"
    assert done["error"] == inline["error"]
    assert only_job_for(firm, queued["id"]).staged_key == ""


def only_job_for(firm, job_id):
    with firm_context(firm.pk):
        return Job.objects.get(pk=job_id)


def test_running_the_same_job_again_after_it_finished_duplicates_nothing(api, firm, client_record):
    """What a crash between the work and its record used to risk: the work done twice. A repeat finds it already there."""
    upload(api, client_record)
    job = only_job(firm)
    key = job.staged_key
    work()
    before = counts(firm)
    get_storage().put(key, PDF)
    with firm_context(firm.pk):
        Job.objects.filter(pk=job.pk).update(status=JobStatus.PENDING, staged_key=key, finished_at=None, result={})

    assert work() == "succeeded"
    assert counts(firm) == before


# ---------------------------------------------------------------------------
# Leases
# ---------------------------------------------------------------------------


def test_a_worker_that_lost_its_job_before_writing_does_nothing(api, firm, client_record):
    upload(api, client_record)
    claim = jobqueue.claim_next("slow-reader")
    with firm_context(firm.pk):
        Job.objects.filter(pk=claim.job_id).update(lease_token=uuid.uuid4())  # taken back and given to another reader

    assert jobqueue.execute(claim, QuietBeat) == "lost"
    assert counts(firm) == {"statements": 0, "rows": 0, "entries": 0}
    assert only_job(firm).status == JobStatus.RUNNING


def test_a_worker_that_lost_its_job_after_writing_has_all_of_it_rolled_back(api, firm, client_record, monkeypatch):
    """The fence that matters: the work and "succeeded" commit together, so losing the job undoes the rows, entries and statement."""
    upload(api, client_record)
    claim = jobqueue.claim_next("paused-reader")
    monkeypatch.setattr(jobqueue.JobContext, "hold", lambda self: None)  # it believed it still held the job, and began to write
    with firm_context(firm.pk):
        Job.objects.filter(pk=claim.job_id).update(lease_token=uuid.uuid4())

    assert jobqueue.execute(claim, QuietBeat) == "lost"
    assert counts(firm) == {"statements": 0, "rows": 0, "entries": 0}
    job = only_job(firm)
    assert job.status == JobStatus.RUNNING and job.result == {}


def test_a_heartbeat_from_a_worker_that_lost_the_job_changes_nothing(api, firm, client_record):
    upload(api, client_record)
    claim = jobqueue.claim_next("reader")
    with firm_context(firm.pk):
        Job.objects.filter(pk=claim.job_id).update(lease_token=uuid.uuid4())
        before = Job.objects.get(pk=claim.job_id)
    beat = jobqueue.Heartbeat(claim)
    beat.say("a late word")
    beat._beat()
    after = only_job(firm)

    assert beat.lost and after.heartbeat_at == before.heartbeat_at and after.message == before.message


def test_a_heartbeat_keeps_the_lease_and_carries_the_words(api, firm, client_record):
    upload(api, client_record)
    claim = jobqueue.claim_next("reader")
    beat = jobqueue.Heartbeat(claim)
    beat.say("Placing rows")
    beat._beat()

    assert not beat.lost and only_job(firm).message == "Placing rows"
    assert jobqueue.worker_status()["current"] == f"{claim.job_id}:1"


def stale(firm, job_id):
    with firm_context(firm.pk):
        Job.objects.filter(pk=job_id).update(heartbeat_at=timezone.now() - timedelta(minutes=10))


def test_a_job_whose_reader_stopped_goes_back_to_waiting_and_is_failed_after_three_executions(api, firm, client_record):
    upload(api, client_record)
    for attempt in (1, 2, 3):
        claim = jobqueue.claim_next("reader")
        assert claim is not None and claim.attempt == attempt
        stale(firm, claim.job_id)
        requeued, failed = jobqueue.recover_stale()
        assert (requeued, failed) == ((1, 0) if attempt < 3 else (0, 1))
    job = only_job(firm)
    assert job.status == JobStatus.FAILED and job.error == jobqueue.LOST_WORDS and job.error_code == "reader_stopped"
    assert jobqueue.claim_next("reader") is None


def test_a_slow_job_that_is_still_beating_is_left_alone(api, firm, client_record):
    upload(api, client_record)
    claim = jobqueue.claim_next("reader")

    assert jobqueue.recover_stale() == (0, 0)
    assert only_job(firm).status == JobStatus.RUNNING and only_job(firm).lease_token == claim.token


def test_two_readers_cannot_take_the_same_job(api, client_record):
    upload(api, client_record)

    assert jobqueue.claim_next("one") is not None
    assert jobqueue.claim_next("two") is None


# ---------------------------------------------------------------------------
# Tidying
# ---------------------------------------------------------------------------


def test_a_failed_delete_leaves_a_successful_job_successful_and_the_sweep_finishes_it(api, firm, client_record, monkeypatch):
    upload(api, client_record)
    key = only_job(firm).staged_key
    real_delete = type(get_storage()).delete

    def broken(self, key):
        raise OSError("cannot delete")

    monkeypatch.setattr(type(get_storage()), "delete", broken)
    assert work() == "succeeded"
    job = only_job(firm)
    assert job.status == JobStatus.SUCCEEDED and job.staged_key == key

    monkeypatch.setattr(type(get_storage()), "delete", real_delete)
    jobqueue.sweep()
    assert only_job(firm).staged_key == "" and not get_storage().exists(key)


def test_the_sweep_removes_a_job_whose_file_never_arrived_but_not_a_new_one(api, firm, client_record):
    with firm_context(firm.pk):
        old = enqueue_job(firm_id=firm.pk, kind="statement.ingest", idempotency_key="old", staged_key="k/old").job
        new = enqueue_job(firm_id=firm.pk, kind="statement.ingest", idempotency_key="new", staged_key="k/new").job
        Job.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(hours=1))

    jobqueue.sweep()

    with firm_context(firm.pk):
        assert list(Job.objects.values_list("pk", flat=True)) == [new.pk]


# ---------------------------------------------------------------------------
# Who goes next
# ---------------------------------------------------------------------------


def waiting_job(firm, key, *, finished_ago=None, created_ago=0):
    """A job in ``firm``'s queue ready to claim, or (with ``finished_ago``) one that finished that long ago."""
    with firm_context(firm.pk):
        job = Job.objects.create(
            firm=firm, kind="statement.ingest", idempotency_key=key, status=JobStatus.PENDING, payload={}, staged_key=f"k/{key}"
        )
        fields = {"created_at": timezone.now() - timedelta(seconds=created_ago), "staged_at": timezone.now()}
        if finished_ago is not None:
            fields.update(status=JobStatus.SUCCEEDED, finished_at=timezone.now() - timedelta(seconds=finished_ago))
        Job.objects.filter(pk=job.pk).update(**fields)
    return job


def test_a_firm_served_longest_ago_goes_before_one_served_recently_and_a_firm_never_served_goes_first(db):
    never, long_ago, recently = (create_firm(name) for name in ("Never Served", "Long Ago", "Recently"))
    waiting_job(never, "n")
    waiting_job(long_ago, "a")
    waiting_job(long_ago, "a-done", finished_ago=86400 * 30)
    waiting_job(recently, "r")
    waiting_job(recently, "r-done", finished_ago=5)

    assert jobqueue.ranked_firms(["statement.ingest"]) == [never.pk, long_ago.pk, recently.pk]


def test_a_failed_job_counts_as_the_firm_being_served(db):
    failed, fresh = create_firm("Failed Last"), create_firm("Other")
    waiting_job(failed, "f")
    waiting_job(fresh, "o")
    waiting_job(fresh, "o-done", finished_ago=3600)
    done = waiting_job(failed, "f-done", finished_ago=60)
    with firm_context(failed.pk):
        Job.objects.filter(pk=done.pk).update(status=JobStatus.FAILED)

    assert jobqueue.ranked_firms(["statement.ingest"]) == [fresh.pk, failed.pk]


def test_firms_with_equal_standing_are_ordered_by_id_and_a_firm_with_many_does_not_hold_up_another(db):
    one, two = create_firm("One"), create_firm("Two")
    for n in range(3):
        waiting_job(one, f"one-{n}", created_ago=100 - n)
    waiting_job(two, "two-0")
    expected = sorted([one.pk, two.pk], key=str)
    assert jobqueue.ranked_firms(["statement.ingest"]) == expected

    first = jobqueue.claim_next("r")
    with firm_context(first.firm_id):
        Job.objects.filter(pk=first.job_id).update(status=JobStatus.SUCCEEDED, finished_at=timezone.now())
    second = jobqueue.claim_next("r")
    assert {first.firm_id, second.firm_id} == {one.pk, two.pk}  # the second claim is the other firm, not the first one's next file


def test_within_a_firm_the_oldest_job_is_taken_first(db):
    firm = create_firm("Ordering")
    newer = waiting_job(firm, "newer", created_ago=10)
    older = waiting_job(firm, "older", created_ago=500)

    assert jobqueue.claim_next("r").job_id == older.pk
    assert jobqueue.claim_next("r").job_id == newer.pk


# ---------------------------------------------------------------------------
# What a person is told while waiting
# ---------------------------------------------------------------------------


def test_a_waiting_job_says_how_many_are_ahead_and_whether_a_reader_is_looking(api, client_record):
    first = upload(api, client_record, PDF + b"1", "one.pdf").json()
    second = upload(api, client_record, PDF + b"2", "two.pdf").json()

    assert (first["queue_ahead"], second["queue_ahead"]) == (0, 1)
    assert second["reader_running"] is False  # nothing has looked at the queue yet

    jobqueue.note_poll()
    assert api.get(f"{V1}/jobs/{second['id']}/").json()["reader_running"] is True


def test_a_stale_poll_means_no_reader_and_a_missing_one_too(db):
    assert jobqueue.reader_running() is False
    cache.set("jobqueue:poll", 1.0)
    assert jobqueue.reader_running() is False
    jobqueue.note_poll()
    assert jobqueue.reader_running() is True


def test_a_finished_job_says_nothing_about_the_queue(api, client_record):
    queued = upload(api, client_record).json()
    work()
    done = api.get(f"{V1}/jobs/{queued['id']}/").json()

    assert done["queue_ahead"] is None and done["reader_running"] is None
