-- Create the two database roles this application requires.
--
-- Run ONCE per environment, as a superuser (or as Supabase's `postgres` role),
-- via the Supabase SQL editor or psql. Substitute the two passwords first.
--
-- Why two roles: row-level security has three escape hatches -- superuser,
-- BYPASSRLS, and table ownership without FORCE. The app role has none of them,
-- so tenant isolation holds even if every line of Python in this repository is
-- wrong. That is the property being bought here.

-- ---------------------------------------------------------------------------
-- 1. The owner role. Owns the schema, runs migrations, never serves a request.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autoca_owner') THEN
        CREATE ROLE autoca_owner LOGIN PASSWORD 'CHANGE_ME_OWNER'
            NOSUPERUSER NOBYPASSRLS NOCREATEROLE;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 2. The group role that holds the application's DML grants. Migrations grant
--    to this stable name so they never need to know the login credentials.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autoca_app') THEN
        CREATE ROLE autoca_app NOLOGIN NOSUPERUSER NOBYPASSRLS;
    END IF;
END
$$;

-- ---------------------------------------------------------------------------
-- 3. The login role the application actually connects as.
--    NOSUPERUSER and NOBYPASSRLS are the load-bearing words in this file.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autoca_web') THEN
        CREATE ROLE autoca_web LOGIN PASSWORD 'CHANGE_ME_WEB'
            NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE INHERIT;
    END IF;
END
$$;

-- WITH INHERIT TRUE is not decoration. From PostgreSQL 16 onward, a role
-- membership records its inherit option AT GRANT TIME, copied from the member
-- role's current rolinherit setting. Granting to a NOINHERIT role and running
-- ALTER ROLE ... INHERIT afterwards does NOT retroactively fix the membership:
-- the role keeps showing as a member while silently inheriting nothing, and
-- every query fails with "permission denied for table ..." instead of the
-- tenant-context error you expect. Being explicit here removes the ordering
-- dependency entirely.
GRANT autoca_app TO autoca_web WITH INHERIT TRUE;

-- ---------------------------------------------------------------------------
-- 4. The role the test suite connects as.
--
--    Django's test runner creates and drops a scratch database per run, so this
--    role needs CREATEDB -- and nothing else. It must NOT be a superuser and
--    must NOT have BYPASSRLS: if it did, every assertion in the isolation suite
--    would pass vacuously while proving nothing.
--    core/tests/test_rls_isolation.py::test_connection_role_cannot_bypass_rls
--    fails the build if this is ever got wrong.
--
--    Tables in the scratch database end up owned by this role. That is fine
--    precisely because every policy is FORCE'd -- which is also the property
--    being tested.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autoca_test') THEN
        CREATE ROLE autoca_test LOGIN PASSWORD 'CHANGE_ME_TEST'
            NOSUPERUSER NOBYPASSRLS CREATEDB;
    END IF;
END
$$;

-- The test role stands in for the application role, so it must be a MEMBER of
-- autoca_app. Policies are scoped `TO autoca_app`; a role outside that group has
-- no policy applied to it at all, and RLS then denies everything by default --
-- including a firm's writes to its own rows. That failure looks like working
-- isolation while actually testing nothing.
GRANT autoca_app TO autoca_test WITH INHERIT TRUE;

-- CREATE on the database: migrations run `CREATE SCHEMA app`, and the test role
-- runs those same migrations inside its scratch database.
GRANT CREATE ON DATABASE postgres TO autoca_owner, autoca_test;

-- ---------------------------------------------------------------------------
-- 5. Schema privileges. The app role may use the schema but never create in it.
-- ---------------------------------------------------------------------------
GRANT USAGE ON SCHEMA public TO autoca_app;
REVOKE CREATE ON SCHEMA public FROM autoca_app, PUBLIC;
GRANT ALL ON SCHEMA public TO autoca_owner;

-- ---------------------------------------------------------------------------
-- Then, from the repository:
--
--   DATABASE_OWNER_URL=postgresql://autoca_owner:...@host:5432/postgres
--   DATABASE_URL=postgresql://autoca_web:...@host:6543/postgres
--
--   python manage.py migrate --database=owner
--   python manage.py grant_app_role --database=owner
--   python manage.py check --deploy --database default
--   python manage.py rls_status
--
-- Note the ports: migrations go direct (5432), the app goes through the
-- transaction pooler (6543) with DATABASE_IS_POOLED=1.
-- ---------------------------------------------------------------------------
