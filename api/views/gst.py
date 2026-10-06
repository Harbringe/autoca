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
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from api.pagination import DefaultPagination
from api.permissions import HasFirmPermission
from api.throttles import enforce
from core.access import get_visible_client
from gst import books, report, services
from gst.matching import ItcStatus, MatchKind, Section
from gst.models import (
    DecisionKind,
    GstRegistration,
    ReconMatch,
    ReconRun,
    RegistrationType,
    RunStatus,
)


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


# ---------------------------------------------------------------------------
# Response shapes. Documentation only: the views return plain dictionaries
# (``gst.report.run_report``) and these describe exactly those, so the generated
# types match what is on the wire.
# ---------------------------------------------------------------------------

_KINDS = [k.value for k in MatchKind]
_ITC = [i.value for i in ItcStatus]
_SECTIONS = [s.value for s in Section]
_DECISIONS = [d.value for d in DecisionKind if d != DecisionKind.SIGN_OFF]


class GstErrorSerializer(serializers.Serializer):
    code = serializers.CharField(
        help_text="Stable code: gst_rule (409), gst_file_unreadable (422), invalid (400), "
        "not_found (404), forbidden (403)."
    )
    detail = serializers.CharField(help_text="A sentence for a person; show it as it is.")


def _responses(ok, *, created=False, rule=False, unreadable=False) -> dict:
    out = {
        201 if created else 200: ok,
        400: GstErrorSerializer,
        403: GstErrorSerializer,
        404: GstErrorSerializer,
    }
    if rule:
        out[409] = GstErrorSerializer
    if unreadable:
        out[422] = GstErrorSerializer
    return out


_ERRORS = (
    "\n\nErrors are `{code, detail}`: `403 forbidden` (the role lacks the permission), "
    "`404 not_found` (no such client, run or row for the caller), `400 invalid` (the body has a "
    "`fields` object naming what is wrong)"
)
_RULE = (
    "; `409 gst_rule` (a reconciliation rule refused the step: the run is already signed off, "
    "or the message says what is missing or mismatched)"
)
_UNREADABLE = "; `422 gst_file_unreadable` (the file could not be read as a register or GSTR-2B)"


class RunListItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    registration = serializers.UUIDField(help_text="The GST registration (GSTIN) this run is for.")
    gstin = serializers.CharField()
    period_start = serializers.DateField(help_text="First day of the return month.")
    status = serializers.ChoiceField(choices=RunStatus.choices)


class ReportRegistrationSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    gstin = serializers.CharField()
    state_code = serializers.CharField(help_text="The first two digits of the GSTIN.")


class ReportInvoiceSerializer(serializers.Serializer):
    """One invoice as it stands in the purchase register (`book`) or GSTR-2B (`portal`)."""

    gstin = serializers.CharField(help_text="The supplier's GSTIN; may be blank or invalid.")
    invoice_no = serializers.CharField()
    invoice_date = serializers.DateField(allow_null=True)
    supplier_name = serializers.CharField()
    hsn = serializers.CharField()
    section = serializers.ChoiceField(
        choices=_SECTIONS,
        help_text="B2B invoice; CDN credit note (reduces credit); DN debit note (adds credit); "
        "IMPG import of goods; ISD credit from an Input Service Distributor.",
    )
    taxable_paise = serializers.IntegerField()
    igst_paise = serializers.IntegerField()
    cgst_paise = serializers.IntegerField()
    sgst_paise = serializers.IntegerField()
    cess_paise = serializers.IntegerField()


class ReportDecisionSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=_DECISIONS)
    note = serializers.CharField(allow_blank=True)
    at = serializers.DateTimeField(help_text="When the decision was recorded.")


