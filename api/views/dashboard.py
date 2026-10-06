"""The reporting dashboards."""

from __future__ import annotations

import datetime

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import HasFirmPermission
from api.serializers.dashboard import (
    AlertFeedSerializer,
    ClientSnapshotSerializer,
    PortfolioSerializer,
)
from core.access import get_visible_client
from core.rbac import has_permission
from ledger import alerts as alerts_mod
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
            "45 days. Amounts (receivables, payables, TDS) are left out for a caller without `journal.view`. Beyond 60 clients the per-client detail is left out (`detailed: false`)."
        ),
        responses={200: PortfolioSerializer},
    )
    def get(self, request):
        return Response(
            PortfolioSerializer(
                dashboard.portfolio(
                    request.membership,
                    include_money=has_permission(request.membership, "journal.view"),
                )
            ).data
        )


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


def _feed(alerts, module):
    counts = alerts_mod.summarise(alerts)
    shown = [a for a in alerts if a.module == module] if module else alerts
    return Response(AlertFeedSerializer({"counts": counts, "alerts": shown}).data)


def _module(request):
    value = request.query_params.get("module")
    if value and value not in alerts_mod.MODULES:
        raise serializers.ValidationError(
            {"module": f"Use one of: {', '.join(alerts_mod.MODULES)}."}
        )
    return value


@extend_schema(tags=["clients"])
class FirmAlertsView(APIView):
    permission_classes = [HasFirmPermission]
    required_permission = "client.view"

    @extend_schema(
        summary="Alerts across every client the caller may see",
        description=(
            "Everything that wants a person, most serious first. Each alert names its module and carries `to` and `search`, "
            "which open the screen where it is fixed. `counts` always covers all modules, so a badge can show the total "
            "while `module` narrows the list. Computed on request: a fixed problem is simply gone. Amounts are left out "
            "(and so are TDS alerts) for a caller without `journal.view`."
        ),
        parameters=[
            OpenApiParameter(
                "module",
                OpenApiTypes.STR,
                description="Only this module: bank, bookkeeping, reports, gst or documents.",
            )
        ],
        responses={200: AlertFeedSerializer},
    )
    def get(self, request):
        module = _module(request)
        alerts = alerts_mod.firm_alerts(
            request.membership, include_money=has_permission(request.membership, "journal.view")
        )
        return _feed(alerts, module)


@extend_schema(tags=["clients"])
class ClientAlertsView(APIView):
    permission_classes = [HasFirmPermission]
    required_permission = "client.view"

    @extend_schema(
        summary="Alerts for one client",
        description="The same alerts as the firm feed, for one client.",
        parameters=[
            OpenApiParameter(
                "module",
                OpenApiTypes.STR,
                description="Only this module: bank, bookkeeping, reports, gst or documents.",
            )
        ],
        responses={200: AlertFeedSerializer},
    )
    def get(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        module = _module(request)
        alerts = alerts_mod.client_alerts_for(
            request.membership,
            client,
            include_money=has_permission(request.membership, "journal.view"),
        )
        return _feed(alerts, module)
