#!/bin/sh
# Publish "how old is the newest backup, in hours" to CloudWatch. Run every 30 minutes by a systemd timer.
#
# An alarm on that number emails you when it passes ~26 hours, AND when the numbers stop arriving, which is
# what a dead or wedged server looks like. A backup job that only writes "ok" to a log can tell you neither.
set -eu

cd "$(dirname "$0")/.."

SUDO=""
[ "$(id -u)" -eq 0 ] || SUDO="sudo"

$SUDO docker compose --env-file .env.prod -f compose.prod.yaml exec -T web python -m integrations.backup.s3 age-metric < /dev/null
