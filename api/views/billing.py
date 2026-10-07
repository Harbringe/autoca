"""Purchase and sales vouchers, as the bills they book."""

from __future__ import annotations

import uuid

from django.db import transaction
from django.db.models import BigIntegerField, F, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.pagination import DefaultPagination
from api.permissions import HasFirmPermission
from api.serializers.billing import (
    BillCreateSerializer,
    BillDetailSerializer,
    BillSerializer,
    RemoveBillSerializer,
)
from api.views.base import ClientScopedMixin
from classify.models import LedgerAccount, Party
from documents.models import Document
from ledger import billing, editing, invoice_intake
from ledger.billing import BillInput
from ledger.models import Bill, BillKind, InvoiceReading

POSTERS = {
    BillKind.PURCHASE: billing.post_purchase,
    BillKind.SALES: billing.post_sales,
    BillKind.DEBIT_NOTE: billing.post_debit_note,
    BillKind.CREDIT_NOTE: billing.post_credit_note,
}


@extend_schema(tags=["bills"])
class BillViewSet(ClientScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet):
    """A client's purchase and sales invoices and the notes that reverse them.

    Each bill is booked to its party's own account on its own date, apart from whatever later pays it, which is what
    makes "what do we owe this supplier" answerable. A bill is a permanent fact: it is posted or removed, never edited,
    and once the books are signed off it cannot be removed at all.
    """

    permission_classes = [HasFirmPermission]
    pagination_class = DefaultPagination
    required_permission = {"GET": "journal.view", "POST": "journal.approve"}
    queryset = Bill.objects.all()
    serializer_class = BillSerializer

    def get_queryset(self):
        queryset = (
            super()
            .get_queryset()
            .filter(firm_id=self.request.firm.pk)
            .select_related("party", "entry", "client", "document", "reading")
            .annotate(settled_paise=Coalesce(Sum("allocations__amount_paise"), Value(0), output_field=BigIntegerField()))
            .annotate(open_paise=F("total_paise") - F("settled_paise"))
        )
        params = self.request.query_params
        if params.get("kind"):
            queryset = queryset.filter(kind=params["kind"])
        if params.get("party"):
            try:
                queryset = queryset.filter(party_id=uuid.UUID(params["party"]))
            except ValueError as exc:
                raise serializers.ValidationError({"party": "Not a party id."}) from exc
        if params.get("fy"):
            try:
                queryset = queryset.filter(financial_year=int(params["fy"]))
            except ValueError as exc:
                raise serializers.ValidationError({"fy": "A starting year, like 2025."}) from exc
        if params.get("status") == "open":
            queryset = queryset.filter(open_paise__gt=0)
        elif params.get("status") == "settled":
            queryset = queryset.filter(open_paise__lte=0)
        if params.get("q"):
            text = params["q"].strip()
            queryset = queryset.filter(Q(reference__icontains=text) | Q(party__canonical_name__icontains=text))
        return queryset.order_by("-bill_date", "-created_at")

    def get_serializer_class(self):
        return BillDetailSerializer if self.action == "retrieve" else BillSerializer

    @extend_schema(
        parameters=[
            OpenApiParameter("kind", str, enum=[kind.value for kind in BillKind], description="Only this kind."),
            OpenApiParameter("party", str, description="Only this party's bills."),
            OpenApiParameter("fy", int, description="Financial year by its starting year: 2025 means FY2025-26."),
            OpenApiParameter("status", str, enum=["open", "settled"], description="Only bills still owing, or fully settled."),
            OpenApiParameter("q", str, description="Part of the invoice number or the party's name."),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Book a purchase, sales, debit-note or credit-note voucher",
        description=(
            "Writes the voucher, the bill and the journal lines together, or nothing. Needs `journal.approve` on a "
            "client the caller may post to, and is refused inside signed-off books.\n\n"
            "Money is whole paise. A purchase credits the supplier the taxable value plus GST, less any TDS typed here; "
            "under reverse charge the supplier is owed only the taxable value. A sale debits the customer. A debit note "
            "reverses a purchase and a credit note a sale. The GST split is as printed on the invoice: it is not "
            "computed from the place of supply in this version.\n\n"
            "The same invoice number from the same supplier in the same financial year is refused as a duplicate "
            "(422 `billing_rule`), however the number is punctuated."
        ),
        request=BillCreateSerializer,
        responses={201: BillDetailSerializer},
    )
    def create(self, request, *args, **kwargs):
        payload = BillCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        bill = self._book(request, payload.validated_data)
        # A payment already on the party's account for exactly this amount is its payment: not left as an island.
        invoice_intake.settle_payment(bill)
        return Response(BillDetailSerializer(self.get_queryset().get(pk=bill.pk)).data, status=status.HTTP_201_CREATED)

    def _book(self, request, data) -> Bill:
        client = self.client

        party = get_object_or_404(Party, pk=data["party"], firm_id=request.firm.pk, client=client)
        wanted = [head["ledger"] for head in data["heads"]]
        found = {
            ledger.pk: ledger
            for ledger in LedgerAccount.objects.filter(firm_id=request.firm.pk, client=client, pk__in=wanted)
        }
        missing = [str(pk) for pk in wanted if pk not in found]
        if missing:
            raise serializers.ValidationError({"heads": f"Not ledgers of this client: {', '.join(missing)}."})
        heads = [(found[head["ledger"]], head["amount_paise"]) for head in data["heads"]]

        document = None
        if data["document"] is not None:
            document = get_object_or_404(Document, pk=data["document"], firm_id=request.firm.pk, client=client)

        with transaction.atomic():
            bill = POSTERS[data["kind"]](
                client,
                party,
                heads,
                BillInput(
                    reference=data["reference"],
                    bill_date=data["bill_date"],
                    due_date=data["due_date"],
                    narration=data["narration"],
                    document=document,
                    own_gstin=data["own_gstin"],
                    cgst=data["cgst_paise"],
                    sgst=data["sgst_paise"],
                    igst=data["igst_paise"],
                    cess=data["cess_paise"],
                    round_off=data["round_off_paise"],
                    tds=data["tds_paise"],
                    tds_section=data["tds_section"],
                    rcm=data["rcm"],
                ),
                membership=request.membership,
            )
            # An uploaded invoice that was waiting for this is no longer waiting: the bill carries it.
            if document is not None:
                invoice_intake.note_booked(document, bill, user=request.user)
        return bill

    @extend_schema(
        summary="Change a booked bill",
        description=(
            "Replaces the bill with the corrected one, in one step: the old bill and its voucher are removed (the change log "
            "keeps what it was) and the new one is booked with the same invoice file. Any payment that settled the old "
            "bill is put against the new one when it still fits, otherwise left on the party's account. Same rules as "
            "booking: refused inside signed-off books, and nothing changes if the new one is refused."
        ),
        request=BillCreateSerializer,
        responses={200: BillDetailSerializer},
    )
    @action(detail=True, methods=["post"])
    def revise(self, request, client_id=None, pk=None):
        bill = self.get_object()
        payload = BillCreateSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = dict(payload.validated_data)
        if data.get("document") is None and bill.document_id:
            data["document"] = bill.document_id
        if data.get("document") is None:
            reading = InvoiceReading.objects.filter(bill=bill).first()
            data["document"] = reading.document_id if reading else None
        with transaction.atomic():
            settled = [(a.line, a.amount_paise) for a in bill.allocations.select_related("line__entry")]
            # A payment inside signed-off books is not re-linked from here, whatever it settled.
            for line, _ in settled:
                editing.require_editable(line.entry)
            for allocation in bill.allocations.all():
                allocation.delete()
            billing.remove_bill(bill, membership=request.membership, note="Changed by a person.")
            fresh = self._book(request, data)
            for line, amount in settled:
                try:
                    with transaction.atomic():
                        billing.allocate(line, amount_paise=amount, bill=fresh)
                except billing.BillingError:
                    billing.allocate(line, amount_paise=amount)
        return Response(BillDetailSerializer(self.get_queryset().get(pk=fresh.pk)).data)

    @extend_schema(
        summary="Remove a bill and its voucher",
        description=(
            "Only before the books are signed off, and only while nothing has been allocated to it. What it was is "
            "kept in the change log. A bill with a payment against it is changed with a debit or credit note instead."
        ),
        request=RemoveBillSerializer,
        responses={204: None},
    )
    @action(detail=True, methods=["post"])
    def remove(self, request, client_id=None, pk=None):
        bill = self.get_object()
        payload = RemoveBillSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        billing.remove_bill(bill, membership=request.membership, note=payload.validated_data["note"])
        return Response(status=status.HTTP_204_NO_CONTENT)
