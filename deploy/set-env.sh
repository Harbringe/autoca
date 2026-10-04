#!/bin/sh
# Change one setting in .env.prod without showing its value or leaving it in your shell history.
#
#   deploy/set-env.sh GROQ_API_KEY
#
# It asks for the value (typing is hidden), replaces the existing KEY=... line, and keeps the file private.
# The key must already be in the file; add a brand-new setting by hand. Settings are read when a container
# is CREATED, so after changing one run:  ac up -d --force-recreate web   (a plain restart keeps the old value).
set -eu

cd "$(dirname "$0")/.."

key="${1:?usage: deploy/set-env.sh KEY}"
case "$key" in
    "" | *[!A-Z0-9_]*)
        echo "set-env: '$key' is not a setting name (capitals, digits and underscores only)" >&2
        exit 1
        ;;
esac
[ -f .env.prod ] || { echo "set-env: .env.prod not found; run deploy/init-env.sh first" >&2; exit 1; }
grep -q "^${key}=" .env.prod || { echo "set-env: ${key} is not in .env.prod (add it by hand first)" >&2; exit 1; }

if [ -t 0 ]; then
    printf 'New value for %s (typing is hidden): ' "$key" >&2
    stty -echo
    trap 'stty echo' EXIT
    IFS= read -r value
    stty echo
    trap - EXIT
    printf '\n' >&2
else
    IFS= read -r value
fi

# The value travels in the environment, never on a command line (where `ps` shows it) and never through sed,
# which would treat '&', '|' and '\' in a secret as instructions.
umask 077
VALUE="$value" awk -v key="$key" 'BEGIN { FS = OFS = "=" }
    $1 == key { print key "=" ENVIRON["VALUE"]; next }
    { print }' .env.prod > .env.prod.new
mv .env.prod.new .env.prod
chmod 600 .env.prod

if [ -z "$value" ]; then
    echo "set-env: ${key} is now empty." >&2
else
    echo "set-env: ${key} updated. Now run:  ac up -d --force-recreate web" >&2
fi
