"""The audit trail of one client's books: voucher changes and master changes in one list, newest first."""

from __future__ import annotations

import datetime
import uuid

from django.db.models import Q
from django.db.models.fields.json import KeyTextTransform
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import HasFirmPermission
from core.access import get_visible_client
from ledger.models import EntryChange, JournalEntry, MasterChange

DEFAULT_LIMIT, MAX_LIMIT = 50, 200
KINDS = ("ENTRY", "LEDGER", "PARTY", "RULE", "SETTING")


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


def _created_row(e: JournalEntry) -> dict:
    return {
        "id": f"created-{e.pk}", "at": e.created_at, "kind": "ENTRY", "action": "CREATED", "action_display": "Created",
        "label": f"{e.get_voucher_type_display()} no. {e.entry_no}, {e.entry_date:%d-%m-%Y}", "actor_name": _name(e.approved_by), "note": e.narration,
        "before": {}, "after": {"narration": e.narration, "total_paise": e.total_paise},
    }


def _removed_created_row(pk, entry_no, voucher_type, entry_date, narration, made) -> dict:
    """The creation of a voucher that has since been removed, from the snapshot its removal kept."""
    return {
        "id": f"made-{pk}", "at": made, "kind": "ENTRY", "action": "CREATED", "action_display": "Created",
        "label": f"{voucher_type} no. {entry_no}, {entry_date:%d-%m-%Y}", "actor_name": "", "note": narration,
        "before": {}, "after": {"narration": narration},
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
        # A voucher's creation is not a change row: it is the voucher itself, so the trail lists it from there.
        created = JournalEntry.objects.filter(firm_id=client.firm_id, client=client).select_related("approved_by")
        if kind == "ENTRY":
            masters = masters.none()
        elif kind:
            entries, masters, created = entries.none(), masters.filter(kind=kind), created.none()
        if actor:
            entries, masters, created = entries.filter(actor_id=actor), masters.filter(actor_id=actor), created.filter(approved_by_id=actor)
        if start:
            entries, masters, created = entries.filter(created_at__date__gte=start), masters.filter(created_at__date__gte=start), created.filter(created_at__date__gte=start)
        if end:
            entries, masters, created = entries.filter(created_at__date__lte=end), masters.filter(created_at__date__lte=end), created.filter(created_at__date__lte=end)
        if text:
            entries = entries.filter(Q(note__icontains=text) | Q(voucher_type__icontains=text))
            masters = masters.filter(Q(label__icontains=text))
            created = created.filter(Q(narration__icontains=text) | Q(voucher_type__icontains=text))

        # A voucher that has been removed is no longer there to read "created" from; the snapshot kept at its removal has it.
        made = []
        if kind in ("", "ENTRY") and not actor:
            gone = (
                EntryChange.objects.filter(firm_id=client.firm_id, client=client, action="REMOVED", before__has_key="created_at")
                .annotate(made=KeyTextTransform("created_at", "before"), said=KeyTextTransform("narration", "before"))
                .values_list("pk", "entry_no", "voucher_type", "entry_date", "said", "made")
            )
            for pk, entry_no, voucher_type, entry_date, said, when in gone:
                at = datetime.datetime.fromisoformat(when)
                if (start and at.date() < start) or (end and at.date() > end):
                    continue
                if text and text.lower() not in f"{said or ''} {voucher_type}".lower():
                    continue
                made.append(_removed_created_row(pk, entry_no, voucher_type, entry_date, said or "", at))

        window = offset + limit
        rows = (
            [_entry_row(c) for c in entries.order_by("-created_at")[:window]]
            + [_master_row(c) for c in masters.order_by("-created_at")[:window]]
            + [_created_row(c) for c in created.order_by("-created_at").prefetch_related("lines")[:window]]
            + made
        )
        rows.sort(key=lambda r: (r["at"], r["id"]), reverse=True)
        return Response({"count": entries.count() + masters.count() + created.count() + len(made), "results": AuditTrailRowSerializer(rows[offset:window], many=True).data})
