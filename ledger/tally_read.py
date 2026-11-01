"""Reading a large Tally vouchers export in the background, one queued import per calendar month.

A firm's years of vouchers are far more than a web request can read (the proxy gives it 60 seconds). The upload is stored as the client's
document and a worker (``core.jobqueue``) reads it, cuts it by month, and stages each month as an import of its own, so each can be reviewed,
posted and undone separately. A month already staged for the same file is reused, so a worker that stopped part-way and is replaced, or the
same file uploaded twice, makes nothing new.
"""

from __future__ import annotations

import hashlib
import json
import logging

from django.core.exceptions import PermissionDenied
from django.db import transaction

from core import jobqueue
from core.access import can_see_client
from core.db.session import firm_context
from core.jobs import JobResult, enqueue_job, mark_staged
from core.models import Client, FirmMembership, Job, JobStatus
from core.rbac import has_permission
from documents.models import Document
from integrations.registry import get_storage
from ledger.models import ImportStatus, LedgerImportRun
from ledger.tally_import import TallyImportError, _require_rights
from ledger.tally_split import split_by_month
from ledger.tally_voucher_import import _keep_file, normalise_type_map, stage_month
from ledger.tally_vouchers import parse_vouchers, voucher_file_limit

logger = logging.getLogger(__name__)

KIND = "tally.read"
NO_LONGER_ALLOWED = "You no longer have permission to import into this client, so the file was not read."


def enqueue_read(client, membership, user, *, data: bytes, filename: str, voucher_types: dict | None) -> JobResult:
    """Store the file as the client's document and queue its reading. Returns at once with the job."""
    _require_rights(membership, client)
    document = _keep_file(client, user, data, filename)
    types = normalise_type_map(voucher_types)
    key = f"tally-read:{client.pk}:{document.sha256}:{hashlib.sha256(json.dumps(sorted(types.items())).encode()).hexdigest()[:16]}"
    # A file whose imports were all discarded may be read again: its finished job would otherwise be handed back as "done".
    # Only a finished job is replaced: one still waiting or running is the same upload, handed back as it is.
    if not LedgerImportRun.objects.filter(client=client, document=document).exclude(status=ImportStatus.DISCARDED).exists():
        Job.objects.filter(firm_id=client.firm_id, idempotency_key=key, status__in=JobStatus.terminal()).delete()
    outcome = enqueue_job(
        firm_id=client.firm_id,
        kind=KIND,
        idempotency_key=key,
        user=user,
        message="Waiting to be read",
        payload={"client": str(client.pk), "document": str(document.pk), "voucher_types": types},
    )
    if not outcome.reused:
        mark_staged(outcome.job)
    return outcome


def run(ctx: jobqueue.JobContext) -> None:
    """The worker's half: read the stored file, cut it by month, stage each month."""
    claim = ctx.claim
    with firm_context(claim.firm_id):
        job = Job.objects.select_related("created_by").get(pk=claim.job_id)
        meta, user = job.payload, job.created_by
        client = Client.objects.get(pk=meta["client"])
        document = Document.objects.get(pk=meta["document"])
        membership = (
            FirmMembership.objects.filter(firm_id=claim.firm_id, user=user, is_active=True).first()
            if user is not None and user.is_active
            else None
        )
        if membership is None or not has_permission(membership, "ledger.import") or not can_see_client(membership, client):
            raise PermissionDenied(NO_LONGER_ALLOWED)

    ctx.say("Reading the file")
    data = get_storage().get(document.storage_key)
    parsed = parse_vouchers(data, document.original_filename, max_bytes=voucher_file_limit(document.original_filename))
    if len(parsed.companies) > 1:
        raise TallyImportError("This file has vouchers from more than one company. Export one company at a time.")
    months = split_by_month(parsed.vouchers)
    if not months:
        raise TallyImportError("There are no vouchers to import in this file.")

    types = meta.get("voucher_types") or {}
    seed = f"{document.sha256}|{json.dumps(sorted(types.items()))}"
    made: list[str] = []
    failed: list[dict[str, str]] = []
    for number, (month, vouchers) in enumerate(months, start=1):
        ctx.say(f"Reading month {number} of {len(months)}")
        # The file's vouchers that could not be read at all have no date, so they ride with the first month.
        skipped = parsed.skipped if number == 1 else []
        try:
            with firm_context(claim.firm_id), transaction.atomic():
                staged, _reused = stage_month(client, user, vouchers, skipped, month, seed, types, document)
            made.append(str(staged.pk))
        except Exception as exc:  # one month that cannot be staged (signed off, say) must not stop the others
            if not exc.__class__.__name__.startswith(("Tally", "EntryLocked")):
                logger.warning("A month of a Tally file could not be staged (%s)", type(exc).__name__)
            failed.append({"month": month, "reason": str(exc) if exc.__class__.__name__.startswith(("Tally", "EntryLocked")) else "This month could not be read."})
    # The worker has no ambient firm, and the job row is the firm's: its last write is made inside the firm's context.
    with firm_context(claim.firm_id):
        ctx.hold()
        ctx.complete({"runs": made, "months": len(months), "failed": failed}, message=f"Read {len(months)} months")


jobqueue.register(KIND, run)
