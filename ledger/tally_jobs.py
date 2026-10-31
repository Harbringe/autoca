"""Posting a queued Tally import in the background: the web side that queues it, and the worker side that writes the vouchers.

A real client's history is thousands of vouchers, each written in a transaction of its own; that takes minutes, longer than a web
request may. So posting a queued import records a job and answers at once (``enqueue_post``), and the worker (``core.jobqueue``)
writes the vouchers while the screen shows how far it has got. A voucher already written is never written twice (Tally's own id), so a
worker that stopped part-way and is replaced simply carries on.
"""

from __future__ import annotations

import logging

from django.core.exceptions import PermissionDenied

from core import jobqueue
from core.access import can_see_client
from core.db.session import firm_context
from core.jobs import JobResult, enqueue_job, mark_staged
from core.models import FirmMembership, Job
from core.rbac import has_permission
from ledger.models import ImportKind, ImportStatus, LedgerImportRun
from ledger.tally_voucher_import import check_postable, confirm_vouchers

logger = logging.getLogger(__name__)

KIND = "tally.post"
NO_LONGER_ALLOWED = "You no longer have permission to import into this client, so nothing was posted."


def enqueue_post(run: LedgerImportRun, membership, user, *, allow_overlap: bool) -> JobResult:
    """Check the import can be posted now, mark it as being posted, and queue the work. Returns at once."""
    check_postable(run, membership, allow_overlap=allow_overlap)
    total = int(run.counts.get("will_post", 0))
    run.result = {"posting": True, "progress": {"done": 0, "total": total}}
    run.save(update_fields=["result"])
    outcome = enqueue_job(
        firm_id=run.firm_id,
        kind=KIND,
        idempotency_key=f"tally-post:{run.pk}",
        user=user,
        message="Waiting to be posted",
        payload={"run": str(run.pk), "allow_overlap": bool(allow_overlap)},
    )
    if not outcome.reused:
        mark_staged(outcome.job)
    return outcome


def _note(run_id, **result) -> None:
    LedgerImportRun.objects.filter(pk=run_id, status=ImportStatus.PREVIEW).update(result=result)


def run(ctx: jobqueue.JobContext) -> None:
    """The worker's half."""
    claim = ctx.claim
    with firm_context(claim.firm_id):
        job = Job.objects.select_related("created_by").get(pk=claim.job_id)
        run_ = LedgerImportRun.objects.select_related("client").get(pk=job.payload["run"], kind=ImportKind.VOUCHERS)
        user = job.created_by
        membership = (
            FirmMembership.objects.filter(firm_id=claim.firm_id, user=user, is_active=True).first()
            if user is not None and user.is_active
            else None
        )
        if membership is None or not has_permission(membership, "ledger.import") or not can_see_client(membership, run_.client):
            _note(run_.pk, error=NO_LONGER_ALLOWED)
            raise PermissionDenied(NO_LONGER_ALLOWED)
        total = int(run_.counts.get("will_post", 0))
        allow_overlap = bool(job.payload.get("allow_overlap"))

    def progress(done: int, of: int) -> None:
        ctx.say(f"Posting {done} of {of}")
        with firm_context(claim.firm_id):
            _note(run_.pk, posting=True, progress={"done": done, "total": of})

    ctx.say(f"Posting 0 of {total}")
    try:
        with firm_context(claim.firm_id):
            ctx.hold()  # about to write: only if the job is still this worker's
            done = confirm_vouchers(run_, membership, user, allow_overlap=allow_overlap, on_progress=progress)
            ctx.complete({"run": str(done.pk), "posted": done.result.get("posted", 0)}, message=f"Posted {done.result.get('posted', 0)} vouchers")
    except Exception as exc:
        # The screen reads the run, not the job: say there why it stopped, and that it is no longer being posted.
        with firm_context(claim.firm_id):
            _note(run_.pk, error=str(exc) if exc.__class__.__name__.startswith("Tally") else "The import could not be posted. Try again.")
        raise


jobqueue.register(KIND, run)
