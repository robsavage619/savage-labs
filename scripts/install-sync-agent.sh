#!/bin/zsh
# Installs the SHC sync LaunchAgent. Run once after pulling this script.
# Re-running is safe — it unloads any prior copy before reloading.

set -e

REPO_ROOT="${HOME}/projects/savage-health-center"
SRC_PLIST="${REPO_ROOT}/scripts/com.savage.shc-sync.plist"
DEST_PLIST="${HOME}/Library/LaunchAgents/com.savage.shc-sync.plist"

if [[ ! -f "${SRC_PLIST}" ]]; then
  echo "✗ Source plist not found at ${SRC_PLIST}"
  exit 1
fi

mkdir -p "${HOME}/Library/LaunchAgents"
mkdir -p "${HOME}/Library/Logs/shc-sync"

# Unload any existing version (ignore errors).
launchctl unload "${DEST_PLIST}" 2>/dev/null || true

cp "${SRC_PLIST}" "${DEST_PLIST}"
launchctl load "${DEST_PLIST}"

echo "✓ Installed: ${DEST_PLIST}"
echo "  Schedule: 7am, 1pm, 6pm, 10pm"
echo "  Logs:     ${HOME}/Library/Logs/shc-sync/sync.log"
echo
echo "Test it now: ${REPO_ROOT}/scripts/sync-shc.sh"
echo "Disable:     launchctl unload ${DEST_PLIST}"
