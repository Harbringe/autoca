"""TDS: the position by section and month, and recording the challan for a deposit."""

from __future__ import annotations

import datetime

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.pagination import DefaultPagination
from api.permissions import CanApprove, HasFirmPermission
from api.serializers.tds import (
    ChallanCreateSerializer,
    ChallanSerializer,
    TdsSummarySerializer,
    summary_payload,
)
from api.views.base import ClientScopedMixin
from ledger import tds
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
