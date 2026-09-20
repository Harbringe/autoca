-- Platform layer: remove the role. Run as `postgres` AFTER
--   python manage.py migrate superadmin zero --database=owner
-- (which drops the platform views and functions and revokes the table grants).

REVOKE autoca_platform_reader FROM autoca_owner;
REVOKE autoca_platform_reader FROM autoca_test;
DROP ROLE IF EXISTS autoca_platform_reader;
