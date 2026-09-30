"""Per-request tenant context.

Position in MIDDLEWARE matters and is asserted by ``core.checks``:

* AFTER ``AuthenticationMiddleware`` and ``OTPMiddleware`` -- it needs an
  authenticated, second-factor-verified user to know which firm to bind.
* BEFORE ``AuditMiddleware`` -- audit rows are themselves firm-scoped, so the
  audit writer has to run inside the context this opens.

The transaction is opened here rather than relying on ``ATOMIC_REQUESTS``,
because ``ATOMIC_REQUESTS`` wraps only the view. The tenant setting has to be
established before anything -- including other middleware, and including a
context processor that touches the ORM -- can issue a query.

What happens when there is no firm context: nothing special. The request runs,
and any query against a firm-scoped table raises ``InsufficientPrivilege`` from
``app.current_firm_id()``. That is the deny-by-default behaviour, and it is
enforced in Postgres rather than here, so it holds for code that never passes
through this middleware at all.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import JsonResponse
from django.urls import Resolver404, resolve
from django.utils.module_loading import import_string

from core.db.session import _apply, _apply_user
from core.http import wants_json
from core.models import FirmMembership

logger = logging.getLogger("autoca.tenancy")


def resolve_membership(user):
    """The active membership for ``user``, or None.

    Touches ``core_firm_membership`` and nothing else. No ``select_related``, no
    ``firm__is_active`` filter -- either would join ``core_firm``, whose policy
    raises when no firm context is set, and we are running precisely to
    establish that context. The firm is loaded, and its active flag checked, one
    step later once the context exists.

    Single role per firm-user today, so there is at most one active membership
    and nothing to choose between. When a user may belong to several firms, this
    is the one function that changes: it will read the selected firm from the
    session and validate it against the memberships.
    """
    if not user or not user.is_authenticated:
        return None
    return FirmMembership.objects.filter(user=user, is_active=True).order_by("created_at").first()


def opens_own_firm_context(request) -> bool:
    """Does the view about to run say it opens its own ``firm_context``?

    A view that must call something slow (a model provider) cannot sit inside a
    transaction that holds a connection and its locks for the whole call, so it
    opts out with ``opens_own_firm_context = True`` on its class -- an explicit
    marker, not a path pattern. Nothing else changes: the request still needs a
    verified user and an active firm membership, and every query the view makes
    outside its own ``firm_context`` is refused by the database.
    """
    try:
        match = resolve(request.path_info, getattr(request, "urlconf", None))
    except Resolver404:
        return False
    return getattr(getattr(match.func, "cls", None), "opens_own_firm_context", False) is True


class TenantContextMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)

        if not user or not user.is_authenticated:
            request.firm = None
            request.membership = None
            return self.get_response(request)

        # Two-stage context. The membership lookup cannot run under a firm
        # context, because reading it is how the firm is discovered. Instead of
        # bypassing RLS for that one query, we set the *user* context first;
        # the membership table's policy accepts either. See core/db/rls.py.
        with transaction.atomic():
            _apply_user(str(user.pk), "default")
            membership = resolve_membership(user)

            if _firmless_allowed(request, membership):
                # Only the user context is set; firm-scoped tables still raise.
                request.firm = None
                request.membership = None
                return self.get_response(request)

            if membership is None:
                logger.warning(
                    "authenticated user %s has no active firm membership; "
                    "serving with no tenant context",
                    user.pk,
                )
                request.firm = None
                request.membership = None
                return _refuse(
                    request, "no_firm", "Your account is not attached to an active firm."
                )

            firm_id = str(membership.firm_id)
            _apply(firm_id, "default")

            # Now that the context is set, the firm row is readable -- and the
            # policy guarantees it is that firm's row and no other.
            firm = membership.firm
            if not firm.is_active:
                return _refuse(request, "firm_inactive", "This firm has been deactivated.")

            request.firm = firm
            request.membership = membership
            request.firm_id = firm_id

            if not opens_own_firm_context(request):
                return self.get_response(request)

            # Cleared explicitly: the local settings would go with the commit, but a test
            # runs inside one outer transaction that a savepoint release does not revert.
            _apply("", "default")
            _apply_user("", "default")

        # The view runs with no transaction and no tenant context of its own making;
        # a query outside a firm_context it opens itself is refused by Postgres.
        return self.get_response(request)


def _firmless_allowed(request, membership) -> bool:
    """Serve this request with only the user context, not a firm's?

    ``settings.FIRMLESS_ACCESS`` decides, given the membership that would
    otherwise be bound (possibly None); unset means never.
    """
    path = getattr(settings, "FIRMLESS_ACCESS", None)
    return bool(path) and import_string(path)(request, membership)


def _refuse(request, code: str, detail: str):
    """A 403 the caller can read: JSON for the API, Django's page for a browser."""
    if wants_json(request):
        return JsonResponse({"code": code, "detail": detail}, status=403)
    raise PermissionDenied(detail)
