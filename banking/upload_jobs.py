"""A statement upload that is read in the background: the web side that accepts it, and the worker side that reads it.

The request validates the file, puts it in storage under the firm's prefix, records a job and answers at once (``enqueue_statement_upload``).
The worker (``core.jobqueue``) then does the slow part with no transaction open (``read_statement_file``, about 19 s for 238 pages) and the
database part in one transaction that also records the job as succeeded (``run``), so a worker that lost the job rolls all of it back.

A password is never stored, so an upload that carries one is not given to a worker (the view reads it inline).
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied

from banking.ingest import already_ingested, read_statement_file
from core import jobqueue
from core.access import can_see_client
from core.db.session import firm_context
from core.jobs import JobResult, enqueue_job, mark_staged
from core.models import Client, FirmMembership, Job
from core.rbac import has_permission
from documents.models import Document
from integrations.registry import get_storage

KIND = "statement.ingest"


def enqueue_statement_upload(*, client, data: bytes, filename: str, user, allow_gap: bool, layout, key: str) -> JobResult:
    """Record the upload and put its file where the worker will find it. Returns at once with the job (PENDING)."""
    storage = get_storage()
    staged_key = storage.tenant_key(client.firm_id, "clients", str(client.pk), "uploads", Document.digest(data))
    outcome = enqueue_job(
        firm_id=client.firm_id,
        kind=KIND,
        idempotency_key=key,
        user=user,
        message=jobqueue.WAITING_WORDS,
        payload={"client": str(client.pk), "filename": filename[:255], "allow_gap": bool(allow_gap), "layout": layout or None},
        staged_key=staged_key,
    )
    if outcome.reused:
        return outcome  # the same file is already queued, running or done: nothing more to stage, nothing of ours to delete
    try:
        storage.put(staged_key, data, content_type="application/pdf")
    except Exception:
        outcome.job.delete()  # no job without a file behind it
        raise
    mark_staged(outcome.job)
    return outcome


NO_LONGER_ALLOWED = "You no longer have access to upload statements for this client, so this file was not read. Nothing was imported."


def _still_allowed(firm_id, user, client) -> None:
    """Raise PermissionDenied unless the person who uploaded may still do it.

    The upload was allowed when it was accepted; the worker runs it later, and access can be taken away in between (a person removed from
    the firm, a role changed, a client reassigned). The same rules the request used decide again: an active account, an active membership
    in this firm with ``document.upload``, and the client still one they may see.
    """
    membership = (
        FirmMembership.objects.filter(firm_id=firm_id, user=user, is_active=True).first() if user is not None and user.is_active else None
    )
    if membership is None or not has_permission(membership, "document.upload") or not can_see_client(membership, client):
        raise PermissionDenied(NO_LONGER_ALLOWED)


def run(ctx: jobqueue.JobContext) -> None:
    """The worker's half. Reads with no transaction open, then writes (and records success) in one."""
    # The same placing of the rows the inline path has always done.
    from api.views.banking import _ingest

    claim = ctx.claim
    with firm_context(claim.firm_id):
        job = Job.objects.select_related("created_by").get(pk=claim.job_id)
        meta, staged_key, user = job.payload, job.staged_key, job.created_by
        client = Client.objects.get(pk=meta["client"])
        _still_allowed(claim.firm_id, user, client)

    ctx.say("Reading the PDF")
    data = get_storage().get(staged_key)
    with firm_context(claim.firm_id):
        repeat = already_ingested(client, data)
    read = None
    if repeat is None:  # a file already read is not read again; the write part hands back the original statement
        read = read_statement_file(client=client, data=data, filename=meta.get("filename", ""), layout=meta.get("layout"))

    ctx.hold()  # about to write: only if the job is still this worker's
    ctx.say("Saving the rows")
    with firm_context(claim.firm_id):
        _still_allowed(claim.firm_id, user, client)  # again: the read took a while, and nothing is written for someone who lost access
        result = _ingest(
            client=client,
            data=data,
            filename=meta.get("filename", ""),
            user=user,
            allow_gap=bool(meta.get("allow_gap")),
            layout=meta.get("layout"),
            read=read,
            on_stage=ctx.say,
        )
        ctx.complete(result, message=f"Read {meta.get('filename', 'the statement')}")


jobqueue.register(KIND, run)
