#!/bin/sh
# Prove the backups work: take a fresh one, restore it into a scratch database, and compare it with the live one.
#
#   sh deploy/restore-drill.sh          run once after setting up backups, then monthly
#
# The live database is only READ. The scratch database (restore_drill_<time>) is created, checked and dropped.
# A backup that has never been restored is a hope, not a backup.
set -eu

cd "$(dirname "$0")/.."

SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"
compose() { $SUDO docker compose --env-file .env.prod -f compose.prod.yaml "$@"; }
psql() { compose exec -T db psql -U postgres -v ON_ERROR_STOP=1 -tA "$@" < /dev/null; }

# The tables whose row counts are compared, plus the settings that make this a multi-tenant database.
TABLES="core_firm core_user core_client banking_statement banking_statement_transaction classify_ledger_account classify_transaction_classification ledger_journal_entry django_migrations"

echo "drill: taking a fresh backup first, so the live data and the dump agree"
out="$(sh deploy/backup.sh)"
printf '%s\n' "$out"
key="$(printf '%s\n' "$out" | sed -n 's/^backup ok: \([^ ]*\) .*/\1/p' | tail -1)"
[ -n "$key" ] || { echo "drill FAILED: the backup did not report a key" >&2; exit 1; }

scratch="restore_drill_$(date -u +%s)"
cleanup() { psql -d postgres -c "drop database if exists $scratch" > /dev/null 2>&1 || true; }
trap cleanup EXIT

echo "drill: restoring $key into the scratch database $scratch"
psql -d postgres -c "create database $scratch" > /dev/null
compose exec -T web python -m integrations.backup.s3 get "$key" < /dev/null \
    | compose exec -T db pg_restore -U postgres -d "$scratch" --no-password 2> /tmp/restore-drill.err || true
if [ -s /tmp/restore-drill.err ]; then
    echo "drill: pg_restore reported (first lines):"
    head -5 /tmp/restore-drill.err
fi

failed=0
echo "drill: comparing the restored copy with the live database"
for t in $TABLES; do
    live="$(psql -d autoca -c "select count(*) from $t")" || { echo "  cannot read live $t"; failed=1; continue; }
    restored="$(psql -d "$scratch" -c "select count(*) from $t" 2> /dev/null)" || { echo "  MISSING in the restore: $t"; failed=1; continue; }
    # The live database may have gained a row since the dump was taken, but it cannot have lost one.
    # The migration history must match exactly.
    if [ "$t" = "django_migrations" ]; then
        [ "$restored" = "$live" ] && status=ok || status=MISMATCH
    else
        [ "$restored" -le "$live" ] && status=ok || status=MISMATCH
    fi
    [ "$status" = ok ] || failed=1
    printf '  %-45s live=%-8s restored=%-8s %s\n' "$t" "$live" "$restored" "$status"
done

for check in \
    "tables|select count(*) from information_schema.tables where table_schema in ('public','app')" \
    "row-level-security policies|select count(*) from pg_policies"; do
    label="${check%%|*}"
    query="${check#*|}"
    live="$(psql -d autoca -c "$query")"
    restored="$(psql -d "$scratch" -c "$query")"
    [ "$restored" = "$live" ] && status=ok || status=MISMATCH
    [ "$status" = ok ] || failed=1
    printf '  %-45s live=%-8s restored=%-8s %s\n' "$label" "$live" "$restored" "$status"
done

if [ "$failed" -ne 0 ]; then
    echo "DRILL FAILED: the restored copy does not match. Do not trust this backup until it is explained." >&2
    exit 1
fi
echo "DRILL PASSED: $key restores completely."
