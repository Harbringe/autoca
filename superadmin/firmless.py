"""Which firmless requests TenantContextMiddleware may serve, and who may open the admin.

Referenced by dotted path from ``settings.FIRMLESS_ACCESS`` and
``settings.ADMIN_ACCESS``; ``core`` never imports this app.

The platform owner belongs to no firm. They get the SPA shell (which sends them
on to the admin), their session, sign-out and the Django admin -- and nothing
firm-scoped through the app, which row-level security refuses anyway without a
firm context. What they read in the admin comes through the gated views in
``superadmin/sql.py``.
"""

from __future__ import annotations

from superadmin.models import is_superadmin

#: ``/admin`` is safe to allow because the database, not this list, decides what
#: a firmless session can read: firm-scoped tables raise without a tenant
#: context, and the platform views return rows only to the platform owner.
ADMIN_PREFIX = "/admin"
ALLOWED_PREFIXES = (
    "/app",
    ADMIN_PREFIX,
    "/api/v1/me/",
    "/auth/logout/",
    "/auth/csrf/",
)


def allow_firmless(request, membership) -> bool:
    user = getattr(request, "user", None)
    if membership is not None or not request.path.startswith(ALLOWED_PREFIXES):
        return False
    return is_superadmin(user)


def allow_admin(user) -> bool:
    """May this user open the Django admin? Referenced by ``settings.ADMIN_ACCESS``.

    Only the platform owner. Django's own test is ``is_staff``, which a firm's
    administrator can hold: they are staff of their firm, not of the platform.
    The admin edits rows with none of the app's guard rails in front of them, so
    the one account that may open it is the one that belongs to no firm and
    answers for the whole deployment.

    A firm's own people administer their firm from the app's Team and Clients
    screens, which enforce those rules.
    """
    return is_superadmin(user)
