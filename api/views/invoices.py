"""Uploaded invoices: the drafts read from them, and what a person does with each."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from api.pagination import DefaultPagination
from api.permissions import CanApprove, HasFirmPermission
from api.serializers.invoices import (
    AttachSerializer,
    InvoiceReadingSerializer,
    InvoiceUploadSerializer,
    SayKindSerializer,
    reading_payload,
)
from api.throttles import enforce
from api.views.base import ClientScopedMixin
from ledger import invoice_intake
from ledger.models import Bill, InvoiceReading


@extend_schema(tags=["invoices"])
class InvoiceReadingViewSet(
    ClientScopedMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet
):
    """Invoices uploaded as files, and what each appears to say.

    A reading is only a draft. Booking it is the ordinary purchase or sales voucher with this file attached
    (`POST bills/` with `document`), which closes the reading; or it is attached to a bill booked by hand first, or set
    aside. Until then it is an open item, so a file cannot sit unseen.
    """

    permission_classes = [HasFirmPermission]
    pagination_class = DefaultPagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    required_permission = {"GET": "journal.view", "POST": "document.upload", "DELETE": "journal.approve"}
    queryset = InvoiceReading.objects.all()
    serializer_class = InvoiceReadingSerializer

    def get_queryset(self):
        queryset = super().get_queryset().filter(firm_id=self.request.firm.pk).select_related("document", "client")
        wanted = self.request.query_params.get("status")
        return queryset.filter(status=wanted) if wanted else queryset

    def _payload(self, reading: InvoiceReading) -> dict:
        return reading_payload(
            reading,
            invoice_intake.fields_of(reading),
            invoice_intake.suggested_party(reading),
            invoice_intake.matching_bill(reading),
            invoice_intake.payment_candidates(reading) if reading.status == "OPEN" or reading.auto_booked else (),
        )

    def list(self, request, *args, **kwargs):
        page = self.paginate_queryset(self.get_queryset())
        return self.get_paginated_response(InvoiceReadingSerializer([self._payload(r) for r in page], many=True).data)

    def retrieve(self, request, *args, **kwargs):
        return Response(InvoiceReadingSerializer(self._payload(self.get_object())).data)

    @extend_schema(
        summary="Upload an invoice, read it, and book it when certain",
        description=(
            "Stores the PDF with the client's other documents and reads it (its text layer, or for a scan the vision "
            "model when switched on) with the arithmetic that proves or faults it. Whether it is a purchase or a sale is "
            "told from the client's own GSTIN unless `kind` is given. When the kind, the proof and the party are all "
            "certain the bill is booked at once (`auto_booked`) and matched to its bank payment if exactly one fits; "
            "otherwise nothing is booked and `attention` says why. The same file again returns its reading (`200`). "
            "Needs `document.upload`."
        ),
        request=InvoiceUploadSerializer,
        responses={201: InvoiceReadingSerializer, 200: InvoiceReadingSerializer},
    )
    @action(detail=False, methods=["post"], url_path="upload")
    def upload(self, request, client_id=None):
        enforce(request, self, "upload")
        payload = InvoiceUploadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        upload = payload.validated_data["file"]
        reading, is_new = invoice_intake.read_upload(
            client=self.client,
            data=upload.read(),
            filename=upload.name,
            kind=payload.validated_data["kind"],
            uploaded_by=request.user,
        )
        if is_new and not payload.validated_data["kind"] and payload.validated_data["book"]:
            # Left to the system: certain, then it is booked now; if not, it waits with the reason, and an alert.
            # (A person who names the kind is doing the booking themselves and gets the draft, as before.)
            reading = invoice_intake.try_auto_book(reading, membership=request.membership)
        reading = self.get_queryset().get(pk=reading.pk)
        return Response(
            InvoiceReadingSerializer(self._payload(reading)).data,
            status=status.HTTP_201_CREATED if is_new else status.HTTP_200_OK,
        )

    @extend_schema(
        summary="Attach this file to a bill booked by hand",
        request=AttachSerializer,
        responses={200: InvoiceReadingSerializer},
    )
    @action(detail=True, methods=["post"], url_path="attach", permission_classes=[CanApprove])
    def attach(self, request, client_id=None, pk=None):
        reading = self.get_object()
        payload = AttachSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        bill = get_object_or_404(Bill, pk=payload.validated_data["bill"], firm_id=request.firm.pk, client=self.client)
        invoice_intake.attach_to_bill(reading, bill, membership=request.membership)
        return Response(InvoiceReadingSerializer(self._payload(self.get_queryset().get(pk=reading.pk))).data)

    @extend_schema(
        summary="Delete an uploaded invoice",
        description=(
            "Removes the reading, the stored file and its pages for good. An invoice that is booked is refused unless "
            "`with_bill=true`, which removes its bill and voucher first by the rules for removing a bill (nothing settled "
            "against it, books not signed off). Needs `journal.approve` on a client the caller may post to."
        ),
        parameters=[
            OpenApiParameter("with_bill", bool, description="Also remove the bill booked from it."),
            OpenApiParameter("release_payments", bool, description="With `with_bill`: also undo payments settled against the bill."),
        ],
        responses={204: None},
    )
    def destroy(self, request, client_id=None, pk=None):
        reading = self.get_object()
        with_bill = request.query_params.get("with_bill", "").lower() in {"1", "true", "yes"}
        release = request.query_params.get("release_payments", "").lower() in {"1", "true", "yes"}
        invoice_intake.delete_reading(reading, membership=request.membership, with_bill=with_bill, release_payments=release)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Say whether this invoice is a purchase or a sale",
        description=(
            "For a file the system could not tell (the client's own GSTIN is not on it, or not on record). Records the "
            "answer and tries to book it as usual; if it still cannot, `attention` says why. Needs `journal.approve`."
        ),
        request=SayKindSerializer,
        responses={200: InvoiceReadingSerializer},
    )
    @action(detail=True, methods=["post"], url_path="kind", permission_classes=[CanApprove])
    def kind(self, request, client_id=None, pk=None):
        reading = self.get_object()
        payload = SayKindSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        invoice_intake.say_kind(reading, payload.validated_data["kind"], membership=request.membership)
        return Response(InvoiceReadingSerializer(self._payload(self.get_queryset().get(pk=reading.pk))).data)

    @extend_schema(summary="Set this invoice aside", request=None, responses={200: InvoiceReadingSerializer})
    @action(detail=True, methods=["post"], url_path="discard", permission_classes=[CanApprove])
    def discard(self, request, client_id=None, pk=None):
        reading = self.get_object()
        invoice_intake.discard(reading, membership=request.membership)
        return Response(InvoiceReadingSerializer(self._payload(self.get_queryset().get(pk=reading.pk))).data)
