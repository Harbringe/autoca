#!/bin/sh
# Delete audit-log rows past their retention window (default 30 days; core/management/commands/trim_audit_log.py).
#
#   sudo sh deploy/trim-audit-log.sh          (the systemd timer runs it nightly; run it by hand any time)
#
# Runs as the privileged database role, the same one migrations use: the application's own role has no DELETE grant
# on this table at all (core/migrations/0013_audit_log_append_only.py), and the database itself refuses to remove
# anything younger than the floor (core/migrations/0016_audit_log_retention.py), whatever this is asked to delete.
set -eu

cd "$(dirname "$0")/.."

SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"
compose() { $SUDO docker compose --env-file .env.prod -f compose.prod.yaml "$@"; }

compose exec -T web python manage.py trim_audit_log --database=owner < /dev/null
