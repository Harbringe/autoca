"""The audit log, in words a firm owner can read.

``AuditLog`` records every write request: who, when, method, path and outcome.
This turns each path back into the action it was ("Approved entries for Acme
Traders") by matching it against the API's own routes, and names the client it
touched where the path carries one.
"""

from __future__ import annotations

import datetime
import re
import uuid

from django.utils import timezone
from rest_framework import serializers
from rest_framework.views import APIView

from api.pagination import DefaultPagination
from api.permissions import HasFirmPermission
from core.models import AuditLog, Client, FirmMembership

UUID = r"[0-9a-fA-F-]{36}"

#: (method, path pattern, description). First match wins. {client} is filled in
#: from the client id in the path when there is one.
ACTIONS: list[tuple[str, str, str]] = [
    ("POST", r"^/auth/login/$", "Signed in"),
    ("POST", r"^/auth/logout/$", "Signed out"),
    ("POST", r"^/auth/mfa/", "Set up or used their second factor"),
    ("POST", r"^/auth/invite/$", "Accepted an invite"),
    ("POST", r"^/api/v1/clients/$", "Created a client"),
    ("PATCH", rf"^/api/v1/clients/(?P<client>{UUID})/$", "Changed the details of {client}"),
    ("PUT", rf"^/api/v1/clients/(?P<client>{UUID})/$", "Changed the details of {client}"),
    ("DELETE", rf"^/api/v1/clients/(?P<client>{UUID})/$", "Deleted a client"),
    ("POST", rf"^/api/v1/clients/(?P<client>{UUID})/statements/upload/$", "Uploaded a statement for {client}"),
    ("POST", rf"^/api/v1/clients/(?P<client>{UUID})/approvals/$", "Approved entries for {client}"),
    ("POST", rf"^/api/v1/clients/(?P<client>{UUID})/review-queue/suggest/$", "Asked the model about {client}'s rows"),
    ("POST", rf"^/api/v1/clients/(?P<client>{UUID})/assistant/next-batch/$", "The assistant read a batch of {client}'s rows"),
    ("POST", rf"^/api/v1/clients/(?P<client>{UUID})/review-queue/recategorize/$", "Re-categorized {client}'s rows with the model"),
    ("POST", rf"^/api/v1/clients/(?P<client>{UUID})/ledgers/{UUID}/accept/$", "Accepted a proposed ledger for {client}"),
    ("POST", rf"^/api/v1/clients/(?P<client>{UUID})/ledgers/{UUID}/merge/$", "Merged a proposed ledger for {client}"),
    ("POST", rf"^/api/v1/clients/(?P<client>{UUID})/ledgers/{UUID}/reject/$", "Rejected a proposed ledger for {client}"),
    ("POST", rf"^/api/v1/clients/(?P<client>{UUID})/ledgers/$", "Added a ledger for {client}"),
    ("PATCH", rf"^/api/v1/clients/(?P<client>{UUID})/ledgers/{UUID}/$", "Changed a ledger for {client}"),
    ("DELETE", rf"^/api/v1/clients/(?P<client>{UUID})/ledgers/{UUID}/$", "Deleted a ledger for {client}"),
    ("POST", rf"^/api/v1/clients/(?P<client>{UUID})/parties/$", "Added a party for {client}"),
    ("PATCH", rf"^/api/v1/clients/(?P<client>{UUID})/parties/{UUID}/$", "Changed a party for {client}"),
    ("DELETE", rf"^/api/v1/clients/(?P<client>{UUID})/parties/{UUID}/$", "Deleted a party for {client}"),
    ("POST", rf"^/api/v1/clients/(?P<client>{UUID})/rules/$", "Wrote a rule for {client}"),
    ("PATCH", rf"^/api/v1/clients/(?P<client>{UUID})/rules/{UUID}/$", "Changed a rule for {client}"),
    ("DELETE", rf"^/api/v1/clients/(?P<client>{UUID})/rules/{UUID}/$", "Deleted a rule for {client}"),
    ("PATCH", rf"^/api/v1/clients/(?P<client>{UUID})/bank-accounts/{UUID}/$", "Renamed a bank ledger for {client}"),
    ("POST", rf"^/api/v1/clients/(?P<client>{UUID})/bank-accounts/{UUID}/opening-balance/$", "Set an opening balance for {client}"),
    ("POST", rf"^/api/v1/classifications/{UUID}/review/$", "Placed a transaction in a ledger"),
    ("POST", rf"^/api/v1/journal-entries/{UUID}/correct/$", "Corrected a posted entry"),
    ("POST", r"^/api/v1/team/members/$", "Invited someone to the firm"),
    ("PATCH", rf"^/api/v1/team/members/{UUID}/$", "Changed a team member"),
    ("PUT", rf"^/api/v1/team/clients/(?P<client>{UUID})/lead/$", "Changed {client}'s lead"),
    ("POST", rf"^/api/v1/team/clients/(?P<client>{UUID})/team/$", "Put someone on {client}"),
    ("DELETE", rf"^/api/v1/team/clients/(?P<client>{UUID})/team/{UUID}/$", "Took someone off {client}"),
    ("DELETE", rf"^/api/v1/team/invites/{UUID}/$", "Revoked an invite"),
    ("PATCH", r"^/api/v1/firm/$", "Renamed the firm"),
    ("POST", r"^/api/v1/firm/owner/$", "Transferred ownership of the firm"),
]
_COMPILED = [(m, re.compile(p), d) for m, p, d in ACTIONS]


