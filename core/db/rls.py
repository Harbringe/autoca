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
# Making DDL survive the policies it is installing
# ---------------------------------------------------------------------------

#: A reserved firm id that no firm will ever hold. Used only to give a DDL
#: transaction *a* tenant context, so that PostgreSQL's own maintenance queries
#: are answered instead of raising. It matches nothing, which is the point.
DDL_FIRM_ID = "00000000-0000-0000-0000-000000000000"

DDL_CONTEXT_SQL = "SELECT set_config('{guc}', '{firm_id}', true);"


def ddl_tenant_context_operations():
    """Give a migration a tenant context. **First operation, or it will not work.**

    Adding a foreign key makes PostgreSQL validate it by scanning the child
    table and joining the parent:

        SELECT fk.client_id FROM ONLY banking_bank_account fk
        LEFT OUTER JOIN ONLY core_client pk ON pk.id = fk.client_id
        WHERE pk.id IS NULL AND fk.client_id IS NOT NULL

    Both sides of that join are firm-scoped, and a migration has no tenant
    context, so the scan raises ``tenant context missing`` and takes the whole
    migration with it. The error names the tenancy layer and looks like a bug in
    it; it is really the cost of ``FORCE ROW LEVEL SECURITY``, which subjects
    the migration's own owner role to the policies. That is exactly what FORCE
    is for, so the answer is to give the migration a context, not to weaken it.

    It has to be the first operation because Django holds a migration's foreign
    key SQL in ``deferred_sql`` and flushes it when the schema editor closes --
    after every operation has run. ``set_config(..., is_local => true)`` is
    transaction-scoped and the migration is one transaction, so a context set at
    the top is still in force at that flush.

    **The caveat, which matters.** Under this context the validation scan sees
    zero rows, so it validates nothing. For a migration that *creates* a table
    that is fine: the table is empty and there is nothing to validate. For a
    migration that adds a foreign key to a table with data in it, this would
    turn a real integrity check into a no-op -- validate those per firm
    afterwards rather than trusting the constraint's VALID flag.
    """
    sql = DDL_CONTEXT_SQL.format(guc=settings.TENANT_GUC, firm_id=DDL_FIRM_ID)
    return [migrations.RunSQL(sql=sql, reverse_sql=migrations.RunSQL.noop)]


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

    Call this in a migration that runs *after* the one creating the table, never
    in the same one. Django flushes a migration's deferred SQL -- which is where
    foreign key constraints live -- when the schema editor closes, so operations
    appended to a CreateModel migration are applied before the foreign keys are.
    Adding a foreign key then triggers PostgreSQL's validation scan over a table
    that is already FORCE ROW LEVEL SECURITY, from a migration that has no
    tenant context, and the migration dies with ``tenant context missing``.
    See ``banking/migrations/0002_row_level_security.py``.

    The isolation test suite fails the build if a firm-scoped table ever ships
    without a policy, so a forgotten call is caught by CI rather than by a
    customer.
    """
    return [
        migrations.RunSQL(
            sql=enable_rls_sql(table, column),
            reverse_sql=disable_rls_sql(table, column),
        )
    ]


# ---------------------------------------------------------------------------
# Append-only tables
# ---------------------------------------------------------------------------


def append_only_sql(table: str, column: str = "firm_id") -> str:
    """Tenant isolation plus immutability, enforced two independent ways.

    Indian company law expects a permanent, unalterable record of edits to
    financial entries: corrections are recorded as new entries, never as silent
    overwrites. That is a database guarantee here, not an application one, for
    the same reason tenant isolation is -- an application bug must not be able
    to violate it.

    Two mechanisms, deliberately redundant:

    1.  **No UPDATE or DELETE grant.** The application role is given SELECT and
        INSERT and nothing else, so the statement fails before it reaches a row.
    2.  **A trigger that raises.** Belt to the grant's braces.

    Either alone would do on a good day. Grants get widened by a careless
    ``GRANT ALL`` in a later migration; triggers get dropped by a restore from a
    schema-only dump. Both failing in the same deployment is unlikely enough to
    be worth the duplication, and the trigger's error message names the rule,
    which the bare permission error does not.
    """
    guard = f"{table}_immutable"
    return f"""
ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;
ALTER TABLE {table} FORCE  ROW LEVEL SECURITY;

