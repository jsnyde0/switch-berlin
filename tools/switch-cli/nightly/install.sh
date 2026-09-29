#!/bin/bash
# Install (or re-install) the nightly collector LaunchAgent for this checkout.
# Usage: tools/switch-cli/nightly/install.sh          install and load
#        tools/switch-cli/nightly/install.sh --remove unload and delete
set -euo pipefail
LABEL="berlin.switch.collector-nightly"
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
TARGET="$HOME/Library/LaunchAgents/$LABEL.plist"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
if [ "${1:-}" = "--remove" ]; then
    rm -f "$TARGET"
    echo "removed $LABEL"
    exit 0
fi
mkdir -p "$HOME/Library/Logs/switch-collector"
sed -e "s|__REPO__|$REPO|g" -e "s|__HOME__|$HOME|g" "$HERE/$LABEL.plist" > "$TARGET"
plutil -lint "$TARGET"
launchctl bootstrap "gui/$(id -u)" "$TARGET"
echo "loaded $LABEL -> $TARGET"
