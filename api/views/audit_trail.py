"""The audit trail of one client's books: voucher changes and master changes in one list, newest first."""

from __future__ import annotations

import datetime
import uuid

from django.db.models import Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import HasFirmPermission
from core.access import get_visible_client
from ledger.models import EntryChange, MasterChange

DEFAULT_LIMIT, MAX_LIMIT = 50, 200
KINDS = ("ENTRY", "LEDGER", "PARTY", "RULE")


class AuditTrailRowSerializer(serializers.Serializer):
    id = serializers.CharField()
    at = serializers.DateTimeField()
    kind = serializers.ChoiceField(choices=KINDS)
    action = serializers.CharField()
    action_display = serializers.CharField()
    label = serializers.CharField(help_text="The voucher, ledger, party or rule it was about, as it was named then.")
    actor_name = serializers.CharField(help_text="Empty when the change was the assistant's own.")
    note = serializers.CharField()
    before = serializers.JSONField()
    after = serializers.JSONField()


class AuditTrailPageSerializer(serializers.Serializer):
    count = serializers.IntegerField()
    results = AuditTrailRowSerializer(many=True)


def _name(user) -> str:
    return (user.full_name or user.email) if user else ""


def _entry_row(c: EntryChange) -> dict:
    return {
        "id": str(c.pk), "at": c.created_at, "kind": "ENTRY", "action": c.action, "action_display": c.get_action_display(),
        "label": f"{c.voucher_type} no. {c.entry_no}, {c.entry_date:%d-%m-%Y}", "actor_name": _name(c.actor), "note": c.note,
        "before": c.before, "after": c.after,
    }


def _master_row(c: MasterChange) -> dict:
    return {
        "id": str(c.pk), "at": c.created_at, "kind": c.kind, "action": c.action, "action_display": c.get_action_display(),
        "label": c.label, "actor_name": _name(c.actor), "note": "", "before": c.before, "after": c.after,
    }


def _date(request, name: str):
    raw = request.query_params.get(name)
    if not raw:
        return None
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError as exc:
        raise ValidationError({name: "Give a date like 2025-04-01."}) from exc


@extend_schema(tags=["ledger"])
class AuditTrailView(APIView):
    permission_classes = [HasFirmPermission]
    required_permission = "report.view"

    @extend_schema(
        summary="The audit trail of the client's books",
        description="Changes to vouchers and to ledgers, parties and rules, newest first, each with what it was before and after.",
        parameters=[
            OpenApiParameter("kind", OpenApiTypes.STR, enum=list(KINDS)),
            OpenApiParameter("actor", OpenApiTypes.UUID, description="Only this person's changes."),
            OpenApiParameter("from", OpenApiTypes.DATE),
            OpenApiParameter("to", OpenApiTypes.DATE),
            OpenApiParameter("q", OpenApiTypes.STR, description="Text in the label or the note."),
            OpenApiParameter("limit", OpenApiTypes.INT),
            OpenApiParameter("offset", OpenApiTypes.INT),
        ],
        responses={200: AuditTrailPageSerializer},
    )
    def get(self, request, client_id):
        client = get_visible_client(request, client_id)
        params = request.query_params
        kind = params.get("kind", "")
        if kind and kind not in KINDS:
            raise ValidationError({"kind": f"One of {', '.join(KINDS)}."})
        try:
            actor = uuid.UUID(params["actor"]) if params.get("actor") else None
            limit = min(max(int(params.get("limit", DEFAULT_LIMIT)), 1), MAX_LIMIT)
            offset = max(int(params.get("offset", 0)), 0)
        except ValueError as exc:
            raise ValidationError({"detail": "actor must be an id; limit and offset must be numbers."}) from exc
        start, end, text = _date(request, "from"), _date(request, "to"), params.get("q", "").strip()

        entries = EntryChange.objects.filter(firm_id=client.firm_id, client=client).select_related("actor")
        masters = MasterChange.objects.filter(firm_id=client.firm_id, client=client).select_related("actor")
        if kind == "ENTRY":
            masters = masters.none()
        elif kind:
            entries, masters = entries.none(), masters.filter(kind=kind)
        if actor:
            entries, masters = entries.filter(actor_id=actor), masters.filter(actor_id=actor)
        if start:
            entries, masters = entries.filter(created_at__date__gte=start), masters.filter(created_at__date__gte=start)
        if end:
            entries, masters = entries.filter(created_at__date__lte=end), masters.filter(created_at__date__lte=end)
        if text:
            entries = entries.filter(Q(note__icontains=text) | Q(voucher_type__icontains=text))
            masters = masters.filter(Q(label__icontains=text))

        window = offset + limit
        rows = [_entry_row(c) for c in entries.order_by("-created_at")[:window]] + [_master_row(c) for c in masters.order_by("-created_at")[:window]]
        rows.sort(key=lambda r: (r["at"], r["id"]), reverse=True)
        return Response({"count": entries.count() + masters.count(), "results": AuditTrailRowSerializer(rows[offset:window], many=True).data})
