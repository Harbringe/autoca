"""Importing a client's chart of accounts and opening balances from a Tally export.

Thin over ``ledger.tally_import``, which holds the rules. Every route is under
``clients/{id}/tally-imports/`` and resolves the client through
``get_visible_client``, so a client the caller cannot see is a 404; a run is then
looked up *within that client*. The role check (``ledger.import``: firm admin and
Senior CA) is the permission class, and the client's lead or a firm
administrator is the object rule, checked again inside the service.
"""

from __future__ import annotations

import os

from django.conf import settings
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from api.permissions import HasFirmPermission
from api.serializers.tally import (
    TallyBankReportUploadSerializer,
    TallyConfirmSerializer,
    TallyDiscoverSerializer,
    TallyDiscoveryResponseSerializer,
    TallyErrorSerializer,
    TallyImportDetailSerializer,
    TallyImportSummarySerializer,
    TallyImportUploadSerializer,
    TallyPostSerializer,
    TallyRefreshSerializer,
    TallySetupResultSerializer,
    TallySetupSerializer,
    TallyVoucherRunSerializer,
    TallyVoucherRunSummarySerializer,
    TallyVouchersUploadSerializer,
)
from core.access import get_visible_client
from ledger.models import ImportKind, ImportStatus, LedgerImportRun
from ledger.tally_import import confirm_run, stage_upload
from ledger.tally_jobs import enqueue_post
from ledger.tally_setup import apply_setup, discover_files
from ledger.tally_voucher_import import (
    discard_run,
    refresh_run,
    stage_bank_reports,
    stage_vouchers,
    undo_run,
)

_ERRORS = {
    400: TallyErrorSerializer,
    403: TallyErrorSerializer,
    404: TallyErrorSerializer,
}


