"""Setting and clearing the per-transaction tenant context.

Everything that touches a firm-scoped table runs inside ``firm_context()``,
either directly (Celery tasks, management commands) or via
``TenantContextMiddleware`` (web requests).

Why ``set_config(..., is_local => true)`` rather than a literal ``SET LOCAL``:

* It is transaction-scoped, exactly like ``SET LOCAL``. That is mandatory under
  a transaction pooler such as Supabase's pgbouncer, where the same backend
  connection is handed to a different tenant's request the moment ours commits.
  A session-scoped ``SET`` would leak one firm's context into another firm's
  query. This is the single most dangerous mistake available in this codebase.
* ``SET LOCAL`` cannot take a bind parameter, so it would have to be built by
  string interpolation. ``set_config`` takes the firm id as a real parameter,
  which removes the injection surface entirely.
"""

from __future__ import annotations

import contextlib
import logging
import uuid

from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, connections, transaction

logger = logging.getLogger("autoca.tenancy")


class TenantContextError(RuntimeError):
    """Raised when the tenant context is missing, malformed, or contradictory."""


def _coerce(firm_id) -> str:
    if isinstance(firm_id, uuid.UUID):
        return str(firm_id)
    try:
        return str(uuid.UUID(str(firm_id)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise TenantContextError(f"Not a valid firm id: {firm_id!r}") from exc


def get_current_firm_id(using: str = DEFAULT_DB_ALIAS) -> str | None:
    """Return the firm id active on this connection's transaction, or None."""
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT nullif(current_setting(%s, true), '')", [settings.TENANT_GUC])
        row = cursor.fetchone()
    return row[0] if row else None


def _apply(firm_id: str, using: str) -> None:
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT set_config(%s, %s, true)", [settings.TENANT_GUC, firm_id])


def _apply_user(user_id: str, using: str = DEFAULT_DB_ALIAS) -> None:
    """Set the authenticated user for this transaction.

    Read by exactly one RLS policy: the membership bootstrap. It is not an
    authorisation mechanism and must never be treated as one -- it answers
    "which firm does this user belong to?" and nothing else.
    """
    with connections[using].cursor() as cursor:
        cursor.execute("SELECT set_config(%s, %s, true)", [settings.TENANT_USER_GUC, user_id])


@contextlib.contextmanager
def user_context(user_id, using: str = DEFAULT_DB_ALIAS):
    """Open a transaction that can resolve one user's firm memberships."""
    user_id = _coerce(user_id)
    with transaction.atomic(using=using):
        _apply_user(user_id, using)
        yield user_id


@contextlib.contextmanager
def firm_context(firm_id, using: str = DEFAULT_DB_ALIAS):
    """Open a transaction bound to one firm.

    Refuses to nest a *different* firm inside an existing context. A codepath
    that wants two firms' data in one transaction is either a bug or a
    cross-tenant feature that needs its own explicit design review; silently
    switching mid-transaction is not an outcome worth supporting.
    """
    firm_id = _coerce(firm_id)

    with transaction.atomic(using=using):
        current = get_current_firm_id(using)
        if current and current != firm_id:
            raise TenantContextError(
                f"Refusing to switch tenant context mid-transaction: "
                f"{current} is already active, asked for {firm_id}."
            )
        _apply(firm_id, using)
        try:
            yield firm_id
        finally:
            # Not strictly required -- COMMIT/ROLLBACK reverts a local setting
            # on its own -- but an explicit clear keeps the invariant true even
            # if an outer transaction continues after this block.
            if not current:
                with contextlib.suppress(Exception):
                    _apply("", using)


@contextlib.contextmanager
def no_firm_context(using: str = DEFAULT_DB_ALIAS):
    """Explicitly assert that no tenant context is active.

    Used by tests and by genuinely firm-agnostic codepaths (login by email,
    health checks). Inside this block, any query against a firm-scoped table
    raises rather than returning rows.
    """
    with transaction.atomic(using=using):
        _apply("", using)
        yield
