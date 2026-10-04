#!/bin/sh
# Replace the three permanent application keys in .env.prod with new random ones, then show them once for
# saving (see show-keys.sh).
#
#   sh deploy/new-keys.sh
#
# ONLY safe while nothing is encrypted under the old keys. The first two protect stored bank account
# numbers: after a key is replaced, every number encrypted under the old one is unreadable and every lookup
# misses. So this REFUSES to run if any firm exists, and it cannot be talked into it. Use it right after
# setting a server up, or after a key was exposed before anyone had stored data.
set -eu

cd "$(dirname "$0")/.."
[ -f .env.prod ] || { echo "new-keys: .env.prod not found" >&2; exit 1; }

compose() { sudo docker compose --env-file .env.prod -f compose.prod.yaml "$@"; }

firms="$(compose exec -T db psql -U postgres -d autoca -tAc "select count(*) from core_firm" 2>/dev/null || echo '?')"
firms="$(printf '%s' "$firms" | tr -d '[:space:]')"
if [ "$firms" != "0" ]; then
    echo "new-keys: refusing. The database has '$firms' firm(s) (or could not be read)." >&2
    echo "Replacing the keys now would make stored bank account numbers unreadable." >&2
    exit 1
fi

umask 077
{
    printf 's|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=%s|\n' "$(openssl rand -hex 50)"
    printf 's|^KMS_LOCAL_MASTER_KEY=.*|KMS_LOCAL_MASTER_KEY=%s|\n' "$(openssl rand -base64 32 | tr '+/' '-_')"
    printf 's|^BLIND_INDEX_KEY=.*|BLIND_INDEX_KEY=%s|\n' "$(openssl rand -base64 48 | tr -d '\n' | tr '+/' '-_' | tr -d '=')"
} | sed -i -f - .env.prod
chmod 600 .env.prod

echo "New keys written to .env.prod. The old ones no longer match anything."
echo "Now apply them (the app reads settings when it is created):   ac up -d --force-recreate web"
echo
sh deploy/show-keys.sh
