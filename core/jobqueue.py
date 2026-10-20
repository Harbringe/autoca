"""The queue behind background jobs: a worker claims a waiting job, holds it on a lease, and finishes it or loses it cleanly.

Work that takes tens of seconds (reading a 238-page statement) used to run inside the web request, holding one of the server's few web
workers for the whole time. Here the request only records the job and the worker does the work (``python manage.py run_uploads``). The
database is the queue; there is no broker, because the volume is far below what Postgres handles.

How a job is kept safe:

* **Claiming is a short transaction** (``FOR UPDATE SKIP LOCKED``): the job becomes RUNNING with a fresh ``lease_token`` and the worker's id.
  The work itself runs with no transaction open across the slow part.
* **Everything the holder writes carries the token.** A heartbeat thread refreshes ``heartbeat_at`` (the database's clock) while the job runs,
  and the work's own transaction ends with a write of "succeeded" guarded by the token and committed *with the work*: a worker that lost the
  job changes no row, raises :class:`LeaseLost`, and its whole transaction rolls back. A stale worker can therefore leave nothing behind.
* **A worker that stops is noticed** by a heartbeat older than ``LEASE_SECONDS`` and its job goes back to PENDING (up to ``MAX_ATTEMPTS``
  executions), then FAILED with a message a person can act on.
* **Fairness without state.** Of the firms with something waiting, the one whose last finished job is oldest goes next (never-served first,
  ties by firm id); within a firm, the oldest job. It is worked out from the job table each time, so a restart loses nothing.
* **The uploaded file waits in storage** under the firm's prefix and is deleted after the job is final (the final state commits first). Anything
  left behind is found from the job table by :func:`sweep`.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta

from django.core.cache import cache
from django.db import DatabaseError, connection, connections
from django.db.models import DateTimeField, ExpressionWrapper, F, Max
from django.db.models.functions import Now

from core.db.session import firm_context
from core.models import Job, JobStatus

logger = logging.getLogger("autoca.jobqueue")

HEARTBEAT_SECONDS = 20
#: A RUNNING job whose heartbeat is older than this (by the database's clock) is taken back.
LEASE_SECONDS = 300
#: Executions a job gets: the first run, then two recoveries after a worker stopped.
MAX_ATTEMPTS = 3
#: A job whose file never reached storage (the request died half-way) is removed after this long.
UNSTAGED_SECONDS = 600
WAITING_WORDS = "Waiting to be read"
LOST_WORDS = "The reader stopped while reading this file; upload it again."

#: kind -> function(ctx). Registered by the app that owns the work (``banking.upload_jobs``).
HANDLERS: dict = {}

_POLL, _BEAT, _CURRENT, _SWEEP = "jobqueue:poll", "jobqueue:beat", "jobqueue:current", "jobqueue:sweep"


class LeaseLost(RuntimeError):
    """This worker no longer holds the job (it was taken back after the worker stopped answering). Nothing it did is kept."""


@dataclass(frozen=True)
class Claim:
    job_id: object
    firm_id: object
    kind: str
    token: uuid.UUID
    worker_id: str
    attempt: int


def register(kind: str, handler) -> None:
    HANDLERS[kind] = handler


# ---------------------------------------------------------------------------
# Health: three separate signals, so a worker that is alive but stuck is told apart from one that is just busy
# ---------------------------------------------------------------------------


def note_poll() -> None:
    """The worker looked at the queue and the database answered."""
    cache.set(_POLL, time.time(), timeout=3600)


def note_beat(claim: Claim | None) -> None:
    """A job's heartbeat was written (or, with None, no job is running)."""
    if claim is None:
        cache.delete(_CURRENT)
        return
    cache.set(_BEAT, time.time(), timeout=3600)
    cache.set(_CURRENT, f"{claim.job_id}:{claim.attempt}", timeout=3600)


def worker_status() -> dict:
    """Seconds since the worker last polled the queue and last beat a job (None when never or long ago), and the job it is on."""
    now = time.time()
    poll, beat = cache.get(_POLL), cache.get(_BEAT)
    return {
        "poll_age": None if poll is None else round(now - poll, 1),
        "beat_age": None if beat is None else round(now - beat, 1),
        "current": cache.get(_CURRENT),
    }


def reader_running(max_poll_age: float = 120.0) -> bool:
    """Is a worker looking at the queue? A job waiting is not proof it is not: only a stale poll is."""
    age = worker_status()["poll_age"]
    return age is not None and age <= max_poll_age


# ---------------------------------------------------------------------------
# Choosing and claiming
# ---------------------------------------------------------------------------


