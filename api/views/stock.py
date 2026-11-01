"""Opening stock and count adjustments: the stock movements no invoice carries."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.pagination import DefaultPagination
from api.permissions import CanApprove, HasFirmPermission
from api.serializers.stock import (
    StockEntryCreateSerializer,
    StockEntrySerializer,
    StockItemSerializer,
)
from api.views.base import ClientScopedMixin, FirmScopedViewSet
from api.views.master_audit import MasterAuditMixin
from ledger import stock
from ledger.audit import ITEM_FIELDS
from ledger.models import StockEntry, StockItem


@extend_schema(tags=["inventory"])
class StockEntryViewSet(ClientScopedMixin, mixins.ListModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """Opening stock and count adjustments. Purchases and sales move stock through their own invoice lines."""

    permission_classes = [HasFirmPermission]
    pagination_class = DefaultPagination
    required_permission = {"GET": "journal.view", "POST": "journal.approve"}
    queryset = StockEntry.objects.all()
    serializer_class = StockEntrySerializer

    def get_queryset(self):
        return super().get_queryset().filter(firm_id=self.request.firm.pk).order_by("-entry_date", "name")

    @extend_schema(summary="Record opening stock or a count adjustment", request=StockEntryCreateSerializer, responses={201: StockEntrySerializer})
    def create(self, request, *args, **kwargs):
        payload = StockEntryCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        made = stock.record(self.client, membership=request.membership, **payload.validated_data)
        return Response(StockEntrySerializer(made).data, status=status.HTTP_201_CREATED)

    @extend_schema(summary="Remove a stock entry", responses={204: None})
    @action(detail=True, methods=["post"], url_path="remove", permission_classes=[CanApprove])
    def remove(self, request, client_id=None, pk=None):
        stock.remove(self.get_object(), membership=request.membership)
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema(tags=["inventory"])
class StockItemViewSet(MasterAuditMixin, ClientScopedMixin, FirmScopedViewSet):
    """The client's stock items. Purchases and sales name them on their invoice lines; this is where they are kept tidy."""

    queryset = StockItem.objects.select_related("purchase_ledger", "sales_ledger").order_by("name")
    serializer_class = StockItemSerializer
    pagination_class = DefaultPagination
    audit_kind = "ITEM"
    audit_fields = ITEM_FIELDS
    required_permission = {"GET": "client.view", "POST": "ledger.manage", "PUT": "ledger.manage", "PATCH": "ledger.manage", "DELETE": "ledger.manage"}

    def audit_label(self, obj) -> str:
        return f"Stock item: {obj.name}"

