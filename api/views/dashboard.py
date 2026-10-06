"""The reporting dashboards."""

from __future__ import annotations

import datetime

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import HasFirmPermission
from api.serializers.dashboard import ClientSnapshotSerializer, PortfolioSerializer
from core.access import get_visible_client
from ledger import dashboard


def _current_fy_year(today: datetime.date) -> int:
    return today.year if today.month >= 4 else today.year - 1


@extend_schema(tags=["clients"])
class PortfolioView(APIView):
    permission_classes = [HasFirmPermission]
    required_permission = "client.view"

    @extend_schema(
        summary="The firm portfolio: health of every client, what needs attention, what falls due",
        description=(
            "One row per client the caller may see, with books status, open items, unreconciled bank accounts, overdue TDS, "
            "receivables and payables; the things that need attention most serious first; and what falls due in the next "
            "45 days. Beyond 60 clients the per-client detail is left out (`detailed: false`)."
        ),
        responses={200: PortfolioSerializer},
    )
    def get(self, request):
        return Response(PortfolioSerializer(dashboard.portfolio(request.membership)).data)


@extend_schema(tags=["books"])
class ClientSnapshotView(APIView):
    permission_classes = [HasFirmPermission]
    required_permission = "journal.view"

    @extend_schema(
        summary="One client position and trend",
        description=(
            "Income, expense and profit by month for a financial year; the biggest expense heads; bank, card and loan "
            "balances; what customers owe and what is owed to suppliers (with the part over 90 days); GST and TDS "
            "balances; and where the books stand. Read from the journal, never stored."
        ),
        parameters=[
            OpenApiParameter(
                "fy",
                OpenApiTypes.INT,
                description="The year the financial year starts in. Default: the current one.",
            )
        ],
        responses={200: ClientSnapshotSerializer},
    )
    def get(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        raw = request.query_params.get("fy")
        try:
            year = int(raw) if raw else _current_fy_year(datetime.date.today())
        except ValueError as exc:
            raise serializers.ValidationError({"fy": f"Not a year: {raw!r}."}) from exc
        if not 2000 <= year <= 2100:
            raise serializers.ValidationError(
                {"fy": "Send the year the financial year starts in, like 2025."}
            )
        return Response(ClientSnapshotSerializer(dashboard.client_snapshot(client, year)).data)
