#!/bin/sh
# Restore the REAL database from a backup. Destructive: it replaces what the database holds now.
#
#   sh deploy/restore.sh daily/2026/10/05/autoca-20261005T203000Z.dump       (see: sh deploy/backup-status.sh 20)
#
# Use it on a replacement server (set up with deploy/init-env.sh --carry-secrets and the SAME three keys from
# your password manager), or after data was damaged. To merely prove that backups work, use
# deploy/restore-drill.sh, which only touches a scratch database.
set -eu

cd "$(dirname "$0")/.."

key="${1:?usage: sh deploy/restore.sh S3_KEY   (list them with: sh deploy/backup-status.sh 20)}"

SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"
compose() { $SUDO docker compose --env-file .env.prod -f compose.prod.yaml "$@"; }

echo "This REPLACES the contents of the live database with the backup:"
echo "    $key"
echo "Anything saved since that backup is lost. The web app is stopped while it runs."
printf 'Type RESTORE to continue: '
IFS= read -r answer
[ "$answer" = "RESTORE" ] || { echo "Cancelled; nothing was changed."; exit 1; }

echo "restore: stopping the web app and the proxy"
compose stop web caddy

echo "restore: loading $key"
# A one-off web container does the download (it holds the S3 tooling and the role); --clean drops each object
# before recreating it, so the database-level grants made when it was first created are kept.
compose run --rm --no-deps -T web python -m integrations.backup.s3 get "$key" \
    | compose exec -T db pg_restore -U postgres -d autoca --clean --if-exists --no-password

echo "restore: starting everything again (migrations run first)"
compose up -d
echo "restore: done. Check the site, then:  ac ps"
