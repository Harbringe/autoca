"""Uploading statements, and reading what came out of them."""

from __future__ import annotations

import hashlib

from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import MethodNotAllowed
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
from banking.removal import remove_statement
from classify.engine import classify_statement
from classify.queue import mark_waiting
from classify.seeds import rename_account_ledger, seed_client
from core.access import get_visible_client, visible_client_ids
from core.jobs import run_job
from core.models import Job, JobStatus


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
        client = get_visible_client(request, client_id)
        payload = self.get_serializer(data=request.data)
        payload.is_valid(raise_exception=True)

        upload = payload.validated_data["file"]
        data = upload.read()
        key = _upload_key(client, data)
        _drop_job_for_removed_statement(request.firm.pk, key)

        outcome = run_job(
            firm_id=request.firm.pk,
            kind="statement.ingest",
            user=request.user,
            idempotency_key=key,
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


def _upload_key(client, data: bytes) -> str:
    """The same file for the same client is the same job, however many times it is sent."""
    return "statement.ingest:" + hashlib.sha256(str(client.pk).encode() + b"|" + data).hexdigest()


def _drop_job_for_removed_statement(firm_id, key: str) -> None:
    """A finished job whose statement has since been removed must not stop a fresh upload."""
    job = Job.objects.filter(firm_id=firm_id, idempotency_key=key, status=JobStatus.SUCCEEDED).first()
    if job is None:
        return
    statement_id = (job.result or {}).get("statement")
    if not statement_id or not Statement.objects.filter(firm_id=firm_id, pk=statement_id).exists():
        job.delete()


def _ingest(*, client, data, filename, user, allow_gap) -> dict:
    """Ingest, seed the client's baseline ledgers, classify by rules, and queue what is left.

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

    # Whatever the rules left waits for the assistant, which reads it a few rows at a
    # time through the next-batch endpoint. The model is never asked from here: a
    # rate limit part-way through used to abandon the rest, and the wait sat inside
    # this request.
    waiting = mark_waiting(_unresolved_in(result.statement).filter(model_state__isnull=True))

    # What a rule is very sure of goes straight into the books, as a working
    # draft: nothing is permanent until a senior signs off, and each of these is
    # marked so a CA can find what nobody has yet looked at. The assistant's own
    # suggestions are posted the same way when its batch is applied.
    from ledger.approval import auto_post_client

    auto_posted = auto_post_client(client)

    return {
        "statement": str(result.statement.pk),
        "bank_account": str(result.bank_account.pk),
        "is_new": result.is_new,
        "rows_created": result.rows_created,
        "rows_already_present": result.rows_already_present,
        "needs_opening_confirmation": result.needs_opening_confirmation,
        "suggested": classified.placed,
        "queued_for_review": classified.queued,
        "waiting_for_assistant": waiting,
        "auto_posted": auto_posted,
        # Where this statement's own rows stand now, after rules and auto-posting.
        # The three always add up to the rows in the statement; the counters above are the
        # steps' own tallies, which overlap and are not for showing a person.
        **_where_rows_stand(result.statement),
    }


def _where_rows_stand(statement) -> dict:
    from classify.models import TransactionClassification

    rows = TransactionClassification.objects.filter(transaction__statement=statement).prefetch_related(
        "transaction__journal_entries"
    )
    posted = ready = unplaced = 0
    for row in rows:
        live = row.mirrored_entry_id or any(not e.is_superseded for e in row.transaction.journal_entries.all())
        if live:
            posted += 1
        elif row.ledger_id:
            ready += 1
        else:
            unplaced += 1
    return {"rows_posted": posted, "rows_ready_to_post": ready, "rows_need_ledger": unplaced}


def _unresolved_in(statement):
    """The statement's own unresolved rows, for the model tier."""
    from classify.models import TransactionClassification

    return TransactionClassification.objects.filter(
        firm_id=statement.firm_id, transaction__statement=statement, ledger__isnull=True
    )


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

    def create(self, request, *args, **kwargs):
        # POST stays routable for the opening-balance action, but an account is made by uploading a statement.
        raise MethodNotAllowed("POST")

    def get_serializer_class(self):
        return BankAccountDetailSerializer if self.action == "retrieve" else self.serializer_class

    def partial_update(self, request, *args, **kwargs):
        """Renaming the Tally ledger moves the existing ledger, entries and all."""
        account = self.get_object()
        payload = self.get_serializer(account, data=request.data, partial=True)
        payload.is_valid(raise_exception=True)
        posted_lines = 0
        if "ledger_name" in payload.validated_data:
            posted_lines = rename_account_ledger(account, payload.validated_data["ledger_name"])
        account.refresh_from_db()
        return Response({**self.get_serializer(account).data, "posted_lines": posted_lines})

    @extend_schema(
        summary="Confirm the opening balance",
        description=(
            "What the client's books actually started from. Pre-filled from the "
            "first statement's own opening line, but confirmed rather than "
            "assumed: a client onboarding in October has six months of history "
            "this system never saw, and starting them at that statement's opening "
            "figure misstates every balance from then on.\n\n"
            "Month-end reconciliation is not meaningful until this is set.\n\n"
            "Once the client's books are signed off on or after the opening date, a "
            "change is refused with 409 `entry_locked`; the client's senior CA or a "
            "firm administrator must reopen the books first."
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
    ClientScopedMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Statements on file for a client."""

    queryset = Statement.objects.select_related("bank_account", "document").all()
    serializer_class = StatementSerializer
    permission_classes = [HasFirmPermission]
    pagination_class = DefaultPagination
    required_permission = {
        "GET": "document.view",
        "HEAD": "document.view",
        "OPTIONS": "document.view",
        "DELETE": "statement.delete",
    }

    def get_queryset(self):
        return Statement.objects.filter(
            firm_id=self.request.firm.pk, bank_account__client=self.client
        ).select_related("bank_account", "document")

    @extend_schema(
        summary="Remove a statement uploaded by mistake",
        description=(
            "Removes the statement, its rows, the file, and every entry posted from it "
            "that is not yet signed off (each is kept in the change log). Refused with "
            "`entry_locked` if any of them is inside signed-off books. Rules and party "
            "names learned meanwhile are kept. Returns what was removed."
        ),
        responses={200: OpenApiTypes.OBJECT},
    )
    def destroy(self, request, client_id=None, pk=None):
        statement = self.get_object()
        removed = remove_statement(statement, actor=request.user)
        return Response(removed)

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
        return StatementTransaction.objects.filter(
            firm_id=self.request.firm.pk,
            bank_account__client__in=visible_client_ids(self.request.membership),
        )
