"""The only way this app reads across firms: views and functions owned by one role.

Everything here is owned by ``autoca_platform_reader`` -- a NOLOGIN role with
BYPASSRLS that nothing can connect as -- and exposes fixed directory columns
only: who exists, which firms, who works where, which clients a firm carries,
what happened. No ciphertext, account numbers, transactions, ledgers or journals
ever come out. The two exceptions are *counts* of a client's bank accounts and
statements, which say how busy a client is without opening anything.

**Views** back the platform admin's lists. A view runs with its owner's access
to the tables beneath it, which is how it sees every firm, so each one is gated
twice:

* ``WHERE app.superadmin_can_read()`` -- in the database, the transaction's user
  (``app.try_user_id()``, set by TenantContextMiddleware) must be an active
  superuser with no active firm membership. Anyone else reads zero rows.
* ``security_barrier`` -- so a caller's own filter cannot run ahead of that gate
  and observe rows it removes.

The application role is granted SELECT on the views and nothing else. That is
not tidiness: a single-table view is automatically updatable in PostgreSQL, and
a write through it would run as its BYPASSRLS owner. SELECT-only is what keeps a
read path from being a cross-firm write path.

**Functions** are the older, narrower form of the same thing, kept for the
tests and the management command.

Writes never come through here. The platform admin writes with the ordinary
models inside ``core.db.session.firm_context`` for the one firm being changed,
under the normal row-level security rules.

If the role does not exist yet (it needs the Supabase ``postgres`` login, see
``superadmin/setup_sql/role.sql``), nothing here is installed and the platform
sections are empty. Nothing else in the app is affected.
"""

from __future__ import annotations

READER_ROLE = "autoca_platform_reader"
APP_ROLE = "autoca_app"

TABLES = (
    "core_firm",
    "core_user",
    "core_firm_membership",
    "core_client",
    "core_audit_log",
    "banking_bank_account",
    "banking_statement",
    "core_client_assignment",
    "core_job",
)

FUNCTIONS = (
    "app.superadmin_can_read()",
    "app.superadmin_assert()",
    "app.superadmin_firms()",
    "app.superadmin_members(uuid)",
    "app.superadmin_clients(uuid)",
    "app.superadmin_member_clients(uuid, uuid)",
)

# pg_temp is listed last on purpose: PostgreSQL searches it FIRST unless it is named, so a session that could create a
# temporary table called core_user would otherwise be read by these functions instead of the real one.
_HEADER = "LANGUAGE plpgsql STABLE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp"

