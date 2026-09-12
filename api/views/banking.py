"""Uploading statements, and reading what came out of them."""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.response import Response

from api.pagination import DefaultPagination
from api.permissions import HasFirmPermission
from api.serializers.banking import (
    BankAccountDetailSerializer,
    BankAccountSerializer,
    OpeningBalanceSerializer,
    StatementSerializer,
    StatementTransactionSerializer,
    StatementUploadSerializer,
)
from api.serializers.core import JobSerializer
from api.views.base import ClientScopedMixin, FirmScopedViewSet
from banking.ingest import confirm_opening_balance, ingest_statement
from banking.models import BankAccount, Statement, StatementTransaction
from classify.engine import classify_statement
from classify.seeds import seed_client
from core.jobs import run_job
from core.models import Client


@extend_schema(tags=["statements"])
class StatementUploadView(viewsets.GenericViewSet):
    """Upload a bank statement for a client."""

    serializer_class = StatementUploadSerializer
    permission_classes = [HasFirmPermission]
    parser_classes = [MultiPartParser, FormParser]
    required_permission = "document.upload"

    @extend_schema(
        summary="Upload a statement",
        description=(
            "Accepts the PDF and returns **202 Accepted** with a job. Poll "
            "`/api/v1/jobs/{id}/` or subscribe to its events.\n\n"
            "The bank is not asked for and cannot be supplied: it is read from the "
            "file. The statement itself is the authority on which account it "
            "belongs to, and a dropdown is one more way to file one against the "
            "wrong account.\n\n"
            "On success the job result carries `statement`, `rows_created`, "
            "`rows_already_present`, `needs_opening_confirmation` and the outcome "
            "of the first classification pass. Re-uploading the same file returns "
            "the original statement rather than a duplicate.\n\n"
            "Failures that are about the *file* rather than the request come back "
            "on the job with a code: `no_text_layer` (a scan -- OCR is not wired), "
            "`unsupported_bank`, `balance_chain_broken`, `statement_period_missing`."
        ),
        request=StatementUploadSerializer,
        responses={202: JobSerializer},
    )
    def create(self, request, client_id=None):
        client = get_object_or_404(Client, pk=client_id, firm_id=request.firm.pk)
        payload = self.get_serializer(data=request.data)
        payload.is_valid(raise_exception=True)

        upload = payload.validated_data["file"]
        data = upload.read()

        outcome = run_job(
            firm_id=request.firm.pk,
            kind="statement.ingest",
            user=request.user,
            message=f"Reading {upload.name}",
            work=lambda: _ingest(
                client=client,
                data=data,
                filename=upload.name,
                user=request.user,
                allow_gap=payload.validated_data["allow_gap"],
            ),
        )
        return Response(
            JobSerializer(outcome.job).data,
            status=status.HTTP_200_OK if outcome.reused else status.HTTP_202_ACCEPTED,
        )


def _ingest(*, client, data, filename, user, allow_gap) -> dict:
    """Ingest, seed the client's baseline ledgers, and classify in one pass.

    Seeding on every upload rather than at client creation is deliberate: a
    client created before the seeds existed would otherwise never get them, and
    the operation is idempotent.
    """
    result = ingest_statement(
        client=client,
        data=data,
        filename=filename,
        uploaded_by=user,
        allow_gap=allow_gap,
    )
    seed_client(client, created_by=user)
    classified = classify_statement(result.statement)

    return {
        "statement": str(result.statement.pk),
        "bank_account": str(result.bank_account.pk),
        "is_new": result.is_new,
        "rows_created": result.rows_created,
        "rows_already_present": result.rows_already_present,
        "needs_opening_confirmation": result.needs_opening_confirmation,
        "suggested": classified.placed,
        "queued_for_review": classified.queued,
    }


@extend_schema(tags=["statements"])
class BankAccountViewSet(ClientScopedMixin, FirmScopedViewSet):
    """A client's bank accounts.

    Created by uploading a statement, never by hand -- the account number comes
    from the file. Only the Tally ledger name is editable here.
    """

    queryset = BankAccount.objects.select_related("client").all()
    serializer_class = BankAccountSerializer
    http_method_names = ["get", "patch", "post", "head", "options"]
    required_permission = {"GET": "client.view", "PATCH": "ledger.manage", "POST": "ledger.manage"}

    def get_serializer_class(self):
        return BankAccountDetailSerializer if self.action == "retrieve" else self.serializer_class

    @extend_schema(
        summary="Confirm the opening balance",
        description=(
            "What the client's books actually started from. Pre-filled from the "
            "first statement's own opening line, but confirmed rather than "
            "assumed: a client onboarding in October has six months of history "
            "this system never saw, and starting them at that statement's opening "
            "figure misstates every balance from then on.\n\n"
            "Month-end reconciliation is not meaningful until this is set."
        ),
        request=OpeningBalanceSerializer,
        responses={200: BankAccountDetailSerializer},
    )
    @action(detail=True, methods=["post"], url_path="opening-balance")
    def opening_balance(self, request, client_id=None, pk=None):
        account = self.get_object()
        payload = OpeningBalanceSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        confirm_opening_balance(
            account,
            balance_paise=payload.validated_data["opening_balance_paise"],
            as_of=payload.validated_data["opening_as_of"],
        )
        return Response(BankAccountDetailSerializer(account).data)


@extend_schema(tags=["statements"])
class StatementViewSet(
    ClientScopedMixin, mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """Statements on file for a client."""

    queryset = Statement.objects.select_related("bank_account", "document").all()
    serializer_class = StatementSerializer
    permission_classes = [HasFirmPermission]
    pagination_class = DefaultPagination
    required_permission = "document.view"

    def get_queryset(self):
        return Statement.objects.filter(
            firm_id=self.request.firm.pk, bank_account__client=self.client
        ).select_related("bank_account", "document")

    @extend_schema(
        summary="The rows read out of a statement",
        description=(
            "Exactly as the bank printed them. Nothing here says what a "
            "transaction *means* -- that is a classification, and it points at "
            "these rows rather than changing them."
        ),
        parameters=[
            OpenApiParameter("page_size", int, description="Up to 500. Defaults to 50."),
        ],
        responses=StatementTransactionSerializer(many=True),
    )
    @action(detail=True, methods=["get"])
    def transactions(self, request, client_id=None, pk=None):
        statement = self.get_object()
        rows = statement.transactions.order_by("row_number")
        page = self.paginate_queryset(rows)
        serializer = StatementTransactionSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)


@extend_schema(tags=["statements"])
class TransactionViewSet(
    mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """Statement rows across every statement, for lookups by id."""

    queryset = StatementTransaction.objects.all()
    serializer_class = StatementTransactionSerializer
    permission_classes = [HasFirmPermission]
    pagination_class = DefaultPagination
    required_permission = "transaction.view"

    def get_queryset(self):
        return StatementTransaction.objects.filter(firm_id=self.request.firm.pk)
