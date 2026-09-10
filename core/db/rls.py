"""Row-level security primitives.

This module is the single source of truth for how tenant isolation is expressed
in the database. Every firm-scoped table gets the same three things, generated
here and applied in a migration:

    ALTER TABLE t ENABLE ROW LEVEL SECURITY;
    ALTER TABLE t FORCE  ROW LEVEL SECURITY;   -- applies to the table owner too
    CREATE POLICY tenant_isolation ON t
        USING      (<tenant column> = app.current_firm_id())
        WITH CHECK (<tenant column> = app.current_firm_id());

Two deliberate choices, both load-bearing:

1.  FORCE, not just ENABLE. Without FORCE, the role that owns the table is
    exempt from its own policies. We also run the app on a role that neither
    owns the tables nor has BYPASSRLS, so this is belt and braces. Keep both:
    the belt is what saves you the day someone runs the app as the owner by
    accident.

2.  ``app.current_firm_id()`` instead of the more obvious inline
    ``current_setting('app.firm_id')::uuid``.

    The inline form looks like it fails loudly when the GUC is unset, and it
    does -- the first time. But ``SET LOCAL`` reverts the parameter at commit,
    and on that path Postgres leaves the custom GUC *defined and empty* rather
    than undefined. ``''::uuid`` then raises a confusing cast error, and worse,
    a policy written as ``current_setting('app.firm_id', true)`` would quietly
    return NULL and match zero rows -- silent, not loud.

    The function collapses both cases into one explicit, greppable exception.
    Deny by default, and audibly so.
"""

from __future__ import annotations

from django.conf import settings
from django.db import migrations

POLICY_NAME = "tenant_isolation"

#: Postgres group role that owns the application's DML grants. The actual login
#: role is a member of it, so migrations can grant to a stable name without
#: knowing the deployment's credentials.
APP_ROLE = "autoca_app"


# ---------------------------------------------------------------------------
# One-time bootstrap: the app schema, the guard function, the group role.
# ---------------------------------------------------------------------------

# ruff: noqa: S608 -- these are DDL templates built from module constants, not
# from user input. The only interpolated value is APP_ROLE, defined above.
BOOTSTRAP_SQL = f"""
CREATE SCHEMA IF NOT EXISTS app;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
        CREATE ROLE {APP_ROLE} NOLOGIN;
    END IF;
END
$$;

GRANT USAGE ON SCHEMA app TO {APP_ROLE};
GRANT USAGE ON SCHEMA public TO {APP_ROLE};

-- Soft readers. Return NULL when the context is absent. Only the membership
-- bootstrap below is allowed to use these.
CREATE OR REPLACE FUNCTION app.try_firm_id()
RETURNS uuid LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('{{firm_guc}}', true), '')::uuid;
$$;

CREATE OR REPLACE FUNCTION app.try_user_id()
RETURNS uuid LANGUAGE sql STABLE AS $$
    SELECT nullif(current_setting('{{user_guc}}', true), '')::uuid;
$$;

-- The firm id for the current transaction, or a hard error. Never NULL: a NULL
-- would silently match zero rows, and a silent empty result set is exactly the
-- failure mode this whole design exists to prevent.
CREATE OR REPLACE FUNCTION app.current_firm_id()
RETURNS uuid
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    value uuid;
BEGIN
    value := app.try_firm_id();
    IF value IS NULL THEN
        RAISE EXCEPTION
            'tenant context missing: {{firm_guc}} is not set for this transaction'
            USING ERRCODE = '42501',
                  HINT = 'Queries against firm-scoped tables must run inside '
                         'core.db.session.firm_context() or behind '
                         'TenantContextMiddleware.';
    END IF;
    RETURN value;
END;
$$;

-- Membership is the one table that must be readable *before* a firm context
-- exists, because reading it is how the firm context is discovered. Rather than
-- granting a bypass -- a hole that would inevitably get reused for something
-- else -- it gets its own predicate: a row is visible if it belongs to the
-- active firm, or if it belongs to the authenticated user. With neither context
-- set, this still raises, so deny-by-default survives intact.
CREATE OR REPLACE FUNCTION app.membership_visible(row_firm uuid, row_user uuid)
RETURNS boolean
LANGUAGE plpgsql
STABLE
AS $$
DECLARE
    ctx_firm uuid := app.try_firm_id();
    ctx_user uuid := app.try_user_id();
BEGIN
    IF ctx_firm IS NULL AND ctx_user IS NULL THEN
        RAISE EXCEPTION
            'tenant context missing: neither {{firm_guc}} nor {{user_guc}} is set'
            USING ERRCODE = '42501',
                  HINT = 'Membership lookups run inside TenantContextMiddleware, '
                         'which sets the user context before the firm context.';
    END IF;
    RETURN (ctx_firm IS NOT NULL AND row_firm = ctx_firm)
        OR (ctx_user IS NOT NULL AND row_user = ctx_user);
END;
$$;

REVOKE ALL ON FUNCTION app.try_firm_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION app.try_user_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION app.current_firm_id() FROM PUBLIC;
REVOKE ALL ON FUNCTION app.membership_visible(uuid, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.try_firm_id() TO {APP_ROLE};
GRANT EXECUTE ON FUNCTION app.try_user_id() TO {APP_ROLE};
GRANT EXECUTE ON FUNCTION app.current_firm_id() TO {APP_ROLE};
GRANT EXECUTE ON FUNCTION app.membership_visible(uuid, uuid) TO {APP_ROLE};
"""

