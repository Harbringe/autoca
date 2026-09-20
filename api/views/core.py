"""Session, clients, and job progress."""

from __future__ import annotations

import json
import time

from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from api.pagination import DefaultPagination
from api.permissions import IsFirmMember
from api.serializers.core import ClientSerializer, JobSerializer, MeSerializer
from api.views.base import FirmScopedViewSet
from core.access import visible_clients
from core.models import Client, Job, JobStatus, Role


@extend_schema(tags=["session"])
class MeView(APIView):
    """Who is signed in, which firm they are bound to, and what they may do."""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        responses=MeSerializer,
        summary="The current session",
        description=(
            "The permission list lets a client hide what it must not offer. That is "
            "presentation only -- every permission is checked again server-side, "
            "because a hidden button is not a permission system."
        ),
    )
    def get(self, request):
        return Response(MeSerializer(MeSerializer.for_request(request)).data)


@extend_schema(tags=["clients"])
class ClientViewSet(FirmScopedViewSet):
    """The firm's clients."""

    serializer_class = ClientSerializer
    queryset = Client.objects.select_related("lead__user")
    search_fields = ["name"]
    required_permission = {
        "GET": "client.view",
        "POST": "client.create",
        "PUT": "client.update",
        "PATCH": "client.update",
        "DELETE": "client.delete",
    }

    def get_queryset(self):
        queryset = super().get_queryset().filter(pk__in=visible_clients(self.request.membership).values("pk"))
        search = self.request.query_params.get("search")
        return queryset.filter(name__icontains=search) if search else queryset

    @extend_schema(
        parameters=[
            OpenApiParameter("search", str, description="Filter by name, case-insensitive.")
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        from ledger.models import JournalEntry

        client = self.get_object()
        posted = JournalEntry.objects.filter(client=client).count()
        if posted:
            return Response(
                {
                    "code": "in_use",
                    "detail": (
                        f"{client.name} has {posted} posted journal entr{'y' if posted == 1 else 'ies'}. "
                        "The books are permanent, so a client with posted entries can't be deleted."
                    ),
                },
                status=409,
            )
        return super().destroy(request, *args, **kwargs)


@extend_schema(tags=["jobs"])
class JobViewSet(mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet):
    """Progress on work the API did not block for.

    Every endpoint that starts slow work answers 202 with one of these. Poll it,
    or subscribe to ``events`` for the same thing pushed.
    """

    serializer_class = JobSerializer
    permission_classes = [IsFirmMember]
    pagination_class = DefaultPagination
    queryset = Job.objects.all()

    def get_queryset(self):
        jobs = Job.objects.filter(firm_id=self.request.firm.pk)
        # A job's message and result name the client it ran for. Firm admins see
        # every job; everyone else sees the jobs they started.
        if self.request.membership.role == Role.FIRM_ADMIN:
            return jobs
        return jobs.filter(created_by=self.request.user)

    @extend_schema(
        summary="Follow a job as it progresses",
        description=(
            "Server-sent events. Each message is a JSON job object; the stream "
            "closes once the job reaches a terminal state.\n\n"
            "Work currently runs inline, so a job is already finished by the time "
            "its id is returned and this stream will usually emit one message and "
            "close. The contract is here so that moving execution onto a worker "
            "changes nothing a client can see."
        ),
        responses={(200, "text/event-stream"): None},
    )
    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        job = get_object_or_404(self.get_queryset(), pk=pk)
        response = StreamingHttpResponse(
            _job_events(self.get_queryset(), job.pk), content_type="text/event-stream"
        )
        # nginx buffers proxied responses by default, which would hold every
        # message until the stream closed and make this pointless.
        response["Cache-Control"] = "no-cache"
        response["X-Accel-Buffering"] = "no"
        return response


def _job_events(queryset, job_id, *, poll_seconds: float = 0.5, timeout_seconds: float = 30.0):
    """Yield the job until it finishes, then stop.

    Bounded by a timeout so a wedged job cannot hold a worker thread open
    forever; a client that hits the timeout reconnects or falls back to polling.
    """
    deadline = time.monotonic() + timeout_seconds
    while True:
        job = queryset.filter(pk=job_id).first()
        if job is None:
            return
        yield f"data: {json.dumps(JobSerializer(job).data, default=str)}\n\n"
        if job.status in JobStatus.terminal() or time.monotonic() > deadline:
            return
        time.sleep(poll_seconds)
