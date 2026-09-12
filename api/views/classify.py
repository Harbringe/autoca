"""The review queue, and the decisions made against it.

This is the part of the API a review screen is built on, so the shapes here are
chosen for that screen: a queue sorted by confidence, a summary that says how
much of it is bulk-approvable, and one endpoint per decision.
"""

from __future__ import annotations

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.pagination import DefaultPagination
from api.permissions import HasFirmPermission
from api.serializers.classify import (
    ClassificationRuleSerializer,
    ClassificationSerializer,
    LedgerAccountSerializer,
    PlacementResultSerializer,
    ReviewSummarySerializer,
    TreatmentSerializer,
    VendorSerializer,
)
from api.views.base import ClientScopedMixin, FirmScopedViewSet
from classify.engine import (
    pending_approval,
    review,
    review_queue,
    review_summary,
    unresolved_for,
)
from classify.models import (
    ClassificationRule,
    LedgerAccount,
    TransactionClassification,
    Vendor,
)
from classify.treatment import ReviewBand, Treatment
from core.models import Client

BANDS = (ReviewBand.HIGH, ReviewBand.ADVISED, ReviewBand.JUDGEMENT)


@extend_schema(tags=["review"])
class LedgerAccountViewSet(ClientScopedMixin, FirmScopedViewSet):
    """The client's chart of accounts."""

    queryset = LedgerAccount.objects.all()
    serializer_class = LedgerAccountSerializer
    required_permission = {
        "GET": "client.view",
        "POST": "ledger.manage",
        "PUT": "ledger.manage",
        "PATCH": "ledger.manage",
        "DELETE": "ledger.manage",
    }


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
        return TransactionClassification.objects.filter(
            firm_id=self.request.firm.pk
        ).select_related("transaction", "ledger", "vendor")

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
