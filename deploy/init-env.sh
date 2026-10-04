#!/bin/sh
# Writes .env.prod for compose.prod.yaml.
#
#   deploy/init-env.sh api.example.in my-s3-bucket
#
# It generates the three database passwords (so no one ever types or sees them), fills in what is known
# from the two arguments, and leaves BLANK the secrets that must be carried over from the running
# deployment, then lists them. It never overwrites an existing .env.prod.
set -eu

cd "$(dirname "$0")/.."

API_HOST="${1:?usage: deploy/init-env.sh API_HOST S3_BUCKET}"
BUCKET="${2:?usage: deploy/init-env.sh API_HOST S3_BUCKET}"

if [ -e .env.prod ]; then
    echo ".env.prod already exists; not overwriting it." >&2
    exit 1
fi

# Hex, so the passwords are safe inside a URL and inside the sed in init-roles.sh.
secret() { openssl rand -hex 24; }
PG="$(secret)"
OWNER="$(secret)"
WEB="$(secret)"

cp deploy/prod.env.example .env.prod
chmod 600 .env.prod

# Replace the value of KEY=... in the template. '|' is the delimiter: none of these values contain it.
put() { sed -i "s|^$1=.*|$1=$2|" .env.prod; }

put API_HOST "$API_HOST"
put DJANGO_ALLOWED_HOSTS "$API_HOST"
put STORAGE_BUCKET "$BUCKET"
put DATABASE_URL "postgresql://autoca_web:${WEB}@db:5432/autoca"
put DATABASE_OWNER_URL "postgresql://autoca_owner:${OWNER}@db:5432/autoca"
put DATABASE_IS_POOLED 0
put DATABASE_SSL_REQUIRE 0
put CELERY_BROKER_URL "redis://redis:6379/0"
put TRUSTED_PROXY_COUNT 1

{
    echo ""
    echo "# Read by compose to create the database roles on first start (see init-roles.sh)."
    echo "POSTGRES_PASSWORD=${PG}"
    echo "AUTOCA_OWNER_PASSWORD=${OWNER}"
    echo "AUTOCA_WEB_PASSWORD=${WEB}"
} >> .env.prod

echo "Wrote .env.prod (mode 600). Still empty, and to be filled in by hand:"
grep -E '^[A-Z_]+=$' .env.prod | sed 's/=$//' | sed 's/^/  - /'
