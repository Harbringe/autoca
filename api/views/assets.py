"""The asset register: register an asset from a purchase, sell it, and read the depreciation schedule for a year."""

from __future__ import annotations

import datetime

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.pagination import DefaultPagination
from api.permissions import CanApprove, HasFirmPermission
from api.serializers.assets import (
    AssetCreateSerializer,
    AssetSerializer,
    DepreciationStatusSerializer,
    DepreciationYearSerializer,
    DisposeSerializer,
    ScheduleSerializer,
    asset_payload,
    depreciation_payload,
    schedule_payload,
)
from api.views.base import ClientScopedMixin
from classify.models import LedgerAccount
from core.fy import financial_year
from ledger import assets
from ledger.models import Bill, FixedAsset


@extend_schema(tags=["assets"])
class AssetViewSet(
    ClientScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet
):
    """A client's fixed assets and what each is worth.

    An asset's cost comes from a purchase the books already hold, so the register and the ledger agree. Depreciation is
    computed from the asset's terms for whatever year is asked, never stored.
    """

    permission_classes = [HasFirmPermission]
    pagination_class = DefaultPagination
    required_permission = {"GET": "journal.view", "POST": "journal.approve", "DELETE": "journal.approve"}
    queryset = FixedAsset.objects.all()
    serializer_class = AssetSerializer

    def get_queryset(self):
        return super().get_queryset().filter(firm_id=self.request.firm.pk).select_related("ledger", "client")

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(AssetSerializer([asset_payload(a) for a in page], many=True).data)

    def retrieve(self, request, *args, **kwargs):
        return Response(AssetSerializer(asset_payload(self.get_object())).data)

    @extend_schema(
        summary="Register an asset",
        description=(
            "Needs `journal.approve`. With `bill`, the cost cannot exceed what that purchase put on the ledger and has not "
            "already been registered; a purchase of a fixed asset that is not registered is an open item."
        ),
        request=AssetCreateSerializer,
        responses={201: AssetSerializer},
    )
    def create(self, request, *args, **kwargs):
        payload = AssetCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        client = self.client
        ledger = get_object_or_404(LedgerAccount, pk=data["ledger"], firm_id=request.firm.pk, client=client)
        bill = (
            get_object_or_404(Bill, pk=data["bill"], firm_id=request.firm.pk, client=client) if data["bill"] else None
        )
        made = assets.register_asset(
            client,
            name=data["name"],
            ledger=ledger,
            bill=bill,
            cost_paise=data["cost_paise"],
            residual_paise=data["residual_paise"],
            put_to_use=data["put_to_use"],
            method=data["method"],
            life_years=data["life_years"],
            rate_bp=data["rate_bp"],
            membership=request.membership,
        )
        return Response(AssetSerializer(asset_payload(made)).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Record the sale of an asset", request=DisposeSerializer, responses={200: AssetSerializer})
    @action(detail=True, methods=["post"], url_path="dispose", permission_classes=[CanApprove])
    def dispose(self, request, client_id=None, pk=None):
        asset = self.get_object()
        payload = DisposeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        assets.dispose(
            asset,
            on=payload.validated_data["disposed_on"],
            proceeds_paise=payload.validated_data["proceeds_paise"],
            membership=request.membership,
        )
        return Response(AssetSerializer(asset_payload(self.get_object())).data)

    @extend_schema(summary="Remove an asset from the register", responses={204: None})
    @action(detail=True, methods=["post"], url_path="remove", permission_classes=[CanApprove])
    def remove(self, request, client_id=None, pk=None):
        assets.remove(self.get_object(), membership=request.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)

    def _year(self, request) -> int:
        raw = request.query_params.get("fy") or request.data.get("fy")
        try:
            return int(raw) if raw else financial_year(datetime.date.today())
        except (TypeError, ValueError) as exc:
            raise serializers.ValidationError({"fy": "A starting year, like 2025."}) from exc

    @extend_schema(
        summary="Is a year's depreciation booked?",
        parameters=[OpenApiParameter("fy", int, description="Starting year: 2025 is FY 2025-26. Default the current year.")],
        responses={200: DepreciationStatusSerializer},
    )
    @action(detail=False, methods=["get"], url_path="depreciation", pagination_class=None)
    def depreciation(self, request, client_id=None):
        status_ = assets.depreciation_status(self.client, self._year(request))
        return Response(DepreciationStatusSerializer(depreciation_payload(status_)).data)

    @extend_schema(
        summary="Book a year's depreciation",
        description=(
            "One journal entry dated 31 March: Dr Depreciation, Cr each asset's own ledger. Once per year. Refused inside "
            "sealed books. Needs `journal.approve`."
        ),
        request=DepreciationYearSerializer,
        responses={201: DepreciationStatusSerializer},
    )
    @depreciation.mapping.post
    def post_depreciation(self, request, client_id=None):
        payload = DepreciationYearSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        year = payload.validated_data.get("fy") or financial_year(datetime.date.today())
        assets.post_depreciation(self.client, year, membership=request.membership)
        return Response(
            DepreciationStatusSerializer(depreciation_payload(assets.depreciation_status(self.client, year))).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        summary="Take a year's depreciation out of the books",
        request=DepreciationYearSerializer,
        responses={200: DepreciationStatusSerializer},
    )
    @action(detail=False, methods=["post"], url_path="depreciation/remove", permission_classes=[CanApprove])
    def unpost_depreciation(self, request, client_id=None):
        payload = DepreciationYearSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        year = payload.validated_data.get("fy") or financial_year(datetime.date.today())
        assets.unpost_depreciation(self.client, year, membership=request.membership, note=payload.validated_data["note"])
        return Response(DepreciationStatusSerializer(depreciation_payload(assets.depreciation_status(self.client, year))).data)

    @extend_schema(
        summary="Depreciation schedule for a year",
        parameters=[OpenApiParameter("fy", int, description="Starting year: 2025 is FY 2025-26. Default the current year.")],
        responses={200: ScheduleSerializer},
    )
    @action(detail=False, methods=["get"], url_path="schedule", pagination_class=None)
    def schedule(self, request, client_id=None):
        raw = request.query_params.get("fy")
        try:
            year = int(raw) if raw else financial_year(datetime.date.today())
        except ValueError as exc:
            raise serializers.ValidationError({"fy": "A starting year, like 2025."}) from exc
        return Response(ScheduleSerializer(schedule_payload(year, assets.schedule(self.client, year))).data)
