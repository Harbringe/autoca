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
    ConfirmPartySerializer,
    LedgerAccountSerializer,
    PlacementResultSerializer,
    RecategorizeSerializer,
    ReviewSummarySerializer,
    TreatmentSerializer,
    PartySerializer,
)
from api.serializers.core import JobSerializer
from api.views.base import ClientScopedMixin, FirmScopedViewSet
from ledger.learning import learn_from_decision
from classify.engine import (
    confirm_party as confirm_party_decision,
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
    Party,
)
from classify.treatment import ReviewBand, Treatment
from core.jobs import run_job
from core.access import can_sign_off, get_visible_client, sign_off_refusal, visible_client_ids
from core.models import Client
from core.rbac import has_permission
from teams import activity
from teams.models import ActivityKind

BANDS = (ReviewBand.HIGH, ReviewBand.ADVISED, ReviewBand.JUDGEMENT)


@extend_schema(tags=["review"])
class LedgerAccountViewSet(ClientScopedMixin, FirmScopedViewSet):
    """The client's chart of accounts."""

    # Meta.ordering is dropped once annotate() adds a GROUP BY, so say it again.
    queryset = LedgerAccount.objects.annotate(row_count=Count("classifications")).order_by(
        "name", "pk"
    )
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
            name__iexact=serializer.validated_data["name"],
        ).exclude(status=LedgerStatus.ACTIVE).first()
        self._record(ActivityKind.LEDGER_CREATED)
        if existing is None:
            serializer.save(firm_id=self.request.firm.pk, client=self.client)
            return
        existing.status = LedgerStatus.ACTIVE
        existing.is_active = True
        existing.group = serializer.validated_data.get("group", existing.group)
        existing.save(update_fields=["status", "is_active", "group"])
        serializer.instance = existing

    def _record(self, kind):
        activity.record(
            firm_id=self.request.firm.pk, user=self.request.user, kind=kind, client=self.client
        )

    def _decision(self, request):
        if not has_permission(request.membership, "journal.approve"):
            raise PermissionDenied("Accepting or rejecting a proposed ledger is for a Senior CA or firm admin.")
        if not can_sign_off(request.membership, self.client):
            raise PermissionDenied(
                f"Only {self.client.name}'s lead or a firm administrator can decide its proposed ledgers."
            )
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
        self._record(ActivityKind.PROPOSAL_DECIDED)
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
        self._record(ActivityKind.PROPOSAL_DECIDED)
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
        self._record(ActivityKind.PROPOSAL_DECIDED)
        return Response({"released": released})


@extend_schema(tags=["review"])
class PartyViewSet(ClientScopedMixin, FirmScopedViewSet):
    """Parties the client transacts with.

    Separate from ledger heads because they answer different questions: the
    ledger says what kind of expense it was, the party says who it was with.
    Reverse-charge and TDS defaults live here, because they are properties of
    who you are paying rather than of the category it was booked under.
    """

    queryset = Party.objects.all()
    serializer_class = PartySerializer
    required_permission = {
        "GET": "client.view",
        "POST": "party.manage",
        "PUT": "party.manage",
        "PATCH": "party.manage",
        "DELETE": "party.manage",
    }


def _model_warning(outcome) -> str:
    """What to tell a person when the model could not do its part. Empty when it could."""
    if not getattr(outcome, "failed", False):
        return ""
    return (
        f"The model stopped before it finished ({outcome.error}). "
        "Rules were applied as usual, and the rows it did not reach are yours to place."
    )


def _refuse_if_posted(classification) -> None:
    """A posted row's entry is the record; changing the row would leave the two disagreeing."""
    from ledger.approval import AlreadyPostedError

    posted = classification.mirrored_entry_id or any(
        not entry.is_superseded for entry in classification.transaction.journal_entries.all()
    )
    if posted:
        raise AlreadyPostedError(
            "This row is already posted, so its ledger and party are part of a journal entry. "
            "To change it, correct the entry from the Day Book."
        )


