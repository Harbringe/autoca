#!/bin/sh
# Runs once, when the Postgres volume is first created (docker-entrypoint-initdb.d).
# Creates the owner and app roles from scripts/bootstrap_db_roles.sql with the
# passwords supplied to the container, so no password is ever committed.
set -eu

: "${AUTOCA_OWNER_PASSWORD:?AUTOCA_OWNER_PASSWORD is required}"
: "${AUTOCA_WEB_PASSWORD:?AUTOCA_WEB_PASSWORD is required}"

sed -e "s/CHANGE_ME_OWNER/${AUTOCA_OWNER_PASSWORD}/g" \
    -e "s/CHANGE_ME_WEB/${AUTOCA_WEB_PASSWORD}/g" \
    /bootstrap_db_roles.sql \
  | psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"
