"""Request-level audit trail.

Coarse by design for this phase: one row per mutating request, recording who,
what, when, from where. Field-level change tracking belongs with the models that
will need it (ledger entries, GST filings) and would be guesswork today.

What matters now is that the hook point exists before any feature code lands, so
there is never a window in which mutations happen unaudited.

Runs INSIDE ``TenantContextMiddleware`` because ``AuditLog`` is firm-scoped: the
audit row is written under the same tenant context as the request it describes,
and the RLS policy on the audit table applies to it like anything else.
"""

from __future__ import annotations

import logging
import re
import time

from django.db import DatabaseError

from core.db.session import firm_context
from core.http import client_ip, request_id

logger = logging.getLogger("autoca.audit")

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
#: HEAD runs the same view as GET (the number is decrypted, the file fetched) and only drops the body.
READ_METHODS = {"GET", "HEAD"}

#: Reads that hand over something sensitive and so are recorded like a write: a stored statement being downloaded, and a
#: bank account being opened (its number is decrypted for the response).
_UUID = r"[0-9a-fA-F-]{36}"
SENSITIVE_READS = (
    re.compile(rf"^/api/v1/documents/{_UUID}/download/$"),
    re.compile(rf"^/api/v1/clients/{_UUID}/bank-accounts/{_UUID}/$"),
)


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = request_id(request)
        started = time.monotonic()

        response = self.get_response(request)

        if request.method in MUTATING_METHODS or (
            request.method in READ_METHODS and any(p.fullmatch(request.path_info) for p in SENSITIVE_READS)
        ):
            self._record(request, response, time.monotonic() - started)

        response["X-Request-ID"] = request.request_id
        return response

    def _record(self, request, response, elapsed):
        firm = getattr(request, "firm", None)
        user = getattr(request, "user", None)

        if firm is None:
            # No tenant context: nothing to attach the row to. Log it instead --
            # a mutating request with no firm is unusual enough to want visible.
            logger.warning(
                "unattributed mutating request %s %s -> %s (request_id=%s)",
                request.method,
                request.path,
                response.status_code,
                request.request_id,
            )
            return

        from core.models import AuditLog

        if getattr(request, "audit_skip", False):
            # A view that polls says so when a call did nothing worth a permanent row.
            return

        try:
            # A view that opened its own firm context left none open for this row. Nesting
            # the same firm is harmless, so the ordinary path takes the same route.
            with firm_context(firm.pk):
                AuditLog.objects.create(
                    firm=firm,
                    user=user if (user and user.is_authenticated) else None,
                    method=request.method,
                    path=request.get_full_path()[:512],
                    status_code=response.status_code,
                    ip_address=client_ip(request),
                    user_agent=request.headers.get("User-Agent", "")[:512],
                    request_id=request.request_id,
                    duration_ms=int(elapsed * 1000),
                )
        except DatabaseError:
            # Never let auditing break the response. It is logged loudly instead
            # so a persistent failure surfaces rather than silently disabling
            # the trail.
            logger.exception(
                "failed to write audit row for %s %s (request_id=%s)",
                request.method,
                request.path,
                request.request_id,
            )
