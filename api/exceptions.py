"""Turning domain exceptions into HTTP responses that say something useful.

The exceptions this codebase raises were written to be read. "Balance chain
broke at row 30 (26-07-2025, 'NEFT/MB/AXOMB20702009852/...'): expected a balance
of ₹20,74,322.43 after applying -₹15,00,000.00, but the statement prints
₹5,74,322.43" tells a person exactly what to look at. Replacing that with
"400 Bad Request" throws away the entire value of having written it.

So the handler passes the message through, and adds a stable ``code`` beside it
for clients that need to branch on the kind of failure rather than parse prose.

The status codes are chosen to mean something:

* **422** -- the document is not what it claims to be, or cannot be read. The
  request was well-formed; the file was the problem.
* **409** -- the request conflicts with the current state. Already posted, a
  missing statement period, an entry already corrected. Retrying will not help
  until something changes.
* **403** -- a role boundary. Never silently downgraded to "not found".
* **404** -- nothing to act on.
"""

from __future__ import annotations

import logging

from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import ProtectedError
from django.http import Http404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

logger = logging.getLogger("autoca.api")

#: Exception class name -> (HTTP status, stable code). Kept as names rather than
#: classes so this module imports nothing from the feature apps and can be
#: loaded during settings evaluation.
DOMAIN_ERRORS = {
    # The document could not be read, or is not a statement.
    "NoTextLayerError": (status.HTTP_422_UNPROCESSABLE_ENTITY, "no_text_layer"),
    "UnsupportedBankError": (status.HTTP_422_UNPROCESSABLE_ENTITY, "unsupported_bank"),
    "ColumnInferenceError": (status.HTTP_422_UNPROCESSABLE_ENTITY, "columns_not_inferred"),
    "BalanceChainError": (status.HTTP_422_UNPROCESSABLE_ENTITY, "balance_chain_broken"),
    "StatementParseError": (status.HTTP_422_UNPROCESSABLE_ENTITY, "statement_unreadable"),
    "PdfExtractionError": (status.HTTP_422_UNPROCESSABLE_ENTITY, "unreadable_file"),
    "PdfTruncationError": (status.HTTP_422_UNPROCESSABLE_ENTITY, "pages_missing"),
    "PdfPasswordRequired": (status.HTTP_422_UNPROCESSABLE_ENTITY, "password_required"),
    "PdfPasswordIncorrect": (status.HTTP_422_UNPROCESSABLE_ENTITY, "password_incorrect"),
    "MoneyError": (status.HTTP_400_BAD_REQUEST, "bad_amount"),
    # The request conflicts with where things currently stand.
    "StatementContinuityError": (status.HTTP_409_CONFLICT, "statement_period_missing"),
    "StatementElsewhereError": (status.HTTP_409_CONFLICT, "statement_elsewhere"),
    "AlreadyPostedError": (status.HTTP_409_CONFLICT, "already_posted"),
    "NotApprovableError": (status.HTTP_409_CONFLICT, "not_approvable"),
    "ProposalError": (status.HTTP_409_CONFLICT, "proposal_conflict"),
    "LedgerRenameError": (status.HTTP_409_CONFLICT, "ledger_name_taken"),
    "TenantContextError": (status.HTTP_409_CONFLICT, "tenant_context"),
    "TeamError": (status.HTTP_409_CONFLICT, "team_rule"),
    # The books' review workflow, and the lock that follows sign-off.
    "NotReadyError": (status.HTTP_409_CONFLICT, "books_not_ready"),
    "AiEntriesUncheckedError": (status.HTTP_409_CONFLICT, "ai_entries_unchecked"),
    "NotApprovedError": (status.HTTP_409_CONFLICT, "approval_needed"),
    "NotASealDateError": (status.HTTP_409_CONFLICT, "not_a_seal_date"),
    "UnexplainedItemsError": (status.HTTP_409_CONFLICT, "open_items_unexplained"),
    "CloseError": (status.HTTP_422_UNPROCESSABLE_ENTITY, "close_rule"),
    "NothingRequestedError": (status.HTTP_409_CONFLICT, "nothing_requested"),
    "BooksError": (status.HTTP_409_CONFLICT, "books_state"),
    "EntryLockedError": (status.HTTP_409_CONFLICT, "entry_locked"),
    # Purchase and sales vouchers, bills and their settlement. Both are things a person can fix.
    "BillingError": (status.HTTP_422_UNPROCESSABLE_ENTITY, "billing_rule"),
    "IntakeError": (status.HTTP_422_UNPROCESSABLE_ENTITY, "invoice_intake"),
    "RectifyError": (status.HTTP_422_UNPROCESSABLE_ENTITY, "rectify_rule"),
    "AssetError": (status.HTTP_422_UNPROCESSABLE_ENTITY, "asset_rule"),
    "TdsError": (status.HTTP_422_UNPROCESSABLE_ENTITY, "tds_rule"),
    "PayrollError": (status.HTTP_422_UNPROCESSABLE_ENTITY, "payroll_rule"),
    "WrongEntryKindError": (status.HTTP_409_CONFLICT, "wrong_entry_kind"),
    "MachineEditRefusedError": (status.HTTP_409_CONFLICT, "machine_edit_refused"),
    "StatementRemovalError": (status.HTTP_409_CONFLICT, "statement_in_use"),
    "OpeningDiffersError": (status.HTTP_409_CONFLICT, "opening_differs"),
    # GST reconciliation: an unreadable upload, and a rule that refused the step.
    "GstParseError": (status.HTTP_422_UNPROCESSABLE_ENTITY, "gst_file_unreadable"),
    "GstError": (status.HTTP_409_CONFLICT, "gst_rule"),
    # Importing a client's chart and opening balances from Tally.
    "TallyParseError": (status.HTTP_422_UNPROCESSABLE_ENTITY, "tally_file_unreadable"),
    "TallyTooLargeError": (status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "tally_file_too_large"),
    "TallyYearMismatchError": (status.HTTP_422_UNPROCESSABLE_ENTITY, "tally_year_mismatch"),
    "TallyRunStaleError": (status.HTTP_409_CONFLICT, "tally_run_stale"),
    "TallyConflictsUnresolvedError": (status.HTTP_409_CONFLICT, "tally_conflicts_unresolved"),
    "TallyImportError": (status.HTTP_409_CONFLICT, "tally_rule"),
    # Nothing to act on.
    "NoStatementError": (status.HTTP_404_NOT_FOUND, "no_statement_for_date"),
}


