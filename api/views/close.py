"""The close page: what stands between this client's books and sign-off."""

from __future__ import annotations

import datetime

from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response

from api.permissions import HasFirmPermission
from api.serializers.close import (
    CloseReportSerializer,
    ExplainSerializer,
    WithdrawSerializer,
    report_payload,
)
from core.access import get_visible_client
from ledger import close


@extend_schema(tags=["books"])
class CloseView(viewsets.GenericViewSet):
    """Every control and open item for a client, and the reasons given for the ones that may stand."""

    permission_classes = [HasFirmPermission]
    required_permission = {"GET": "journal.view", "POST": "books.sign_off"}
    serializer_class = CloseReportSerializer

    @extend_schema(
        summary="Close readiness",
        description=(
            "The controls (rows posted, assistant entries checked, nothing in Suspense, each bank account against its "
            "statement) and every open item, with whether it blocks sign-off and whether someone has explained it. "
            "Computed on request: a fixed item is simply not here."
        ),
        parameters=[OpenApiParameter("through", str, description="The date to report as at, YYYY-MM-DD. Default the latest entry.")],
        responses={200: CloseReportSerializer},
    )
    def retrieve(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        raw = request.query_params.get("through")
        through = None
        if raw:
            try:
                through = datetime.date.fromisoformat(raw)
            except ValueError as exc:
                raise serializers.ValidationError({"through": f"Not a date: {raw!r}. Send it as YYYY-MM-DD."}) from exc
        return Response(CloseReportSerializer(report_payload(close.close_report(client, through=through))).data)

    @extend_schema(
        summary="Explain an open item",
        description=(
            "Records why one open item may stand. It stays listed; sign-off stops waiting on it. Needs `books.sign_off`."
        ),
        request=ExplainSerializer,
        responses={200: CloseReportSerializer},
    )
    def explain(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        payload = ExplainSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        close.explain(client, payload.validated_data["item_key"], payload.validated_data["note"], membership=request.membership)
        return Response(CloseReportSerializer(report_payload(close.close_report(client))).data)

    @extend_schema(
        summary="Withdraw an explanation",
        request=WithdrawSerializer,
        responses={200: CloseReportSerializer},
    )
    def withdraw(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        payload = WithdrawSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        close.withdraw(client, payload.validated_data["item_key"], membership=request.membership)
        return Response(CloseReportSerializer(report_payload(close.close_report(client))).data, status=status.HTTP_200_OK)
