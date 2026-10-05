"""Outstanding payables and receivables, as at a date."""

from __future__ import annotations

import datetime

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.response import Response

from api.permissions import HasFirmPermission
from api.serializers.openitems import OpenItemsSerializer, open_items_payload
from api.serializers.partyreports import OutstandingSerializer, outstanding_payload
from core.access import get_visible_client
from ledger import openitems
from ledger.partyreports import PAYABLES, RECEIVABLES, outstanding


def date_param(request, name: str, default: datetime.date) -> datetime.date:
    """A query-string date as YYYY-MM-DD, or ``default`` when absent. Anything else is a 400 that says what to send."""
    raw = request.query_params.get(name)
    if not raw:
        return default
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError as exc:
        raise serializers.ValidationError({name: f"Not a date: {raw!r}. Send it as YYYY-MM-DD."}) from exc


@extend_schema(tags=["reports"])
class OpenItemsView(viewsets.GenericViewSet):
    """Everything that does not yet tie out for a client, as one list, oldest first.

    Each kind of document registers what can be left unmatched about it (see ``ledger.openitems``), so a new document type
    adds items here without adding a report. Computed on request: an item that has been fixed is simply not there.
    """

    permission_classes = [HasFirmPermission]
    required_permission = "journal.view"
    serializer_class = OpenItemsSerializer

    @extend_schema(
        summary="Open items",
        parameters=[OpenApiParameter("kind", str, description="Only this kind. See `kinds` in the response for the names.")],
        responses={200: OpenItemsSerializer},
    )
    def retrieve(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        titles = openitems.kinds()
        kind = request.query_params.get("kind")
        if kind and kind not in titles:
            raise serializers.ValidationError({"kind": f"Not a kind of open item. Choose one of: {', '.join(titles)}."})
        everything = openitems.open_items(client)
        shown = [item for item in everything if not kind or item.kind == kind]
        payload = open_items_payload(shown, titles, datetime.date.today())
        # The counts are for everything, so a filtered view still shows how much else is open.
        payload["count"] = len(everything)
        counts: dict[str, int] = {}
        for item in everything:
            counts[item.kind] = counts.get(item.kind, 0) + 1
        payload["kinds"] = [{"kind": k, "title": t, "count": counts.get(k, 0)} for k, t in titles.items()]
        return Response(OpenItemsSerializer(payload).data)


@extend_schema(tags=["reports"])
class OutstandingView(viewsets.GenericViewSet):
    """What the client owes its suppliers, or its customers owe it, bill by bill, aged.

    Worked out as at the date asked for, counting only the settlements that had happened by then, so last month's report
    stays what it was. Read from the same bills and allocations the party's ledger is checked against.
    """

    permission_classes = [HasFirmPermission]
    required_permission = "report.view"
    serializer_class = OutstandingSerializer

    @extend_schema(
        summary="Outstanding payables or receivables, aged",
        parameters=[
            OpenApiParameter("side", str, enum=[PAYABLES, RECEIVABLES], description="Whom: suppliers or customers. Default payables."),
            OpenApiParameter("as_of", str, description="The report date, as YYYY-MM-DD. Default today."),
        ],
        responses={200: OutstandingSerializer},
    )
    def retrieve(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        side = request.query_params.get("side", PAYABLES)
        if side not in (PAYABLES, RECEIVABLES):
            raise serializers.ValidationError({"side": f"Send {PAYABLES!r} or {RECEIVABLES!r}."})
        as_of = date_param(request, "as_of", datetime.date.today())
        return Response(OutstandingSerializer(outstanding_payload(outstanding(client, as_of, side))).data)
