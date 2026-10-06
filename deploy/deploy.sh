#!/bin/sh
# Update the running server to the latest code on this branch, then check it is healthy.
#
#   deploy/deploy.sh [COMMIT]
#
#   With a COMMIT (what the GitHub deploy job passes), it moves to exactly that commit and refuses to go on if it
#   cannot, so a deploy ships what was tested and never a later push. Without one it pulls the branch tip.
#
# Pulls, rebuilds the images, and brings everything up (the migrate step runs first, every time). It does not
# touch the database's data or the .env files. If the check at the end fails, the previous images are still
# on disk: see the "Going back" notes in docs/AWS.md.
set -eu

cd "$(dirname "$0")/.."

compose() { sudo docker compose --env-file .env.prod -f compose.prod.yaml "$@"; }

want="${1:-}"
if [ -n "$want" ]; then
    # Move to exactly the tested commit, not to whatever the branch tip is by now: a later push must not ship untested.
    git fetch --quiet origin
    git cat-file -e "$want^{commit}" 2>/dev/null || { echo "Refusing: commit $want is not on this server after fetching." >&2; exit 1; }
    git merge --ff-only "$want" || { echo "Refusing: $want cannot be fast-forwarded to from the code now checked out ($(git rev-parse --short HEAD))." >&2; exit 1; }
    [ "$(git rev-parse HEAD)" = "$(git rev-parse "$want^{commit}")" ] || { echo "Refusing: checked out $(git rev-parse --short HEAD), not $want." >&2; exit 1; }
    echo "Deploying $(git rev-parse --short HEAD)."
else
    git pull --ff-only
fi
# Settings kept in AWS Parameter Store are brought into .env.prod first. It never fails the deploy: if it cannot
# reach Parameter Store it says so and the settings already on this server are used.
sh deploy/pull-secrets.sh || true
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
