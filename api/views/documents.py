"""Firm and client document library."""

from __future__ import annotations

import mimetypes
from io import BytesIO

from django.http import FileResponse, Http404, HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.generics import ListAPIView
from rest_framework.response import Response
from rest_framework.views import APIView

from api.pagination import DefaultPagination
from api.permissions import HasFirmPermission
from api.throttles import enforce
from core.access import visible_clients
from documents import preview
from documents.models import Document
from integrations.pdf.base import PdfExtractionError
from integrations.registry import get_storage
from integrations.storage.base import StorageAdapter


class FirmDocumentSerializer(serializers.ModelSerializer):
    client_id = serializers.UUIDField(read_only=True)
    client_name = serializers.CharField(source="client.name", read_only=True)
    kind_display = serializers.CharField(source="get_kind_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    uploaded_by_name = serializers.CharField(source="uploaded_by.get_full_name", read_only=True, allow_null=True)

    class Meta:
        model = Document
        fields = ["id", "client_id", "client_name", "kind", "kind_display", "original_filename",
                  "byte_size", "page_count", "status", "status_display", "failure_reason",
                  "uploaded_by_name", "created_at"]


class FirmDocumentListView(ListAPIView):
    serializer_class = FirmDocumentSerializer
    permission_classes = [HasFirmPermission]
    required_permission = "document.view"
    pagination_class = DefaultPagination

    def get_queryset(self):
        queryset = Document.objects.filter(
            firm_id=self.request.firm.pk,
            client__in=visible_clients(self.request.membership),
        ).select_related("client", "uploaded_by")
        client_id = self.request.query_params.get("client")
        if client_id:
            queryset = queryset.filter(client_id=client_id)
        return queryset


class DocumentDownloadView(APIView):
    permission_classes = [HasFirmPermission]
    required_permission = "document.view"

    def get(self, request, pk):
        document = get_object_or_404(
            Document.objects.filter(
                firm_id=request.firm.pk,
                client__in=visible_clients(request.membership),
            ), pk=pk,
        )
        try:
            StorageAdapter.verify_tenant_key(document.storage_key, request.firm.pk)
            content = get_storage().get(document.storage_key)
        except (PermissionError, FileNotFoundError, KeyError):
            raise Http404("The file is no longer available.") from None
        filename = document.original_filename or f"{document.pk}"
        response = FileResponse(BytesIO(content), as_attachment=True, filename=filename,
                                content_type=mimetypes.guess_type(filename)[0] or "application/octet-stream")
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, no-store"
        return response


def _stored(request, pk) -> tuple[Document, bytes]:
    document = get_object_or_404(
        Document.objects.filter(firm_id=request.firm.pk, client__in=visible_clients(request.membership)), pk=pk
    )
    try:
        StorageAdapter.verify_tenant_key(document.storage_key, request.firm.pk)
        return document, get_storage().get(document.storage_key)
    except (PermissionError, FileNotFoundError, KeyError):
        raise Http404("The file is no longer available.") from None


class DocumentPreviewSerializer(serializers.Serializer):
    pages = serializers.IntegerField(help_text="How many pages the viewer shows.")
    filename = serializers.CharField(allow_blank=True)


@extend_schema(tags=["documents"])
class DocumentPreviewView(APIView):
    """How many pages a stored file shows as, for the viewer beside a form."""

    permission_classes = [HasFirmPermission]
    required_permission = "document.view"

    @extend_schema(summary="Pages of a stored file", responses=DocumentPreviewSerializer)
    def get(self, request, pk):
        enforce(request, self, "preview")
        document, data = _stored(request, pk)
        try:
            pages = preview.page_count(data, document.original_filename or "", str(document.pk))
        except PdfExtractionError as exc:
            raise Http404(str(exc)) from None
        return Response({"pages": pages, "filename": document.original_filename})


@extend_schema(tags=["documents"])
class DocumentPageView(APIView):
    """One page of a stored file as an image. A PDF is drawn; a sheet or Word file is converted to pages first."""

    permission_classes = [HasFirmPermission]
    required_permission = "document.view"

    @extend_schema(summary="One page of a stored file, as a PNG", responses={(200, "image/png"): bytes})
    def get(self, request, pk, number):
        enforce(request, self, "preview")
        document, data = _stored(request, pk)
        try:
            image = preview.page_image(data, document.original_filename or "", str(document.pk), number)
        except PdfExtractionError as exc:
            raise Http404(str(exc)) from None
        if image is None:
            raise Http404("There is no such page.")
        response = HttpResponse(image, content_type="image/png")
        response["X-Content-Type-Options"] = "nosniff"
        response["Cache-Control"] = "private, max-age=300"
        return response
