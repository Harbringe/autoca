-- The database roles for a production deployment (compose.prod.yaml). Run once, when the database is
-- first created, by deploy/init-roles.sh, which fills in the two passwords.
--
-- This is scripts/bootstrap_db_roles.sql without the test-suite role. That role (autoca_test) can create
-- databases and has no business existing where real client data lives, and its password is a placeholder
-- nobody should ever have to invent.
--
-- Why two login roles: row-level security has three escape hatches -- superuser, BYPASSRLS, and table
-- ownership without FORCE. The app role has none of them, so tenant isolation holds even if every line of
-- Python in this repository is wrong. That property is the point of this file.

-- 1. The owner role. Owns the schema, runs migrations, never serves a request.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autoca_owner') THEN
        CREATE ROLE autoca_owner LOGIN PASSWORD 'CHANGE_ME_OWNER'
            NOSUPERUSER NOBYPASSRLS NOCREATEROLE;
    END IF;
END
$$;

-- 2. The group role that holds the application's DML grants. Migrations grant to this stable name so they
--    never need to know the login credentials.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autoca_app') THEN
        CREATE ROLE autoca_app NOLOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;
END
$$;

-- 3. The login role the application connects as. NOSUPERUSER and NOBYPASSRLS are the load-bearing words.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autoca_web') THEN
        CREATE ROLE autoca_web LOGIN PASSWORD 'CHANGE_ME_WEB'
            NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE INHERIT;
    END IF;
END
$$;

-- WITH INHERIT TRUE is not decoration. From PostgreSQL 16 a membership records its inherit option AT GRANT
-- TIME, so being explicit removes an ordering dependency that otherwise fails with "permission denied".
GRANT autoca_app TO autoca_web WITH INHERIT TRUE;

-- 4. The platform reader. The platform owner's admin panel lists firms, people and clients across firms
--    through views owned by this role (see superadmin/README.md). It cannot log in, and it is the one role
--    here that bypasses row-level security, which is why only a superuser can create it: this script runs
--    as one, once, when the database is first made. Without it the views are skipped and the panel's
--    cross-firm lists stay empty. The owner must be a member to hand it ownership of the views.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autoca_platform_reader') THEN
        CREATE ROLE autoca_platform_reader NOLOGIN BYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;

GRANT autoca_platform_reader TO autoca_owner;

-- 5. Privileges. Migrations run `CREATE SCHEMA app`, so the owner needs CREATE on this database (whatever
--    it is called here, not a hard-coded name). The app role may use the schema but never create in it.
DO $$
BEGIN
    EXECUTE format('GRANT CREATE ON DATABASE %I TO autoca_owner', current_database());
END
$$;

GRANT USAGE ON SCHEMA public TO autoca_app;
REVOKE CREATE ON SCHEMA public FROM autoca_app, PUBLIC;
GRANT ALL ON SCHEMA public TO autoca_owner;
