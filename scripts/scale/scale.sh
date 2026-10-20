#!/bin/sh
# Scratch-database scale and load test, run ON THE SERVER (see docs/SCALE.md). Nothing here touches the live database: it starts a second
# Postgres (and, for load tests, a second copy of the app) in its own Compose project (autoca-scale) and removes them again with `down`.
#
#   sh scale.sh check            how much disk and memory the server has to spare
#   sh scale.sh up               start the scratch database and build its tables
#   sh scale.sh fill [args]      fill it with fake rows, e.g.  fill --txns 1000000
#   sh scale.sh time [--plans]   time the queries behind the slow-prone screens
#   sh scale.sh stats            table sizes and row counts
#   sh scale.sh top              the slowest statements Postgres has seen
#   sh scale.sh web-up           start the scratch copy of the app (for load tests)
#   sh scale.sh load run [args]      many people at once, in phases:  load run --users 5,20,50 --seconds 60
#   sh scale.sh load uploads [args]  big statements uploaded together: load uploads --concurrency 2 --pages 238
#   sh scale.sh assistant [args]     the assistant worker over a big queue, with a fake model:  assistant --rows 5000
#   sh scale.sh web-down         stop the scratch copy of the app
#   sh scale.sh down             delete everything: database, volume, app and passwords
#
# Load, upload and assistant runs sample every container's CPU and memory (the live site's too) and stop themselves if the server has
# less than SCALE_MIN_FREE_MB (250) of memory left, so a stress test cannot take the live site down with it.
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
export SCALE_DIR="$HERE"
export REPO="${REPO:-/srv/autoca}"
export SCALE_ENV="$HERE/.env.scale"
DC="sudo env SCALE_DIR=$SCALE_DIR REPO=$REPO SCALE_ENV=$SCALE_ENV docker compose -p autoca-scale --env-file $SCALE_ENV -f $HERE/compose.scale.yaml"

need_env() { [ -f "$SCALE_ENV" ] || { echo "scale: run 'sh scale.sh up' first" >&2; exit 1; }; }
tool() { need_env; $DC run --rm -T tool "$@" </dev/null; }
assistant_tool() { need_env; $DC run --rm -T -e LLM_BACKEND=fake_llm.FakeLLMAdapter -e PYTHONPATH=/srv/app:/scale tool python /scale/assistant.py "$@" </dev/null; }
psql_super() { need_env; $DC exec -T db psql -U postgres -d autoca_scale_test "$@" </dev/null; }

web_running() { [ -n "$(sudo docker ps -q --filter label=com.docker.compose.project=autoca-scale --filter label=com.docker.compose.service=web)" ]; }

# Every container of the scratch project except its database.
kill_scale_work() {
    sudo docker ps --filter label=com.docker.compose.project=autoca-scale --format '{{.ID}} {{.Names}}' \
        | grep -v -- '-db-' | awk '{print $1}' | xargs -r sudo docker kill >/dev/null 2>&1 || true
}

summary() {
    echo
    echo "peaks while it ran (100% CPU = one core; the live site's containers are the ones not named autoca-scale-*):"
    awk '
      function mb(s,   v) { v = s + 0; if (s ~ /GiB/) v *= 1024; else if (s ~ /KiB/ || s ~ /kB/) v /= 1024; return v }
      { name = $1; cpu = $2 + 0; m = mb($3); if (cpu > maxc[name]) maxc[name] = cpu; if (m > maxm[name]) maxm[name] = m; seen[name] = 1 }
      END { for (n in seen) printf "  %-44s cpu %6.1f%%  mem %7.0f MB\n", n, maxc[n], maxm[n] }
    ' "$1" | sort
}

with_stats() {
    log="$(mktemp)"
    "$@" &
    pid=$!
    aborted=0
    while kill -0 "$pid" 2>/dev/null; do
        sudo docker stats --no-stream --format '{{.Name}} {{.CPUPerc}} {{.MemUsage}}' >> "$log" 2>/dev/null || true
        avail="$(free -m | awk '/^Mem:/ {print $7}')"
        if [ "${avail:-9999}" -lt "${SCALE_MIN_FREE_MB:-250}" ]; then
            echo "scale: ABORTING, the server has only ${avail} MB of memory left; stopping the test to protect the live site" >&2
            kill_scale_work
            kill "$pid" 2>/dev/null || true
            aborted=1
            break
        fi
        sleep 3
    done
    rc=0
    wait "$pid" 2>/dev/null || rc=$?
    summary "$log"
    rm -f "$log"
    [ "$aborted" -eq 0 ] || rc=3
    return "$rc"
}

