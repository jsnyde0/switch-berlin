#!/bin/bash
# Switch Berlin VPS disk + uptime monitor (kb-monitor).
#
# Runs per timer tick (every 5 min) performing four checks:
#   1. DISK:   alert if / usage >= DISK_ALERT_THRESHOLD_PERCENT (default 85).
#   2. HEALTHZ: GET HEALTHZ_URL; retry transport errors <=2; count consecutive
#               failures; alert at UPTIME_FAILURE_THRESHOLD (default 3).
#   3. DEAD-MAN'S SWITCH: ping HEALTHCHECKS_PING_URL if set (best-effort).
#   4. BACKUP: alert if kb-backup's last-success marker is older than
#              BACKUP_MAX_AGE_HOURS (default 26), or if no backup has succeeded
#              within that window of the monitor first looking (sb-4sr1).
#              Catches every way a backup stops: script failure, timer not
#              enabled, placeholder target, OnFailure alerter itself broken.
#
# State files live under KB_MONITOR_STATE_DIR (default /var/tmp/kb-monitor/,
# created on first run).
#
# Transport override (for local dry-run testing — never sends real Telegrams):
#   KB_MONITOR_DRY_RUN=1   → send_alert prints payload to stdout instead of
#                            curling the Telegram API.
#
# Usage:
#   kb-monitor.sh                       normal per-tick run (all three checks)
#   kb-monitor.sh --run                 same as no args
#   kb-monitor.sh --test-alert          send canary Telegram and exit
#   kb-monitor.sh --check-disk          run disk check only, print use%, exit
#   kb-monitor.sh --check-healthz       fetch HEALTHZ_URL once, print HTTP code,
#                                       exit (does NOT touch failure-counter state)
#   kb-monitor.sh --simulate-full-disk  force disk-breach path (treat use as 100%)
#   kb-monitor.sh --simulate-down       force healthz-failure path at threshold
#   kb-monitor.sh --check-backup        print last-success age, exit 0 if fresh,
#                                       1 if stale or missing (no state touched)
#   kb-monitor.sh --simulate-backup-stale  force the backup-stale alert path
#   kb-monitor.sh --service-failed-alert  send generic "service failed" message
#                                         (called by kb-monitor-alert.service via
#                                         OnFailure= in kb-monitor.service)

set -euo pipefail

# ---------------------------------------------------------------------------
# Env guards — REUSE the same /etc/kb-backup/env file (loaded by systemd
# EnvironmentFile= in kb-monitor.service). Script just reads the environment.
# ---------------------------------------------------------------------------
: "${TELEGRAM_BOT_TOKEN:=}"
: "${TELEGRAM_OPERATOR_CHAT_ID:=}"

DISK_ALERT_THRESHOLD_PERCENT="${DISK_ALERT_THRESHOLD_PERCENT:-85}"

# HEALTHZ_URL default: poll the PUBLIC url through Caddy. Hitting the app
# directly on 127.0.0.1:8000 fails before reaching the view — Django rejects the
# Host header (ALLOWED_HOSTS -> 400) and then SSL-redirects (301) — so it never
# tests health. The public url exercises the real user-facing path (Caddy +
# gunicorn + DB) and returns 200/500/503 honestly.
HEALTHZ_URL="${HEALTHZ_URL:-https://switch.berlin/healthz}"

UPTIME_FAILURE_THRESHOLD="${UPTIME_FAILURE_THRESHOLD:-3}"

# Optional dead-man's-switch ping URL (e.g. healthchecks.io). If unset, skipped.
HEALTHCHECKS_PING_URL="${HEALTHCHECKS_PING_URL:-}"

# Backup freshness: kb-backup.sh writes epoch seconds to this marker after each
# successful db snapshot. Nightly timer + 15 min jitter → 26h leaves 2h slack.
BACKUP_MAX_AGE_HOURS="${BACKUP_MAX_AGE_HOURS:-26}"
BACKUP_MARKER="${KB_BACKUP_STATE_DIR:-/var/tmp/kb-backup}/last-success"

STATE_DIR="${KB_MONITOR_STATE_DIR:-/var/tmp/kb-monitor}"
FAILURE_COUNT_FILE="${STATE_DIR}/healthz_failure_count"
ALERTED_FILE="${STATE_DIR}/healthz_alerted"
BACKUP_ALERTED_FILE="${STATE_DIR}/backup_alerted"
# First tick the monitor saw no marker; measures the grace window on a fresh host.
BACKUP_FIRST_SEEN_FILE="${STATE_DIR}/backup_first_seen"

