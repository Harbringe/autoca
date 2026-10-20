"""Makes the shared figures (``core.freshness``) forget when a person changes something.

After a successful POST, PUT, PATCH or DELETE under /api/, the firm's version moves on once the change is committed, so the next read works
the figures out again instead of showing what they were a moment before. Reads, failed requests and anonymous ones change nothing.

Placed last: the firm is already known by then (``TenantContextMiddleware``), and the bump waits for the transaction that holds the change, so a
read in between cannot remember a figure worked out from before it.
"""

from __future__ import annotations

from django.db import transaction

from core import freshness

CHANGING = {"POST", "PUT", "PATCH", "DELETE"}


class FreshnessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        firm = getattr(request, "firm", None)
        if firm is not None and request.method in CHANGING and request.path.startswith("/api/") and response.status_code < 400:
            firm_id = firm.pk
            transaction.on_commit(lambda: freshness.bump(firm_id))
        return response
