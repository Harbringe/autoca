"""Bills of materials, and production runs that make finished goods from components."""

from __future__ import annotations

import datetime
from decimal import Decimal

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from api.pagination import DefaultPagination
from api.serializers.manufacturing import (
    BomSerializer,
    ProduceSerializer,
    RunPlanSerializer,
    decimal_text,
)
from api.serializers.stock import StockEntrySerializer
from api.views.base import ClientScopedMixin, FirmScopedViewSet
from api.views.master_audit import MasterAuditMixin
from ledger import manufacturing
from ledger.audit import BOM_FIELDS
from ledger.models import BillOfMaterials, Godown
from ledger.stock import StockError


def _godown(request, client, value):
    if not value:
        return None
    found = Godown.objects.filter(firm_id=request.firm.pk, client=client, pk=value).first()
    if found is None:
        raise NotFound("No such godown for this client.")
    return found


def _plan_payload(worked: dict) -> dict:
    return {
        "quantity": decimal_text(worked["quantity"]),
        "components": [
            {"name": r["name"], "unit": r["unit"], "needed": decimal_text(r["needed"]), "available": decimal_text(r["available"]), "cost_paise": r["cost_paise"], "enough": r["enough"]}
            for r in worked["components"]
        ],
        "cost_paise": worked["cost_paise"],
        "short": worked["short"],
    }


@extend_schema(tags=["manufacturing"])
class BomViewSet(MasterAuditMixin, ClientScopedMixin, FirmScopedViewSet):
    """What each finished item is made from, and the production runs that make it."""

    queryset = BillOfMaterials.objects.order_by("name")
    serializer_class = BomSerializer
    pagination_class = DefaultPagination
    audit_kind = "BOM"
    audit_fields = BOM_FIELDS
    required_permission = {"GET": "client.view", "POST": "journal.approve", "PUT": "ledger.manage", "PATCH": "ledger.manage", "DELETE": "ledger.manage"}

    def audit_label(self, obj) -> str:
        return f"Bill of materials: {obj.name}"

    @extend_schema(
        summary="What a production run would take and cost",
        description="For a quantity of the finished item on a date: each component needed, what is on hand, what it costs at the average, and which are short. Writes nothing.",
        parameters=[
            OpenApiParameter("quantity", OpenApiTypes.STR, required=True),
            OpenApiParameter("date", OpenApiTypes.DATE),
            OpenApiParameter("godown", OpenApiTypes.UUID),
        ],
        responses=RunPlanSerializer,
    )
    @action(detail=True, methods=["get"], url_path="plan")
    def plan(self, request, client_id=None, pk=None):
        bom = self.get_object()
        try:
            on = datetime.date.fromisoformat(request.query_params.get("date") or datetime.date.today().isoformat())
        except ValueError:
            raise ValidationError({"date": "A date as YYYY-MM-DD."}) from None
        try:
            worked = manufacturing.plan(self.client, bom, request.query_params.get("quantity", ""), on, _godown(request, self.client, request.query_params.get("godown")))
        except StockError as exc:
            raise ValidationError({"detail": str(exc)}) from None
        return Response(RunPlanSerializer(_plan_payload(worked)).data)

    @extend_schema(
        summary="Run production",
        description=(
            "Takes each component out of stock at its average cost and brings the finished item in at their total plus the extra cost "
            "given. Refused when a component is short, naming it, or inside sealed books. Removing any row of the run removes all of it. "
            "Needs `journal.approve`."
        ),
        request=ProduceSerializer,
        responses={201: StockEntrySerializer(many=True)},
    )
    @action(detail=True, methods=["post"], url_path="produce")
    def produce(self, request, client_id=None, pk=None):
        bom = self.get_object()
        body = ProduceSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        try:
            made = manufacturing.produce(
                self.client, bom, quantity=Decimal(data["quantity"]), entry_date=data["entry_date"], godown=_godown(request, self.client, data["godown"]),
                extra_cost_paise=data["extra_cost_paise"], note=data["note"], membership=request.membership,
            )
        except StockError as exc:
            raise ValidationError({"detail": str(exc)}) from None
        return Response(StockEntrySerializer(made, many=True).data, status=201)