# ruff: noqa: S608 -- DDL from module constants only.
FUNCTIONS_SQL = f"""
-- Return shapes change between versions, which CREATE OR REPLACE cannot do.
DROP FUNCTION IF EXISTS app.superadmin_members(uuid);

-- The same rule as superadmin_assert, answered rather than raised. The views
-- filter on it, so a caller who is not the platform owner reads nothing instead
-- of breaking whatever query happened to touch a view.
CREATE OR REPLACE FUNCTION app.superadmin_can_read()
RETURNS boolean {_HEADER} AS $$
BEGIN
    RETURN EXISTS (
        SELECT 1 FROM core_user u
        WHERE u.id = app.try_user_id() AND u.is_active AND u.is_superuser
          AND NOT EXISTS (
              SELECT 1 FROM core_firm_membership m WHERE m.user_id = u.id AND m.is_active
          )
    );
END;
$$;

CREATE OR REPLACE FUNCTION app.superadmin_assert()
RETURNS void {_HEADER} AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM core_user u
        WHERE u.id = app.try_user_id() AND u.is_active AND u.is_superuser
          AND NOT EXISTS (
              SELECT 1 FROM core_firm_membership m WHERE m.user_id = u.id AND m.is_active
          )
    ) THEN
        RAISE EXCEPTION 'super admin access denied' USING ERRCODE = '42501';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION app.superadmin_firms()
RETURNS TABLE (
    id uuid, name text, is_active boolean, created_at timestamptz,
    member_count bigint, client_count bigint, last_activity timestamptz
) {_HEADER} AS $$
#variable_conflict use_column
BEGIN
    PERFORM app.superadmin_assert();
    RETURN QUERY
    SELECT f.id, f.name::text, f.is_active, f.created_at,
           (SELECT count(*) FROM core_firm_membership m WHERE m.firm_id = f.id AND m.is_active),
           (SELECT count(*) FROM core_client c WHERE c.firm_id = f.id),
           (SELECT max(a.created_at) FROM core_audit_log a WHERE a.firm_id = f.id)
    FROM core_firm f
    ORDER BY lower(f.name);
END;
$$;

CREATE OR REPLACE FUNCTION app.superadmin_members(target_firm uuid)
RETURNS TABLE (
    membership_id uuid, user_id uuid, email text, full_name text, role text,
    membership_active boolean, user_active boolean, scope_all_clients boolean,
    last_login timestamptz, created_at timestamptz, manager_name text, is_owner boolean
) {_HEADER} AS $$
#variable_conflict use_column
BEGIN
    PERFORM app.superadmin_assert();
    RETURN QUERY
    SELECT m.id, u.id, u.email::text, u.full_name::text, m.role::text,
           m.is_active, u.is_active, m.scope_all_clients, u.last_login, m.created_at,
           coalesce(nullif(mu.full_name, ''), mu.email)::text, m.is_owner
    FROM core_firm_membership m
    JOIN core_user u ON u.id = m.user_id
    LEFT JOIN core_firm_membership mm ON mm.id = m.manager_id
    LEFT JOIN core_user mu ON mu.id = mm.user_id
    WHERE m.firm_id = target_firm
    ORDER BY lower(u.email);
END;
$$;

CREATE OR REPLACE FUNCTION app.superadmin_clients(target_firm uuid)
RETURNS TABLE (
    id uuid, name text, fy_start date, created_at timestamptz,
    bank_account_count bigint, statement_count bigint
) {_HEADER} AS $$
#variable_conflict use_column
BEGIN
    PERFORM app.superadmin_assert();
    RETURN QUERY
    SELECT c.id, c.name::text, c.fy_start, c.created_at,
           (SELECT count(*) FROM banking_bank_account b WHERE b.client_id = c.id),
           (SELECT count(*) FROM banking_statement s
              JOIN banking_bank_account b ON b.id = s.bank_account_id
             WHERE b.client_id = c.id)
    FROM core_client c
    WHERE c.firm_id = target_firm
    ORDER BY lower(c.name);
END;
$$;

-- Mirrors core.access.visible_clients: firm admin or all-clients access sees
-- everything; a Senior CA the clients they lead; everyone their assignments.
CREATE OR REPLACE FUNCTION app.superadmin_member_clients(target_firm uuid, target_membership uuid)
RETURNS TABLE (id uuid, name text, how text) {_HEADER} AS $$
#variable_conflict use_column
BEGIN
    PERFORM app.superadmin_assert();
    RETURN QUERY
    SELECT c.id, c.name::text,
           CASE WHEN m.role = 'FIRM_ADMIN' OR m.scope_all_clients THEN 'all'
                WHEN c.lead_id = m.id THEN 'leads'
                ELSE 'assigned' END
    FROM core_firm_membership m
    JOIN core_client c ON c.firm_id = m.firm_id
    WHERE m.id = target_membership AND m.firm_id = target_firm AND m.is_active
      AND (m.role = 'FIRM_ADMIN' OR m.scope_all_clients
           OR (m.role = 'SENIOR_CA' AND c.lead_id = m.id)
           OR EXISTS (SELECT 1 FROM core_client_assignment a
                      WHERE a.client_id = c.id AND a.membership_id = m.id))
    ORDER BY lower(c.name);
END;
$$;
"""

