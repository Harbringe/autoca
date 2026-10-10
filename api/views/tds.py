"""TDS: the position by section and month, and recording the challan for a deposit."""

from __future__ import annotations

import datetime

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.pagination import DefaultPagination
from api.permissions import CanApprove, HasFirmPermission
from api.serializers.tds import (
    ChallanCreateSerializer,
    ChallanSerializer,
    SalaryReturnSerializer,
    TdsReturnSerializer,
    TdsSummarySerializer,
    return_payload,
    salary_return_payload,
    summary_payload,
)
from api.views.base import ClientScopedMixin
from ledger import tds, tds_return, tds_salary_return
from ledger.models import JournalEntry, TdsChallan


@extend_schema(tags=["tds"])
class TdsChallanViewSet(ClientScopedMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """The challans recorded for a client's TDS deposits."""

    permission_classes = [HasFirmPermission]
    pagination_class = DefaultPagination
    required_permission = {"GET": "journal.view", "POST": "journal.approve"}
    queryset = TdsChallan.objects.all()
    serializer_class = ChallanSerializer

    def get_queryset(self):
        return super().get_queryset().filter(firm_id=self.request.firm.pk).order_by("-paid_on")

    @extend_schema(
        summary="TDS deducted, deposited and due, by section and month",
        responses={200: TdsSummarySerializer},
    )
    @action(detail=False, methods=["get"], url_path="summary", pagination_class=None)
    def summary(self, request, client_id=None):
        payload = summary_payload(tds.position(self.client), tds.payments_without_challan(self.client), datetime.date.today())
        return Response(TdsSummarySerializer(payload).data)

    def _pack(self, request):
        try:
            year, quarter = int(request.query_params["fy"]), int(request.query_params["quarter"])
        except (KeyError, ValueError):
            raise serializers.ValidationError({"detail": "Give fy (the year the financial year starts) and quarter (1 to 4)."}) from None
        return tds_return.build(self.client, year, quarter)

    _PARAMS = [
        OpenApiParameter("fy", int, description="The calendar year the financial year starts in (2025 for 2025-26)."),
        OpenApiParameter("quarter", int, description="1 is April to June."),
    ]

    @extend_schema(
        summary="The data a quarter's TDS return (Form 26Q) is filed from",
        description=(
            "Deductees, challans and the things to look at: a deductee with no PAN, a late deposit, a late return. "
            "Read from the books; nothing is filed. Interest and fee are estimates."
        ),
        parameters=_PARAMS,
        responses={200: TdsReturnSerializer},
    )
    @action(detail=False, methods=["get"], url_path="return", pagination_class=None)
    def tds_return(self, request, client_id=None):
        return Response(TdsReturnSerializer(return_payload(self._pack(request))).data)

    def _salary_pack(self, request):
        try:
            year, quarter = int(request.query_params["fy"]), int(request.query_params["quarter"])
        except (KeyError, ValueError):
            raise serializers.ValidationError({"detail": "Give fy (the year the financial year starts) and quarter (1 to 4)."}) from None
        return tds_salary_return.build(self.client, year, quarter)

    @extend_schema(
        summary="The data a quarter's salary TDS return (Form 24Q) is filed from",
        description="Employees with gross and TDS under section 192, the challans, and late deposits. Read from payroll runs; nothing is filed.",
        parameters=_PARAMS,
        responses={200: SalaryReturnSerializer},
    )
    @action(detail=False, methods=["get"], url_path="salary-return", pagination_class=None)
    def salary_return(self, request, client_id=None):
        return Response(SalaryReturnSerializer(salary_return_payload(self._salary_pack(request))).data)

    @extend_schema(
        summary="The quarter's salary TDS return data as an Excel file",
        parameters=_PARAMS,
        responses={(200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): bytes},
    )
    @action(detail=False, methods=["get"], url_path="salary-return/export", pagination_class=None)
    def salary_return_export(self, request, client_id=None):
        pack = self._salary_pack(request)
        response = HttpResponse(
            tds_salary_return.workbook(self.client, pack),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="tds-24Q-FY{pack.financial_year}-Q{pack.quarter}.xlsx"'
        return response

    @extend_schema(
        summary="The quarter's TDS return data as an Excel file",
        parameters=_PARAMS,
        responses={(200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): bytes},
    )
    @action(detail=False, methods=["get"], url_path="return/export", pagination_class=None)
    def tds_return_export(self, request, client_id=None):
        pack = self._pack(request)
        response = HttpResponse(
            tds_return.workbook(self.client, pack),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="tds-26Q-FY{pack.financial_year}-Q{pack.quarter}.xlsx"'
        return response

    @extend_schema(
        summary="Record the challan for a deposit",
        description=(
            "Says which section a payment to TDS Payable was for and its BSR code and serial. One challan per payment. "
            "Needs `journal.approve`."
        ),
        request=ChallanCreateSerializer,
        responses={201: ChallanSerializer},
    )
    def create(self, request, *args, **kwargs):
        payload = ChallanCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        entry = get_object_or_404(JournalEntry, pk=data["entry"], firm_id=request.firm.pk, client=self.client)
        made = tds.record_challan(
            self.client, entry, section=data["section"], bsr_code=data["bsr_code"], serial=data["serial"],
            paid_on=data["paid_on"], membership=request.membership,
        )
        return Response(ChallanSerializer(made).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Remove a challan record", responses={204: None})
    @action(detail=True, methods=["post"], url_path="remove", permission_classes=[CanApprove])
    def remove(self, request, client_id=None, pk=None):
        tds.remove_challan(self.get_object(), membership=request.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)
