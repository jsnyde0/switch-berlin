#!/bin/bash
# shellcheck disable=SC2329  # stop_pid and cleanup run from the EXIT trap
# Nightly Track A collector run against the LOCAL dev stack (sb-7wzb.5).
#
# collect web + collect telegram --private -> collect push (deletes the rows
# file) -> the dev qcluster extracts -> per-source report into the log.
#
# Stack rule: start what the run needs, stop only what this run started, and
# fail loud when Docker itself is down. Never prints .env values or tokens.
# Scheduled by launchd; see README.md "Nightly run" in this directory's parent.
set -uo pipefail

export PATH="$HOME/.orbstack/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
REPO="$(cd "$(dirname "$0")/../../.." && pwd)"
CLI_DIR="$REPO/tools/switch-cli"
COMPOSE=(docker compose -f "$REPO/docker-compose.yml" -f "$REPO/docker-compose.local.yml")
DB_CONTAINER="switch-berlin-db-1"
SERVER_URL="http://127.0.0.1:8000/"
PUSH_CONFIG="$HOME/.config/switch-collector-dev/config.toml"
DRAIN_TIMEOUT_S=2700
# Cloudflare's public always-pass test keys: manage.py system checks refuse to
# run without Turnstile keys on this host (E007). Scoped to this script.
export TURNSTILE_SITE_KEY=1x00000000000000000000AA
export TURNSTILE_SECRET_KEY=1x0000000000000000000000000000000AA

log() { echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] $*"; }
die() { log "FAIL: $*"; exit 1; }

STARTED_DB=0 SERVER_PID="" QCLUSTER_PID="" ROWS_DIR=""
stop_pid() {  # uv run parent + its python child
    pkill -TERM -P "$1" 2>/dev/null
    kill -TERM "$1" 2>/dev/null
    wait "$1" 2>/dev/null
}
cleanup() {
    [ -n "$ROWS_DIR" ] && rm -rf "$ROWS_DIR"  # wipe rule: rows carry private posts and photos
    [ -n "$QCLUSTER_PID" ] && { log "stopping the qcluster this run started"; stop_pid "$QCLUSTER_PID"; }
    [ -n "$SERVER_PID" ] && { log "stopping the runserver this run started"; stop_pid "$SERVER_PID"; }
    [ "$STARTED_DB" = 1 ] && { log "stopping the db container this run started"; "${COMPOSE[@]}" stop db >/dev/null 2>&1; }
}
trap cleanup EXIT

cd "$REPO" || die "repo not found at $REPO"
RUN_START="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
log "nightly collector run start ($RUN_START)"

# .env's DATABASE_URL is container-shaped (host.orb.internal); host-side
# manage.py needs 127.0.0.1. Read inside Python, never echoed.
DATABASE_URL="$(uv run --no-project python - <<'PY'
from pathlib import Path
for line in Path(".env").read_text().splitlines():
    if line.startswith("DATABASE_URL="):
        print(line.split("=", 1)[1].strip().strip('"').strip("'").replace("host.orb.internal", "127.0.0.1"))
PY
)"
[ -n "$DATABASE_URL" ] || die "no DATABASE_URL in .env"
export DATABASE_URL

manage() { uv run python manage.py "$@"; }

# 1. Stack: Docker must be up; the db container is started if it is not.
docker info >/dev/null 2>&1 || die "Docker (OrbStack) is not running; start it and re-run"
if [ "$(docker inspect -f '{{.State.Running}}' "$DB_CONTAINER" 2>/dev/null)" != "true" ]; then
    log "db container down; starting it for this run"
    "${COMPOSE[@]}" up -d db >/dev/null 2>&1 || die "could not start the db container"
    STARTED_DB=1
fi
for _ in $(seq 60); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' "$DB_CONTAINER" 2>/dev/null)" = "healthy" ] && break
    sleep 2