def firm_ids() -> list:
    """Every active firm's id. The worker has no tenant until it enters one, so it asks the database function that hands out only ids."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT t.id FROM app.active_firm_ids() AS t(id)")
        return [row[0] for row in cursor.fetchall()]


def ranked_firms(kinds) -> list:
    """Firms with a job ready to claim, most deserving first: never served, then longest since a job of theirs finished, then firm id."""
    ranked = []
    for firm_id in firm_ids():
        with firm_context(firm_id):
            if not Job.objects.filter(kind__in=kinds, status=JobStatus.PENDING, staged_at__isnull=False).exists():
                continue
            last = Job.objects.filter(kind__in=kinds, status__in=JobStatus.terminal()).aggregate(m=Max("finished_at"))["m"]
        ranked.append(((0, 0.0) if last is None else (1, last.timestamp()), str(firm_id), firm_id))
    ranked.sort(key=lambda r: (r[0], r[1]))
    return [firm_id for _rank, _text, firm_id in ranked]


def claim_next(worker_id: str, kinds=None) -> Claim | None:
    """Take the next job: a short transaction that ends with the job RUNNING under a new lease."""
    kinds = list(kinds or HANDLERS)
    for firm_id in ranked_firms(kinds):
        with firm_context(firm_id):
            job = (
                Job.objects.select_for_update(skip_locked=True)
                .filter(kind__in=kinds, status=JobStatus.PENDING, staged_at__isnull=False)
                .order_by("created_at", "id")
                .first()
            )
            if job is None:
                continue
            token = uuid.uuid4()
            Job.objects.filter(pk=job.pk).update(
                status=JobStatus.RUNNING,
                attempts=F("attempts") + 1,
                lease_token=token,
                worker_id=worker_id[:64],
                heartbeat_at=Now(),
                started_at=Now(),
                message="Reading the file",
            )
            return Claim(job.pk, firm_id, job.kind, token, worker_id, job.attempts + 1)
    return None


# ---------------------------------------------------------------------------
# While a job runs
# ---------------------------------------------------------------------------


class Heartbeat(threading.Thread):
    """Keeps the lease alive and carries progress words to the job, on a database connection of its own.

    The work's own transaction cannot show its progress (nobody else sees an uncommitted write), so the words go through here.
    """

    def __init__(self, claim: Claim):
        super().__init__(daemon=True, name=f"heartbeat-{claim.job_id}")
        self.claim = claim
        self._stop_event = threading.Event()
        self._wake = threading.Event()
        self._words: str | None = None
        self.lost = False

    def say(self, words: str) -> None:
        self._words = words
        self._wake.set()

    def stop(self) -> None:
        self._stop_event.set()
        self._wake.set()
        self.join(timeout=30)

    def run(self) -> None:
        try:
            while not self._stop_event.is_set():
                self._beat()
                self._wake.wait(HEARTBEAT_SECONDS)
                self._wake.clear()
        finally:
            connections.close_all()

    def _beat(self) -> None:
        words, self._words = self._words, None
        fields = {"heartbeat_at": Now()}
        if words:
            fields["message"] = words[:255]
        try:
            with firm_context(self.claim.firm_id):
                held = Job.objects.filter(pk=self.claim.job_id, lease_token=self.claim.token, status=JobStatus.RUNNING).update(**fields)
            if held:
                note_beat(self.claim)
            elif not self._stop_event.is_set():
                self.lost = True
        except DatabaseError:
            logger.exception("heartbeat for job %s could not be written", self.claim.job_id)


class JobContext:
    """What a handler is given: the job, a way to say where it is, and the one way to finish."""

    def __init__(self, claim: Claim, heartbeat: Heartbeat):
        self.claim = claim
        self._heartbeat = heartbeat

    def say(self, words: str) -> None:
        self._heartbeat.say(words)

    def hold(self) -> None:
        """Raise :class:`LeaseLost` unless this worker still holds the job. Called before any work that writes."""
        with firm_context(self.claim.firm_id):
            if not Job.objects.filter(pk=self.claim.job_id, lease_token=self.claim.token, status=JobStatus.RUNNING).exists():
                raise LeaseLost(str(self.claim.job_id))

    def complete(self, result: dict, message: str = "done") -> None:
        """Record success, inside the transaction that holds the work, as its last step.

        The write names the token, so it changes nothing unless this worker still holds the job; then the work and "succeeded"
        commit together or, on :class:`LeaseLost`, neither does.
        """
        warning = result.get("warning") if isinstance(result, dict) else None
        changed = Job.objects.filter(pk=self.claim.job_id, lease_token=self.claim.token, status=JobStatus.RUNNING).update(
            status=JobStatus.SUCCEEDED,
            progress=100,
            result=result if isinstance(result, dict) else {"value": result},
            message=(warning or message)[:255],
            finished_at=Now(),
            heartbeat_at=Now(),
        )
        if not changed:
            raise LeaseLost(str(self.claim.job_id))


def execute(claim: Claim, heartbeat_factory=Heartbeat) -> str:
    """Run a claimed job and record what happened. Returns ``succeeded``, ``failed`` or ``lost``.

    ``heartbeat_factory`` is for tests, whose uncommitted data a heartbeat thread on its own connection could not see.
    """
    from core.jobs import describe_failure, expected_exceptions

    handler = HANDLERS[claim.kind]
    beat = heartbeat_factory(claim)
    beat.start()
    outcome = "failed"
    try:
        try:
            handler(JobContext(claim, beat))
            outcome = "succeeded"
        except LeaseLost:
            logger.warning("job %s: this worker no longer holds it; its work was rolled back", claim.job_id)
            outcome = "lost"
        except Exception as exc:  # noqa: BLE001 -- recorded on the job
            expected = isinstance(exc, expected_exceptions())
            if not expected:
                logger.exception("job %s (%s) failed unexpectedly", claim.job_id, claim.kind)
            error, code = describe_failure(exc, claim.job_id, expected=expected)
            with firm_context(claim.firm_id):
                Job.objects.filter(pk=claim.job_id, lease_token=claim.token, status=JobStatus.RUNNING).update(
                    status=JobStatus.FAILED, error=error, error_code=code, finished_at=Now(), message="failed"
                )
    finally:
        beat.stop()
        note_beat(None)
    if outcome != "lost":
        clean_staged(claim.firm_id, claim.job_id)  # after the final state is committed, never before
    return outcome


# ---------------------------------------------------------------------------
# Recovery and tidying
# ---------------------------------------------------------------------------


def _older_than(seconds: int):
    return ExpressionWrapper(Now() - timedelta(seconds=seconds), output_field=DateTimeField())


def recover_stale(kinds=None) -> tuple[int, int]:
    """Take back jobs whose worker stopped answering. Returns (requeued, failed).

    Each job is changed by one conditional update, so two workers recovering at once cannot both act on it, and a worker that was
    only slow and answers in time is left alone.
    """
    kinds = list(kinds or HANDLERS)
    requeued = failed = 0
    for firm_id in firm_ids():
        with firm_context(firm_id):
            stale = list(
                Job.objects.filter(kind__in=kinds, status=JobStatus.RUNNING, heartbeat_at__lt=_older_than(LEASE_SECONDS)).values_list("pk", "attempts")
            )
            for pk, attempts in stale:
                still_stale = Job.objects.filter(pk=pk, status=JobStatus.RUNNING, heartbeat_at__lt=_older_than(LEASE_SECONDS))
                if attempts < MAX_ATTEMPTS:
                    requeued += still_stale.update(status=JobStatus.PENDING, lease_token=None, worker_id="", message=WAITING_WORDS)
                else:
                    failed += still_stale.update(
                        status=JobStatus.FAILED, lease_token=None, error=LOST_WORDS, error_code="reader_stopped", finished_at=Now(), message="failed"
                    )
    return requeued, failed


def clean_staged(firm_id, job_id) -> None:
    """Delete a finished job's staged file, unless another unfinished job still points at it. A failure here is logged and left for :func:`sweep`."""
    from integrations.registry import get_storage

    try:
        with firm_context(firm_id):
            job = Job.objects.filter(pk=job_id).first()
            if job is None or not job.staged_key or job.status not in JobStatus.terminal():
                return
            shared = Job.objects.filter(staged_key=job.staged_key).exclude(pk=job.pk).exclude(status__in=JobStatus.terminal()).exists()
            if not shared:
                get_storage().delete(job.staged_key)
            Job.objects.filter(pk=job.pk).update(staged_key="")
    except Exception:  # noqa: BLE001 -- never turns a finished job into a failure
        logger.exception("could not delete the staged file of job %s; the sweep will try again", job_id)


