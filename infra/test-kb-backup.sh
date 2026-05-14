#!/bin/bash
# Tests for kb-backup.sh behaviors added in kb-omx:
#   1. Absolute 50KiB floor: --simulate-tiny-dump exits non-zero
#   2. --simulate-tiny-dump outputs size-floor alert message with floor info
#   3. Existing --test-alert still works (exits 0 when telegram unconfigured)
#
# Run with:
#   bash infra/test-kb-backup.sh
#
# These tests run without restic/docker/telegram configured (local dev).
# --simulate-tiny-dump must exit before any restic call.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$SCRIPT_DIR/kb-backup.sh"

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

echo "=== kb-omx: kb-backup.sh unit tests ==="
echo ""

# Test 1: --simulate-tiny-dump exits non-zero
# (must exit non-zero because dump is below 50KiB floor)
output=$(RESTIC_REPOSITORY=dummy RESTIC_PASSWORD=dummy bash "$SCRIPT" --simulate-tiny-dump 2>&1) && actual_exit=0 || actual_exit=$?
if [ "$actual_exit" -ne 0 ]; then
    check "--simulate-tiny-dump exits non-zero (exit=$actual_exit)" "pass"
else
    check "--simulate-tiny-dump exits non-zero" "fail:expected non-zero exit, got 0. Output: $output"
fi

# Test 2: --simulate-tiny-dump output mentions the 50KiB floor
output=$(RESTIC_REPOSITORY=dummy RESTIC_PASSWORD=dummy bash "$SCRIPT" --simulate-tiny-dump 2>&1) || true
if echo "$output" | grep -qiE "50|floor|tiny|size"; then
    check "--simulate-tiny-dump output mentions size/floor" "pass"
else
    check "--simulate-tiny-dump output mentions size/floor" "fail:expected size/floor mention in output. Output: $output"
fi

# Test 3: --simulate-tiny-dump output contains ALERT text (telegram unconfigured → logged to stderr)
output=$(RESTIC_REPOSITORY=dummy RESTIC_PASSWORD=dummy bash "$SCRIPT" --simulate-tiny-dump 2>&1) || true
if echo "$output" | grep -qiE "alert|ALERT"; then
    check "--simulate-tiny-dump triggers alert path" "pass"
else
    check "--simulate-tiny-dump triggers alert path" "fail:expected ALERT in output. Output: $output"
fi

# Test 4: --test-alert still exits 0 (regression — existing flag must not break)
output=$(RESTIC_REPOSITORY=dummy RESTIC_PASSWORD=dummy bash "$SCRIPT" --test-alert 2>&1) && actual_exit=0 || actual_exit=$?
if [ "$actual_exit" -eq 0 ]; then
    check "--test-alert still exits 0 (unconfigured telegram)" "pass"
else
    check "--test-alert still exits 0 (unconfigured telegram)" "fail:expected 0, got $actual_exit. Output: $output"
fi

# Test 5: --force-alert still exits 0 (regression — existing flag must not break)
output=$(RESTIC_REPOSITORY=dummy RESTIC_PASSWORD=dummy bash "$SCRIPT" --force-alert 2>&1) && actual_exit=0 || actual_exit=$?
if [ "$actual_exit" -eq 0 ]; then
    check "--force-alert still exits 0 (unconfigured telegram)" "pass"
else
    check "--force-alert still exits 0 (unconfigured telegram)" "fail:expected 0, got $actual_exit. Output: $output"
fi

# Test 6: --service-failed-alert exits 0 (fired by OnFailure unit; just sends message)
output=$(RESTIC_REPOSITORY=dummy RESTIC_PASSWORD=dummy bash "$SCRIPT" --service-failed-alert 2>&1) && actual_exit=0 || actual_exit=$?
if [ "$actual_exit" -eq 0 ]; then
    check "--service-failed-alert exits 0 (unconfigured telegram)" "pass"
else
    check "--service-failed-alert exits 0 (unconfigured telegram)" "fail:expected 0, got $actual_exit. Output: $output"
fi

# Test 7: --service-failed-alert output mentions "FAILED" and "journalctl"
output=$(RESTIC_REPOSITORY=dummy RESTIC_PASSWORD=dummy bash "$SCRIPT" --service-failed-alert 2>&1) || true
if echo "$output" | grep -qiE "FAILED|journalctl"; then
    check "--service-failed-alert output has failure context" "pass"
else
    check "--service-failed-alert output has failure context" "fail:expected FAILED/journalctl in output. Output: $output"
fi

echo ""
echo "=== Results: $PASS passed, $FAIL failed, $TOTAL total ==="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
