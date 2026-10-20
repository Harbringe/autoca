#!/bin/sh
# Watches the live site's health endpoint from any machine while a scale or load test runs on the server, so a test that slows the real
# site is seen at once. It only asks for /healthz (no sign-in, nothing stored).
#
#   sh watch-live.sh [url] [slow_seconds]        default: https://api.caworkbench.site/healthz  1.5
#
# Prints a line for every answer that is slow or not 200, and a summary line every five minutes. Stop it with Ctrl+C.
set -u

url="${1:-https://api.caworkbench.site/healthz}"
slow="${2:-1.5}"
count=0
total=0
worst=0
bad=0
started="$(date +%s)"

while :; do
    out="$(curl -s -o /dev/null -m 10 -w '%{http_code} %{time_total}' "$url" 2>/dev/null)" || out="000 10"
    code="${out%% *}"
    secs="${out#* }"
    now="$(date '+%H:%M:%S')"
    count=$((count + 1))
    total="$(awk -v a="$total" -v b="$secs" 'BEGIN { printf "%.4f", a + b }')"
    worst="$(awk -v a="$worst" -v b="$secs" 'BEGIN { print (b > a ? b : a) }')"
    if [ "$code" != "200" ]; then
        bad=$((bad + 1))
        echo "$now LIVE SITE FAILED: HTTP $code after ${secs}s"
    elif awk -v s="$secs" -v l="$slow" 'BEGIN { exit !(s > l) }'; then
        echo "$now LIVE SITE SLOW: ${secs}s (limit ${slow}s)"
    fi
    if [ $(( $(date +%s) - started )) -ge 300 ]; then
        avg="$(awk -v t="$total" -v n="$count" 'BEGIN { printf "%.3f", t / n }')"
        echo "$now live site, last 5 min: $count checks, avg ${avg}s, worst ${worst}s, $bad failed"
        count=0; total=0; worst=0; bad=0; started="$(date +%s)"
    fi
    sleep 5
done