@extend_schema(tags=["review"])
class RuleViewSet(ClientScopedMixin, FirmScopedViewSet):
    """Rules that place transactions automatically.

    Mostly written by the system: every decision a reviewer makes mints one,
    keyed on the payee rather than the narration so it covers that payee
    permanently. Rules can also be created here by hand, which outranks anything
    learned.
    """

    queryset = ClassificationRule.objects.select_related("ledger", "party").all()
    serializer_class = ClassificationRuleSerializer
    required_permission = {
        "GET": "client.view",
        "POST": "suggestion.edit",
        "PUT": "suggestion.edit",
        "PATCH": "suggestion.edit",
        "DELETE": "suggestion.edit",
    }

    def perform_create(self, serializer):
        super().perform_create(serializer)
        activity.record(
            firm_id=self.request.firm.pk,
            user=self.request.user,
            kind=ActivityKind.RULE_CREATED,
            client=self.client,
            subject_id=serializer.instance.pk,
        )


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
            self._client = get_visible_client(self.request, self.kwargs["client_id"])
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
            "model is confident about becomes a *suggestion* with a one-line "
            "rationale; its confidence sets the band, and a very confident one may be "
            "posted automatically (marked, and changeable until sign-off). Rows "
            "it is not confident about stay unresolved, with the rationale attached. "
            "Returns **202** with a job; the result carries `suggested`, `declined` "
            "and `error` (empty unless the provider failed).\n\n"
            "Nothing identifying leaves the server: narrations are masked, people "
            "are pseudonymised, known parties are aliased. Requires "
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
                "warning": _model_warning(outcome),
            }

        outcome = run_job(
            firm_id=request.firm.pk,
            kind="classify.suggest",
            user=request.user,
            message=f"Asking the model about {client.name}'s unresolved rows",
            work=work,
        )
        activity.record(
            firm_id=request.firm.pk, user=request.user, kind=ActivityKind.MODEL_RUN, client=client
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
                "warning": _model_warning(outcome),
            }

        scope = f"statement {statement.pk}" if statement else "all unposted rows"
        outcome = run_job(
            firm_id=request.firm.pk,
            kind="classify.recategorize",
            user=request.user,
            message=f"Re-categorizing {client.name}'s {scope} with the model",
            work=work,
        )
        activity.record(
            firm_id=request.firm.pk, user=request.user, kind=ActivityKind.MODEL_RUN, client=client
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
            firm_id=self.request.firm.pk,
            transaction__bank_account__client__in=visible_client_ids(self.request.membership),
        ).select_related("transaction__bank_account", "ledger", "party").order_by(
            # Statement order, so paging never repeats or skips a row.
            "transaction__value_date", "transaction__row_number", "pk"
        )
        statement = self.request.query_params.get("statement")
        if statement:
            try:
                rows = rows.filter(transaction__statement_id=uuid.UUID(statement))
            except ValueError:
                return rows.none()
        return rows

    @extend_schema(
        summary="Say who a row's payee is",
        description=(
            "Confirms which party this payee is, without placing the row in a "
            "ledger. The spelling is remembered, so the same spelling resolves "
            "on its own from now on, and every other unposted row for it is "
            "updated at once."
        ),
        request=ConfirmPartySerializer,
        responses={200: ClassificationSerializer},
    )
    @action(detail=True, methods=["post"], url_path="confirm-party")
    def confirm_party(self, request, pk=None):
        classification = self.get_object()
        _refuse_if_posted(classification)
        payload = ConfirmPartySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        client = classification.transaction.bank_account.client
        party = get_object_or_404(
            Party, pk=payload.validated_data["party"], firm_id=request.firm.pk, client=client
        )
        confirm_party_decision(classification, party, user=request.user)
        classification.refresh_from_db()
        return Response(ClassificationSerializer(classification).data)

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
        _refuse_if_posted(classification)
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
        party = (
            get_object_or_404(
                Party, pk=data["party"], firm_id=request.firm.pk, client=client
            )
            if data.get("party")
            else None
        )

        before = unresolved_for(client).count()
        updated, rule, revised, auto_posted = learn_from_decision(
            classification,
            Treatment(
                ledger=ledger,
                party=party,
                rcm=data["rcm"],
                tds_section=data.get("tds_section", ""),
            ),
            user=request.user,
            learn=data["learn"],
        )
        after = unresolved_for(client).count()
        also_placed = max(before - after - 1, 0)
        activity.record(
            firm_id=request.firm.pk,
            user=request.user,
            kind=ActivityKind.ROW_PLACED,
            client=client,
            quantity=1 + also_placed,
            subject_id=classification.pk,
        )

        return Response(
            PlacementResultSerializer(
                {
                    "classification": updated,
                    "rule_learned": rule.pk if rule else None,
                    "rule_created": bool(rule and getattr(rule, "just_created", False)),
                    "also_placed": also_placed,
                    "also_revised": revised,
                    "auto_posted": auto_posted,
                }
            ).data
        )
