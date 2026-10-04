#!/bin/sh
# Runs once, when the Postgres volume is first created (docker-entrypoint-initdb.d).
# Creates the owner and app roles from scripts/bootstrap_db_roles.sql with the
# passwords supplied to the container, so no password is ever committed.
set -eu

: "${AUTOCA_OWNER_PASSWORD:?AUTOCA_OWNER_PASSWORD is required}"
: "${AUTOCA_WEB_PASSWORD:?AUTOCA_WEB_PASSWORD is required}"
: "${BOOTSTRAP_SQL:=/bootstrap_db_roles.sql}"

# The passwords go through sed into SQL, so a character either one treats specially would corrupt the
# statement or leave a role with the literal placeholder as its password. Refuse, never guess.
for password in "$AUTOCA_OWNER_PASSWORD" "$AUTOCA_WEB_PASSWORD"; do
    case "$password" in
        *[!A-Za-z0-9]*)
            echo "init-roles: database passwords may contain only letters and digits (e.g. openssl rand -hex 24)" >&2
            exit 1
            ;;
    esac
done

sql="$(sed -e "s/CHANGE_ME_OWNER/${AUTOCA_OWNER_PASSWORD}/g" \
           -e "s/CHANGE_ME_WEB/${AUTOCA_WEB_PASSWORD}/g" \
           "$BOOTSTRAP_SQL")"

case "$sql" in
    *CHANGE_ME*)
        echo "init-roles: a placeholder password is still in the bootstrap SQL; refusing to create the roles" >&2
        exit 1
        ;;
esac

printf '%s\n' "$sql" | psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"
