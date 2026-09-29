"""GST reconciliation endpoints. Thin over ``gst.services``, which holds the rules.

Every route is under ``clients/{id}/gst/`` and resolves the client through
``get_visible_client``, so a client the caller cannot see is a 404 here as
everywhere. Runs, rows and decisions are then looked up *within that client*: an
id from another client, or another firm, is simply not found.
"""

from __future__ import annotations

import datetime
import json

from django.conf import settings
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from api.pagination import DefaultPagination
from api.permissions import HasFirmPermission
from core.access import get_visible_client
from gst import report, services
from gst.models import DecisionKind, GstRegistration, ReconMatch, ReconRun, RegistrationType


class RegistrationSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    gstin = serializers.CharField(max_length=15)
    state_code = serializers.CharField(read_only=True)
    registration_type = serializers.ChoiceField(
        choices=RegistrationType.choices, default=RegistrationType.REGULAR
    )


class RunCreateSerializer(serializers.Serializer):
    registration = serializers.UUIDField()
    period = serializers.RegexField(
        r"^\d{4}-(0[1-9]|1[0-2])$", help_text="Return month, e.g. 2026-08."
    )


class UploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    mapping = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text='Optional JSON mapping a field to a header, e.g. {"gstin": "Vendor GST"}.',
    )

    def validate_file(self, upload):
        limit = settings.MAX_STATEMENT_UPLOAD_BYTES
        if upload.size == 0:
            raise serializers.ValidationError("The file is empty.")
        if upload.size > limit:
            raise serializers.ValidationError(f"The file is too large; the limit is {limit} bytes.")
        return upload


class DecisionSerializer(serializers.Serializer):
    match = serializers.UUIDField()
    kind = serializers.ChoiceField(choices=DecisionKind.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)

    def validate_kind(self, value):
        if value == DecisionKind.SIGN_OFF:
            raise serializers.ValidationError("Sign-off has its own endpoint.")
        return value


def _run_of(client, run_id) -> ReconRun:
    run = (
        ReconRun.objects.filter(client=client, pk=run_id)
        .select_related("registration", "client")
        .first()
    )
    if run is None:
        raise NotFound("No such reconciliation.")
    return run


def _registration_data(reg: GstRegistration) -> dict:
    return {
        "id": str(reg.pk),
        "gstin": reg.gstin,
        "state_code": reg.state_code,
        "registration_type": reg.registration_type,
    }


@extend_schema(tags=["gst"])
class RegistrationViewSet(viewsets.GenericViewSet):
    """The GSTINs a client holds. Each is reconciled and reported separately."""

    serializer_class = RegistrationSerializer
    permission_classes = [HasFirmPermission]
    pagination_class = DefaultPagination
    required_permission = {"GET": "gst.view", "POST": "gst.prepare"}

    def list(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        regs = GstRegistration.objects.filter(client=client, is_active=True)
        page = self.paginate_queryset(regs)
        return self.get_paginated_response([_registration_data(r) for r in page])

    def create(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        payload = self.get_serializer(data=request.data)
        payload.is_valid(raise_exception=True)
        reg = services.add_registration(
            client, payload.validated_data["gstin"], payload.validated_data["registration_type"]
        )
        return Response(_registration_data(reg), status=status.HTTP_201_CREATED)


@extend_schema(tags=["gst"])
class RunViewSet(viewsets.GenericViewSet):
    """One GSTIN's reconciliation for one return month."""

    serializer_class = RunCreateSerializer
    permission_classes = [HasFirmPermission]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    required_permission = {"GET": "gst.view", "POST": "gst.prepare"}

    def list(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        runs = ReconRun.objects.filter(client=client).select_related("registration")
        if reg := request.query_params.get("registration"):
            runs = runs.filter(registration_id=reg)
        return Response(
            [
                {
                    "id": str(r.pk),
                    "registration": str(r.registration_id),
                    "gstin": r.registration.gstin,
                    "period_start": r.period_start.isoformat(),
                    "status": r.status,
                }
                for r in runs
            ]
        )

    def create(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        payload = self.get_serializer(data=request.data)
        payload.is_valid(raise_exception=True)
        reg = GstRegistration.objects.filter(
            client=client, pk=payload.validated_data["registration"]
        ).first()
        if reg is None:
            raise NotFound("No such GST registration for this client.")
        year, month = payload.validated_data["period"].split("-")
        run = services.get_or_create_run(reg, datetime.date(int(year), int(month), 1), request.user)
        return Response(report.run_report(_run_of(client, run.pk)), status=status.HTTP_201_CREATED)

    def retrieve(self, request, client_id=None, pk=None):
        client = get_visible_client(request, client_id)
        return Response(report.run_report(_run_of(client, pk)))

    def _upload(self, request, client_id, pk, loader):
        client = get_visible_client(request, client_id)
        run = _run_of(client, pk)
        payload = UploadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        upload = payload.validated_data["file"]
        kwargs = {}
        if loader is services.load_register and payload.validated_data.get("mapping"):
            try:
                kwargs["mapping"] = json.loads(payload.validated_data["mapping"])
            except ValueError as exc:
                raise serializers.ValidationError({"mapping": "Not valid JSON."}) from exc
        count = loader(run, upload.read(), upload.name, request.user, **kwargs)
        return Response({"rows": count, "run": report.run_report(run)})

    @extend_schema(request=UploadSerializer, summary="Upload the purchase register")
    def register(self, request, client_id=None, pk=None):
        return self._upload(request, client_id, pk, services.load_register)

    @extend_schema(request=UploadSerializer, summary="Upload GSTR-2B (JSON or Excel)")
    def portal(self, request, client_id=None, pk=None):
        return self._upload(request, client_id, pk, services.load_portal)

    @extend_schema(request=None, summary="Match the register against GSTR-2B")
    def reconcile(self, request, client_id=None, pk=None):
        client = get_visible_client(request, client_id)
        run = _run_of(client, pk)
        services.reconcile_run(run)
        return Response(report.run_report(run))

    @extend_schema(request=DecisionSerializer, summary="Record a decision about one invoice")
    def decide(self, request, client_id=None, pk=None):
        client = get_visible_client(request, client_id)
        run = _run_of(client, pk)
        payload = DecisionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        match = ReconMatch.objects.filter(run=run, pk=payload.validated_data["match"]).first()
        if match is None:
            raise NotFound("No such row in this reconciliation.")
        services.decide(
            run, match, payload.validated_data["kind"], payload.validated_data["note"], request.user
        )
        return Response(report.run_report(run))

    @extend_schema(summary="Download the Excel working paper", responses={200: bytes})
    def export(self, request, client_id=None, pk=None):
        client = get_visible_client(request, client_id)
        run = _run_of(client, pk)
        response = HttpResponse(
            report.working_paper(run),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="gst-reconciliation-{run.period_start:%Y-%m}.xlsx"'
        )
        return response


@extend_schema(tags=["gst"])
class RunSignOffView(viewsets.GenericViewSet):
    """Signing a reconciliation off. The lead's or an administrator's act."""

    serializer_class = serializers.Serializer
    permission_classes = [HasFirmPermission]
    required_permission = "gst.sign_off"

    @extend_schema(request=None, summary="Sign the reconciliation off")
    def create(self, request, client_id=None, pk=None):
        client = get_visible_client(request, client_id)
        run = _run_of(client, pk)
        services.sign_off_run(run, request.user, request.membership)
        return Response(report.run_report(run))