cmd="${1:-}"
[ $# -gt 0 ] && shift

case "$cmd" in
check)
    df -h / | tail -1
    free -m | sed -n '1,2p'
    echo
    echo "Disk: a 1 million row fill needs about 1.5 GB. Memory: the scratch database is capped at 480 MB, the tool at 256 MB, the scratch app at 512 MB."
    echo "Live containers right now:"
    sudo docker stats --no-stream --format '  {{.Name}}  cpu {{.CPUPerc}}  mem {{.MemUsage}}' 2>/dev/null | grep -v autoca-scale || true
    ;;
up)
    free_kb="$(df --output=avail -k / | tail -1 | tr -d ' ')"
    [ "$free_kb" -gt 8000000 ] || { echo "scale: refusing, less than 8 GB of disk is free" >&2; exit 1; }
    if [ ! -f "$SCALE_ENV" ]; then
        umask 077
        owner="$(openssl rand -hex 16)"; web="$(openssl rand -hex 16)"; super="$(openssl rand -hex 16)"
        {
            echo "POSTGRES_PASSWORD=$super"
            echo "AUTOCA_OWNER_PASSWORD=$owner"
            echo "AUTOCA_WEB_PASSWORD=$web"
            echo "DATABASE_URL=postgres://autoca_web:$web@db:5432/autoca_scale_test"
            echo "DATABASE_OWNER_URL=postgres://autoca_owner:$owner@db:5432/autoca_scale_test"
            echo "DJANGO_SECRET_KEY=$(openssl rand -hex 50)"
            echo "KMS_LOCAL_MASTER_KEY=$(openssl rand -base64 32 | tr '+/' '-_')"
            echo "BLIND_INDEX_KEY=$(openssl rand -base64 48 | tr -d '\n' | tr '+/' '-_' | tr -d '=')"
        } > "$SCALE_ENV"
    fi
    $DC up -d --wait db
    psql_super -c "CREATE EXTENSION IF NOT EXISTS pg_stat_statements" >/dev/null
    tool sh -c "python manage.py grant_app_role --database=owner && python manage.py migrate --database=owner --noinput && python manage.py grant_app_role --database=owner"
    echo "scale: the scratch database is ready. Next: sh scale.sh fill --txns 300000"
    ;;
fill)
    tool python /scale/fill.py "$@"
    ;;
time)
    tool python /scale/timing.py "$@"
    ;;
stats)
    psql_super -c "ANALYZE" >/dev/null
    psql_super -c "select relname as table, n_live_tup as rows, pg_size_pretty(pg_total_relation_size(relid)) as size_with_indexes from pg_stat_user_tables order by pg_total_relation_size(relid) desc limit 12"
    psql_super -c "select pg_size_pretty(pg_database_size('autoca_scale_test')) as database_size"
    ;;
top)
    psql_super -c "select calls, round(mean_exec_time::numeric,1) as mean_ms, round(total_exec_time::numeric/1000,1) as total_s, left(regexp_replace(query, '\s+', ' ', 'g'), 110) as query from pg_stat_statements where query not like '%pg_stat%' order by total_exec_time desc limit 12"
    ;;
web-up)
    need_env
    $DC --profile load up -d --wait web
    echo "scale: the scratch app is up (web:8000 inside the scratch network). Next: sh scale.sh load run --users 5,20"
    ;;
web-down)
    need_env
    $DC --profile load stop web
    $DC --profile load rm -f web
    ;;
load)
    need_env
    web_running || { echo "scale: the scratch app is not running: sh scale.sh web-up" >&2; exit 1; }
    with_stats tool python /scale/load.py "$@"
    ;;
assistant)
    with_stats assistant_tool "$@"
    ;;
down)
    need_env
    $DC --profile load down -v --remove-orphans
    rm -f "$SCALE_ENV"
    echo "scale: the scratch database, its volume, the scratch app and its passwords are gone."
    ;;
*)
    sed -n '2,19p' "$0"
    exit 1
    ;;
esac
