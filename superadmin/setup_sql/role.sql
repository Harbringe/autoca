-- Platform layer: the one-time role setup.
--
-- Run ONCE per environment as Supabase's `postgres` role (SQL editor or psql).
-- Only a role that itself has BYPASSRLS may create one that does.
--
-- autoca_platform_reader can never log in. It exists only to own the platform
-- views and directory functions in superadmin/sql.py, which return firm names,
-- people and client names -- never books, statements or bank details.
--
-- Then, from the repository:
--   python manage.py superadmin install      (uses the owner database alias)
--   python manage.py superadmin grant you@example.com

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'autoca_platform_reader') THEN
        CREATE ROLE autoca_platform_reader NOLOGIN BYPASSRLS NOSUPERUSER NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;

-- The migrating role must be a member to hand function ownership to the reader.
-- Role attributes such as BYPASSRLS are never inherited through membership.
GRANT autoca_platform_reader TO autoca_owner;

-- The test role runs the same migrations in its scratch database. Omit this
-- line in production if autoca_test does not exist there.
GRANT autoca_platform_reader TO autoca_test;
