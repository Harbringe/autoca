#!/bin/sh
# Show the newest backups and warn if the latest is stale.
#
#   sh deploy/backup-status.sh [how-many]       (default 7)
set -eu

cd "$(dirname "$0")/.."

SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"
compose() { $SUDO docker compose --env-file .env.prod -f compose.prod.yaml "$@"; }

echo "Newest backups (key, age, bytes):"
compose exec -T web python -m integrations.backup.s3 list "${1:-7}" < /dev/null

latest="$(compose exec -T web python -m integrations.backup.s3 latest < /dev/null || true)"
hours="$(printf '%s' "$latest" | awk '{print $2}' | tr -d 'h')"
if [ -z "$hours" ]; then
    echo
    echo "WARNING: there are no backups at all." >&2
    exit 1
fi
if awk -v h="$hours" 'BEGIN { exit !(h > 26) }'; then
    echo
    echo "WARNING: the newest backup is ${hours} hours old (the nightly one should be under 26)." >&2
    exit 1
fi
echo
echo "OK: the newest backup is ${hours} hours old."
