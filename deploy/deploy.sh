#!/bin/sh
# Update the running server to the latest code on this branch, then check it is healthy.
#
#   deploy/deploy.sh
#
# Pulls, rebuilds the images, and brings everything up (the migrate step runs first, every time). It does not
# touch the database's data or the .env files. If the check at the end fails, the previous images are still
# on disk: see the "Going back" notes in docs/AWS.md.
set -eu

cd "$(dirname "$0")/.."

compose() { sudo docker compose --env-file .env.prod -f compose.prod.yaml "$@"; }

git pull --ff-only
compose build
compose up -d

echo "Waiting for the app to come up..."
sleep 30
compose ps

host="$(grep '^APP_HOST=' .env.prod | cut -d= -f2-)"
if curl -fsS "https://${host}/healthz" > /dev/null; then
    echo "Healthy: https://${host}/healthz answered."
else
    echo "NOT healthy: https://${host}/healthz did not answer. Look at:  ac logs --tail 100 web" >&2
    exit 1
fi
