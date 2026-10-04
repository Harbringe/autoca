#!/bin/sh
# Writes the three settings files compose.prod.yaml reads.
#
#   deploy/init-env.sh api.example.in my-s3-bucket
#
# They are separate on purpose, so each container only receives the credentials it needs:
#
#   .env.prod   the app's settings: what the web process and the migrate step both read. It holds the
#               app role's database login, and nothing that can change the schema or bypass row-level
#               security.
#   .env.owner  the owner role's login. Only the migrate step reads it; the web process never does.
#   .env.db     the database's own bootstrap passwords (the superuser and both roles). Only the
#               database container reads it.
#
# The database passwords are generated here (hex), so no one types or sees them. The secrets that must
# be carried over from the running deployment are left BLANK in .env.prod, and listed. Nothing is
# overwritten if any of the files exists.
set -eu

cd "$(dirname "$0")/.."

API_HOST="${1:?usage: deploy/init-env.sh API_HOST S3_BUCKET}"
BUCKET="${2:?usage: deploy/init-env.sh API_HOST S3_BUCKET}"

for existing in .env.prod .env.owner .env.db; do
    if [ -e "$existing" ]; then
        echo "$existing already exists; not overwriting anything." >&2
        exit 1
    fi
done

# Files are created private from the first byte.
umask 077

# Hex, so the passwords are safe inside a URL and inside the sed in init-roles.sh.
secret() { openssl rand -hex 24; }
PG="$(secret)"
OWNER="$(secret)"
WEB="$(secret)"

cp deploy/prod.env.example .env.prod

# Replace KEY=... in .env.prod. The edits are fed to sed on stdin, not on its command line, so the
# values never show up in the process list. '|' is the delimiter: none of these values contain it.
{
    printf 's|^API_HOST=.*|API_HOST=%s|\n' "$API_HOST"
    printf 's|^DJANGO_ALLOWED_HOSTS=.*|DJANGO_ALLOWED_HOSTS=%s|\n' "$API_HOST"
    printf 's|^STORAGE_BUCKET=.*|STORAGE_BUCKET=%s|\n' "$BUCKET"
    printf 's|^DATABASE_URL=.*|DATABASE_URL=postgresql://autoca_web:%s@db:5432/autoca|\n' "$WEB"
    printf 's|^CELERY_BROKER_URL=.*|CELERY_BROKER_URL=redis://redis:6379/0|\n'
    printf 's|^TRUSTED_PROXY_COUNT=.*|TRUSTED_PROXY_COUNT=1|\n'
} | sed -i -f - .env.prod

printf 'DATABASE_OWNER_URL=postgresql://autoca_owner:%s@db:5432/autoca\n' "$OWNER" > .env.owner

{
    printf 'POSTGRES_PASSWORD=%s\n' "$PG"
    printf 'AUTOCA_OWNER_PASSWORD=%s\n' "$OWNER"
    printf 'AUTOCA_WEB_PASSWORD=%s\n' "$WEB"
} > .env.db

echo "Wrote .env.prod, .env.owner and .env.db (all mode 600)."
echo "Still empty in .env.prod, to be filled in by hand:"
grep -E '^[A-Z_]+=$' .env.prod | sed 's/=$//' | sed 's/^/  - /'