class ReportRowSerializer(serializers.Serializer):
    id = serializers.UUIDField(help_text="The match id; send it as `match` when recording a decision.")
    itc_status = serializers.ChoiceField(
        choices=_ITC,
        help_text="eligible; blocked (a section 17(5) category); not_eligible (not claimable on "
        "this evidence yet); rcm_on_payment (reverse charge, claimable after the tax is paid).",
    )
    eligible_paise = serializers.IntegerField(
        help_text="Credit claimable on this row with the latest decision applied; negative for a credit note."
    )
    ineligible_paise = serializers.IntegerField(
        help_text="Credit this row carries that is not claimable, with the latest decision applied."
    )
    cause = serializers.CharField(allow_blank=True, help_text="Why the row is in this group.")
    action = serializers.CharField(allow_blank=True, help_text="What the preparer should do about it.")
    timing = serializers.BooleanField(
        help_text="The difference is one of month, not an error (for example the supplier has not filed yet)."
    )
    differences = serializers.DictField(
        child=serializers.IntegerField(),
        help_text="Books minus GSTR-2B in paise, keyed by `taxable_paise`, `igst_paise`, "
        "`cgst_paise`, `sgst_paise`, `cess_paise`; only the heads that differ beyond rounding.",
    )
    book = ReportInvoiceSerializer(allow_null=True, help_text="Null when the invoice is only in GSTR-2B.")
    portal = ReportInvoiceSerializer(allow_null=True, help_text="Null when the invoice is only in the books.")
    decision = ReportDecisionSerializer(
        allow_null=True, help_text="The latest decision on this invoice; null if none. Notes do not count."
    )


class ReportGroupSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=_KINDS)
    title = serializers.CharField(help_text="Show as sent. Groups arrive in the order a person should work them.")
    count = serializers.IntegerField()
    rows = ReportRowSerializer(many=True)


class ReportActionSerializer(serializers.Serializer):
    match = serializers.UUIDField(help_text="The row this action is about (a `rows[].id`).")
    text = serializers.CharField()


class ReportSummarySerializer(serializers.Serializer):
    counts = serializers.DictField(
        child=serializers.IntegerField(), help_text="Rows per group `kind`; groups with no rows are absent."
    )
    eligible_paise = serializers.IntegerField(help_text="Total eligible ITC, decisions applied.")
    blocked_paise = serializers.IntegerField(help_text="Credit in blocked categories (section 17(5)).")
    ineligible_paise = serializers.IntegerField(help_text="Other credit that is not claimable.")
    rcm_liability_paise = serializers.IntegerField(help_text="Reverse-charge tax payable on rows from the books.")
    unclaimed_in_2b_paise = serializers.IntegerField(
        help_text="Tax on invoices in GSTR-2B that are not in the books."
    )
    unresolved = serializers.IntegerField(
        help_text="Amount differences, tax-head differences and possible matches with no decision. "
        "Sign-off is refused while this is not 0."
    )


class ReportGstr3bLineSerializer(serializers.Serializer):
    code = serializers.CharField(help_text="GSTR-3B table 4 line: 4A(1), 4A(3), 4A(4), 4A(5), 4B(1) or 4D(2).")
    label = serializers.CharField()
    igst_paise = serializers.IntegerField()
    cgst_paise = serializers.IntegerField()
    sgst_paise = serializers.IntegerField()
    cess_paise = serializers.IntegerField()


class RunReportSerializer(serializers.Serializer):
    """The reconciliation as data. The Excel working paper is laid out from this same dictionary."""

    id = serializers.UUIDField()
    registration = ReportRegistrationSerializer()
    period_start = serializers.DateField(help_text="First day of the return month.")
    status = serializers.ChoiceField(choices=RunStatus.choices)
    signed_off_at = serializers.DateTimeField(allow_null=True)
    has_register = serializers.BooleanField(help_text="The purchase register has been uploaded, or taken from the books.")
    register_from_books = serializers.BooleanField(help_text="The register is the books' own purchase bills, not a file.")
    has_portal = serializers.BooleanField(help_text="GSTR-2B has been uploaded.")
    summary = ReportSummarySerializer()
    gstr3b = ReportGstr3bLineSerializer(
        many=True, help_text="Indicative GSTR-3B table 4, not the return. Always all six lines, in order."
    )
    groups = ReportGroupSerializer(many=True)
    actions = ReportActionSerializer(
        many=True, help_text="Rows with an action and no decision, matched rows excluded."
    )