done
[ "$(docker inspect -f '{{.State.Health.Status}}' "$DB_CONTAINER")" = "healthy" ] || die "db container not healthy"
if ! out="$(manage migrate --check 2>&1)"; then
    echo "$out" | tail -5
    die "dev DB lacks HEAD migrations or fails system checks (see above)"
fi
# Register django-q schedules (idempotent) so the qcluster below runs the
# 90-day RawMessage purge the privacy page promises (sb-7wzb.8).
manage schedule_tasks >/dev/null || die "could not register django-q schedules"
# Create the profiles and venues collector_sources.toml names (idempotent):
# collection never creates them, a missing one fails its rows (sb-7wzb.25).
manage seed_collector_sources || die "could not seed the collector source profiles and venues"

if ! curl -s -o /dev/null --max-time 5 "$SERVER_URL"; then
    log "runserver down; starting it for this run"
    uv run python manage.py runserver 127.0.0.1:8000 --skip-checks --noreload &
    SERVER_PID=$!
    for _ in $(seq 60); do curl -s -o /dev/null --max-time 2 "$SERVER_URL" && break; sleep 1; done
    curl -s -o /dev/null --max-time 5 "$SERVER_URL" || die "runserver did not come up"
fi
if ! pgrep -f "$REPO/.venv/bin/python manage.py qcluster" >/dev/null; then
    log "qcluster down; starting it for this run"
    uv run python manage.py qcluster &
    QCLUSTER_PID=$!
fi

# 2. Collect and push. One failing collector does not stop the other; the run
# still exits non-zero.
ROWS_DIR="$(mktemp -d)" && chmod 700 "$ROWS_DIR"
FAILED=0
cd "$CLI_DIR" || die "switch-cli not found"
log "collect web"
uv run switch-cli collect web --out "$ROWS_DIR/web.jsonl" || { log "FAIL: collect web"; FAILED=1; }
log "collect telegram --private"
uv run switch-cli collect telegram --private --out "$ROWS_DIR/telegram.jsonl" || { log "FAIL: collect telegram"; FAILED=1; }
for rows in "$ROWS_DIR/web.jsonl" "$ROWS_DIR/telegram.jsonl"; do
    [ -s "$rows" ] || continue
    log "collect push $(basename "$rows")"
    SWITCH_CLI_CONFIG="$PUSH_CONFIG" uv run switch-cli collect push "$rows" || { log "FAIL: push $(basename "$rows")"; FAILED=1; }
done
cd "$REPO" || die "repo vanished"

# 3. Wait for the extraction queue to drain.
log "waiting for extraction to drain"
drained=0
for _ in $(seq $((DRAIN_TIMEOUT_S / 20))); do
    left="$(manage shell -c "
from django_q.models import OrmQ
from ingestion.models import RawMessage
print(OrmQ.objects.count() + RawMessage.objects.filter(extraction_status='pending').count())
" 2>/dev/null | tail -1)"
    [ "$left" = "0" ] && { drained=1; break; }
    sleep 20
done
[ "$drained" = 1 ] || { log "FAIL: extraction queue did not drain in ${DRAIN_TIMEOUT_S}s"; FAILED=1; }

# 4. Per-source report for the rows this run created (counts only, no content).
log "per-source report, rows received since $RUN_START"
manage shell -c "
from django.db.models import Count
from events.models import Event
from ingestion.models import RawMessage
rows = RawMessage.objects.filter(received_at__gte='$RUN_START')
print('rows:', rows.count())
for r in rows.values('source_type', 'channel_id', 'extraction_status').annotate(n=Count('id')).order_by('source_type', 'channel_id'):
    print('  row', r)
for r in (Event.objects.filter(raw_message__in=rows)
          .values('raw_message__source_type', 'raw_message__channel_id', 'status', 'visibility')
          .annotate(n=Count('id')).order_by('raw_message__source_type', 'raw_message__channel_id')):
    print('  event', r)
" 2>&1 | grep -E "^(rows:|  row|  event)"

log "run end (failed=$FAILED)"
exit "$FAILED"