BOOTSTRAP_REVERSE_SQL = f"""
DROP FUNCTION IF EXISTS app.membership_visible(uuid, uuid);
DROP FUNCTION IF EXISTS app.current_firm_id();
DROP FUNCTION IF EXISTS app.try_user_id();
DROP FUNCTION IF EXISTS app.try_firm_id();
REVOKE USAGE ON SCHEMA app FROM {APP_ROLE};
DROP SCHEMA IF EXISTS app;
"""


def bootstrap_operations():
    """Migration operations that install the RLS machinery. Run once, first."""
    sql = BOOTSTRAP_SQL.replace("{firm_guc}", settings.TENANT_GUC).replace(
        "{user_guc}", settings.TENANT_USER_GUC
    )
    return [migrations.RunSQL(sql=sql, reverse_sql=BOOTSTRAP_REVERSE_SQL)]


# ---------------------------------------------------------------------------
# Per-table policy
# ---------------------------------------------------------------------------


def enable_rls_sql(table: str, column: str = "firm_id") -> str:
    return f"""
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE  ROW LEVEL SECURITY;

DROP POLICY IF EXISTS {POLICY_NAME} ON {table};
CREATE POLICY {POLICY_NAME} ON {table}
    FOR ALL
    TO {APP_ROLE}
    USING      ({column} = app.current_firm_id())
    WITH CHECK ({column} = app.current_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE};
"""


def disable_rls_sql(table: str, column: str = "firm_id") -> str:
    return f"""
REVOKE ALL ON {table} FROM {APP_ROLE};
DROP POLICY IF EXISTS {POLICY_NAME} ON {table};
ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY;
ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;
"""


def rls_operations(table: str, column: str = "firm_id"):
    """Migration operations that put ``table`` behind tenant isolation.

    Call this in the same migration that creates the table. The isolation test
    suite fails the build if a firm-scoped table ever ships without it, so a
    forgotten call is caught by CI rather than by a customer.
    """
    return [
        migrations.RunSQL(
            sql=enable_rls_sql(table, column),
            reverse_sql=disable_rls_sql(table, column),
        )
    ]


def membership_rls_operations(table: str = "core_firm_membership"):
    """RLS for the membership table, which needs the bootstrap predicate.

    Reads use ``app.membership_visible`` so a user can find their own firm.
    Writes still require a full firm context -- discovering your membership must
    never be a route to creating one.
    """
    sql = f"""
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE  ROW LEVEL SECURITY;

DROP POLICY IF EXISTS {POLICY_NAME} ON {table};
CREATE POLICY {POLICY_NAME} ON {table}
    FOR ALL
    TO {APP_ROLE}
    USING      (app.membership_visible(firm_id, user_id))
    WITH CHECK (firm_id = app.current_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP_ROLE};
"""
    return [migrations.RunSQL(sql=sql, reverse_sql=disable_rls_sql(table))]


def sequence_grant_sql() -> str:
    """Grant sequence usage for BigAutoField-backed tables."""
    return f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE};"
