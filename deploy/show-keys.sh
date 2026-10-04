#!/bin/sh
# Show the three permanent application keys ONCE, wait while you copy them into a password manager, then
# wipe the screen and its scrollback so they cannot be pasted anywhere by accident.
#
#   sh deploy/show-keys.sh
#
# Printing a secret and then asking people not to paste the terminal is a trap, so the screen is cleared for
# you. Never copy a whole terminal into a chat, a ticket or an email.
set -eu

cd "$(dirname "$0")/.."
[ -f .env.prod ] || { echo "show-keys: .env.prod not found" >&2; exit 1; }

echo "Copy these three lines into your password manager:"
echo
grep -E '^(DJANGO_SECRET_KEY|KMS_LOCAL_MASTER_KEY|BLIND_INDEX_KEY)=' .env.prod
echo
printf "Press Enter once they are saved. The screen will then be wiped. "
IFS= read -r _
# Full terminal reset: clears the screen and the scrollback.
printf '\033c'
echo "Screen wiped. Keys are in .env.prod on this server and, now, in your password manager."