#: The platform admin's read models, one view per list. See the module docstring
#: for why each is gated and SELECT-only.
VIEWS = (
    "app.platform_firms",
    "app.platform_memberships",
    "app.platform_clients",
    "app.platform_client_assignments",
    "app.platform_audit_log",
    "app.platform_jobs",
)

_VIEW = "WITH (security_barrier = true) AS"
_GATE = "WHERE app.superadmin_can_read()"

VIEWS_SQL = (
    # Column lists change between versions, which CREATE OR REPLACE VIEW cannot
    # do; drop and recreate instead. Nothing depends on these views.
    "".join(f"DROP VIEW IF EXISTS {view};\n" for view in VIEWS)
    + f"""
CREATE VIEW app.platform_firms {_VIEW}
SELECT f.id, f.name::text AS name, f.is_active, f.created_at,
       (SELECT count(*) FROM core_firm_membership m WHERE m.firm_id = f.id) AS member_count,
       (SELECT count(*) FROM core_client c WHERE c.firm_id = f.id) AS client_count
FROM core_firm f
{_GATE};

CREATE VIEW app.platform_memberships {_VIEW}
SELECT m.id, m.firm_id, f.name::text AS firm_name,
       m.user_id, u.email::text AS email, u.full_name::text AS full_name,
       m.role::text AS role, m.is_active, m.is_owner, m.scope_all_clients,
       m.manager_id, mu.email::text AS manager_email, m.created_at
FROM core_firm_membership m
JOIN core_firm f ON f.id = m.firm_id
JOIN core_user u ON u.id = m.user_id
LEFT JOIN core_firm_membership mm ON mm.id = m.manager_id
LEFT JOIN core_user mu ON mu.id = mm.user_id
{_GATE};

-- A client's directory entry. The two counts are the only thing here that
-- touches a firm's financial records, and they are counts: how busy a client
-- is, never what is in a statement. ``business_profile`` is a few sentences the
-- CA wrote about what the client does, which is directory information rather
-- than a record; the app tells the CA to keep names and numbers out of it.
CREATE VIEW app.platform_clients {_VIEW}
SELECT c.id, c.firm_id, f.name::text AS firm_name, c.name::text AS name, c.fy_start,
       c.business_profile::text AS business_profile,
       c.lead_id, lu.email::text AS lead_email, c.created_at,
       (SELECT count(*) FROM core_client_assignment a WHERE a.client_id = c.id) AS team_size,
       (SELECT count(*) FROM banking_bank_account b WHERE b.client_id = c.id) AS bank_account_count,
       (SELECT count(*) FROM banking_statement s
          JOIN banking_bank_account b ON b.id = s.bank_account_id
         WHERE b.client_id = c.id) AS statement_count
FROM core_client c
JOIN core_firm f ON f.id = c.firm_id
LEFT JOIN core_firm_membership lm ON lm.id = c.lead_id
LEFT JOIN core_user lu ON lu.id = lm.user_id
{_GATE};

CREATE VIEW app.platform_client_assignments {_VIEW}
SELECT a.id, a.firm_id, a.client_id, c.name::text AS client_name,
       a.membership_id, m.user_id, u.email::text AS email, a.created_at
FROM core_client_assignment a
JOIN core_client c ON c.id = a.client_id
JOIN core_firm_membership m ON m.id = a.membership_id
JOIN core_user u ON u.id = m.user_id
{_GATE};

-- Request metadata only. The user agent is left out as noise.
CREATE VIEW app.platform_audit_log {_VIEW}
SELECT l.id, l.firm_id, f.name::text AS firm_name, l.user_id, u.email::text AS user_email,
       l.method::text AS method, l.path::text AS path, l.status_code,
       l.ip_address, l.request_id::text AS request_id, l.duration_ms, l.created_at
FROM core_audit_log l
LEFT JOIN core_firm f ON f.id = l.firm_id
LEFT JOIN core_user u ON u.id = l.user_id
{_GATE};

-- A job's state and its one-line message. ``result`` and the raw ``error`` are
-- left out: both can carry what the job read, which is a firm's data.
CREATE VIEW app.platform_jobs {_VIEW}
SELECT j.id, j.firm_id, f.name::text AS firm_name, j.kind::text AS kind,
       j.status::text AS status, j.progress, j.message::text AS message,
       j.error_code::text AS error_code, j.created_by_id,
       cu.email::text AS created_by_email, j.created_at, j.started_at, j.finished_at
FROM core_job j
JOIN core_firm f ON f.id = j.firm_id
LEFT JOIN core_user cu ON cu.id = j.created_by_id
{_GATE};
"""
)

