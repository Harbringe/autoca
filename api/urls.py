"""The v1 API.

Routes are nested the way a CA firm thinks. Not "list the statements" but "list
*this client's* statements" -- every piece of work happens in the context of one
client, and a URL that does not say which client is a URL that invites a missing
filter.

The exceptions are the by-id routes (``/transactions/{id}/``,
``/classifications/{id}/``, ``/journal-entries/{id}/``). Those exist because a
client holding an id from a list should be able to act on it without
reconstructing the path it came from. They are firm-scoped, never global.
"""

from __future__ import annotations

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from api.views.banking import (
    BankAccountViewSet,
    StatementUploadView,
    StatementViewSet,
    TransactionViewSet,
)
from api.views.classify import (
    ClassificationViewSet,
    LedgerAccountViewSet,
    ReviewQueueViewSet,
    RuleViewSet,
    VendorViewSet,
)
from api.views.core import ClientViewSet, JobViewSet, MeView
from api.views.ledger import (
    ApprovalView,
    JournalEntryViewSet,
    ReconciliationView,
    ReportView,
    TallyExportView,
)

app_name = "api"

#: Collections addressed by id, across clients but never across firms.
root = DefaultRouter()
root.register("clients", ClientViewSet, basename="client")
root.register("jobs", JobViewSet, basename="job")
root.register("transactions", TransactionViewSet, basename="transaction")
root.register("classifications", ClassificationViewSet, basename="classification")
root.register("journal-entries", JournalEntryViewSet, basename="journal-entry")
root.register("bank-accounts", ReconciliationView, basename="bank-account-reconciliation")
root.register("statements", TallyExportView, basename="statement-export")

#: Everything that belongs to one client.
per_client = DefaultRouter()
per_client.register("bank-accounts", BankAccountViewSet, basename="client-bank-account")
per_client.register("statements", StatementViewSet, basename="client-statement")
per_client.register("ledgers", LedgerAccountViewSet, basename="client-ledger")
per_client.register("vendors", VendorViewSet, basename="client-vendor")
per_client.register("rules", RuleViewSet, basename="client-rule")
per_client.register("review-queue", ReviewQueueViewSet, basename="client-review-queue")

#: Ids are UUIDs everywhere, so a router's detail route is pinned to that shape.
#: Without it ``statements/{pk}/`` matches ``statements/upload/`` -- the literal
#: route below is shadowed by the router, and a POST to it answers 405 from a
#: read-only detail view. Matching on shape is sturdier than relying on the
#: order of ``urlpatterns``, which a later edit could quietly reverse.
UUID_LOOKUP = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"

for _router in (root, per_client):
    for _prefix, _viewset, _basename in _router.registry:
        _viewset.lookup_value_regex = UUID_LOOKUP

urlpatterns = [
    path("me/", MeView.as_view(), name="me"),
    # Literal routes first, so intent beats pattern matching where both would
    # work at all.
    path(
        "clients/<uuid:client_id>/statements/upload/",
        StatementUploadView.as_view({"post": "create"}),
        name="statement-upload",
    ),
    path(
        "clients/<uuid:client_id>/approvals/",
        ApprovalView.as_view({"post": "create"}),
        name="approvals",
    ),
    path(
        "clients/<uuid:client_id>/reports/trial-balance/",
        ReportView.as_view({"get": "trial_balance"}),
        name="report-trial-balance",
    ),
    path(
        "clients/<uuid:client_id>/reports/profit-and-loss/",
        ReportView.as_view({"get": "profit_and_loss"}),
        name="report-profit-and-loss",
    ),
    path(
        "clients/<uuid:client_id>/reports/balance-sheet/",
        ReportView.as_view({"get": "balance_sheet"}),
        name="report-balance-sheet",
    ),
    path("", include(root.urls)),
    path("clients/<uuid:client_id>/", include(per_client.urls)),
]