class UploadResultSerializer(serializers.Serializer):
    rows = serializers.IntegerField(help_text="Rows read from the file; they replace any earlier upload.")
    run = RunReportSerializer()


class BooksLoadResultSerializer(serializers.Serializer):
    rows = serializers.IntegerField(help_text="Bills of the month taken into the register; they replace any earlier register.")
    unassigned = serializers.IntegerField(
        help_text="Bills of the month booked with no GSTIN of the client's, left out because the client has several registrations."
    )
    run = RunReportSerializer()


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

    @extend_schema(
        summary="List the client's GSTINs",
        description="Active registrations, paginated. Requires `gst.view`." + _ERRORS + ".",
        responses={200: RegistrationSerializer, 403: GstErrorSerializer, 404: GstErrorSerializer},
    )
    def list(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        regs = GstRegistration.objects.filter(client=client, is_active=True)
        page = self.paginate_queryset(regs)
        return self.get_paginated_response([_registration_data(r) for r in page])

    @extend_schema(
        summary="Add a GSTIN for the client",
        description=(
            "The state code is read from the GSTIN. Requires `gst.prepare`." + _ERRORS + _RULE
            + " (not a valid GSTIN, or already registered for this client)."
        ),
        request=RegistrationSerializer,
        responses=_responses(RegistrationSerializer, created=True, rule=True),
    )
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
    pagination_class = None
    permission_classes = [HasFirmPermission]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    required_permission = {"GET": "gst.view", "POST": "gst.prepare"}

    @extend_schema(
        summary="List a client's reconciliation runs",
        description=(
            "A plain array, not paginated; `registration` narrows it to one GSTIN. Requires "
            "`gst.view`." + _ERRORS + "."
        ),
        parameters=[
            OpenApiParameter("registration", OpenApiTypes.UUID, description="Only this registration's runs.")
        ],
        responses={200: RunListItemSerializer(many=True), 403: GstErrorSerializer, 404: GstErrorSerializer},
    )
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

    @extend_schema(
        summary="Start (or open) the reconciliation for one GSTIN and month",
        description=(
            "Idempotent: asking again for the same registration and month returns the existing "
            "run's report. Requires `gst.prepare`." + _ERRORS + "."
        ),
        request=RunCreateSerializer,
        responses={
            201: RunReportSerializer,
            400: GstErrorSerializer,
            403: GstErrorSerializer,
            404: GstErrorSerializer,
        },
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

    @extend_schema(
        summary="The reconciliation report",
        description=(
            "The whole run as data: headline figures, GSTR-3B table 4, the groups of invoices "
            "and what to do next. The Excel working paper is built from this same report. "
            "Requires `gst.view`." + _ERRORS + "."
        ),
        responses={200: RunReportSerializer, 403: GstErrorSerializer, 404: GstErrorSerializer},
    )
    def retrieve(self, request, client_id=None, pk=None):
        client = get_visible_client(request, client_id)
        return Response(report.run_report(_run_of(client, pk)))

    def _upload(self, request, client_id, pk, loader):
        enforce(request, self, "upload")
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

    @extend_schema(
        request={"multipart/form-data": UploadSerializer},
        summary="Upload the purchase register",
        description=(
            "Replaces the run's register rows. `file` is Excel or CSV; `mapping` is optional JSON "
            "naming which header holds which field. Requires `gst.prepare`." + _ERRORS + _RULE + _UNREADABLE
            + "."
        ),
        responses=_responses(UploadResultSerializer, rule=True, unreadable=True),
    )
    def register(self, request, client_id=None, pk=None):
        return self._upload(request, client_id, pk, services.load_register)

    @extend_schema(
        request=None,
        summary="Take the purchase register from the books",
        description=(
            "Builds the run's register from the month's purchase bills and the debit notes that reverse purchases, "
            "instead of an uploaded file, so what is matched against GSTR-2B is exactly what the books hold. Bills "
            "belong to the registration they were booked under; with one registration, bills booked with none belong "
            "to it. Replaces any earlier register. Requires `gst.prepare`." + _ERRORS + _RULE + "."
        ),
        responses=_responses(BooksLoadResultSerializer, rule=True),
    )
    def register_from_books(self, request, client_id=None, pk=None):
        client = get_visible_client(request, client_id)
        run = _run_of(client, pk)
        loaded = books.load_register_from_books(run)
        run.refresh_from_db()
        return Response({"rows": loaded.rows, "unassigned": loaded.unassigned, "run": report.run_report(run)})

    @extend_schema(
        request={"multipart/form-data": UploadSerializer},
        summary="Upload GSTR-2B (JSON or Excel)",
        description=(
            "Replaces the run's GSTR-2B rows. A JSON file must be this GSTIN's and this month's "
            "return (`409 gst_rule` otherwise). Requires `gst.prepare`." + _ERRORS + _RULE + _UNREADABLE + "."
        ),
        responses=_responses(UploadResultSerializer, rule=True, unreadable=True),
    )
    def portal(self, request, client_id=None, pk=None):
        return self._upload(request, client_id, pk, services.load_portal)

    @extend_schema(
        request=None,
        summary="Match the register against GSTR-2B",
        description=(
            "Rebuilds the matches from the two uploads; earlier decisions are kept because they "
            "follow the invoice, not the row. Requires `gst.prepare`." + _ERRORS + _RULE
            + " (either upload is missing, or the run is signed off)."
        ),
        responses=_responses(RunReportSerializer, rule=True),
    )
    def reconcile(self, request, client_id=None, pk=None):
        client = get_visible_client(request, client_id)
        run = _run_of(client, pk)
        services.reconcile_run(run)
        return Response(report.run_report(run))

    @extend_schema(
        request=DecisionSerializer,
        summary="Record a decision about one invoice",
        description=(
            "Appends a decision; the latest one on an invoice stands. `kind` is one of "
            "`accept_match`, `claim_itc`, `disallow_itc`, `defer`, `note` (`sign_off` is refused "
            "with `400 invalid`; signing off has its own endpoint). Requires `gst.prepare`."
            + _ERRORS + _RULE + " (the kind does not apply to that row's group, or the run is signed off)."
        ),
        responses=_responses(RunReportSerializer, rule=True),
    )
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

    @extend_schema(
        summary="Download the Excel working paper",
        description="An .xlsx built from the run report. Requires `gst.view`." + _ERRORS + ".",
        responses={
            (200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): OpenApiTypes.BINARY,
            403: GstErrorSerializer,
            404: GstErrorSerializer,
        },
    )
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

    serializer_class = RunReportSerializer
    permission_classes = [HasFirmPermission]
    required_permission = "gst.sign_off"

    @extend_schema(
        request=None,
        summary="Sign the reconciliation off",
        description=(
            "Locks the run. Requires `gst.sign_off` and, beyond the permission, being the client's "
            "lead or a firm administrator: a role that holds the permission can still get "
            "`403 forbidden`." + _ERRORS + _RULE
            + " (nothing has been matched yet, rows still need a decision, or already signed off)."
        ),
        responses=_responses(RunReportSerializer, rule=True),
    )
    def create(self, request, client_id=None, pk=None):
        client = get_visible_client(request, client_id)
        run = _run_of(client, pk)
        services.sign_off_run(run, request.user, request.membership)
        return Response(report.run_report(run))