def sweep(kinds=None) -> int:
    """Tidy what a crash can leave: finished jobs whose staged file is still there, and jobs whose file never reached storage."""
    from integrations.registry import get_storage

    kinds = list(kinds or HANDLERS)
    tidied = 0
    for firm_id in firm_ids():
        with firm_context(firm_id):
            leftovers = list(Job.objects.filter(kind__in=kinds, status__in=JobStatus.terminal()).exclude(staged_key="").values_list("pk", flat=True))
            unstaged = list(
                Job.objects.filter(kind__in=kinds, status=JobStatus.PENDING, staged_at__isnull=True, created_at__lt=_older_than(UNSTAGED_SECONDS)).values_list("pk", "staged_key")
            )
        for pk in leftovers:
            clean_staged(firm_id, pk)
            tidied += 1
        for pk, key in unstaged:
            try:
                with firm_context(firm_id):
                    Job.objects.filter(pk=pk, status=JobStatus.PENDING, staged_at__isnull=True).delete()
                if key:
                    get_storage().delete(key)
                tidied += 1
            except Exception:  # noqa: BLE001
                logger.exception("could not remove job %s whose file never arrived", pk)
    return tidied


def sweep_due() -> bool:
    """True for one caller an hour (the cache lock is shared by every worker)."""
    return bool(cache.add(_SWEEP, 1, timeout=3600))


def run_once(worker_id: str, heartbeat_factory=Heartbeat) -> str | None:
    """One pass: look at the queue, tidy, and run one job if there is one. Returns what happened to it, or None when nothing was waiting."""
    note_poll()
    recover_stale()
    if sweep_due():
        sweep()
    claim = claim_next(worker_id)
    if claim is None:
        return None
    started = time.monotonic()
    outcome = execute(claim, heartbeat_factory)
    logger.info("job %s (%s, attempt %d) %s in %.1fs", claim.job_id, claim.kind, claim.attempt, outcome, time.monotonic() - started)
    return outcome
