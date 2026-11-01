"""A client's own voucher types (and, as they arrive, number formats and voucher classes)."""

from __future__ import annotations

from drf_spectacular.utils import extend_schema

from api.serializers.voucher_series import CustomVoucherTypeSerializer
from api.views.base import ClientScopedMixin, FirmScopedViewSet
from ledger.models import CustomVoucherType
from ledger.numbering import VoucherTypeInUseError, is_in_use


@extend_schema(tags=["ledger"])
class CustomVoucherTypeViewSet(ClientScopedMixin, FirmScopedViewSet):
    """The voucher types a firm made up in Tally (or here): each posts as its parent and counts in a series of its own."""

    queryset = CustomVoucherType.objects.all().order_by("name")
    serializer_class = CustomVoucherTypeSerializer
    required_permission = {
        "GET": "client.view",
        "POST": "ledger.manage",
        "PUT": "ledger.manage",
        "PATCH": "ledger.manage",
        "DELETE": "ledger.manage",
    }

    def perform_destroy(self, instance):
        if is_in_use(instance):
            raise VoucherTypeInUseError("Vouchers are numbered under this type, so it cannot be removed.")
        instance.delete()
