"""The cheque register: issued and received cheques, post-dated ones, and their status."""

from __future__ import annotations

import datetime

from django.db.models import Q
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from api.pagination import DefaultPagination
from api.serializers.cheques import (
    BankAccountChoiceSerializer,
    ChequeSerializer,
    ChequeStatusSerializer,
    PdcSerializer,
)
from api.views.base import ClientScopedMixin, FirmScopedViewSet
from api.views.master_audit import MasterAuditMixin
from banking.models import BankAccount
from ledger.audit import CHEQUE_FIELDS, record_master_change, snapshot
from ledger.models import Cheque, ChequeStatus


@extend_schema(tags=["cheques"])
class ChequeViewSet(MasterAuditMixin, ClientScopedMixin, FirmScopedViewSet):
    """Cheques issued and received. A record to follow up and print from; it books nothing."""

    queryset = Cheque.objects.select_related("bank_account", "party")
    serializer_class = ChequeSerializer
    pagination_class = DefaultPagination
    audit_kind = "CHEQUE"
    audit_fields = CHEQUE_FIELDS
    required_permission = {"GET": "journal.view", "POST": "journal.approve", "PUT": "journal.approve", "PATCH": "journal.approve", "DELETE": "journal.approve"}

    def audit_label(self, obj) -> str:
        return f"Cheque {obj.number} ({obj.get_direction_display().lower()})"

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params
        if params.get("direction"):
            queryset = queryset.filter(direction=params["direction"])
        if params.get("status"):
            queryset = queryset.filter(status=params["status"])
        if params.get("q"):
            text = params["q"].strip()
            queryset = queryset.filter(Q(number__icontains=text) | Q(payee_name__icontains=text) | Q(party__canonical_name__icontains=text))
        return queryset

    def perform_destroy(self, instance):
        if instance.status != ChequeStatus.PENDING:
            raise ValidationError({"detail": "Only a cheque that is still pending can be removed; cancel it instead."})
        super().perform_destroy(instance)

    @extend_schema(
        summary="Clear, bounce, cancel or reopen a cheque",
        description="Sets the status and the day it happened (today when left out); `PENDING` puts it back. Recorded in the audit trail.",
        request=ChequeStatusSerializer,
        responses=ChequeSerializer,
    )
    @action(detail=True, methods=["post"], url_path="status")
    def set_status(self, request, client_id=None, pk=None):
        cheque = self.get_object()
        body = ChequeStatusSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        before = snapshot(cheque, CHEQUE_FIELDS)
        cheque.status = body.validated_data["status"]
        cheque.status_on = None if cheque.status == ChequeStatus.PENDING else body.validated_data.get("on") or datetime.date.today()
        cheque.save(update_fields=["status", "status_on"])
        record_master_change(
            self.client, "CHEQUE", cheque.pk, "EDITED", label=self.audit_label(cheque), before=before,
            after=snapshot(cheque, CHEQUE_FIELDS), actor=request.user,
        )
        return Response(ChequeSerializer(cheque).data)

    @extend_schema(
        summary="Post-dated cheques still pending",
        description=(
            "What the client has issued and received that is dated after the day it was written and not yet presented, by month; those "
            "falling due in the next seven days; and pending cheques more than three months past their date."
        ),
        responses=PdcSerializer,
    )
    @action(detail=False, methods=["get"], url_path="pdc", pagination_class=None)
    def pdc(self, request, client_id=None):
        today = datetime.date.today()
        pending = list(self.get_queryset().filter(status=ChequeStatus.PENDING))
        months: dict[str, dict] = {}
        issued = received = 0
        for c in pending:
            if c.cheque_date <= c.issued_on:
                continue
            row = months.setdefault(c.cheque_date.strftime("%Y-%m"), {"month": c.cheque_date.strftime("%Y-%m"), "issued_paise": 0, "received_paise": 0})
            if c.direction == "ISSUED":
                row["issued_paise"] += c.amount_paise
                issued += c.amount_paise
            else:
                row["received_paise"] += c.amount_paise
                received += c.amount_paise
        soon = [c for c in pending if today <= c.cheque_date <= today + datetime.timedelta(days=7)]
        stale = [c for c in pending if (today - c.cheque_date).days > 92]
        payload = {
            "issued_paise": issued, "received_paise": received, "by_month": [months[k] for k in sorted(months)],
            "due_soon": soon, "stale": stale,
        }
        return Response(PdcSerializer(payload).data)

    @extend_schema(summary="The client's bank accounts a cheque can be drawn on", responses=BankAccountChoiceSerializer(many=True))
    @action(detail=False, methods=["get"], url_path="accounts", pagination_class=None)
    def accounts(self, request, client_id=None):
        rows = BankAccount.objects.filter(firm_id=request.firm.pk, client=self.client)
        return Response(BankAccountChoiceSerializer(rows, many=True).data)


_ = OpenApiParameter, OpenApiTypes  # the list filters (direction, status, q) are documented on the viewset
