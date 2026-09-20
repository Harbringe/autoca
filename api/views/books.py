"""The books' review workflow: request approval, return, sign off, reopen.

Thin over ``ledger.books``, which holds the rules. This module only turns a
request into a call, and the outcome into JSON.
"""

from __future__ import annotations

from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.response import Response

from api.permissions import HasFirmPermission
from core.access import can_post, can_sign_off, get_visible_client
from classify.engine import review_queue
from core.rbac import has_permission
from ledger import books
from ledger.editing import locked_through
from ledger.models import BooksEvent, EntryMarker, JournalEntry


class NoteSerializer(serializers.Serializer):
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)


class RequiredNoteSerializer(serializers.Serializer):
    note = serializers.CharField(max_length=1000, help_text="Why -- shown to whoever reads the history.")


class SignOffSerializer(serializers.Serializer):
    through = serializers.DateField(
        required=False,
        help_text="Lock everything dated on or before this. Defaults to the latest entry.",
    )
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=1000)


class MarkReviewedSerializer(serializers.Serializer):
    marker = serializers.ChoiceField(
        choices=[EntryMarker.AI_POSTED, EntryMarker.AI_REVISED],
        required=False,
        help_text="Clear only this kind of marker. Omit to clear both.",
    )


class BooksEventSerializer(serializers.ModelSerializer):
    action_display = serializers.CharField(source="get_action_display", read_only=True)
    actor_email = serializers.CharField(source="actor.email", read_only=True, allow_null=True)

    class Meta:
        model = BooksEvent
        fields = ["id", "action", "action_display", "through_date", "note", "actor_email", "created_at"]
        read_only_fields = fields


class BooksStatusSerializer(serializers.Serializer):
    signed_off_through = serializers.DateField(allow_null=True)
    review_pending = serializers.BooleanField()
    requested_by = serializers.CharField(allow_blank=True)
    requested_at = serializers.DateTimeField(allow_null=True)
    returned_note = serializers.CharField(allow_blank=True)
    waiting = serializers.IntegerField(help_text="Rows still needing a decision or a posting.")
    ai_posted = serializers.IntegerField(help_text="Entries the AI posted that nobody has yet looked at.")
    ai_revised = serializers.IntegerField(help_text="Entries the AI changed after a correction, unlooked-at.")
    can_request = serializers.BooleanField()
    can_sign_off = serializers.BooleanField()
    history = BooksEventSerializer(many=True)


@extend_schema(tags=["books"])
class BooksView(viewsets.GenericViewSet):
    """Where a client's books stand, and the steps that move them along."""

    permission_classes = [HasFirmPermission]
    required_permission = {"GET": "report.view", "POST": "books.request"}
    serializer_class = BooksStatusSerializer

    def _client(self, request, client_id):
        return get_visible_client(request, client_id)

    def _status(self, request, client) -> dict:
        current = books.status(client)
        through = locked_through(client.pk)
        unsigned = JournalEntry.objects.filter(firm_id=client.firm_id, client=client)
        if through is not None:
            unsigned = unsigned.filter(entry_date__gt=through)
        waiting = review_queue(client).count()
        return {
            "signed_off_through": current.signed_off_through,
            "review_pending": current.review_pending,
            "requested_by": current.requested_by,
            "requested_at": current.requested_at,
            "returned_note": current.returned_note,
            "waiting": waiting,
            "ai_posted": unsigned.filter(marker=EntryMarker.AI_POSTED).count(),
            "ai_revised": unsigned.filter(marker=EntryMarker.AI_REVISED).count(),
            "can_request": (
                has_permission(request.membership, "books.request")
                and can_post(request.membership, client)
                and not current.review_pending
                and waiting == 0
            ),
            "can_sign_off": (
                has_permission(request.membership, "books.sign_off")
                and can_sign_off(request.membership, client)
            ),
            "history": BooksEvent.objects.filter(firm_id=client.firm_id, client=client)
            .select_related("actor")
            .order_by("-created_at")[:20],
        }

    @extend_schema(summary="Where the books stand", responses={200: BooksStatusSerializer})
    def retrieve(self, request, client_id=None):
        client = self._client(request, client_id)
        return Response(BooksStatusSerializer(self._status(request, client)).data)

    def _respond(self, request, client, code=status.HTTP_200_OK):
        return Response(BooksStatusSerializer(self._status(request, client)).data, status=code)

    @extend_schema(
        summary="Request approval",
        description=(
            "A CA says the books are ready for a senior to look at. Refused while "
            "any transaction still needs a decision or has not been posted."
        ),
        request=NoteSerializer,
        responses={200: BooksStatusSerializer},
    )
    def request_approval(self, request, client_id=None):
        client = self._client(request, client_id)
        payload = NoteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        books.request_review(client, request.membership, payload.validated_data["note"])
        return self._respond(request, client)

    @extend_schema(
        summary="Return the books for changes",
        request=RequiredNoteSerializer,
        responses={200: BooksStatusSerializer},
    )
    def return_books(self, request, client_id=None):
        client = self._client(request, client_id)
        payload = RequiredNoteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        books.return_for_changes(client, request.membership, payload.validated_data["note"])
        return self._respond(request, client)

    @extend_schema(
        summary="Sign the books off",
        description=(
            "Locks everything up to the date signed. Voucher numbers are made "
            "contiguous first. After this the database itself refuses to change "
            "any of it; a later fix is a correcting entry dated after the sign-off."
        ),
        request=SignOffSerializer,
        responses={200: BooksStatusSerializer},
    )
    def sign_off(self, request, client_id=None):
        client = self._client(request, client_id)
        payload = SignOffSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        books.sign_off(
            client,
            request.membership,
            through=payload.validated_data.get("through"),
            note=payload.validated_data["note"],
        )
        return self._respond(request, client)

    @extend_schema(
        summary="Reopen signed-off books",
        request=RequiredNoteSerializer,
        responses={200: BooksStatusSerializer},
    )
    def reopen(self, request, client_id=None):
        client = self._client(request, client_id)
        payload = RequiredNoteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        books.reopen(client, request.membership, note=payload.validated_data["note"])
        return self._respond(request, client)

    @extend_schema(
        summary="Mark the AI's entries as looked at",
        description=(
            "Clears the 'posted by the AI' / 'changed by the AI' markers on entries "
            "that are not yet signed off, once a CA has checked them."
        ),
        request=MarkReviewedSerializer,
        responses={200: BooksStatusSerializer},
    )
    def mark_reviewed(self, request, client_id=None):
        client = self._client(request, client_id)
        if not has_permission(request.membership, "journal.correct") or not can_post(
            request.membership, client
        ):
            from django.core.exceptions import PermissionDenied

            raise PermissionDenied("You cannot review this client's entries.")
        payload = MarkReviewedSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        wanted = payload.validated_data.get("marker")

        entries = JournalEntry.objects.filter(firm_id=client.firm_id, client=client).exclude(
            marker=EntryMarker.NONE
        )
        through = locked_through(client.pk)
        if through is not None:
            # Signed-off entries cannot be touched, and a marker on one is moot.
            entries = entries.filter(entry_date__gt=through)
        if wanted:
            entries = entries.filter(marker=wanted)
        with transaction.atomic():
            entries.update(marker=EntryMarker.NONE)
            from classify.models import TransactionClassification

            if wanted in (None, EntryMarker.AI_REVISED):
                TransactionClassification.objects.filter(
                    firm_id=client.firm_id,
                    transaction__bank_account__client=client,
                    ai_revised=True,
                ).update(ai_revised=False)
        return self._respond(request, client)
