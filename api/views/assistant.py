"""The assistant's queue: read the next few waiting rows."""

from __future__ import annotations

from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.response import Response
from rest_framework.views import APIView

from api.permissions import HasFirmPermission
from api.serializers.classify import (
    AssistantPauseSerializer,
    NextBatchRequestSerializer,
    NextBatchSerializer,
)
from api.throttles import enforce
from classify.queue import process_next_batch
from core.access import get_visible_client
from core.db.session import firm_context


@extend_schema(tags=["review"])
class NextBatchView(APIView):
    """Ask the model about the next few waiting rows of one client."""

    permission_classes = [HasFirmPermission]
    required_permission = "transaction.classify"
    #: Read by ``TenantContextMiddleware``: this request is not wrapped in one transaction,
    #: because a model call must not hold one. Every phase opens its own ``firm_context``.
    opens_own_firm_context = True

    @extend_schema(
        summary="Read the next few waiting rows with the assistant",
        description=(
            "Reads one small batch (10 rows unless `max_rows` says otherwise, at most 15) "
            "of the rows the upload could not place, and returns at once with what "
            "happened and what to do next. Call it again while `state` is `working`; wait "
            "`retry_after_seconds` first when it is `paused`; stop when it is `idle`.\n\n"
            "A call takes about twenty seconds at most and never waits out a rate limit: "
            "it reports `paused` with the seconds to wait. `reason` says why: `rate_limit` "
            "(this minute's allowance), `daily_limit` (today's; the rest is for a person "
            "or for tomorrow), `provider_down`, or `assistant_off` (no model is "
            "configured, so nothing will ever be read and `state` is `idle`).\n\n"
            "Two windows open on the same client never read the same row. Rows the model "
            "is very sure of are posted automatically, marked as the assistant's, exactly as "
            "before. A row it cannot answer after three tries is left for a person. "
            "Requires `transaction.classify`."
        ),
        request=NextBatchRequestSerializer,
        responses={200: NextBatchSerializer},
    )
    def post(self, request, client_id=None):
        enforce(request, self, "model")
        payload = NextBatchRequestSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        with firm_context(request.firm.pk):
            client = get_visible_client(request, client_id)
        outcome = process_next_batch(client, max_rows=payload.validated_data.get("max_rows"))
        # A poll that did nothing leaves no permanent audit row.
        request._request.audit_skip = outcome.processed == 0
        return Response(NextBatchSerializer(outcome.as_dict()).data)


@extend_schema(tags=["review"])
class AssistantPauseView(APIView):
    """Pause the assistant for one client, and resume it."""

    permission_classes = [HasFirmPermission]
    required_permission = "transaction.classify"

    @extend_schema(
        summary="Pause the assistant for this client",
        description=(
            "Stops the background worker reading this client's waiting rows, and makes `next-batch` answer `paused` "
            "(`paused_by_person`). Nothing is lost: rows stay queued, rules still place what they can, and a statement can still be "
            "uploaded. It stays paused until someone resumes it (a restart does not end it). Pausing a paused client changes nothing. "
            "Requires `transaction.classify`."
        ),
        request=None,
        responses={200: AssistantPauseSerializer},
    )
    def post(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        if client.assistant_paused_at is None:
            client.assistant_paused_at = timezone.now()
            client.save(update_fields=["assistant_paused_at"])
        return Response(AssistantPauseSerializer({"paused": True, "paused_at": client.assistant_paused_at}).data)

    @extend_schema(
        summary="Resume the assistant for this client",
        description="The worker reads this client's waiting rows again, within a few seconds. Resuming a client that is not paused changes nothing.",
        responses={200: AssistantPauseSerializer},
    )
    def delete(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        if client.assistant_paused_at is not None:
            client.assistant_paused_at = None
            client.save(update_fields=["assistant_paused_at"])
        return Response(AssistantPauseSerializer({"paused": False, "paused_at": None}).data)
