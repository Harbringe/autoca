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

from api.views.assets import AssetViewSet
from api.views.assistant import NextBatchView
from api.views.audit import AuditLogView
from api.views.banking import (
    BankAccountViewSet,
    StatementUploadView,
    StatementViewSet,
    TransactionViewSet,
)
from api.views.billing import BillViewSet
from api.views.books import BooksView
from api.views.classify import (
    ClassificationViewSet,
    LedgerAccountViewSet,
    PartyViewSet,
    ReviewQueueViewSet,
    RuleViewSet,
)
from api.views.close import CloseView
from api.views.core import ClientViewSet, JobViewSet, MeView
from api.views.dashboard import ClientSnapshotView, PortfolioView
from api.views.documents import DocumentDownloadView, FirmDocumentListView
from api.views.gst import RegistrationViewSet, RunSignOffView, RunViewSet
from api.views.invoices import InvoiceReadingViewSet
from api.views.ledger import (
    ApprovalView,
    JournalEntryViewSet,
    ReconciliationView,
    ReportView,
)
from api.views.overview import FirmMetricsView, FirmOverviewView
from api.views.partyreports import OpenItemsView, OutstandingView
from api.views.payroll import EmployeeViewSet, PayrollRunViewSet
from api.views.tally import TallyImportViewSet
from api.views.tds import TdsChallanViewSet
from teams.views import FirmOwnerView, FirmSettingsView

app_name = "api"

#: Collections addressed by id, across clients but never across firms.
root = DefaultRouter()
root.register("clients", ClientViewSet, basename="client")
root.register("jobs", JobViewSet, basename="job")
root.register("transactions", TransactionViewSet, basename="transaction")
root.register("classifications", ClassificationViewSet, basename="classification")
root.register("journal-entries", JournalEntryViewSet, basename="journal-entry")
root.register("bank-accounts", ReconciliationView, basename="bank-account-reconciliation")

