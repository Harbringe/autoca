"""The review queue, and the decisions made against it.

This is the part of the API a review screen is built on, so the shapes here are
chosen for that screen: a queue sorted by confidence, a summary that says how
much of it is bulk-approvable, and one endpoint per decision.
"""

from __future__ import annotations

import uuid

from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from api.pagination import DefaultPagination
from api.permissions import HasFirmPermission
from api.serializers.classify import (
    AcceptProposalSerializer,
    MergeProposalSerializer,
    ClassificationRuleSerializer,
    ClassificationSerializer,
    LedgerAccountSerializer,
    PlacementResultSerializer,
    RecategorizeSerializer,
    ReviewSummarySerializer,
    TreatmentSerializer,
    VendorSerializer,
)
from api.serializers.core import JobSerializer
from api.views.base import ClientScopedMixin, FirmScopedViewSet
from classify.engine import (
    pending_approval,
    review,
    review_queue,
    review_summary,
    unresolved_for,
)
from banking.models import Statement
from classify.llm import recategorize, suggest_unresolved
from classify.proposals import accept as accept_proposal
from classify.proposals import merge as merge_proposal
from classify.proposals import reject as reject_proposal
from classify.models import (
    ClassificationRule,
    LedgerAccount,
    LedgerStatus,
    TransactionClassification,
    Vendor,
)
from classify.treatment import ReviewBand, Treatment
from core.jobs import run_job
from core.models import Client
from core.rbac import has_permission

BANDS = (ReviewBand.HIGH, ReviewBand.ADVISED, ReviewBand.JUDGEMENT)


@extend_schema(tags=["review"])
class LedgerAccountViewSet(ClientScopedMixin, FirmScopedViewSet):
    """The client's chart of accounts."""

    queryset = LedgerAccount.objects.annotate(row_count=Count("classifications"))
    serializer_class = LedgerAccountSerializer
    required_permission = {
        "GET": "client.view",
        "POST": "ledger.manage",
        "PUT": "ledger.manage",
        "PATCH": "ledger.manage",
        "DELETE": "ledger.manage",
    }

    def perform_create(self, serializer):
        # A name a CA once rejected as a proposal is still a row; typing it in
        # by hand is a deliberate decision to use it, so revive it.
        existing = LedgerAccount.objects.filter(
            firm_id=self.request.firm.pk,
            client=self.client,
            name=serializer.validated_data["name"],
        ).exclude(status=LedgerStatus.ACTIVE).first()
        if existing is None:
            serializer.save(firm_id=self.request.firm.pk, client=self.client)
            return
        existing.status = LedgerStatus.ACTIVE
        existing.is_active = True
        existing.group = serializer.validated_data.get("group", existing.group)
        existing.save(update_fields=["status", "is_active", "group"])
        serializer.instance = existing

    def _decision(self, request):
        if not has_permission(request.membership, "journal.approve"):
            raise PermissionDenied("Accepting or rejecting a proposed ledger is for a Senior CA or firm admin.")
        return self.get_object()

    @extend_schema(
        summary="Accept a proposed ledger",
        description="Optionally rename it to match Tally. Rows already suggested into it stay as suggestions for review.",
        request=AcceptProposalSerializer,
        responses=LedgerAccountSerializer,
    )
    @action(detail=True, methods=["post"])
    def accept(self, request, client_id=None, pk=None):
        ledger = self._decision(request)
        payload = AcceptProposalSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        accept_proposal(ledger, **payload.validated_data)
        return Response(self.get_serializer(self.get_queryset().get(pk=ledger.pk)).data)

    @extend_schema(
        summary="Merge a proposed ledger into an existing one",
        request=MergeProposalSerializer,
        responses={200: None},
    )
    @action(detail=True, methods=["post"])
    def merge(self, request, client_id=None, pk=None):
        ledger = self._decision(request)
        payload = MergeProposalSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        into = get_object_or_404(
            LedgerAccount, pk=payload.validated_data["into"], firm_id=request.firm.pk, client=self.client
        )
        moved = merge_proposal(ledger, into)
        return Response({"moved": moved, "into": str(into.pk)})

    @extend_schema(
        summary="Reject a proposed ledger",
        description="Its rows return to the queue unresolved. The name is remembered so it is not proposed again.",
        request=None,
        responses={200: None},
    )
    @action(detail=True, methods=["post"])
    def reject(self, request, client_id=None, pk=None):
        ledger = self._decision(request)
        released = reject_proposal(ledger)
        return Response({"released": released})


