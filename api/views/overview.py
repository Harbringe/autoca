"""The firm overview: every visible client's stage in one request."""

from __future__ import annotations

from django.conf import settings
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import HasFirmPermission
from api.serializers.metrics import FirmMetricsSerializer
from api.serializers.overview import FirmOverviewSerializer
from ledger.metrics import firm_metrics
from ledger.overview import firm_overview


@extend_schema(tags=["clients"])
class FirmOverviewView(APIView):
    permission_classes = [HasFirmPermission]
    required_permission = "client.view"

    @extend_schema(
        summary="Where every client's books stand",
        description=(
            "One row for each client the caller may see (the same rule as the client list), "
            "with its stage, next step and what is waiting, plus firm totals and the number of "
            "clients in each stage. Computed with a fixed number of queries, so it costs the "
            "same for 5 clients as for 500. Stages, in order of precedence: `no_statements`, "
            "`needs_ledger`, `ready_to_post`, `in_review`, `ready_for_review`, `signed_off`."
        ),
        responses={200: FirmOverviewSerializer},
    )
    def get(self, request):
        return Response(FirmOverviewSerializer(firm_overview(request.membership)).data)


class MetricsQuery(serializers.Serializer):
    def get_fields(self):
        # `from` is a Python keyword, so it cannot be declared as a class attribute.
        fields = super().get_fields()
        fields["from"] = serializers.DateField(required=False)
        fields["to"] = serializers.DateField(required=False)
        return fields


@extend_schema(tags=["clients"])
class FirmMetricsView(APIView):
    permission_classes = [HasFirmPermission]
    required_permission = "team.view"

    @extend_schema(
        summary="Measured figures: automation, accuracy, time saved, what needs attention, turnaround",
        description=(
            "Figures computed only from data already stored, per client and for the firm, for "
            "`from` to `to` inclusive (ISO dates; default the current month up to today). A "
            "firm administrator gets every client; a senior CA the clients of their team; other "
            "roles get 403. Ratios are null, never 0, when there is nothing to divide. "
            "Nothing is a score and people are not ranked. `needs_attention` reflects where the "
            "books stand now, not the period."
        ),
        parameters=[
            OpenApiParameter("from", OpenApiTypes.DATE, description="First day, YYYY-MM-DD."),
            OpenApiParameter("to", OpenApiTypes.DATE, description="Last day, YYYY-MM-DD."),
        ],
        responses={200: FirmMetricsSerializer},
    )
    def get(self, request):
        today = timezone.localdate()
        query = MetricsQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        start = query.validated_data.get("from", today.replace(day=1))
        end = query.validated_data.get("to", today)
        if start > end:
            raise ValidationError({"from": "The start is after the end."})
        body = firm_metrics(request.membership, start, end, minutes_per_row=settings.ASSUMED_MINUTES_PER_ROW)
        return Response(FirmMetricsSerializer(body).data)