# Prints the marker's age in hours, or "missing" if there is no valid marker.
backup_age_hours() {
    local ts
    if [ ! -f "$BACKUP_MARKER" ]; then
        echo missing
        return 0
    fi
    ts=$(cat "$BACKUP_MARKER")
    if ! [[ "$ts" =~ ^[0-9]+$ ]]; then
        echo missing
        return 0
    fi
    echo $(( ($(date +%s) - ts) / 3600 ))
}

# ---------------------------------------------------------------------------
# Transport
# ---------------------------------------------------------------------------
send_alert() {
    local body="$1"
    # Dry-run override: echo payload to stdout instead of curling.
    if [ "${KB_MONITOR_DRY_RUN:-}" = "1" ]; then
        echo "DRY-RUN send_alert: ${body}"
        return 0
    fi
    if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TELEGRAM_OPERATOR_CHAT_ID" ]; then
        echo "kb-monitor: ALERT (telegram unconfigured, log-only): ${body}" >&2
        return 0
    fi
    if ! curl -fsS -m 10 \
            -d "chat_id=${TELEGRAM_OPERATOR_CHAT_ID}" \
            --data-urlencode "text=${body}" \
            "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
            >/dev/null; then
        echo "kb-monitor: WARN telegram alert delivery failed" >&2
        # F1: best-effort — a failed send is logged above but never propagated.
        return 0
    fi
    return 0
}

# ---------------------------------------------------------------------------
# Flag dispatch (near the top, mirroring kb-backup.sh)
# ---------------------------------------------------------------------------
case "${1:-}" in
    --test-alert)
        send_alert "[Switch Berlin] kb-monitor canary $(date -Iseconds) — alert channel wired."
        exit $?
        ;;
    --service-failed-alert)
        send_alert "[Switch Berlin] kb-monitor.service FAILED — check journalctl -u kb-monitor.service."
        exit $?
        ;;
    --check-disk)
        # Print observed use% and exit; no alerting.
        DISK_USE=$(df -P / | awk 'NR==2{gsub(/%/,"",$5); print $5}')
        echo "kb-monitor: disk use=${DISK_USE}%"
        exit 0
        ;;
    --check-healthz)
        # Fetch HEALTHZ_URL once, print HTTP code, exit.
        # Does NOT touch failure-counter state (safe to run ad-hoc).
        # F7: exit 0 on HTTP 200, exit 1 on any non-200 or connection failure.
        if ! HTTP_CODE=$(curl -o /dev/null -s -w "%{http_code}" -m 10 "$HEALTHZ_URL" 2>/dev/null); then
            HTTP_CODE="connection refused"
        fi
        echo "kb-monitor: healthz HTTP code=${HTTP_CODE}"
        if [ "$HTTP_CODE" = "200" ]; then
            exit 0
        else
            exit 1
        fi
        ;;
    --simulate-full-disk)
        # Force disk-breach path (treat use% as 100) to prove alert fires.
        echo "kb-monitor: --simulate-full-disk — forcing disk use=100%"
        send_alert "[Switch Berlin] DISK alert: / at 100% (threshold ${DISK_ALERT_THRESHOLD_PERCENT}%) — free up space before postgres wedges. (simulate-full-disk test)"
        exit 0
        ;;
    --simulate-down)
        # Force healthz-failure path at threshold to prove alert fires.
        echo "kb-monitor: --simulate-down — forcing ${UPTIME_FAILURE_THRESHOLD} consecutive failures"
        mkdir -p "$STATE_DIR"
        echo "$UPTIME_FAILURE_THRESHOLD" > "$FAILURE_COUNT_FILE"
        rm -f "$ALERTED_FILE"
        send_alert "[Switch Berlin] UPTIME alert: /healthz has failed ${UPTIME_FAILURE_THRESHOLD} consecutive ticks — last code: 503 (simulated). Check app immediately."
        echo "$UPTIME_FAILURE_THRESHOLD" > "$ALERTED_FILE"
        exit 0
        ;;
    --check-backup)
        # Print backup age and exit; no alerting, no state.
        AGE=$(backup_age_hours)
        if [ "$AGE" = "missing" ]; then
            echo "kb-monitor: no successful backup recorded (${BACKUP_MARKER} missing)"
            exit 1
        fi
        echo "kb-monitor: last successful backup ${AGE}h ago (max ${BACKUP_MAX_AGE_HOURS}h)"
        if [ "$AGE" -ge "$BACKUP_MAX_AGE_HOURS" ]; then
            exit 1
        fi
        exit 0
        ;;
    --simulate-backup-stale)
        echo "kb-monitor: --simulate-backup-stale — forcing backup-stale alert"
        send_alert "[Switch Berlin] BACKUP alert: last successful backup is older than ${BACKUP_MAX_AGE_HOURS}h (simulated). Check journalctl -u kb-backup.service and the restic target."
        exit 0
        ;;
    --run|"")
        # Normal per-tick run — fall through to checks below.
        ;;
    *)
        echo "kb-monitor: unknown flag: ${1}" >&2
        exit 1
        ;;