def api_exception_handler(exc, context):
    """DRF's handler, with the domain's own exceptions given first refusal."""
    name = type(exc).__name__

    if name in DOMAIN_ERRORS:
        http_status, code = DOMAIN_ERRORS[name]
        detail = "; ".join(exc.messages) if isinstance(exc, DjangoValidationError) else str(exc)
        return Response({"code": code, "detail": detail}, status=http_status)

    if isinstance(exc, ProtectedError):
        # Deleting a ledger or a party that posted entries point at. The
        # journal is append-only, so the referencing rows cannot go either; the
        # answer is to deactivate it, and the message says so.
        return Response(
            {
                "code": "in_use",
                "detail": (
                    "This is referenced by posted journal entries and cannot be deleted. "
                    "Mark it inactive instead."
                ),
            },
            status=status.HTTP_409_CONFLICT,
        )

    if isinstance(exc, DjangoValidationError):
        # A malformed value that reached the ORM -- a query parameter that is
        # not a UUID, say. A client error, not a server one.
        return Response(
            {"code": "invalid", "detail": "; ".join(exc.messages)},
            status=status.HTTP_400_BAD_REQUEST,
        )

    if isinstance(exc, DjangoPermissionDenied):
        # Raised by ``core.rbac.require_permission`` deep inside the domain.
        # Surfaced as a 403 with its own message, which names the permission.
        return Response(
            {"code": "forbidden", "detail": str(exc) or "Not permitted."},
            status=status.HTTP_403_FORBIDDEN,
        )

    response = drf_exception_handler(exc, context)
    if response is not None:
        response.data = _normalise(response.data, exc)
        return response

    # Nothing recognised it. That is a bug, not an outcome: log it with a
    # traceback and return something that does not leak internals.
    logger.exception("unhandled exception in %s", context.get("view"))
    if isinstance(exc, Http404):
        return Response({"code": "not_found", "detail": "Not found."}, status=404)
    return Response(
        {"code": "internal_error", "detail": "Something went wrong. It has been logged."},
        status=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


def _normalise(data, exc):
    """Give DRF's own errors the same shape as the domain's.

    A client should not have to tell a validation error from a parse error by
    the shape of the body. Field errors keep their structure under ``fields``,
    because losing which field was wrong would be worse than consistency.
    """
    # Django's Http404 carries no code of its own; without this it would be reported as "error".
    code = "not_found" if isinstance(exc, Http404) else getattr(exc, "default_code", "error")
    if isinstance(data, dict) and "detail" in data and len(data) == 1:
        return {"code": code, "detail": str(data["detail"])}
    if isinstance(data, dict):
        return {"code": "invalid", "detail": "Some fields are invalid.", "fields": data}
    return {"code": code, "detail": data}
