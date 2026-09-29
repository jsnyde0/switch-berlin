#!/bin/bash
# Tests for kb-backup.sh behaviors added in sb-omx:
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

echo "=== sb-omx: kb-backup.sh unit tests ==="
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

# --- sb-4sr1: off-provider target placeholder + success marker ---------------
# Stubs for docker/restic on PATH so the normal-run path executes locally
# without a db, a restic repo or the network.
STUB_DIR=$(mktemp -d)
STATE_DIR_T="$STUB_DIR/state"
cat > "$STUB_DIR/docker" <<'STUB'
#!/bin/bash
case "$1" in
    ps)   echo "app-db-1" ;;
    exec) head -c 60000 /dev/zero ;;   # 60KB dump, above the 50KiB floor
esac
STUB
cat > "$STUB_DIR/restic" <<'STUB'
#!/bin/bash
case "$1" in
    stats)  echo '{"total_size": 60000}' ;;
    backup) cat >/dev/null; [ "${RESTIC_STUB_FAIL:-}" = "1" ] && exit 1; exit 0 ;;
esac
STUB
chmod +x "$STUB_DIR/docker" "$STUB_DIR/restic"

# Test 8: the unfilled template placeholder refuses to run (fail loud, no backup)
output=$(PATH="$STUB_DIR:$PATH" KB_BACKUP_STATE_DIR="$STATE_DIR_T" \
    RESTIC_REPOSITORY=REPLACE_ME_off_provider_restic_repo RESTIC_PASSWORD=dummy \
    bash "$SCRIPT" 2>&1) && actual_exit=0 || actual_exit=$?
if [ "$actual_exit" -ne 0 ] && echo "$output" | grep -q "placeholder"; then
    check "placeholder RESTIC_REPOSITORY exits non-zero naming the placeholder" "pass"
else
    check "placeholder RESTIC_REPOSITORY exits non-zero naming the placeholder" "fail:exit=$actual_exit. Output: $output"
fi

# Test 9: --test-alert still works with the placeholder (wire Telegram before the target)
output=$(RESTIC_REPOSITORY=REPLACE_ME_off_provider_restic_repo RESTIC_PASSWORD=dummy \
    bash "$SCRIPT" --test-alert 2>&1) && actual_exit=0 || actual_exit=$?
if [ "$actual_exit" -eq 0 ]; then
    check "--test-alert exits 0 with placeholder target" "pass"
else
    check "--test-alert exits 0 with placeholder target" "fail:exit=$actual_exit. Output: $output"
fi

# Test 10: a successful db snapshot writes the last-success marker (epoch seconds)
rm -rf "$STATE_DIR_T"
output=$(PATH="$STUB_DIR:$PATH" KB_BACKUP_STATE_DIR="$STATE_DIR_T" \
    RESTIC_REPOSITORY=s3:https://example.invalid/bucket RESTIC_PASSWORD=dummy \
    bash "$SCRIPT" 2>&1) && actual_exit=0 || actual_exit=$?
marker=$(cat "$STATE_DIR_T/last-success" 2>/dev/null || true)
if [ "$actual_exit" -eq 0 ] && [[ "$marker" =~ ^[0-9]+$ ]]; then
    check "successful backup writes last-success marker" "pass"
else
    check "successful backup writes last-success marker" "fail:exit=$actual_exit marker='$marker'. Output: $output"
fi

# Test 11: a failed restic backup leaves no marker (monitor must see it as stale)
rm -rf "$STATE_DIR_T"
output=$(PATH="$STUB_DIR:$PATH" KB_BACKUP_STATE_DIR="$STATE_DIR_T" RESTIC_STUB_FAIL=1 \
    RESTIC_REPOSITORY=s3:https://example.invalid/bucket RESTIC_PASSWORD=dummy \
    bash "$SCRIPT" 2>&1) && actual_exit=0 || actual_exit=$?
if [ "$actual_exit" -ne 0 ] && [ ! -f "$STATE_DIR_T/last-success" ]; then
    check "failed restic backup exits non-zero and writes no marker" "pass"
else
    check "failed restic backup exits non-zero and writes no marker" "fail:exit=$actual_exit marker-exists=$([ -f "$STATE_DIR_T/last-success" ] && echo yes || echo no)"
fi
rm -rf "$STUB_DIR"

echo ""
echo "=== Results: $PASS passed, $FAIL failed, $TOTAL total ==="

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
