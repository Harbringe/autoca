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

from django.core.exceptions import PermissionDenied
from django.db import transaction

from core.db.session import _apply, _apply_user
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

            if membership is None:
                logger.warning(
                    "authenticated user %s has no active firm membership; "
                    "serving with no tenant context",
                    user.pk,
                )
                request.firm = None
                request.membership = None
                raise PermissionDenied(
                    "Your account is not attached to an active firm."
                )

            firm_id = str(membership.firm_id)
            _apply(firm_id, "default")

            # Now that the context is set, the firm row is readable -- and the
            # policy guarantees it is that firm's row and no other.
            firm = membership.firm
            if not firm.is_active:
                raise PermissionDenied("This firm has been deactivated.")

            request.firm = firm
            request.membership = membership
            request.firm_id = firm_id

            return self.get_response(request)
