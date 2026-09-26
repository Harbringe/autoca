"""Deploy-time system checks.

These exist because the isolation guarantees in this project depend on facts
that live outside the Python code -- which database role the app connects as,
what order the middleware runs in. A comment in a docstring does not survive a
hurried config change at 2am; a failing check does.

Run with ``manage.py check --deploy --database default``. CI runs them, and so
does the Render start command.
"""

from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register
from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections

TENANCY_MW = "core.middleware.tenancy.TenantContextMiddleware"
AUDIT_MW = "core.middleware.audit.AuditMiddleware"
MFA_MW = "core.middleware.mfa.MFARequiredMiddleware"
AUTH_MW = "django.contrib.auth.middleware.AuthenticationMiddleware"
OTP_MW = "django_otp.middleware.OTPMiddleware"


@register()
def check_mfa_not_disabled_outside_debug(app_configs, **kwargs):
    """MFA_DISABLED is a local-demo switch. Anywhere else it is a misconfiguration."""
    if getattr(settings, "MFA_DISABLED", False) and not settings.DEBUG:
        return [
            Error(
                "MFA_DISABLED is set without DEBUG. The second factor is mandatory "
                "outside local development; unset MFA_DISABLED.",
                id="core.E015",
            )
        ]
    return []


@register()
def check_frontend_url_is_not_local_in_production(app_configs, **kwargs):
    """An invitation that links to localhost is a dead link for everyone but its sender."""
    if not settings.IS_PRODUCTION:
        return []
    host = settings.FRONTEND_URL.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0]
    if host in {"localhost", "127.0.0.1", "[::1]"}:
        return [
            Warning(
                f"FRONTEND_URL is {settings.FRONTEND_URL}, a local address. Invitation links "
                "and the trusted CSRF origin are built from it; set it to where the web "
                "application is actually served.",
                id="core.W016",
            )
        ]
    return []


@register()
def check_middleware_order(app_configs, **kwargs):
    """The ordering constraints documented in each middleware, enforced."""
    errors = []
    mw = list(settings.MIDDLEWARE)

    def index(name):
        return mw.index(name) if name in mw else None

    positions = {name: index(name) for name in (TENANCY_MW, AUDIT_MW, MFA_MW, AUTH_MW, OTP_MW)}

    for name, pos in positions.items():
        if pos is None:
            errors.append(
                Error(f"{name} is missing from MIDDLEWARE.", id="core.E001")
            )

    if all(positions[n] is not None for n in (AUTH_MW, TENANCY_MW)):
        if positions[AUTH_MW] > positions[TENANCY_MW]:
            errors.append(
                Error(
                    "TenantContextMiddleware must come after AuthenticationMiddleware; "
                    "it needs request.user to resolve the firm.",
                    id="core.E002",
                )
            )

    if all(positions[n] is not None for n in (OTP_MW, MFA_MW)):
        if positions[OTP_MW] > positions[MFA_MW]:
            errors.append(
                Error(
                    "MFARequiredMiddleware must come after OTPMiddleware; it reads "
                    "user.is_verified(), which OTPMiddleware installs.",
                    id="core.E003",
                )
            )

    if all(positions[n] is not None for n in (MFA_MW, TENANCY_MW)):
        if positions[MFA_MW] > positions[TENANCY_MW]:
            errors.append(
                Error(
                    "MFARequiredMiddleware must come before TenantContextMiddleware; "
                    "a session without a verified second factor must never acquire a "
                    "tenant context.",
                    id="core.E004",
                )
            )

    if all(positions[n] is not None for n in (TENANCY_MW, AUDIT_MW)):
        if positions[TENANCY_MW] > positions[AUDIT_MW]:
            errors.append(
                Error(
                    "AuditMiddleware must come after TenantContextMiddleware; audit "
                    "rows are firm-scoped and must be written inside the tenant "
                    "context.",
                    id="core.E005",
                )
            )

    return errors


@register(Tags.database)
def check_app_role_cannot_bypass_rls(app_configs, **kwargs):
    """The application's database role must be powerless to ignore RLS.

    Three ways a role escapes row-level security:
      * it is a superuser;
      * it has been granted BYPASSRLS;
      * it owns the table and the table is only ENABLE'd, not FORCE'd.

    We FORCE every policy, which closes the third. This check closes the first
    two, and flags table ownership anyway -- defence in depth is the whole point
    of having both.
    """
    messages = []
    connection = connections[DEFAULT_DB_ALIAS]

    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT current_user, rolsuper, rolbypassrls "
                "FROM pg_roles WHERE rolname = current_user"
            )
            row = cursor.fetchone()
            if not row:
                return []
            role, is_super, can_bypass = row

            cursor.execute(
                """
                SELECT count(*) FROM pg_tables
                WHERE schemaname = 'public' AND tableowner = current_user
                """
            )
            owned = cursor.fetchone()[0]
    except DatabaseError:
        # No reachable database (e.g. `manage.py check` with no DB). Nothing to
        # assert; other tooling will report the connection problem.
        return []

    is_prod = not settings.DEBUG
    Level = Error if is_prod else Warning

    if is_super:
        messages.append(
            Level(
                f"The application connects as {role!r}, which is a superuser. "
                f"Superusers bypass every row-level security policy, so tenant "
                f"isolation is not in force.",
                hint="Run scripts/bootstrap_db_roles.sql and point DATABASE_URL at "
                "the autoca_app login role.",
                id="core.E010",
            )
        )

    if can_bypass:
        messages.append(
            Level(
                f"The application role {role!r} has BYPASSRLS. Tenant isolation is "
                f"not in force.",
                hint=f"ALTER ROLE {role} NOBYPASSRLS;",
                id="core.E011",
            )
        )

    if owned:
        messages.append(
            Warning(
                f"The application role {role!r} owns {owned} table(s) in public. "
                f"Policies are FORCE'd so this is currently contained, but the app "
                f"role should not own the schema it queries.",
                hint="Apply migrations with DATABASE_OWNER_URL and keep DATABASE_URL "
                "on a role that only has DML grants.",
                id="core.W012",
            )
        )

    return messages


@register(Tags.security, deploy=True)
def check_shared_cache_for_throttling(app_configs, **kwargs):
    """Login lockouts are counted in the cache; a deployment must share it.

    An in-memory cache is per process. With two web workers, an attacker gets
    twice the attempts and a lockout on one worker means nothing on the other.
    """
    backend = settings.CACHES["default"]["BACKEND"]
    if "locmem" in backend:
        return [
            Warning(
                "CACHES['default'] is in-memory. Login and MFA lockout counters are "
                "per process, so with more than one web worker the limits are not "
                "enforced as configured.",
                hint="Set CACHE_URL to a Redis instance shared by every web process.",
                id="core.W014",
            )
        ]
    return []


@register(Tags.security, deploy=True)
def check_distinct_db_roles(app_configs, **kwargs):
    """In a deployed environment the app and owner roles must differ."""
    app_user = settings.DATABASES["default"].get("USER")
    owner_user = settings.DATABASES["owner"].get("USER")
    if app_user and app_user == owner_user:
        return [
            Error(
                "DATABASE_URL and DATABASE_OWNER_URL use the same role "
                f"({app_user!r}). The application would then own its own tables, "
                "which is the configuration RLS FORCE exists to survive -- not one "
                "to rely on.",
                hint="Set DATABASE_OWNER_URL to the owner role and DATABASE_URL to "
                "the restricted app role.",
                id="core.E013",
            )
        ]
    return []
