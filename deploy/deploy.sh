#!/bin/sh
# Update the running server to the latest code on this branch, then check it is healthy.
#
#   deploy/deploy.sh [COMMIT]
#
#   With a COMMIT (what the GitHub deploy job passes), it refuses to go on unless that commit is part of what it
#   just pulled, so a deploy can never quietly ship something other than what was tested.
#
# Pulls, rebuilds the images, and brings everything up (the migrate step runs first, every time). It does not
# touch the database's data or the .env files. If the check at the end fails, the previous images are still
# on disk: see the "Going back" notes in docs/AWS.md.
set -eu

cd "$(dirname "$0")/.."

compose() { sudo docker compose --env-file .env.prod -f compose.prod.yaml "$@"; }

git pull --ff-only

want="${1:-}"
if [ -n "$want" ]; then
    git cat-file -e "$want^{commit}" 2>/dev/null || { echo "Refusing: commit $want is not on this server after pulling." >&2; exit 1; }
    git merge-base --is-ancestor "$want" HEAD || { echo "Refusing: $want is not part of the code now checked out ($(git rev-parse --short HEAD))." >&2; exit 1; }
    echo "Deploying $(git rev-parse --short HEAD) (includes $want)."
fi
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
