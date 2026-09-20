"""Shared view machinery.

Two things every endpoint here needs and none of them should restate.

**Tenant scoping.** ``TenantContextMiddleware`` has already bound the request's
firm before a view runs, so a query against a firm-scoped table is scoped by
PostgreSQL whether or not the view remembers to filter. The explicit
``firm_id=request.firm.pk`` filter in :class:`FirmScopedViewSet` is defence in
depth, not the mechanism -- RLS is the wall, this is the lock on the door, and
if one is ever misconfigured the other still holds.

**Client scoping.** Most endpoints hang off a client, because that is how a CA
firm thinks: not "show me statements" but "show me this client's statements".
:class:`ClientScopedMixin` resolves the client from the URL once and fails with
a 404 rather than an empty list, so a typo in an id is visible immediately.
"""

from __future__ import annotations

from rest_framework import viewsets

from api.pagination import DefaultPagination
from api.permissions import HasFirmPermission
from core.access import get_visible_client
from core.models import Client


class FirmScopedViewSet(viewsets.ModelViewSet):
    permission_classes = [HasFirmPermission]
    pagination_class = DefaultPagination

    def get_queryset(self):
        return super().get_queryset().filter(firm_id=self.request.firm.pk)

    def perform_create(self, serializer):
        serializer.save(firm_id=self.request.firm.pk)


class ClientScopedMixin:
    """For routes nested under ``/clients/{client_id}/``."""

    @property
    def client(self) -> Client:
        if not hasattr(self, "_client"):
            self._client = get_visible_client(self.request, self.kwargs["client_id"])
        return self._client

    def get_queryset(self):
        return super().get_queryset().filter(client=self.client)

    def perform_create(self, serializer):
        serializer.save(firm_id=self.request.firm.pk, client=self.client)
