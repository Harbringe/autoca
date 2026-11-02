"""Cost centres, budgets, and the reports that read them."""

from __future__ import annotations

import datetime
import uuid

from django.db import transaction
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from api.pagination import DefaultPagination
from api.permissions import HasFirmPermission
from api.serializers.analysis import (
    BudgetSerializer,
    BudgetSetSerializer,
    BudgetVarianceSerializer,
    CostCentreReportSerializer,
    CostCentreSerializer,
    CostCentreTagsSerializer,
    TagRowSerializer,
)
from api.views.base import ClientScopedMixin, FirmScopedViewSet
from api.views.master_audit import MasterAuditMixin
from classify.models import LedgerAccount
from ledger import analysis
from ledger.audit import CENTRE_FIELDS, record_master_change
from ledger.models import Budget, CostCentre, CostCentreTag, JournalLine
from ledger.reports import PROFIT_AND_LOSS_GROUPS

FY = OpenApiParameter("fy", int, description="The calendar year the financial year starts in (2025 for 2025-26).")


def _fy(request) -> int:
    try:
        return int(request.query_params["fy"])
    except (KeyError, ValueError):
        raise ValidationError({"fy": "Give fy, the year the financial year starts."}) from None


@extend_schema(tags=["analysis"])
class CostCentreViewSet(MasterAuditMixin, ClientScopedMixin, FirmScopedViewSet):
    """The client's cost centres. One with lines tagged to it cannot be removed."""

    queryset = CostCentre.objects.order_by("name")
    serializer_class = CostCentreSerializer
    pagination_class = DefaultPagination
    audit_kind = "CENTRE"
    audit_fields = CENTRE_FIELDS
    required_permission = {"GET": "client.view", "POST": "ledger.manage", "PUT": "ledger.manage", "PATCH": "ledger.manage", "DELETE": "ledger.manage"}

    def audit_label(self, obj) -> str:
        return f"Cost centre: {obj.name}"

    def perform_destroy(self, instance):
        if instance.tags.exists():
            raise ValidationError({"detail": "Lines are tagged to this cost centre. Clear those first."})
        super().perform_destroy(instance)


@extend_schema(tags=["analysis"])
class CostCentreTagViewSet(ClientScopedMixin, viewsets.GenericViewSet):
    """Which cost centres a journal line belongs to. Reads from an entry; writes replace one line's split."""

    permission_classes = [HasFirmPermission]
    required_permission = {"GET": "journal.view", "POST": "journal.approve"}
    queryset = CostCentreTag.objects.all()
    serializer_class = TagRowSerializer

    @extend_schema(
        summary="Cost centre tags on an entry's lines",
        parameters=[OpenApiParameter("entry", OpenApiTypes.UUID, required=True)],
        responses=TagRowSerializer(many=True),
    )
    def list(self, request, client_id=None):
        try:
            entry = uuid.UUID(request.query_params.get("entry", ""))
        except ValueError:
            raise ValidationError({"entry": "Give the entry's id."}) from None
        tags = CostCentreTag.objects.filter(firm_id=request.firm.pk, client=self.client, line__entry_id=entry).select_related("cost_centre")
        rows = [{"line": t.line_id, "cost_centre": t.cost_centre_id, "cost_centre_name": t.cost_centre.name, "amount_paise": t.amount_paise} for t in tags]
        return Response(TagRowSerializer(rows, many=True).data)

    @extend_schema(
        summary="Split a journal line across cost centres",
        description=(
            "Replaces the line's cost centres with the ones sent; an empty list clears them. Only income and expense lines can be tagged, "
            "the amounts together cannot exceed the line, and what is not tagged stays unallocated. The books are not changed."
        ),
        request=CostCentreTagsSerializer,
        responses=TagRowSerializer(many=True),
    )
    def create(self, request, client_id=None):
        body = CostCentreTagsSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        line = JournalLine.objects.filter(firm_id=request.firm.pk, entry__client=self.client, pk=data["line"]).select_related("ledger_account").first()
        if line is None:
            raise NotFound("No such journal line for this client.")
        if line.ledger_account.group not in PROFIT_AND_LOSS_GROUPS:
            raise ValidationError({"line": "Only income and expense lines can be tagged to a cost centre."})
        ids = [a["cost_centre"] for a in data["allocations"]]
        if len(set(ids)) != len(ids):
            raise ValidationError({"allocations": "Name each cost centre once."})
        found = {c.pk: c for c in CostCentre.objects.filter(firm_id=request.firm.pk, client=self.client, pk__in=ids)}
        if len(found) != len(ids):
            raise ValidationError({"allocations": "A cost centre is not this client's."})
        if sum(a["amount_paise"] for a in data["allocations"]) > line.amount_paise:
            raise ValidationError({"allocations": "The amounts together are more than the line."})
        with transaction.atomic():
            CostCentreTag.objects.filter(firm_id=request.firm.pk, line=line).delete()
            for a in data["allocations"]:
                CostCentreTag.objects.create(firm_id=request.firm.pk, client=self.client, line=line, cost_centre=found[a["cost_centre"]], amount_paise=a["amount_paise"])
        tags = CostCentreTag.objects.filter(firm_id=request.firm.pk, line=line).select_related("cost_centre")
        rows = [{"line": t.line_id, "cost_centre": t.cost_centre_id, "cost_centre_name": t.cost_centre.name, "amount_paise": t.amount_paise} for t in tags]
        return Response(TagRowSerializer(rows, many=True).data, status=201)