@extend_schema(tags=["ledger"])
class TallyImportViewSet(viewsets.GenericViewSet):
    """Bring a client's ledgers and opening balances in from Tally."""

    permission_classes = [HasFirmPermission]
    required_permission = "ledger.import"
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = TallyImportDetailSerializer
    queryset = LedgerImportRun.objects.none()

    def _runs(self, request, client_id, kind=ImportKind.CHART_OPENING):
        client = get_visible_client(request, client_id)
        return client, LedgerImportRun.objects.filter(firm_id=request.firm.pk, client=client, kind=kind)

    @extend_schema(
        summary="Upload a Tally masters export and preview the import",
        description=(
            "Reads the file and returns a **preview**; nothing is changed. Ledgers in the file are "
            "compared with the client's chart by name (case, spacing and Unicode form ignored): each row "
            "is a `create`, a `match`, a `conflict` the person must settle, a `needs_group` (one of the "
            "firm's own Tally groups), or `skipped` with a reason. Opening balances are Debits positive.\n\n"
            "Accepts `.xml` (Tally's own export, UTF-8 or UTF-16), `.xlsx` or `.csv`, up to 10 MB; the "
            "kind is decided from the contents, not the name. The same file for the same year, with the "
            "chart unchanged, returns the existing preview with **200** instead of a new one.\n\n"
            "Firm administrators and Senior CAs (`ledger.import`), and only the client's lead or a firm "
            "administrator. Refused with `entry_locked` when the books are signed off through the start "
            "of the year."
        ),
        request=TallyImportUploadSerializer,
        responses={
            200: TallyImportDetailSerializer,
            201: TallyImportDetailSerializer,
            **_ERRORS,
            409: TallyErrorSerializer,
            413: TallyErrorSerializer,
            422: TallyErrorSerializer,
        },
    )
    def create(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        payload = TallyImportUploadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        upload = payload.validated_data["file"]
        data = upload.read(settings.MAX_TALLY_IMPORT_BYTES + 1)
        run, reused = stage_upload(
            client,
            request.membership,
            request.user,
            data=data,
            filename=os.path.basename(upload.name),
            financial_year=payload.validated_data["financial_year"],
            include_openings=payload.validated_data["include_openings"],
        )
        return Response(
            TallyImportDetailSerializer(run).data,
            status=status.HTTP_200_OK if reused else status.HTTP_201_CREATED,
        )

    @extend_schema(
        summary="Earlier Tally imports for a client",
        description="Newest first, the last 50, without their rows.",
        responses={200: TallyImportSummarySerializer(many=True), **_ERRORS},
    )
    def list(self, request, client_id=None):
        _client, runs = self._runs(request, client_id)
        return Response(TallyImportSummarySerializer(runs[:50], many=True).data)

    @extend_schema(
        summary="One Tally import, with its rows",
        responses={200: TallyImportDetailSerializer, **_ERRORS},
    )
    def retrieve(self, request, client_id=None, pk=None):
        _client, runs = self._runs(request, client_id)
        return Response(TallyImportDetailSerializer(get_object_or_404(runs, pk=pk)).data)

    @extend_schema(
        summary="Apply a previewed Tally import",
        description=(
            "Applies exactly what the person chose, in one transaction: creates the ledgers, applies "
            "the choices on conflicts, stores the opening balances (a bank account's opening goes to the "
            "bank account, once). **Idempotent**: confirming a run that was already applied returns it "
            "unchanged.\n\n"
            "Every row whose `action` is `conflict` or `needs_group`, and every `bank` panel with "
            "status `conflict`, needs a resolution; otherwise `409 tally_conflicts_unresolved` and nothing is "
            "written. `409 tally_run_stale` when the client's ledgers or openings changed since the preview "
            "(upload again). `409 entry_locked` when the books are signed off through the start of the "
            "year. A group cannot be changed on a ledger with posted lines (`409 tally_rule`)."
        ),
        request=TallyConfirmSerializer,
        responses={200: TallyImportDetailSerializer, **_ERRORS, 409: TallyErrorSerializer},
    )
    def confirm(self, request, client_id=None, pk=None):
        client, runs = self._runs(request, client_id)
        run = get_object_or_404(runs, pk=pk)
        payload = TallyConfirmSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        run = confirm_run(run, request.membership, request.user, payload.validated_data["resolutions"])
        return Response(TallyImportDetailSerializer(run).data)

    @extend_schema(
        summary="Upload a Tally vouchers export and preview importing it",
        description=(
            "Reads the vouchers and returns a **preview**; nothing is posted. Each voucher is `post` or `skip` with a "
            "reason (a ledger not in the client's chart, unbalanced, cancelled, a bank voucher that waits for a later "
            "release...). The vouchers are written exactly as Tally had them, so the client's ledgers must be imported "
            "first.\n\n"
            "Refused with `409 tally_rule` when the period already has entries for the client, `409 entry_locked` when "
            "it reaches a signed-off date, and `409 tally_rule` for a file with more than one company. The same file "
            "with the chart unchanged returns the existing preview with **200**. Same roles as the masters import."
        ),
        request=TallyVouchersUploadSerializer,
        responses={
            200: TallyVoucherRunSerializer,
            201: TallyVoucherRunSerializer,
            **_ERRORS,
            409: TallyErrorSerializer,
            413: TallyErrorSerializer,
            422: TallyErrorSerializer,
        },
    )
    @action(detail=False, methods=["post"], url_path="vouchers")
    def vouchers(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        payload = TallyVouchersUploadSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        upload = payload.validated_data["file"]
        data = upload.read(settings.MAX_TALLY_IMPORT_BYTES + 1)
        run, reused = stage_vouchers(
            client,
            request.membership,
            request.user,
            data=data,
            filename=os.path.basename(upload.name),
            date_from=payload.validated_data.get("date_from"),
            date_to=payload.validated_data.get("date_to"),
            voucher_types=payload.validated_data.get("voucher_types"),
        )
        return Response(
            TallyVoucherRunSerializer(run).data,
            status=status.HTTP_200_OK if reused else status.HTTP_201_CREATED,
        )

    @extend_schema(
        summary="Post a previewed Tally vouchers import",
        description=(
            "Writes each voucher the preview marked `post`, in date order, each in its own transaction: one that fails is "
            "listed in `result.failed` and the rest go on. **Idempotent**: confirming an applied run returns it unchanged, "
            "and a voucher already imported is never written twice. `409 tally_run_stale` when the client's ledgers changed "
            "since the preview."
        ),
        request=None,
        responses={200: TallyVoucherRunSerializer, **_ERRORS, 409: TallyErrorSerializer},
    )
    @action(detail=True, methods=["post"], url_path="confirm-vouchers")
    def confirm_vouchers(self, request, client_id=None, pk=None):
        _client, runs = self._runs(request, client_id, ImportKind.VOUCHERS)
        run = get_object_or_404(runs.select_related("client", "document", "uploaded_by"), pk=pk)
        if run.status == ImportStatus.CONFIRMED:
            return Response(TallyVoucherRunSerializer(run).data)
        payload = TallyPostSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        enqueue_post(run, request.membership, request.user, allow_overlap=payload.validated_data["allow_overlap"])
        run.refresh_from_db()
        return Response(TallyVoucherRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        summary="The imports waiting to be posted, being posted, or done, newest first",
        description="The client's queue of Tally vouchers imports, without their voucher rows (read one to see those).",
        responses={200: TallyVoucherRunSummarySerializer(many=True), **_ERRORS},
    )
    @action(detail=False, methods=["get"], url_path="voucher-runs")
    def voucher_runs(self, request, client_id=None):
        _client, runs = self._runs(request, client_id, ImportKind.VOUCHERS)
        runs = runs.select_related("document", "uploaded_by").order_by("-created_at")[:200]
        return Response(TallyVoucherRunSummarySerializer(runs, many=True).data)

    @extend_schema(
        summary="One queued import with its voucher rows",
        responses={200: TallyVoucherRunSerializer, **_ERRORS},
    )
    @action(detail=True, methods=["get"], url_path="voucher-run")
    def voucher_run(self, request, client_id=None, pk=None):
        _client, runs = self._runs(request, client_id, ImportKind.VOUCHERS)
        run = get_object_or_404(runs.select_related("document", "uploaded_by"), pk=pk)
        return Response(TallyVoucherRunSerializer(run).data)

    @extend_schema(
        summary="Read a queued import's stored file again against the client's ledgers as they are now",
        description="Replaces the queued import with a fresh reading of the same file; nothing is uploaded again. Optionally says what the firm's own voucher types count as.",
        request=TallyRefreshSerializer,
        responses={200: TallyVoucherRunSerializer, **_ERRORS, 409: TallyErrorSerializer},
    )
    @action(detail=True, methods=["post"], url_path="refresh-vouchers")
    def refresh_vouchers(self, request, client_id=None, pk=None):
        _client, runs = self._runs(request, client_id, ImportKind.VOUCHERS)
        run = get_object_or_404(runs.select_related("client", "document"), pk=pk)
        payload = TallyRefreshSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        fresh = refresh_run(run, request.membership, request.user, voucher_types=payload.validated_data.get("voucher_types"))
        return Response(TallyVoucherRunSerializer(fresh).data)

    @extend_schema(
        summary="Take a queued import out of the queue",
        description="The stored file stays with the client's documents.",
        request=None,
        responses={200: TallyVoucherRunSerializer, **_ERRORS, 409: TallyErrorSerializer},
    )
    @action(detail=True, methods=["post"], url_path="discard")
    def discard(self, request, client_id=None, pk=None):
        _client, runs = self._runs(request, client_id, ImportKind.VOUCHERS)
        run = discard_run(get_object_or_404(runs.select_related("client", "document"), pk=pk), request.membership)
        return Response(TallyVoucherRunSerializer(run).data)

    @extend_schema(
        summary="Undo an applied Tally vouchers import",
        description=(
            "Takes every entry and bill the run wrote back out. Refused with `409 tally_rule` once a payment or adjustment "
            "is applied to one of its bills, and `409 entry_locked` when any of its entries is now inside signed-off books."
        ),
        request=None,
        responses={200: TallyVoucherRunSerializer, **_ERRORS, 409: TallyErrorSerializer},
    )
    @action(detail=True, methods=["post"], url_path="undo")
    def undo(self, request, client_id=None, pk=None):
        _client, runs = self._runs(request, client_id, ImportKind.VOUCHERS)
        run = undo_run(get_object_or_404(runs, pk=pk), request.membership, request.user)
        return Response(TallyVoucherRunSerializer(run).data)

    @extend_schema(
        summary="Read Tally files and propose the ledgers and bank accounts they use",
        description=(
            "Reads any mix of voucher exports and bank ledger reports and returns what the client would need: the ledgers the files use "
            "that the client does not have, each with the group the files suggest and why, and the bank, loan or card accounts among "
            "them. **Writes nothing.** A bank report's own bank ledger is told from its file name where possible; otherwise it is given in "
            "`bank_ledgers`, and until then its rows' other ledgers are not proposed."
        ),
        request=TallyDiscoverSerializer,
        responses={200: TallyDiscoveryResponseSerializer, **_ERRORS, 409: TallyErrorSerializer, 413: TallyErrorSerializer, 422: TallyErrorSerializer},
    )
    @action(detail=False, methods=["post"], url_path="discover")
    def discover(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        given_data = {"files": request.FILES.getlist("files")}
        if request.data.get("bank_ledgers"):  # absent is not null: the field takes a value or nothing
            given_data["bank_ledgers"] = request.data.get("bank_ledgers")
        payload = TallyDiscoverSerializer(data=given_data)
        payload.is_valid(raise_exception=True)
        given = payload.validated_data.get("bank_ledgers")
        if isinstance(given, str):
            import json

            try:
                given = json.loads(given) if given else {}
            except ValueError:
                given = {}
        files = [(os.path.basename(u.name), u.read(settings.MAX_TALLY_IMPORT_BYTES + 1)) for u in payload.validated_data["files"]]
        return Response(discover_files(client, request.membership, files, given if isinstance(given, dict) else {}))

    @extend_schema(
        summary="Create the ledgers and bank accounts a person confirmed from the files",
        description=(
            "Creates exactly the ledgers listed, each in the group given, and the bank accounts listed that have an account number, each "
            "tied to the ledger of the same name. Existing ledgers are left alone. All or nothing."
        ),
        request=TallySetupSerializer,
        responses={200: TallySetupResultSerializer, **_ERRORS, 409: TallyErrorSerializer},
    )
    @action(detail=False, methods=["post"], url_path="setup")
    def set_up(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        payload = TallySetupSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        return Response(apply_setup(client, request.membership, request.user, **payload.validated_data))

    @extend_schema(
        summary="Upload Tally bank ledger reports and preview importing them",
        description=(
            "Each row of the report becomes a bank entry between the chosen bank account and the row's other ledger, through the same preview "
            "as a vouchers export; confirm it with `confirm-vouchers`. A row where Tally shows several ledgers is left out with the reason."
        ),
        request=TallyBankReportUploadSerializer,
        responses={200: TallyVoucherRunSerializer, 201: TallyVoucherRunSerializer, **_ERRORS, 409: TallyErrorSerializer, 413: TallyErrorSerializer, 422: TallyErrorSerializer},
    )
    @action(detail=False, methods=["post"], url_path="bank-report")
    def bank_report(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        upload = {
            "files": request.FILES.getlist("files"),
            "accounts": request.data.getlist("accounts") if hasattr(request.data, "getlist") else request.data.get("accounts", []),
        }
        for field in ("date_from", "date_to"):  # absent is not null: leave a field out rather than send it empty
            if request.data.get(field):
                upload[field] = request.data.get(field)
        payload = TallyBankReportUploadSerializer(data=upload)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        reports = [
            (os.path.basename(u.name), u.read(settings.MAX_TALLY_IMPORT_BYTES + 1), account)
            for u, account in zip(data["files"], data["accounts"], strict=True)
        ]
        run, reused = stage_bank_reports(
            client, request.membership, request.user, reports=reports, date_from=data.get("date_from"), date_to=data.get("date_to")
        )
        return Response(TallyVoucherRunSerializer(run).data, status=status.HTTP_200_OK if reused else status.HTTP_201_CREATED)