esac

# ---------------------------------------------------------------------------
# Ensure state directory exists
# ---------------------------------------------------------------------------
mkdir -p "$STATE_DIR"

# ---------------------------------------------------------------------------
# CHECK 1: DISK
# Fail loud if df can't be read (data integrity failure, not transient).
# ---------------------------------------------------------------------------
check_disk() {
    local use
    if ! use=$(df -P / | awk 'NR==2{gsub(/%/,"",$5); print $5}'); then
        send_alert "[Switch Berlin] DISK check FAILED: df / returned an error — check filesystem immediately."
        return 1
    fi
    # F6: validate use% is numeric before integer comparison; fail loud if not.
    if ! [[ "$use" =~ ^[0-9]+$ ]]; then
        send_alert "[Switch Berlin] DISK check FAILED: unparseable df output: ${use}"
        return 1
    fi
    echo "kb-monitor: disk use=${use}%"
    if [ "$use" -ge "$DISK_ALERT_THRESHOLD_PERCENT" ]; then
        send_alert "[Switch Berlin] DISK alert: / at ${use}% (threshold ${DISK_ALERT_THRESHOLD_PERCENT}%) — free up space before postgres wedges."
    fi
}

# ---------------------------------------------------------------------------
# CHECK 2: HEALTHZ
# ADR-008 D4: transport errors → retry ≤2 times; any final non-200 = failure.
# Persists consecutive-failure counter; alerts once at threshold; recovery note.
# ---------------------------------------------------------------------------
check_healthz() {
    local http_code
    local attempt
    local transport_ok=0

    # Retry loop: up to 3 attempts (initial + 2 retries) for transport errors.
    for attempt in 1 2 3; do
        http_code=$(curl -o /dev/null -s -w "%{http_code}" -m 10 "$HEALTHZ_URL" 2>/dev/null) || true
        if [ -n "$http_code" ] && [ "$http_code" != "000" ]; then
            transport_ok=1
            break
        fi
        # Transport error (empty code or 000 = connect/timeout failure).
        if [ "$attempt" -lt 3 ]; then
            echo "kb-monitor: healthz transport error (attempt ${attempt}/3), retrying in 2s..."
            sleep 2
        fi
    done

    if [ "$transport_ok" = "0" ]; then
        http_code="connection refused"
    fi

    echo "kb-monitor: healthz HTTP code=${http_code}"

    # Read persisted state.
    # F8: sanitize state-file values — non-numeric (corrupted/partial write) → reset to 0.
    local failure_count=0
    if [ -f "$FAILURE_COUNT_FILE" ]; then
        failure_count=$(cat "$FAILURE_COUNT_FILE")
        if ! [[ "$failure_count" =~ ^[0-9]+$ ]]; then
            echo "kb-monitor: WARN failure_count file contained non-numeric value '${failure_count}', resetting to 0" >&2
            failure_count=0
        fi
    fi
    local alerted=0
    if [ -f "$ALERTED_FILE" ]; then
        alerted=$(cat "$ALERTED_FILE")
        if ! [[ "$alerted" =~ ^[0-9]+$ ]]; then
            echo "kb-monitor: WARN alerted file contained non-numeric value '${alerted}', resetting to 0" >&2
            alerted=0
        fi
    fi

    if [ "$http_code" = "200" ]; then
        # Recovery path.
        # F3: only page "RECOVERED" if we actually alerted during this outage
        # (alerted flag is non-zero). Avoids spurious recovery pages for sub-threshold blips.
        if [ "$alerted" -gt 0 ]; then
            send_alert "[Switch Berlin] RECOVERED: /healthz 200 again (was down for ${failure_count} consecutive ticks)."
        fi
        # Always reset state on recovery regardless.
        echo 0 > "$FAILURE_COUNT_FILE"
        echo 0 > "$ALERTED_FILE"
    else
        # Failure tick.
        failure_count=$((failure_count + 1))
        echo "$failure_count" > "$FAILURE_COUNT_FILE"
        echo "kb-monitor: healthz failure count=${failure_count}/${UPTIME_FAILURE_THRESHOLD}"

        if [ "$failure_count" -ge "$UPTIME_FAILURE_THRESHOLD" ] && [ "${alerted:-0}" != "$UPTIME_FAILURE_THRESHOLD" ]; then
            # Alert exactly once per outage: when we first hit the threshold.
            # Track alerted by storing the failure count at alert time; re-alert
            # on extended outage only if counter was reset (recovery) then failed again.
            send_alert "[Switch Berlin] UPTIME alert: /healthz has failed ${failure_count} consecutive ticks — last code: ${http_code}. Check app immediately."
            echo "$failure_count" > "$ALERTED_FILE"
        fi
    fi
}

