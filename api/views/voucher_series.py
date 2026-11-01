"""A client's own voucher types and number formats (voucher classes follow)."""

from __future__ import annotations

import datetime

from django.db import transaction
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import HasFirmPermission
from api.serializers.voucher_series import (
    CustomVoucherTypeSerializer,
    NumberingItemSerializer,
    VoucherClassSerializer,
)
from api.views.base import ClientScopedMixin, FirmScopedViewSet
from core.access import get_visible_client
from core.fy import financial_year
from ledger.models import (
    CustomVoucherType,
    NumberingFormat,
    VoucherClass,
    VoucherSequence,
    VoucherType,
)
from ledger.numbering import VoucherTypeInUseError, format_voucher_number, is_in_use, load_formats


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


@extend_schema(tags=["ledger"])
class NumberingView(APIView):
    """How each of the client's voucher series reads its numbers: a prefix and zero padding. The stored numbers never change."""

    permission_classes = [HasFirmPermission]
    required_permission = {"GET": "client.view", "PUT": "ledger.manage"}

    @staticmethod
    def _series(client) -> list[tuple[str, str]]:
        standard = [(vt, "") for vt, _label in VoucherType.choices]
        own = [(t.parent, t.name) for t in CustomVoucherType.objects.filter(firm_id=client.firm_id, client=client).order_by("name")]
        return standard + own

    def _payload(self, client, year: int) -> list[dict]:
        formats = load_formats(client)
        counters = {
            (s.voucher_type, s.type_name): s.next_number
            for s in VoucherSequence.objects.filter(firm_id=client.firm_id, client=client, financial_year=year)
        }
        out = []
        for voucher_type, type_name in self._series(client):
            fmt = formats.get((voucher_type, type_name))
            number = counters.get((voucher_type, type_name), 1)
            out.append(
                {
                    "voucher_type": voucher_type,
                    "type_name": type_name,
                    "prefix": fmt.prefix if fmt else "",
                    "padding": fmt.padding if fmt else 0,
                    "example": format_voucher_number(client, voucher_type, type_name, number, year, formats=formats),
                }
            )
        return out

    def _year(self, request) -> int:
        raw = request.query_params.get("fy")
        try:
            year = int(raw) if raw else financial_year(datetime.date.today())
        except ValueError as exc:
            raise ValidationError({"fy": "Give the financial year by its starting year, e.g. 2025."}) from exc
        if not 2000 <= year <= 2100:
            raise ValidationError({"fy": "Give the financial year by its starting year, e.g. 2025."})
        return year

    @extend_schema(
        summary="Number formats of every voucher series of the client",
        parameters=[OpenApiParameter("fy", OpenApiTypes.INT, description="Financial year (starting year) the example is for; default this year.")],
        responses={200: NumberingItemSerializer(many=True)},
    )
    def get(self, request, client_id):
        client = get_visible_client(request, client_id)
        return Response(self._payload(client, self._year(request)))

    @extend_schema(
        summary="Set the number formats of some series",
        description="A series sent with no prefix and no padding goes back to the plain number. Nothing is saved unless every item is allowed.",
        request=NumberingItemSerializer(many=True),
        responses={200: NumberingItemSerializer(many=True)},
    )
    def put(self, request, client_id):
        client = get_visible_client(request, client_id)
        payload = NumberingItemSerializer(data=request.data, many=True)
        payload.is_valid(raise_exception=True)
        known = set(self._series(client))
        for item in payload.validated_data:
            if (item["voucher_type"], item["type_name"]) not in known:
                raise ValidationError({"type_name": f"{item['type_name']!r} is not a voucher type of this client."})
        with transaction.atomic():
            for item in payload.validated_data:
                key = {"firm_id": client.firm_id, "client": client, "voucher_type": item["voucher_type"], "type_name": item["type_name"]}
                if not item["prefix"] and item["padding"] == 0:
                    NumberingFormat.objects.filter(**key).delete()
                else:
                    NumberingFormat.objects.update_or_create(**key, defaults={"prefix": item["prefix"], "padding": item["padding"]})
        return Response(self._payload(client, self._year(request)))


@extend_schema(tags=["ledger"])
class VoucherClassViewSet(ClientScopedMixin, FirmScopedViewSet):
    """Presets for sales and purchase vouchers: choosing one fills in the head ledger and the GST rate. Nothing posts differently."""

    queryset = VoucherClass.objects.select_related("head_ledger").order_by("name")
    serializer_class = VoucherClassSerializer
    required_permission = {
        "GET": "client.view",
        "POST": "ledger.manage",
        "PUT": "ledger.manage",
        "PATCH": "ledger.manage",
        "DELETE": "ledger.manage",
    }
