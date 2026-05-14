#!/bin/bash
# Switch Berlin nightly backup (kb-6nq.3 + kb-336 size-regression alert).
#
# Pipes pg_dump from the compose db container into restic on BX11. After the
# run, compares the new db-snapshot total_size to the previous tag=db latest
# snapshot; if the new snapshot is < prev / DROP_RATIO (default 5x drop),
# sends a Telegram alert to TELEGRAM_OPERATOR_CHAT_ID via TELEGRAM_BOT_TOKEN.
# Both alert variables are sourced from /etc/kb-backup/env alongside the
# restic creds. When unset/empty, alert delivery is a no-op (logs to stderr).
#
# Usage:
#   kb-backup.sh                 normal run
#   kb-backup.sh --test-alert    send a canary message only; skip backup
#   kb-backup.sh --force-alert   force the regression message; skip backup
#                                (used to exercise the threshold path)

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

DB_CONTAINER=$(docker ps --filter label=com.docker.compose.service=db --format "{{.Names}}" | head -1)
if [ -n "${DB_CONTAINER}" ]; then
    echo "kb-backup: dumping db from container ${DB_CONTAINER}"
    docker exec -i "${DB_CONTAINER}" pg_dump -U postgres -Fc postgres \
        | restic backup --stdin --stdin-filename "db-$(date +%Y%m%d-%H%M%S).dump" \
            --tag db --tag automatic
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
