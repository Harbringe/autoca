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
import time
import uuid

from django.db import DatabaseError

logger = logging.getLogger("autoca.audit")

MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        started = time.monotonic()

        response = self.get_response(request)

        if request.method in MUTATING_METHODS:
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

        try:
            AuditLog.objects.create(
                firm=firm,
                user=user if (user and user.is_authenticated) else None,
                method=request.method,
                path=request.get_full_path()[:512],
                status_code=response.status_code,
                ip_address=self._client_ip(request),
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

    @staticmethod
    def _client_ip(request):
        # Render terminates TLS and sets X-Forwarded-For. Take the first entry,
        # which is the client as seen by the edge.
        forwarded = request.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip() or None
        return request.META.get("REMOTE_ADDR") or None