@extend_schema(tags=["review"])
class VendorViewSet(ClientScopedMixin, FirmScopedViewSet):
    """Parties the client transacts with.

    Separate from ledger heads because they answer different questions: the
    ledger says what kind of expense it was, the vendor says who it was with.
    Reverse-charge and TDS defaults live here, because they are properties of
    who you are paying rather than of the category it was booked under.
    """

    queryset = Vendor.objects.all()
    serializer_class = VendorSerializer
    required_permission = {
        "GET": "client.view",
        "POST": "vendor.manage",
        "PUT": "vendor.manage",
        "PATCH": "vendor.manage",
        "DELETE": "vendor.manage",
    }


@extend_schema(tags=["review"])
class RuleViewSet(ClientScopedMixin, FirmScopedViewSet):
    """Rules that place transactions automatically.

    Mostly written by the system: every decision a reviewer makes mints one,
    keyed on the payee rather than the narration so it covers that payee
    permanently. Rules can also be created here by hand, which outranks anything
    learned.
    """

    queryset = ClassificationRule.objects.select_related("ledger", "vendor").all()
    serializer_class = ClassificationRuleSerializer
    required_permission = {
        "GET": "client.view",
        "POST": "suggestion.edit",
        "PUT": "suggestion.edit",
        "PATCH": "suggestion.edit",
        "DELETE": "suggestion.edit",
    }


