#!/bin/sh
# Runs once, when the Postgres volume is first created (docker-entrypoint-initdb.d).
# Creates the database roles from the bootstrap SQL with the passwords supplied to the container, so no
# password is ever committed. compose.prod.yaml mounts scripts/bootstrap_db_roles_prod.sql as the
# bootstrap SQL; the dev compose mounts scripts/bootstrap_db_roles.sql, which also creates the test role.
set -eu

: "${AUTOCA_OWNER_PASSWORD:?AUTOCA_OWNER_PASSWORD is required}"
: "${AUTOCA_WEB_PASSWORD:?AUTOCA_WEB_PASSWORD is required}"
: "${BOOTSTRAP_SQL:=/bootstrap_db_roles.sql}"

# The passwords go through sed into SQL, so a character sed treats specially would corrupt the statement
# or leave a role with the literal placeholder as its password. Refuse, never guess. The test-role
# password is optional (only the dev SQL has that role) and is checked the same way when it is given.
for password in "$AUTOCA_OWNER_PASSWORD" "$AUTOCA_WEB_PASSWORD" "${AUTOCA_TEST_PASSWORD:-}"; do
    case "$password" in
        *[!A-Za-z0-9]*)
            echo "init-roles: database passwords may contain only letters and digits (e.g. openssl rand -hex 24)" >&2
            exit 1
            ;;
    esac
done

sql="$(sed -e "s/CHANGE_ME_OWNER/${AUTOCA_OWNER_PASSWORD}/g" \
           -e "s/CHANGE_ME_WEB/${AUTOCA_WEB_PASSWORD}/g" \
           -e "s/CHANGE_ME_TEST/${AUTOCA_TEST_PASSWORD:-CHANGE_ME_TEST}/g" \
           "$BOOTSTRAP_SQL")"

# A role with a placeholder password is a login with a known password. If any placeholder is left,
# create nothing.
case "$sql" in
    *CHANGE_ME*)
        echo "init-roles: a placeholder password is still in the bootstrap SQL; refusing to create the roles" >&2
        exit 1
        ;;
esac

printf '%s\n' "$sql" | psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB"
