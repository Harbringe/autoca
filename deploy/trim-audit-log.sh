#!/bin/sh
# Delete audit-log rows past their retention window (default 30 days; core/management/commands/trim_audit_log.py).
#
#   sudo sh deploy/trim-audit-log.sh          (the systemd timer runs it nightly; run it by hand any time)
#
# One-time setup, before the first run: superadmin/setup_sql/role.sql (as Postgres's own superuser), then
#   sudo docker compose --env-file .env.prod -f compose.prod.yaml exec -T web python manage.py install_log_retention --database=owner
#
# No login role here can delete an old row by itself: the application's own role has no DELETE grant on this table
# at all (core/migrations/0013_audit_log_append_only.py), and the privileged migrating role has no row-level-security
# policy that lets it see rows outside one firm at a time (docs/ARCHITECTURE.md, "Two database roles"). Deletion goes
# through app.trim_audit_log (core/retention_sql.py), the one function allowed to cross every firm for this one
# purpose; the database itself refuses it anything younger than the floor (core/migrations/0016), whatever is asked.
set -eu

cd "$(dirname "$0")/.."

SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"
compose() { $SUDO docker compose --env-file .env.prod -f compose.prod.yaml "$@"; }

compose exec -T web python manage.py trim_audit_log --database=owner < /dev/null
