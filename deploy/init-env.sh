#!/bin/sh
# Writes the three settings files compose.prod.yaml reads.
#
#   deploy/init-env.sh APP_HOST API_HOST S3_BUCKET [BACKUP_BUCKET] [--carry-secrets]
#   deploy/init-env.sh app.example.in api.example.in my-s3-bucket my-backups-bucket
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
# The database passwords are always generated here (hex), so no one types or sees them.
#
# The three application secrets (DJANGO_SECRET_KEY, KMS_LOCAL_MASTER_KEY, BLIND_INDEX_KEY) are generated
# too, for a NEW deployment. They are then permanent: the first two protect stored bank account numbers,
# and losing either makes them unreadable, so back them up. For a deployment that already has data,
# pass --carry-secrets and they are left blank, to be copied exactly from the running one.
#
# Nothing is overwritten if any of the files exists.
set -eu

cd "$(dirname "$0")/.."

CARRY=0
args=""
for arg in "$@"; do
    case "$arg" in
        --carry-secrets) CARRY=1 ;;
        *) args="$args $arg" ;;
    esac
done
# shellcheck disable=SC2086
set -- $args

APP_HOST="${1:?usage: deploy/init-env.sh APP_HOST API_HOST S3_BUCKET [--carry-secrets]}"
API_HOST="${2:?usage: deploy/init-env.sh APP_HOST API_HOST S3_BUCKET [--carry-secrets]}"
BUCKET="${3:?usage: deploy/init-env.sh APP_HOST API_HOST S3_BUCKET [BACKUP_BUCKET] [--carry-secrets]}"
BACKUP_BUCKET="${4:-}"

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
    printf 's|^APP_HOST=.*|APP_HOST=%s|\n' "$APP_HOST"
    printf 's|^API_HOST=.*|API_HOST=%s|\n' "$API_HOST"
    printf 's|^DJANGO_ALLOWED_HOSTS=.*|DJANGO_ALLOWED_HOSTS=%s,%s|\n' "$APP_HOST" "$API_HOST"
    printf 's|^FRONTEND_URL=.*|FRONTEND_URL=https://%s|\n' "$APP_HOST"
    printf 's|^CSRF_TRUSTED_ORIGINS=.*|CSRF_TRUSTED_ORIGINS=https://%s,https://%s|\n' "$APP_HOST" "$API_HOST"
    printf 's|^STORAGE_BUCKET=.*|STORAGE_BUCKET=%s|\n' "$BUCKET"
    if [ -n "$BACKUP_BUCKET" ]; then printf 's|^BACKUP_BUCKET=.*|BACKUP_BUCKET=%s|\n' "$BACKUP_BUCKET"; fi
    printf 's|^DATABASE_URL=.*|DATABASE_URL=postgresql://autoca_web:%s@db:5432/autoca|\n' "$WEB"
    printf 's|^CELERY_BROKER_URL=.*|CELERY_BROKER_URL=redis://redis:6379/0|\n'
    printf 's|^TRUSTED_PROXY_COUNT=.*|TRUSTED_PROXY_COUNT=1|\n'
    printf 's|^GROQ_MODEL=.*|GROQ_MODEL=openai/gpt-oss-120b|\n'
    if [ "$CARRY" -eq 0 ]; then
        printf 's|^DJANGO_SECRET_KEY=.*|DJANGO_SECRET_KEY=%s|\n' "$(openssl rand -hex 50)"
        # A Fernet key: 32 random bytes, urlsafe base64.
        printf 's|^KMS_LOCAL_MASTER_KEY=.*|KMS_LOCAL_MASTER_KEY=%s|\n' "$(openssl rand -base64 32 | tr '+/' '-_')"
        printf 's|^BLIND_INDEX_KEY=.*|BLIND_INDEX_KEY=%s|\n' "$(openssl rand -base64 48 | tr -d '\n' | tr '+/' '-_' | tr -d '=')"
    fi
} | sed -i -f - .env.prod

printf 'DATABASE_OWNER_URL=postgresql://autoca_owner:%s@db:5432/autoca\n' "$OWNER" > .env.owner

{
    printf 'POSTGRES_PASSWORD=%s\n' "$PG"
    printf 'AUTOCA_OWNER_PASSWORD=%s\n' "$OWNER"
    printf 'AUTOCA_WEB_PASSWORD=%s\n' "$WEB"
} > .env.db

echo "Wrote .env.prod, .env.owner and .env.db (all mode 600)."
if [ "$CARRY" -eq 0 ]; then
    echo "Generated DJANGO_SECRET_KEY, KMS_LOCAL_MASTER_KEY and BLIND_INDEX_KEY. They are permanent."
    echo "BACK THEM UP NOW (password manager): losing the last two makes stored bank account numbers unreadable."
fi
echo "Still empty in .env.prod, to be filled in by hand:"
grep -E '^[A-Z_]+=$' .env.prod | sed 's/=$//' | sed 's/^/  - /'
