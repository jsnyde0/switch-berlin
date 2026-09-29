#!/bin/bash
# Tests for kb-monitor.sh's backup-staleness check (sb-4sr1):
#   the monitor pages when kb-backup's last-success marker is older than
#   BACKUP_MAX_AGE_HOURS, or when no backup has succeeded within that window
#   of the monitor first looking.
#
# Run with:
#   bash infra/test-kb-monitor.sh
#
# Runs locally: KB_MONITOR_DRY_RUN=1 prints alerts instead of sending them,
# state dirs point at a tempdir, and HEALTHZ_URL points at a closed local port
# (each normal tick spends ~4s on healthz transport retries).

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$SCRIPT_DIR/kb-monitor.sh"

PASS=0
FAIL=0
TOTAL=0

check() {
    local name="$1"
    local result="$2"   # "pass" or "fail:reason"
    TOTAL=$((TOTAL + 1))
    if [ "$result" = "pass" ]; then
        echo "PASS: $name"
        PASS=$((PASS + 1))
    else
        echo "FAIL: $name — ${result#fail:}"
        FAIL=$((FAIL + 1))
    fi
}

T=$(mktemp -d)
export KB_MONITOR_DRY_RUN=1
export KB_MONITOR_STATE_DIR="$T/monitor"
export KB_BACKUP_STATE_DIR="$T/backup"
export HEALTHZ_URL="http://127.0.0.1:9/healthz"
export BACKUP_MAX_AGE_HOURS=26
MARKER="$KB_BACKUP_STATE_DIR/last-success"
NOW=$(date +%s)

reset_state() {
    rm -rf "$KB_MONITOR_STATE_DIR" "$KB_BACKUP_STATE_DIR"
    mkdir -p "$KB_BACKUP_STATE_DIR"
}

echo "=== sb-4sr1: kb-monitor.sh backup-staleness tests ==="
echo ""

# Test 1: --check-backup with a fresh marker exits 0 and prints the age
reset_state
echo "$((NOW - 3600))" > "$MARKER"
output=$(bash "$SCRIPT" --check-backup 2>&1) && rc=0 || rc=$?
if [ "$rc" -eq 0 ] && echo "$output" | grep -q "last successful backup"; then
    check "--check-backup fresh marker exits 0" "pass"
else
    check "--check-backup fresh marker exits 0" "fail:rc=$rc. Output: $output"
fi

# Test 2: --check-backup with a stale marker exits 1
reset_state
echo "$((NOW - 30 * 3600))" > "$MARKER"
output=$(bash "$SCRIPT" --check-backup 2>&1) && rc=0 || rc=$?
if [ "$rc" -eq 1 ]; then
    check "--check-backup stale marker exits 1" "pass"
else
    check "--check-backup stale marker exits 1" "fail:rc=$rc. Output: $output"
fi

# Test 3: --check-backup with no marker exits 1 and says so
reset_state
output=$(bash "$SCRIPT" --check-backup 2>&1) && rc=0 || rc=$?
if [ "$rc" -eq 1 ] && echo "$output" | grep -q "no successful backup"; then
    check "--check-backup missing marker exits 1" "pass"
else
    check "--check-backup missing marker exits 1" "fail:rc=$rc. Output: $output"
fi

# Test 4: normal tick with a stale marker pages BACKUP alert
reset_state
echo "$((NOW - 30 * 3600))" > "$MARKER"
output=$(bash "$SCRIPT" 2>&1) && rc=0 || rc=$?
if [ "$rc" -eq 0 ] && echo "$output" | grep -q "DRY-RUN send_alert: .*BACKUP"; then
    check "normal tick with stale marker pages BACKUP alert" "pass"
else
    check "normal tick with stale marker pages BACKUP alert" "fail:rc=$rc. Output: $output"
fi

# Test 5: the next stale tick does not page again (one page per staleness episode)
output=$(bash "$SCRIPT" 2>&1) || true
if ! echo "$output" | grep -q "DRY-RUN send_alert: .*BACKUP"; then
    check "second stale tick does not re-page" "pass"
else
    check "second stale tick does not re-page" "fail:paged again. Output: $output"
fi

# Test 6: a fresh marker after an alert sends a recovery note, once
echo "$NOW" > "$MARKER"
output=$(bash "$SCRIPT" 2>&1) || true
output2=$(bash "$SCRIPT" 2>&1) || true
if echo "$output" | grep -q "DRY-RUN send_alert: .*BACKUP RECOVERED" \
        && ! echo "$output2" | grep -q "BACKUP RECOVERED"; then
    check "fresh marker after alert sends one recovery note" "pass"
else
    check "fresh marker after alert sends one recovery note" "fail:Output1: $output Output2: $output2"
fi

# Test 7: no marker on a fresh host does not page before the grace window
reset_state
output=$(bash "$SCRIPT" 2>&1) || true
if ! echo "$output" | grep -q "DRY-RUN send_alert: .*BACKUP"; then
    check "missing marker within grace window does not page" "pass"
else
    check "missing marker within grace window does not page" "fail:paged early. Output: $output"
fi

# Test 8: no marker and the monitor has been looking longer than the window → page
echo "$((NOW - 30 * 3600))" > "$KB_MONITOR_STATE_DIR/backup_first_seen"
output=$(bash "$SCRIPT" 2>&1) || true
if echo "$output" | grep -q "DRY-RUN send_alert: .*BACKUP.*no successful backup"; then
    check "missing marker past grace window pages" "pass"
else
    check "missing marker past grace window pages" "fail:Output: $output"
fi

# Test 9: --simulate-backup-stale forces the alert path
reset_state
output=$(bash "$SCRIPT" --simulate-backup-stale 2>&1) && rc=0 || rc=$?
if [ "$rc" -eq 0 ] && echo "$output" | grep -q "DRY-RUN send_alert: .*BACKUP"; then
    check "--simulate-backup-stale sends BACKUP alert" "pass"
else
    check "--simulate-backup-stale sends BACKUP alert" "fail:rc=$rc. Output: $output"
fi

rm -rf "$T"

echo ""
echo "=== Results: $PASS passed, $FAIL failed, $TOTAL total ==="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