#: Everything that belongs to one client.
per_client = DefaultRouter()
per_client.register("bank-accounts", BankAccountViewSet, basename="client-bank-account")
per_client.register("statements", StatementViewSet, basename="client-statement")
per_client.register("ledgers", LedgerAccountViewSet, basename="client-ledger")
per_client.register("parties", PartyViewSet, basename="client-party")
per_client.register("bills", BillViewSet, basename="client-bill")
per_client.register("invoices", InvoiceReadingViewSet, basename="client-invoice")
per_client.register("tds", TdsChallanViewSet, basename="client-tds")
per_client.register("employees", EmployeeViewSet, basename="client-employee")
per_client.register("payroll", PayrollRunViewSet, basename="client-payroll")
per_client.register("assets", AssetViewSet, basename="client-asset")
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
    path("documents/", FirmDocumentListView.as_view(), name="documents"),
    path("documents/<uuid:pk>/download/", DocumentDownloadView.as_view(), name="document-download"),
    # Literal routes first, so intent beats pattern matching where both would
    # work at all.
    path(
        "clients/<uuid:client_id>/statements/preview/",
        StatementUploadView.as_view({"post": "preview"}),
        name="statement-preview",
    ),
    path(
        "clients/<uuid:client_id>/statements/upload/",
        StatementUploadView.as_view({"post": "create"}),
        name="statement-upload",
    ),
    path(
        "clients/<uuid:client_id>/open-items/",
        OpenItemsView.as_view({"get": "retrieve"}),
        name="open-items",
    ),
    path(
        "clients/<uuid:client_id>/outstanding/",
        OutstandingView.as_view({"get": "retrieve"}),
        name="outstanding",
    ),
    path(
        "clients/<uuid:client_id>/approvals/",
        ApprovalView.as_view({"post": "create"}),
        name="approvals",
    ),
    path(
        "clients/<uuid:client_id>/assistant/next-batch/",
        NextBatchView.as_view(),
        name="assistant-next-batch",
    ),
    path("clients/<uuid:client_id>/books/", BooksView.as_view({"get": "retrieve"}), name="books"),
    path(
        "clients/<uuid:client_id>/books/request/",
        BooksView.as_view({"post": "request_approval"}),
        name="books-request",
    ),
    path(
        "clients/<uuid:client_id>/books/return/",
        BooksView.as_view({"post": "return_books"}),
        name="books-return",
    ),
    path(
        "clients/<uuid:client_id>/books/close/",
        CloseView.as_view({"get": "retrieve"}),
        name="books-close",
    ),
    path(
        "clients/<uuid:client_id>/books/close/explain/",
        CloseView.as_view({"post": "explain"}),
        name="books-close-explain",
    ),
    path(
        "clients/<uuid:client_id>/books/close/withdraw/",
        CloseView.as_view({"post": "withdraw"}),
        name="books-close-withdraw",
    ),
    path(
        "clients/<uuid:client_id>/books/approve/",
        BooksView.as_view({"post": "approve"}),
        name="books-approve",
    ),
    path(
        "clients/<uuid:client_id>/books/sign-off/",
        BooksView.as_view({"post": "sign_off"}),
        name="books-sign-off",
    ),
    path(
        "clients/<uuid:client_id>/books/reopen/",
        BooksView.as_view({"post": "reopen"}),
        name="books-reopen",
    ),
    path(
        "clients/<uuid:client_id>/books/mark-reviewed/",
        BooksView.as_view({"post": "mark_reviewed"}),
        name="books-mark-reviewed",
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
    path(
        "clients/<uuid:client_id>/tally-imports/",
        TallyImportViewSet.as_view({"get": "list", "post": "create"}),
        name="tally-imports",
    ),
    path(
        "clients/<uuid:client_id>/tally-imports/<uuid:pk>/",
        TallyImportViewSet.as_view({"get": "retrieve"}),
        name="tally-import",
    ),
    path(
        "clients/<uuid:client_id>/tally-imports/<uuid:pk>/confirm/",
        TallyImportViewSet.as_view({"post": "confirm"}),
        name="tally-import-confirm",
    ),
    # GST reconciliation -- a removable add-on: delete this block, api/views/gst.py and gst/.
    path(
        "clients/<uuid:client_id>/gst/registrations/",
        RegistrationViewSet.as_view({"get": "list", "post": "create"}),
        name="gst-registrations",
    ),
    path(
        "clients/<uuid:client_id>/gst/runs/",
        RunViewSet.as_view({"get": "list", "post": "create"}),
        name="gst-runs",
    ),
    path(
        "clients/<uuid:client_id>/gst/runs/<uuid:pk>/",
        RunViewSet.as_view({"get": "retrieve"}),
        name="gst-run",
    ),
    path(
        "clients/<uuid:client_id>/gst/runs/<uuid:pk>/register/",
        RunViewSet.as_view({"post": "register"}),
        name="gst-run-register",
    ),
    path(
        "clients/<uuid:client_id>/gst/runs/<uuid:pk>/register-from-books/",
        RunViewSet.as_view({"post": "register_from_books"}),
        name="gst-run-register-from-books",
    ),
    path(
        "clients/<uuid:client_id>/gst/runs/<uuid:pk>/portal/",
        RunViewSet.as_view({"post": "portal"}),
        name="gst-run-portal",
    ),
    path(
        "clients/<uuid:client_id>/gst/runs/<uuid:pk>/reconcile/",
        RunViewSet.as_view({"post": "reconcile"}),
        name="gst-run-reconcile",
    ),
    path(
        "clients/<uuid:client_id>/gst/runs/<uuid:pk>/decisions/",
        RunViewSet.as_view({"post": "decide"}),
        name="gst-run-decide",
    ),
    path(
        "clients/<uuid:client_id>/gst/runs/<uuid:pk>/export/",
        RunViewSet.as_view({"get": "export"}),
        name="gst-run-export",
    ),
    path(
        "clients/<uuid:client_id>/gst/runs/<uuid:pk>/sign-off/",
        RunSignOffView.as_view({"post": "create"}),
        name="gst-run-sign-off",
    ),
    path("team/", include("teams.urls")),
    path("firm/", FirmSettingsView.as_view(), name="firm-settings"),
    path("firm/overview/", FirmOverviewView.as_view(), name="firm-overview"),
    path("firm/portfolio/", PortfolioView.as_view(), name="firm-portfolio"),
    path("clients/<uuid:client_id>/dashboard/", ClientSnapshotView.as_view(), name="client-dashboard"),
    path("firm/metrics/", FirmMetricsView.as_view(), name="firm-metrics"),
    path("firm/owner/", FirmOwnerView.as_view(), name="firm-owner"),
    path("audit/", AuditLogView.as_view(), name="audit-log"),
    path("", include(root.urls)),
    path("clients/<uuid:client_id>/", include(per_client.urls)),
]
