#!/bin/sh
# Nightly database backup: dump, prove the dump is readable, upload it to S3, prove S3 holds all of it.
#
#   sudo sh deploy/backup.sh          (the systemd timer runs it at 02:00 IST; run it by hand any time)
#
# It stops at the first thing that does not check out, exits non-zero, and uploads nothing it could not read
# back. A backup that quietly saved a broken file is worse than none, because it is trusted.
#
# The three permanent keys (.env.prod) are NOT in the dump, on purpose: without them the stored bank account
# numbers cannot be read, which is exactly why they are kept apart (password manager). The dump holds the data.
set -eu

cd "$(dirname "$0")/.."

SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"
compose() { $SUDO docker compose --env-file .env.prod -f compose.prod.yaml "$@"; }
fail() { echo "backup FAILED: $*" >&2; exit 1; }

# A migrated, empty database already dumps to well over this, so anything smaller is not a real dump.
MIN_BYTES="${BACKUP_MIN_BYTES:-20000}"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

key="daily/$(date -u +%Y/%m/%d)/autoca-$(date -u +%Y%m%dT%H%M%SZ).dump"

echo "backup: dumping the database"
compose exec -T db pg_dump -U postgres -d autoca -Fc < /dev/null > "$tmp/db.dump" || fail "pg_dump did not finish"
size="$(wc -c < "$tmp/db.dump" | tr -d ' ')"
[ "$size" -ge "$MIN_BYTES" ] || fail "the dump is only $size bytes (expected at least $MIN_BYTES)"

echo "backup: checking the dump can be read back ($size bytes)"
compose exec -T db pg_restore --list < "$tmp/db.dump" > "$tmp/contents.txt" || fail "pg_restore cannot read the dump"
tables="$(grep -c 'TABLE DATA' "$tmp/contents.txt" || true)"
[ "$tables" -gt 0 ] || fail "the dump lists no table data"

echo "backup: uploading to S3 as $key"
stored="$(compose exec -T web python -m integrations.backup.s3 put "$key" < "$tmp/db.dump")" || fail "the upload did not finish"
[ "$stored" = "$size" ] || fail "S3 holds $stored bytes but the dump is $size"

echo "backup ok: $key ($size bytes)"
