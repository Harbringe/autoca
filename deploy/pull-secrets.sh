#!/bin/sh
# Bring the settings kept in AWS Parameter Store into .env.prod. Run by deploy.sh before the images are rebuilt.
#
#   deploy/pull-secrets.sh
#
# Reads /autoca/prod/* and, for each setting, replaces the KEY=... line in .env.prod or adds it. The permanent
# keys and database credentials are only filled in when missing, never replaced (see integrations/paramstore.py). A setting that is not in Parameter Store is left exactly as it
# is, so nothing breaks while you move settings over one at a time. The values never appear on screen, in the
# deploy log, or on a command line: they pass through a private temporary file and an environment variable.
#
# If Parameter Store cannot be reached (no permission yet, no network), this says so and leaves .env.prod
# untouched, and the deploy goes on with the settings already there. It never fails the deploy.
set -u

cd "$(dirname "$0")/.."
[ -f .env.prod ] || { echo "pull-secrets: .env.prod not found; nothing to update." >&2; exit 0; }

umask 077
fetched="$(mktemp)"
trap 'rm -f "$fetched" "$fetched.err" .env.prod.new' EXIT

# A one-off container: the server's IAM role signs the request, and the app image already has the client library.
if ! sudo docker compose --env-file .env.prod -f compose.prod.yaml run --rm --no-deps -T web \
        python -m integrations.paramstore > "$fetched" 2> "$fetched.err"; then
    sed 's/^/pull-secrets: /' "$fetched.err" >&2
    rm -f "$fetched.err"
    echo "pull-secrets: keeping the settings already in .env.prod." >&2
    exit 0
fi
sed 's/^/pull-secrets: /' "$fetched.err" >&2
rm -f "$fetched.err"

changed=""
while IFS= read -r line; do
    key="${line%%=*}"
    value="${line#*=}"
    seed=""
    case "$key" in "?"*) seed=1; key="${key#?}" ;; esac
    case "$key" in "" | *[!A-Z0-9_]*) continue ;; esac
    current="$(grep "^${key}=" .env.prod | head -n 1 | cut -d= -f2-)"
    [ "$current" = "$value" ] && continue
    if [ -n "$seed" ] && [ -n "$current" ]; then
        # A permanent key or a database credential: Parameter Store fills in a missing one but never replaces one.
        echo "pull-secrets: ${key} in Parameter Store differs from this server; kept the server's value."
        continue
    fi
    # The value travels in the environment, never on a command line and never through sed, which would treat
    # '&', '|' and '\' in a secret as instructions.
    if grep -q "^${key}=" .env.prod; then
        VALUE="$value" awk -v key="$key" 'BEGIN { FS = OFS = "=" }
            $1 == key { print key "=" ENVIRON["VALUE"]; next }
            { print }' .env.prod > .env.prod.new
    else
        { cat .env.prod; VALUE="$value" awk -v key="$key" 'BEGIN { print key "=" ENVIRON["VALUE"] }'; } > .env.prod.new
    fi
    mv .env.prod.new .env.prod
    chmod 600 .env.prod
    changed="$changed $key"
done < "$fetched"

if [ -n "$changed" ]; then
    echo "pull-secrets: updated from Parameter Store:$changed"
else
    echo "pull-secrets: nothing changed."
fi