def describe(method: str, path: str, clients: dict) -> tuple[str, str | None]:
    for m, pattern, text in _COMPILED:
        if m != method:
            continue
        match = pattern.match(path)
        if match:
            client_id = match.groupdict().get("client")
            name = clients.get(client_id.lower()) if client_id else None
            return text.replace("{client}", name or "a client"), client_id
    return f"{method} {path}", None


class AuditLogView(APIView):
    """GET /api/v1/audit/?user=<membership id>&client=<id>&from=YYYY-MM-DD&to=YYYY-MM-DD&failed=true"""

    permission_classes = [HasFirmPermission]
    required_permission = "audit.view"

    def get(self, request):
        firm_id = request.firm.pk
        rows = AuditLog.objects.filter(firm_id=firm_id).select_related("user").order_by("-created_at")
        params = request.query_params
        tz = timezone.get_current_timezone()

        def date(name):
            raw = params.get(name)
            if not raw:
                return None
            try:
                return datetime.date.fromisoformat(raw)
            except ValueError as exc:
                raise serializers.ValidationError({name: "Use YYYY-MM-DD."}) from exc

        if start := date("from"):
            rows = rows.filter(created_at__gte=datetime.datetime.combine(start, datetime.time.min, tzinfo=tz))
        if end := date("to"):
            rows = rows.filter(
                created_at__lt=datetime.datetime.combine(end + datetime.timedelta(days=1), datetime.time.min, tzinfo=tz)
            )
        if member := params.get("user"):
            m = FirmMembership.objects.filter(firm_id=firm_id, pk=_uuid(member, "user")).first()
            rows = rows.filter(user_id=m.user_id) if m else rows.none()
        if client := params.get("client"):
            rows = rows.filter(path__icontains=str(_uuid(client, "client")))
        if params.get("failed") == "true":
            rows = rows.filter(status_code__gte=400)

        paginator = DefaultPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        clients = {
            str(pk): name for pk, name in Client.objects.filter(firm_id=firm_id).values_list("pk", "name")
        }
        results = []
        for row in page:
            text, client_id = describe(row.method, row.path, clients)
            results.append(
                {
                    "id": str(row.pk),
                    "at": row.created_at,
                    "who": (row.user.full_name or row.user.email) if row.user else "Unknown",
                    "email": row.user.email if row.user else None,
                    "action": text,
                    "client_id": client_id,
                    "succeeded": row.status_code < 400,
                    "status_code": row.status_code,
                    "ip_address": row.ip_address,
                }
            )
        return paginator.get_paginated_response(results)


def _uuid(value: str, field: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError as exc:
        raise serializers.ValidationError({field: "Not an id."}) from exc