@extend_schema(tags=["analysis"])
class BudgetViewSet(ClientScopedMixin, viewsets.GenericViewSet):
    """What each ledger is expected to come to, month by month."""

    permission_classes = [HasFirmPermission]
    required_permission = {"GET": "report.view", "PUT": "ledger.manage"}
    queryset = Budget.objects.all()
    serializer_class = BudgetSerializer

    @extend_schema(summary="The year's budgets", parameters=[FY], responses=BudgetSerializer(many=True))
    def list(self, request, client_id=None):
        return Response(BudgetSerializer(analysis.budgets_for(self.client, _fy(request)), many=True).data)

    @extend_schema(
        summary="Set a ledger's budget for a year",
        description="An amount for each month named (whole paise); null clears a month, a month left out is kept. Recorded in the audit trail.",
        request=BudgetSetSerializer,
        responses=BudgetSerializer(many=True),
    )
    @action(detail=False, methods=["put"], url_path="set")
    def set_budget(self, request, client_id=None):
        body = BudgetSetSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        ledger = LedgerAccount.objects.filter(firm_id=request.firm.pk, client=self.client, pk=data["ledger"]).first()
        if ledger is None:
            raise NotFound("No such ledger for this client.")
        fy = data["fy"]
        wanted = {}
        for month, amount in data["months"].items():
            try:
                day = datetime.date.fromisoformat(f"{month}-01")
            except ValueError:
                raise ValidationError({"months": f"{month} is not a month (YYYY-MM)."}) from None
            if (day.year if day.month >= 4 else day.year - 1) != fy:
                raise ValidationError({"months": f"{month} is not in the financial year starting {fy}."})
            wanted[day] = amount
        before = {d.strftime("%Y-%m"): b.amount_paise for d, b in ((b.period, b) for b in Budget.objects.filter(firm_id=request.firm.pk, client=self.client, ledger=ledger))}
        with transaction.atomic():
            for day, amount in wanted.items():
                if amount is None:
                    Budget.objects.filter(firm_id=request.firm.pk, client=self.client, ledger=ledger, period=day).delete()
                else:
                    Budget.objects.update_or_create(firm_id=request.firm.pk, client=self.client, ledger=ledger, period=day, defaults={"amount_paise": amount})
        after = {d.strftime("%Y-%m"): b.amount_paise for d, b in ((b.period, b) for b in Budget.objects.filter(firm_id=request.firm.pk, client=self.client, ledger=ledger))}
        record_master_change(
            self.client, "BUDGET", ledger.pk, "EDITED", label=f"Budget: {ledger.name} ({fy}-{str(fy + 1)[2:]})",
            before=before, after=after, actor=request.user,
        )
        return Response(BudgetSerializer(analysis.budgets_for(self.client, fy), many=True).data)

    @extend_schema(
        summary="Budget against the books",
        description="Each budgeted ledger month by month: the budget, what the books show and the difference. `through` (YYYY-MM) limits the year-to-date totals.",
        parameters=[FY, OpenApiParameter("through", OpenApiTypes.STR)],
        responses=BudgetVarianceSerializer,
    )
    @action(detail=False, methods=["get"], url_path="variance")
    def variance(self, request, client_id=None):
        through = request.query_params.get("through") or None
        if through is not None:
            try:
                datetime.date.fromisoformat(f"{through}-01")
            except ValueError:
                raise serializers.ValidationError({"through": "A month as YYYY-MM."}) from None
        return Response(BudgetVarianceSerializer(analysis.budget_variance(self.client, _fy(request), through=through)).data)


@extend_schema(tags=["analysis"])
class CostCentreReportViewSet(ClientScopedMixin, viewsets.GenericViewSet):
    permission_classes = [HasFirmPermission]
    required_permission = "report.view"
    queryset = CostCentre.objects.all()
    serializer_class = CostCentreReportSerializer

    @extend_schema(
        summary="Income and expense by cost centre",
        description="From the journal lines tagged to each centre, with what is not tagged yet. Read from the books; nothing is written.",
        parameters=[FY],
        responses=CostCentreReportSerializer,
    )
    def list(self, request, client_id=None):
        return Response(CostCentreReportSerializer(analysis.cost_centre_report(self.client, _fy(request))).data)
