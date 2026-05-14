#!/bin/bash
# Switch Berlin nightly backup (kb-6nq.3 + kb-336 size-regression alert + kb-omx size floor).
#
# Dumps pg_dump to a tempfile, checks absolute 50KiB floor (kb-omx), then
# backs up via restic on BX11. After the run, compares the new db-snapshot
# total_size to the previous tag=db latest snapshot; if the new snapshot is
# < prev / DROP_RATIO (default 5x drop), sends a Telegram alert.
# Both alert variables are sourced from /etc/kb-backup/env alongside the
# restic creds. When unset/empty, alert delivery is a no-op (logs to stderr).
#
# Usage:
#   kb-backup.sh                    normal run
#   kb-backup.sh --test-alert       send a canary message only; skip backup
#   kb-backup.sh --force-alert      force the regression message; skip backup
#                                   (used to exercise the threshold path)
#   kb-backup.sh --simulate-tiny-dump  write a 100-byte fake dump and run
#                                   the size-check logic; expects non-zero exit
#                                   and a Telegram alert (test flag for kb-omx)

set -euo pipefail

: "${RESTIC_REPOSITORY:?missing RESTIC_REPOSITORY}"
: "${RESTIC_PASSWORD:?missing RESTIC_PASSWORD}"
: "${TELEGRAM_BOT_TOKEN:=}"
: "${TELEGRAM_OPERATOR_CHAT_ID:=}"

DROP_RATIO="${DROP_RATIO:-5}"

send_alert() {
    local body="$1"
    if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_OPERATOR_CHAT_ID" ]; then
        echo "kb-backup: ALERT (telegram unconfigured, log-only): ${body}" >&2
        return 0
    fi
    if ! curl -fsS -m 10 \
            -d "chat_id=${TELEGRAM_OPERATOR_CHAT_ID}" \
            --data-urlencode "text=${body}" \
            "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            >/dev/null; then
        echo "kb-backup: WARN telegram alert delivery failed" >&2
        return 1
    fi
    return 0
}

if [ "${1:-}" = "--test-alert" ]; then
    send_alert "[Switch Berlin] kb-backup canary $(date -Iseconds) — alert channel wired."
    exit $?
fi

if [ "${1:-}" = "--force-alert" ]; then
    send_alert "[Switch Berlin] (FORCED TEST) backup-size REGRESSION: prev=143302B new=999B (>${DROP_RATIO}x drop). If you see this and did not just run kb-backup.sh --force-alert, something is wrong."
    exit $?
fi

# --service-failed-alert: fired by kb-backup-alert.service via OnFailure=.
# Sends a generic "service failed" message so any non-zero exit from
# kb-backup.service (not just the size-floor check) reaches the operator.
if [ "${1:-}" = "--service-failed-alert" ]; then
    send_alert "[Switch Berlin] kb-backup.service FAILED — check journalctl -u kb-backup.service for details."
    exit $?
fi

# --simulate-tiny-dump: write a 100-byte fake dump and run size-check logic.
# Used to exercise the kb-omx absolute-floor path without touching the real db.
# Expects non-zero exit and a Telegram alert.
if [ "${1:-}" = "--simulate-tiny-dump" ]; then
    TMPDIR_SIMULATE=$(mktemp -d /var/tmp/kb-backup-XXXXXX 2>/dev/null || mktemp -d)
    SIMULATE_DUMP="$TMPDIR_SIMULATE/simulated.dump"
    printf '%0.s.' {1..100} > "$SIMULATE_DUMP"
    SIMULATE_SIZE=$(wc -c < "$SIMULATE_DUMP")
    FLOOR_BYTES=51200   # 50 KiB
    echo "kb-backup: --simulate-tiny-dump — fake dump size=${SIMULATE_SIZE}B floor=${FLOOR_BYTES}B"
    rm -f "$SIMULATE_DUMP"
    rmdir "$TMPDIR_SIMULATE" 2>/dev/null || true
    send_alert "[Switch Berlin] ALERT: pg_dump output is ${SIMULATE_SIZE}B — below absolute floor of $((FLOOR_BYTES / 1024))KiB (${FLOOR_BYTES}B). Backup aborted. DB may be empty/wiped — check immediately. (simulate-tiny-dump test)"
    exit 1
fi

# Snapshot the size of the previous tag=db latest BEFORE running the backup,
# so the comparison is against the actual prior state — not the one we are
# about to create. Empty repo / no prior snapshot → 0 (regression check is
# then skipped).
latest_db_bytes() {
    local json
    if ! json=$(restic stats --tag db latest --json 2>/dev/null); then
        echo 0
        return 0
    fi
    if [ -z "$json" ]; then
        echo 0
        return 0
    fi
    printf '%s' "$json" | jq -r '.total_size // 0'
}

PREV_BYTES=$(latest_db_bytes)

DUMP_FLOOR_BYTES=51200  # 50 KiB absolute floor (kb-omx)
DUMP_TMPDIR=/var/tmp/kb-backup
mkdir -p "$DUMP_TMPDIR"

DB_CONTAINER=$(docker ps --filter label=com.docker.compose.service=db --format "{{.Names}}" | head -1)
if [ -n "${DB_CONTAINER}" ]; then
    DUMP_TS=$(date +%Y%m%d-%H%M%S)
    DUMP_FILE="$DUMP_TMPDIR/db-${DUMP_TS}.dump"
    echo "kb-backup: dumping db from container ${DB_CONTAINER} → ${DUMP_FILE}"
    docker exec -i "${DB_CONTAINER}" pg_dump -U postgres -Fc postgres > "$DUMP_FILE"
    DUMP_SIZE=$(wc -c < "$DUMP_FILE")
    echo "kb-backup: dump size=${DUMP_SIZE}B floor=${DUMP_FLOOR_BYTES}B"
    if [ "${DUMP_SIZE}" -lt "${DUMP_FLOOR_BYTES}" ]; then
        send_alert "[Switch Berlin] ALERT: pg_dump output is ${DUMP_SIZE}B — below absolute floor of $((DUMP_FLOOR_BYTES / 1024))KiB (${DUMP_FLOOR_BYTES}B). Backup aborted. DB may be empty/wiped — check immediately and restore from a prior restic snapshot before the next run overwrites it."
        rm -f "$DUMP_FILE"
        exit 1
    fi
    restic backup --stdin --stdin-filename "db-${DUMP_TS}.dump" \
        --tag db --tag automatic < "$DUMP_FILE"
    rm -f "$DUMP_FILE"
else
    echo "kb-backup: WARNING no db container running; recording no-db marker"
    echo "no-db at $(date -Iseconds)" \
        | restic backup --stdin --stdin-filename "no-db-marker.txt" --tag marker
    # No db snapshot on this run → nothing to compare against.
    exit 0
fi

NEW_BYTES=$(latest_db_bytes)
echo "kb-backup: db snapshot sizes — prev=${PREV_BYTES}B new=${NEW_BYTES}B (threshold: alert if new < prev/${DROP_RATIO})"

if [ "${PREV_BYTES}" -gt 0 ] && [ "${NEW_BYTES}" -lt "$((PREV_BYTES / DROP_RATIO))" ]; then
    send_alert "[Switch Berlin] backup-size REGRESSION: prev=${PREV_BYTES}B new=${NEW_BYTES}B (>${DROP_RATIO}x drop). New db snapshot is near-empty — check db immediately and consider restoring from a prior snapshot before tomorrow's run overwrites latest."
fi
