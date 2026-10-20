"""Makes the shared figures (``core.freshness``) forget when a person changes something.

After a successful POST, PUT, PATCH or DELETE under /api/, the version moves on once the change is committed, so the next read works the
figures out again instead of showing what they were a moment before. A change under /api/v1/clients/<id>/ moves that client's version (and
the firm-wide one); any other change moves the firm's structural version too, which forgets everything. Reads, failed requests and anonymous ones change nothing.

Placed last: the firm is already known by then (``TenantContextMiddleware``), and the bump waits for the transaction that holds the change, so a
read in between cannot remember a figure worked out from before it.
"""

from __future__ import annotations

import re

from django.db import transaction

from core import freshness

CHANGING = {"POST", "PUT", "PATCH", "DELETE"}
#: The client a change is made under, from the address: /api/v1/clients/<id>/...
CLIENT_PATH = re.compile(r"^/api/v1/clients/([0-9a-fA-F-]{36})/")


class FreshnessMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        firm = getattr(request, "firm", None)
        if firm is not None and request.method in CHANGING and request.path.startswith("/api/") and response.status_code < 400:
            firm_id = firm.pk
            under = CLIENT_PATH.match(request.path)
            client_id = under.group(1).lower() if under else None
            transaction.on_commit(lambda: freshness.bump(firm_id, client_id))
        return response
