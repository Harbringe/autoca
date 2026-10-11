"""One narrowly-scoped function that deletes aged audit-log rows across every firm, and the one-time setup it needs.

``core_audit_log`` is append-only with a floor (``core/migrations/0016_audit_log_retention.py``): nothing newer than
the retention window can ever be removed, however it is asked. But nothing with an ordinary login can remove even an
*old* row either: ``autoca_web`` has no DELETE grant on the table at all (``core/migrations/0013``), and
``autoca_owner``, which owns the table, holds no row-level-security policy that lets it see rows outside whatever one
firm its transaction happens to be bound to -- no login role in this project bypasses tenant isolation (see
``docs/ARCHITECTURE.md``, "Two database roles").

So removing old rows across every firm needs the one mechanism this project already has for a genuinely cross-firm
operation: a function owned by ``autoca_platform_reader``, the single NOLOGIN role that holds BYPASSRLS
(``superadmin/setup_sql/role.sql``). Unlike that app's own functions, this one is not gated by who is signed in -- a
retention job run from a systemd timer has no Django session to ask -- it is gated by EXECUTE, granted to
``autoca_owner`` alone. Nothing else may call it.

Installed by ``python manage.py install_log_retention``, the same opt-in, idempotent, "skip if the role is not set
up yet" shape as ``python manage.py superadmin install`` (``superadmin/management/commands/superadmin.py``); never
by an ordinary migration, which would fail everywhere the one-time role has not been created.
"""

from __future__ import annotations

READER_ROLE = "autoca_platform_reader"
OWNER_ROLE = "autoca_owner"

#: The retention floor the function itself enforces, belt to 0016's trigger braces: two independent checks on two
#: different objects, so a bug or a drift in either alone still leaves the other standing.
RETENTION_FLOOR_DAYS = 30

# ruff: noqa: S608 -- DDL from module constants only.
FUNCTION_SQL = f"""
CREATE OR REPLACE FUNCTION app.trim_audit_log(retention_days integer, dry_run boolean DEFAULT false)
RETURNS bigint
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
    affected bigint;
    cutoff timestamptz;
BEGIN
    IF retention_days < {RETENTION_FLOOR_DAYS} THEN
        RAISE EXCEPTION 'the retention window must be at least {RETENTION_FLOOR_DAYS} days, got %', retention_days
            USING ERRCODE = '42501';
    END IF;
    cutoff := now() - make_interval(days => retention_days);
    IF dry_run THEN
        SELECT count(*) INTO affected FROM core_audit_log WHERE created_at < cutoff;
    ELSE
        DELETE FROM core_audit_log WHERE created_at < cutoff;
        GET DIAGNOSTICS affected = ROW_COUNT;
    END IF;
    RETURN affected;
END;
$$;
"""

PRIVILEGES_SQL = f"""
ALTER FUNCTION app.trim_audit_log(integer, boolean) OWNER TO {READER_ROLE};
REVOKE ALL ON FUNCTION app.trim_audit_log(integer, boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.trim_audit_log(integer, boolean) TO {OWNER_ROLE};
"""

CREATE_SQL = FUNCTION_SQL + PRIVILEGES_SQL

DROP_SQL = "DROP FUNCTION IF EXISTS app.trim_audit_log(integer, boolean);\n"


def reader_role_usable(cursor) -> bool:
    """The role exists and the current (migrating) role may hand it ownership. Same check superadmin/sql.py makes."""
    cursor.execute(
        "SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s) "
        "THEN pg_has_role(current_user, %s, 'MEMBER') ELSE false END",
        [READER_ROLE, READER_ROLE],
    )
    return bool(cursor.fetchone()[0])


def installed(cursor) -> bool:
    cursor.execute("SELECT to_regprocedure('app.trim_audit_log(integer, boolean)') IS NOT NULL")
    return bool(cursor.fetchone()[0])