# ---------------------------------------------------------------------------
# CHECK 4: BACKUP FRESHNESS
# One page per staleness episode; one recovery note when a backup lands again.
# ---------------------------------------------------------------------------
check_backup() {
    local age
    local reason=""
    age=$(backup_age_hours)

    if [ "$age" = "missing" ]; then
        # Fresh host: start the grace window the first time we look.
        if [ ! -f "$BACKUP_FIRST_SEEN_FILE" ]; then
            date +%s > "$BACKUP_FIRST_SEEN_FILE"
        fi
        local first_seen
        first_seen=$(cat "$BACKUP_FIRST_SEEN_FILE")
        if ! [[ "$first_seen" =~ ^[0-9]+$ ]]; then
            date +%s > "$BACKUP_FIRST_SEEN_FILE"
            first_seen=$(date +%s)
        fi
        local waited=$(( ($(date +%s) - first_seen) / 3600 ))
        echo "kb-monitor: backup: no successful backup recorded (watching ${waited}h)"
        if [ "$waited" -ge "$BACKUP_MAX_AGE_HOURS" ]; then
            reason="no successful backup recorded in ${waited}h of watching"
        fi
    else
        rm -f "$BACKUP_FIRST_SEEN_FILE"
        echo "kb-monitor: backup: last success ${age}h ago (max ${BACKUP_MAX_AGE_HOURS}h)"
        if [ "$age" -ge "$BACKUP_MAX_AGE_HOURS" ]; then
            reason="last successful backup was ${age}h ago"
        fi
    fi

    if [ -n "$reason" ]; then
        if [ ! -f "$BACKUP_ALERTED_FILE" ]; then
            send_alert "[Switch Berlin] BACKUP alert: ${reason} (max ${BACKUP_MAX_AGE_HOURS}h). Check journalctl -u kb-backup.service and the restic target."
            date +%s > "$BACKUP_ALERTED_FILE"
        fi
    elif [ -f "$BACKUP_ALERTED_FILE" ]; then
        send_alert "[Switch Berlin] BACKUP RECOVERED: last successful backup ${age}h ago."
        rm -f "$BACKUP_ALERTED_FILE"
    fi
}

# ---------------------------------------------------------------------------
# CHECK 3: DEAD-MAN'S SWITCH (best-effort; never fails the script)
# ---------------------------------------------------------------------------
ping_deadmans_switch() {
    if [ -z "$HEALTHCHECKS_PING_URL" ]; then
        return 0
    fi
    if ! curl -fsS -m 10 "$HEALTHCHECKS_PING_URL" >/dev/null 2>&1; then
        echo "kb-monitor: WARN dead-man's-switch ping failed" >&2
    fi
}

# ---------------------------------------------------------------------------
# Main per-tick run
# F2: each check is independent — one failure must never block the others.
# check_disk/check_healthz may return 1 (fail-loud per ADR-008 D3) but that
# must not abort the tick under set -e.
# ---------------------------------------------------------------------------
check_disk || true
check_healthz || true
check_backup || true
ping_deadmans_switch || true