@extend_schema(tags=["review"])
class ReviewQueueViewSet(
    ClientScopedMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """Everything still to be dealt with, surest first.

    "Still to be dealt with" means **not yet posted to the ledger** -- not "not
    yet looked at". A row a person has placed but nobody has approved is not
    finished work, and a queue that hid it is how a month closes short.
    """

    serializer_class = ClassificationSerializer
    permission_classes = [HasFirmPermission]
    pagination_class = DefaultPagination
    required_permission = "transaction.view"
    queryset = TransactionClassification.objects.none()

    @property
    def client(self) -> Client:
        if not hasattr(self, "_client"):
            self._client = get_object_or_404(
                Client, pk=self.kwargs["client_id"], firm_id=self.request.firm.pk
            )
        return self._client

    def get_queryset(self):
        band = self.request.query_params.get("band")
        stage = self.request.query_params.get("stage")
        if stage == "unresolved":
            return unresolved_for(self.client)
        if stage == "pending_approval":
            return pending_approval(self.client)
        return review_queue(self.client, band if band in BANDS else None)

    @extend_schema(
        summary="The review queue",
        parameters=[
            OpenApiParameter(
                "band",
                str,
                enum=list(BANDS),
                description=(
                    "HIGH is bulk-approvable. ADVISED is suggested but worth a look. "
                    "JUDGEMENT has no suggestion and needs a person."
                ),
            ),
            OpenApiParameter(
                "stage",
                str,
                enum=["unresolved", "pending_approval"],
                description=(
                    "`unresolved` is the half with no ledger yet; `pending_approval` "
                    "is the half waiting on a senior CA. Omit for both."
                ),
            ),
        ],
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Ask the model about every unresolved row",
        description=(
            "Runs the model tier over the rows no rule could place. Each row the "
            "model is confident about becomes a *suggestion* in the ADVISED band -- "
            "never HIGH, so never bulk-approvable -- with a one-line rationale. Rows "
            "it is not confident about stay unresolved, with the rationale attached. "
            "Returns **202** with a job; the result carries `suggested`, `declined` "
            "and `error` (empty unless the provider failed).\n\n"
            "Nothing identifying leaves the server: narrations are masked, people "
            "are pseudonymised, known vendors are aliased. Requires "
            "`transaction.classify`."
        ),
        request=None,
        responses={202: JobSerializer},
    )
    @action(detail=False, methods=["post"], url_path="suggest")
    def suggest(self, request, client_id=None):
        client = self.client
        if not has_permission(request.membership, "transaction.classify"):
            raise PermissionDenied("Your role does not permit transaction.classify.")

        def work():
            outcome = suggest_unresolved(client)
            return {
                "considered": outcome.considered,
                "suggested": outcome.suggested,
                "declined": outcome.declined,
                "proposed": outcome.proposed,
                "error": outcome.error,
            }

        outcome = run_job(
            firm_id=request.firm.pk,
            kind="classify.suggest",
            user=request.user,
            message=f"Asking the model about {client.name}'s unresolved rows",
            work=work,
        )
        return Response(JobSerializer(outcome.job).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        summary="Re-categorize with the model",
        description=(
            "Asks the model again about every row that is **not posted** and was "
            "**not placed by a person** -- rule placements, earlier model "
            "suggestions and unresolved rows alike. Pass `statement` to limit it "
            "to one statement.\n\n"
            "Where the model agrees with a rule, the rule's placement stands "
            "(`confirmed`). Where it disagrees, the row becomes a model suggestion "
            "in the ADVISED band, so a person sees the disagreement before it can "
            "be posted (`suggested`). Where it declines, nothing changes but the "
            "rationale (`declined`). Posted entries are immutable and never "
            "touched. Returns **202** with a job."
        ),
        request=RecategorizeSerializer,
        responses={202: JobSerializer},
    )
    @action(detail=False, methods=["post"], url_path="recategorize")
    def recategorize(self, request, client_id=None):
        client = self.client
        if not has_permission(request.membership, "transaction.classify"):
            raise PermissionDenied("Your role does not permit transaction.classify.")
        payload = RecategorizeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        statement_id = payload.validated_data.get("statement")
        statement = (
            get_object_or_404(
                Statement,
                pk=statement_id,
                firm_id=request.firm.pk,
                bank_account__client=client,
            )
            if statement_id
            else None
        )

        def work():
            outcome = recategorize(client, statement=statement)
            return {
                "considered": outcome.considered,
                "suggested": outcome.suggested,
                "confirmed": outcome.confirmed,
                "declined": outcome.declined,
                "proposed": outcome.proposed,
                "error": outcome.error,
            }

        scope = f"statement {statement.pk}" if statement else "all unposted rows"
        outcome = run_job(
            firm_id=request.firm.pk,
            kind="classify.recategorize",
            user=request.user,
            message=f"Re-categorizing {client.name}'s {scope} with the model",
            work=work,
        )
        return Response(JobSerializer(outcome.job).data, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        summary="How much work is waiting",
        responses=ReviewSummarySerializer,
        description=(
            "Split by how much thought each row needs. The ordering is the "
            "feature: it turns an hour of checking every row into minutes of "
            "checking the ones that need it."
        ),
    )
    @action(detail=False, methods=["get"])
    def summary(self, request, client_id=None):
        summary = review_summary(self.client)
        return Response(
            ReviewSummarySerializer(
                {
                    "high": summary.high,
                    "advised": summary.advised,
                    "judgement": summary.judgement,
                    "total": summary.total,
                    "bulk_approvable": summary.bulk_approvable,
                    "unresolved": unresolved_for(self.client).count(),
                    "pending_approval": pending_approval(self.client).count(),
                }
            ).data
        )


@extend_schema(tags=["review"])
class ClassificationViewSet(
    mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """One transaction's classification, and the decision endpoint."""

    serializer_class = ClassificationSerializer
    permission_classes = [HasFirmPermission]
    pagination_class = DefaultPagination
    queryset = TransactionClassification.objects.all()

    #: Reading a classification is open to anyone in the firm; changing one is
    #: preparing work, which read-only members may not do.
    required_permission = {
        "GET": "transaction.view",
        "POST": "transaction.classify",
    }

    def get_queryset(self):
        rows = TransactionClassification.objects.filter(
            firm_id=self.request.firm.pk
        ).select_related("transaction", "ledger", "vendor")
        statement = self.request.query_params.get("statement")
        if statement:
            try:
                rows = rows.filter(transaction__statement_id=uuid.UUID(statement))
            except ValueError:
                return rows.none()
        return rows

    @extend_schema(
        summary="Place a row in a ledger",
        description=(
            "Records the full treatment -- ledger head, party, reverse charge, TDS "
            "-- and, unless `learn` is false, teaches a rule from it. The rule is "
            "keyed on the payee rather than the narration, so it covers that payee "
            "permanently: placing one of nine identical cashback credits places "
            "all nine.\n\n"
            "This does **not** post anything to the ledger. It moves the row from "
            "the unresolved half of the queue to the half waiting for approval."
        ),
        request=TreatmentSerializer,
        responses={200: PlacementResultSerializer},
    )
    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        classification = self.get_object()
        payload = TreatmentSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        client = classification.transaction.bank_account.client
        ledger = get_object_or_404(
            LedgerAccount, pk=data["ledger"], firm_id=request.firm.pk, client=client
        )
        if ledger.status != LedgerStatus.ACTIVE:
            raise ValidationError(
                {"ledger": ["This ledger is only proposed. A CA has to accept it before rows can be placed in it."]}
            )
        if ledger.name == classification.transaction.bank_account.ledger_name:
            raise ValidationError(
                {"ledger": ["This is the bank account the transaction came from. Choose the other side of the entry."]}
            )
        vendor = (
            get_object_or_404(
                Vendor, pk=data["vendor"], firm_id=request.firm.pk, client=client
            )
            if data.get("vendor")
            else None
        )

        before = unresolved_for(client).count()
        updated, rule = review(
            classification,
            Treatment(
                ledger=ledger,
                vendor=vendor,
                rcm=data["rcm"],
                tds_section=data.get("tds_section", ""),
            ),
            user=request.user,
            learn=data["learn"],
        )
        after = unresolved_for(client).count()

        return Response(
            PlacementResultSerializer(
                {
                    "classification": updated,
                    "rule_learned": rule.pk if rule else None,
                    "also_placed": max(before - after - 1, 0),
                }
            ).data
        )
