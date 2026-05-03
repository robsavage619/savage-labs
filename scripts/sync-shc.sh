#!/bin/zsh
# Hit the SHC sync endpoints (WHOOP + Hevy) — meant to be invoked by the
# launchd agent at `com.savage.shc-sync.plist`. Skips gracefully if the
# local API is not running (no error spam when the laptop is closed or the
# dev server is down).

set -u
LOG_DIR="${HOME}/Library/Logs/shc-sync"
mkdir -p "${LOG_DIR}"
LOG="${LOG_DIR}/sync.log"

ts() { date +"%Y-%m-%d %H:%M:%S"; }
log() { echo "[$(ts)] $*" >> "${LOG}"; }

# Reachability check — bail quietly if the API isn't up.
if ! curl -sS --max-time 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8000/api/state/today | grep -qE "^(200|304)$"; then
  log "API not reachable on :8000 — skipping sync"
  exit 0
fi

log "── sync start"

WHOOP_OUT=$(curl -sS --max-time 60 -X POST http://127.0.0.1:8000/auth/whoop/sync 2>&1) && \
  log "whoop ok · ${WHOOP_OUT}" || \
  log "whoop FAILED · ${WHOOP_OUT}"

HEVY_OUT=$(curl -sS --max-time 60 -X POST http://127.0.0.1:8000/api/hevy/sync 2>&1) && \
  log "hevy  ok · ${HEVY_OUT}" || \
  log "hevy  FAILED · ${HEVY_OUT}"

# Trigger adherence recompute so yesterday's plan-vs-execution row updates.
curl -sS --max-time 30 -X POST http://127.0.0.1:8000/api/training/adherence/recompute > /dev/null 2>&1 \
  && log "adherence recomputed" \
  || log "adherence recompute skipped"

log "── sync end"