DROP POLICY IF EXISTS {POLICY_NAME} ON {table};
CREATE POLICY {POLICY_NAME} ON {table}
    FOR ALL
    TO {APP_ROLE}
    USING      ({column} = app.current_firm_id())
    WITH CHECK ({column} = app.current_firm_id());

REVOKE ALL ON {table} FROM {APP_ROLE};
GRANT SELECT, INSERT ON {table} TO {APP_ROLE};

CREATE OR REPLACE FUNCTION app.{guard}()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION
        '{table} is append-only: rows cannot be % once written',
        lower(TG_OP)
        USING ERRCODE = '42501',
              HINT = 'Record a correction as a new, superseding entry. Indian '
                     'company law requires the original to remain visible.';
END;
$$;

DROP TRIGGER IF EXISTS {guard} ON {table};
CREATE TRIGGER {guard}
    BEFORE UPDATE OR DELETE ON {table}
    FOR EACH ROW EXECUTE FUNCTION app.{guard}();
"""


def append_only_reverse_sql(table: str) -> str:
    guard = f"{table}_immutable"
    return f"""
DROP TRIGGER IF EXISTS {guard} ON {table};
DROP FUNCTION IF EXISTS app.{guard}();
{disable_rls_sql(table)}
"""


def append_only_operations(table: str, column: str = "firm_id"):
    """Migration operations for a table that may only ever be inserted into."""
    return [
        migrations.RunSQL(
            sql=append_only_sql(table, column),
            reverse_sql=append_only_reverse_sql(table),
        )
    ]


def balanced_entry_trigger_sql(
    line_table: str, entry_column: str = "entry_id", amount_column: str = "signed_paise"
) -> str:
    """A deferred constraint: every journal entry's lines sum to zero at commit.

    Deferred rather than immediate, because an entry is written one line at a
    time and is legitimately unbalanced in between. Checking per statement would
    make it impossible to write a two-line entry at all; checking at commit is
    the only point where "balanced" is a meaningful question.

    This is the double-entry invariant itself, held by the database. Application
    code that produces a lopsided entry fails at commit rather than quietly
    storing books that do not add up.

    **Why the function re-establishes the tenant context.** Being deferred, it
    fires during COMMIT -- after ``firm_context()`` has cleared the GUC on its
    way out. Its own ``SELECT`` would then hit the table's RLS policy with no
    context and raise ``tenant context missing``, which reads like a tenancy bug
    and is really a lifecycle one. So it sets the context from the row it is
    checking. That is not a hole: the only value it can set is the firm that
    owns the row being inserted, which the inserting transaction already had
    access to, and the sum is filtered to that firm as well.
    """
    firm_column = "firm_id"
    return f"""
CREATE OR REPLACE FUNCTION app.assert_entry_balances()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    imbalance bigint;
BEGIN
    -- See balanced_entry_trigger_sql in core/db/rls.py: this runs at COMMIT,
    -- when the request's tenant context is already gone. Scope to the row's own
    -- firm, which can never be wider than what the inserting transaction had.
    PERFORM set_config('{settings.TENANT_GUC}', NEW.{firm_column}::text, true);

    SELECT COALESCE(SUM({amount_column}), 0) INTO imbalance
    FROM {line_table}
    WHERE {entry_column} = NEW.{entry_column}
      AND {firm_column} = NEW.{firm_column};

    IF imbalance <> 0 THEN
        RAISE EXCEPTION
            'journal entry % does not balance: debits and credits differ by % paise',
            NEW.{entry_column}, imbalance
            USING ERRCODE = '23514',
                  HINT = 'Every entry needs equal debits and credits. This is '
                         'checked at commit, so the offending entry is the one '
                         'named, not necessarily the last one written.';
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS assert_entry_balances ON {line_table};
CREATE CONSTRAINT TRIGGER assert_entry_balances
    AFTER INSERT ON {line_table}
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION app.assert_entry_balances();
"""


def balanced_entry_operations(line_table: str, **kwargs):
    return [
        migrations.RunSQL(
            sql=balanced_entry_trigger_sql(line_table, **kwargs),
            reverse_sql=(
                f"DROP TRIGGER IF EXISTS assert_entry_balances ON {line_table};\n"
                f"DROP FUNCTION IF EXISTS app.assert_entry_balances();"
            ),
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
