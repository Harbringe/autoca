"""Work counts for the dashboards."""

from __future__ import annotations

import datetime

from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import HasFirmPermission, IsFirmMember
from api.serializers.workload import MyWorkSerializer, PeopleWorkSerializer, WorkFlowSerializer
from core.rbac import has_permission
from ledger import workload
from ledger.workload import MAX_DAYS, week_start

_FROM = OpenApiParameter("from", OpenApiTypes.DATE, description="First day, YYYY-MM-DD.")
_TO = OpenApiParameter("to", OpenApiTypes.DATE, description="Last day, YYYY-MM-DD.")


class PeriodQuery(serializers.Serializer):
    scope = serializers.ChoiceField(choices=["firm", "team"], required=False)

    def get_fields(self):
        # `from` is a Python keyword, so it cannot be declared as a class attribute.
        fields = super().get_fields()
        fields["from"] = serializers.DateField(required=False)
        fields["to"] = serializers.DateField(required=False)
        return fields


def _period(request, default_start: datetime.date, today: datetime.date):
    query = PeriodQuery(data=request.query_params)
    query.is_valid(raise_exception=True)
    start = query.validated_data.get("from", default_start)
    end = query.validated_data.get("to", today)
    if start > end:
        raise serializers.ValidationError({"from": "The start is after the end."})
    if (end - start).days + 1 > MAX_DAYS:
        raise serializers.ValidationError({"to": f"Ask for at most {MAX_DAYS} days at a time."})
    return start, end


@extend_schema(tags=["clients"])
class WorkFlowView(APIView):
    permission_classes = [HasFirmPermission]
    required_permission = "client.view"

    @extend_schema(
        summary="Work received against work finished, week by week",
        description=(
            "Per week (Monday dates): bank statement rows received (by when their statement was uploaded) and journal "
            "entries finished (posted or approved, corrections not counted), plus the totals for the period and for the "
            "period of equal length immediately before it. Covers the clients the caller may see, enforced by the server: "
            "a firm administrator, or anyone who sees every client, gets the firm (`scope: firm`); everyone else gets "
            "their own clients (`scope: team`) whatever `scope` they ask for. Default period: the last 12 weeks. At most "
            "366 days."
        ),
        parameters=[
            _FROM,
            _TO,
            OpenApiParameter(
                "scope",
                OpenApiTypes.STR,
                enum=["firm", "team"],
                description="Accepted for clarity; the server decides the scope from the caller.",
            ),
        ],
        responses={200: WorkFlowSerializer},
    )
    def get(self, request):
        today = timezone.localdate()
        start, end = _period(request, week_start(today) - datetime.timedelta(weeks=11), today)
        return Response(WorkFlowSerializer(workload.work_flow(request.membership, start, end)).data)


@extend_schema(tags=["clients"])
class PeopleWorkView(APIView):
    permission_classes = [HasFirmPermission]
    required_permission = "team.view"

    @extend_schema(
        summary="What each person has on: counts of work, alphabetical, never a rank",
        description=(
            "One row per active member the caller may see: a firm administrator sees everyone, a Senior CA themselves and "
            "their team; Staff and Read-only get 403. Each count says what it counts in its own description. These are "
            "counts of work, not a rating of people. `open_items`, `overdue` and `waiting_on_others` are as things stand "
            "now; `finished_in_period` follows `from` and `to` (default: this month so far). At most 366 days."
        ),
        parameters=[_FROM, _TO],
        responses={200: PeopleWorkSerializer},
    )
    def get(self, request):
        today = timezone.localdate()
        start, end = _period(request, today.replace(day=1), today)
        body = workload.people(
            request.membership,
            start,
            end,
            today,
            include_money=has_permission(request.membership, "journal.view"),
        )
        return Response(PeopleWorkSerializer(body).data)


@extend_schema(tags=["clients"])
class MyWorkView(APIView):
    permission_classes = [IsFirmMember]

    @extend_schema(
        summary="The signed-in member's own work",
        description=(
            "Own data only. The clients the member is assigned to or leads, what is open and overdue on them right now, "
            "what the member finished each day of the period (default: this month so far; at most 366 days), and up to "
            "8 next tasks, overdue first, built from the same alerts the bell shows."
        ),
        parameters=[_FROM, _TO],
        responses={200: MyWorkSerializer},
    )
    def get(self, request):
        today = timezone.localdate()
        start, end = _period(request, today.replace(day=1), today)
        body = workload.me_work(
            request.membership,
            start,
            end,
            today,
            include_money=has_permission(request.membership, "journal.view"),
        )
        return Response(MyWorkSerializer(body).data)
