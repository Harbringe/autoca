"""Running work that an HTTP request should not sit and wait for.

One function, :func:`run_job`, and the whole point of it is that callers never
learn where the work happened. Today it happens inline, in the request that
asked for it. When Celery workers land it happens on a worker, and nothing
above this module changes -- not the API, not the URLs, not a frontend.

That is worth the indirection because the alternative is the version of this
project where parsing is a blocking call for six months and then every call
site has to be rewritten at once.

Errors are recorded rather than swallowed. The domain's exception messages are
written for people -- "Balance chain broke at row 30 (26-07-2025, 'NEFT/MB/...'):
expected a balance of ..." -- so they are stored verbatim and handed back, with
a stable machine-readable code beside them for clients that want to branch.
"""

from __future__ import annotations

import functools
import logging
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from core.models import Job, JobStatus

logger = logging.getLogger("autoca.jobs")

#: Domain exception class name -> the code a client sees. Anything not listed
#: is reported as ``internal_error`` and logged with a traceback, because an
#: unrecognised exception is a bug rather than a user-facing outcome.
ERROR_CODES = {
    "PdfExtractionError": "unreadable_file",
    "PdfTruncationError": "pages_missing",
    "PdfPasswordRequired": "password_required",
    "PdfPasswordIncorrect": "password_incorrect",
    "NoTextLayerError": "no_text_layer",
    "UnsupportedBankError": "unsupported_bank",
    "BalanceChainError": "balance_chain_broken",
    "ColumnInferenceError": "columns_not_inferred",
    "StatementParseError": "statement_unreadable",
    "StatementContinuityError": "statement_period_missing",
    "StatementElsewhereError": "statement_elsewhere",
    "AlreadyPostedError": "already_posted",
    "NotApprovableError": "not_approvable",
    "NoStatementError": "no_statement_for_date",
    "MoneyError": "bad_amount",
    "PermissionDenied": "forbidden",
}

class JobFailed(RuntimeError):
    """Raised by :func:`run_job_sync` when the caller wants the failure inline."""

    def __init__(self, job: Job):
        self.job = job
        super().__init__(job.error or "job failed")


@dataclass(frozen=True)
class JobResult:
    job: Job
    #: True when an existing job was returned instead of a new one being run.
    reused: bool = False


def run_job(
    *, firm_id, kind: str, work, user=None, idempotency_key: str = "", message: str = ""
) -> JobResult:
    """Record a job, do the work, and record what happened.

    ``work`` is called with no arguments and returns anything JSON-serialisable,
    which becomes ``job.result``.

    A repeat of a job that already succeeded returns the original rather than
    doing the work again -- that is what the idempotency key is for, and it is
    what makes a retried upload or a double-clicked button harmless.
    """
    if idempotency_key:
        existing = Job.objects.filter(firm_id=firm_id, idempotency_key=idempotency_key).first()
        if existing is not None and existing.status == JobStatus.SUCCEEDED:
            return JobResult(job=existing, reused=True)
        if existing is not None:
            existing.delete()  # a previous failure; let this attempt replace it

    try:
        # A savepoint of its own: two requests carrying the same key race on the unique
        # constraint, and the loser must not poison the transaction it is running in.
        with transaction.atomic():
            job = Job.objects.create(
                firm_id=firm_id,
                kind=kind,
                idempotency_key=idempotency_key,
                status=JobStatus.RUNNING,
                message=message,
                started_at=timezone.now(),
                created_by=user,
            )
    except IntegrityError:
        existing = (
            Job.objects.filter(firm_id=firm_id, idempotency_key=idempotency_key).first()
            if idempotency_key
            else None
        )
        if existing is None:
            raise
        return JobResult(job=existing, reused=True)

    try:
        # A failure must not roll the Job row back along with the work, or the
        # caller is handed a job id that no longer exists. The work gets its own
        # savepoint; the record of it surviving is the point.
        with transaction.atomic():
            result = work()
    except expected_exceptions() as exc:
        return JobResult(job=_fail(job, exc, expected=True))
    except Exception as exc:  # noqa: BLE001 -- recorded, then re-raised context
        logger.exception("job %s (%s) failed unexpectedly", job.pk, kind)
        return JobResult(job=_fail(job, exc, expected=False))

    job.status = JobStatus.SUCCEEDED
    job.progress = 100
    job.result = result if isinstance(result, dict) else {"value": result}
    # Work that finished but could not do all of what was asked (the model was unreachable,
    # say) still succeeded, and says so here, where a person looking at the job will see it.
    warning = result.get("warning") if isinstance(result, dict) else None
    job.message = warning or message or "done"
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "progress", "result", "message", "finished_at"])
    return JobResult(job=job)


def run_job_sync(**kwargs) -> Job:
    """As :func:`run_job`, but raise on failure instead of returning a failed job.

    For management commands and tests, where an exception is the more useful
    shape and there is nobody to poll a job id.
    """
    outcome = run_job(**kwargs)
    if outcome.job.status == JobStatus.FAILED:
        raise JobFailed(outcome.job)
    return outcome.job


def _fail(job: Job, exc: Exception, *, expected: bool) -> Job:
    """Record the failure on the job.

    An expected failure carries the domain's own message, which was written for
    the person who will read it. An unexpected one does not: a stray exception
    from a driver or a library quotes whatever it was holding -- a SQL
    statement, a file path, a narration -- and none of that belongs in an API
    response. The traceback is in the log under the job id, which is what the
    message points at.
    """
    name = type(exc).__name__
    job.status = JobStatus.FAILED
    job.error = (
        str(exc)
        if expected
        else f"Something went wrong while running this job. It has been logged (job {job.pk})."
    )
    job.error_code = ERROR_CODES.get(name, "internal_error")
    job.finished_at = timezone.now()
    job.save(update_fields=["status", "error", "error_code", "finished_at"])
    return job


@functools.cache
def expected_exceptions() -> tuple[type[Exception], ...]:
    """The exceptions that mean "cannot be done" rather than "is broken".

    Resolved on first use rather than at import: these live in ``banking``,
    ``ledger`` and ``classify``, all of which import ``core``, so naming them at
    module scope would be a circular import.
    """
    from django.core.exceptions import PermissionDenied

    from banking.ingest import StatementContinuityError, StatementElsewhereError
    from banking.parsers.base import (
        BalanceChainError,
        NoTextLayerError,
        StatementParseError,
        UnsupportedBankError,
    )
    from banking.parsers.columns import ColumnInferenceError
    from core.money import MoneyError
    from integrations.pdf.base import PdfExtractionError
    from ledger.approval import AlreadyPostedError, NotApprovableError
    from ledger.reconciliation import NoStatementError

    return (
        StatementParseError,  # covers the parse family by inheritance
        BalanceChainError,
        NoTextLayerError,
        UnsupportedBankError,
        ColumnInferenceError,
        # A corrupt or non-PDF upload is an outcome, not a bug. PdfTruncationError
        # subclasses this one.
        PdfExtractionError,
        StatementContinuityError,
        StatementElsewhereError,
        NotApprovableError,
        AlreadyPostedError,
        NoStatementError,
        MoneyError,
        PermissionDenied,
    )