# Handing a function to a new owner requires that owner to hold CREATE on the
# schema -- PostgreSQL will not let you park an object somewhere its owner could
# not have created it. The reader needs that right only for the instant of the
# ALTER, so it is granted here and taken back at the end; ownership, once set,
# outlives the privilege. USAGE stays, because the function bodies run as the
# reader and call app.try_user_id().
#
# This runs as the role that owns the schema -- the migrating role -- so it needs
# no superuser. That is deliberate: setup_sql/role.sql should remain the only
# step that needs Supabase's postgres login.
SCHEMA_GRANT_SQL = (
    f"GRANT USAGE, CREATE ON SCHEMA app TO {READER_ROLE};\n"
    # The directory functions are SECURITY DEFINER, so their bodies run as
    # the reader, not as the caller. app.superadmin_assert() asks
    # app.try_user_id() who the request belongs to, and without EXECUTE the
    # check that gates every one of these functions cannot run at all.
    # Granted to the reader alone; try_user_id only reads a GUC.
    f"GRANT EXECUTE ON FUNCTION app.try_user_id() TO {READER_ROLE};\n"
)
SCHEMA_REVOKE_SQL = f"REVOKE CREATE ON SCHEMA app FROM {READER_ROLE};\n"

PRIVILEGES_SQL = SCHEMA_GRANT_SQL + "".join(
    f"""
ALTER FUNCTION {fn} OWNER TO {READER_ROLE};
REVOKE ALL ON FUNCTION {fn} FROM PUBLIC;
GRANT EXECUTE ON FUNCTION {fn} TO {APP_ROLE};
"""
    for fn in FUNCTIONS
) + "".join(
    f"""
ALTER VIEW {view} OWNER TO {READER_ROLE};
REVOKE ALL ON {view} FROM PUBLIC;
GRANT SELECT ON {view} TO {APP_ROLE};
"""
    for view in VIEWS
) + "".join(f"GRANT SELECT ON {table} TO {READER_ROLE};\n" for table in TABLES) + SCHEMA_REVOKE_SQL

CREATE_SQL = FUNCTIONS_SQL + VIEWS_SQL + PRIVILEGES_SQL

#: Views first: they depend on app.superadmin_can_read().
DROP_VIEWS_SQL = "".join(f"DROP VIEW IF EXISTS {view};\n" for view in VIEWS)

DROP_SQL = DROP_VIEWS_SQL + "".join(f"DROP FUNCTION IF EXISTS {fn};\n" for fn in reversed(FUNCTIONS)) + "".join(
    f"""
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{READER_ROLE}') THEN
        REVOKE ALL ON {table} FROM {READER_ROLE};
    END IF;
END $$;
"""
    for table in TABLES
)


def reader_role_usable(cursor) -> bool:
    """The role exists and the current (migrating) role may hand it ownership."""
    cursor.execute(
        "SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_roles WHERE rolname = %s) "
        "THEN pg_has_role(current_user, %s, 'MEMBER') ELSE false END",
        [READER_ROLE, READER_ROLE],
    )
    return bool(cursor.fetchone()[0])


def functions_installed(cursor) -> bool:
    cursor.execute("SELECT to_regprocedure('app.superadmin_firms()') IS NOT NULL")
    return bool(cursor.fetchone()[0])


def views_installed(cursor) -> bool:
    cursor.execute("SELECT to_regclass('app.platform_firms') IS NOT NULL")
    return bool(cursor.fetchone()[0])
