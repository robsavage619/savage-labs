#!/usr/bin/env zsh
# Kills whatever is on :3000/:8000 and starts SHC from the given worktree (or latest).
# Usage: ./dev-restart.sh [worktree-path]
# Called by Claude automatically — don't edit the path selection logic.

set -e

REPO=/Users/robsavage/Projects/savage-health-center

# Always run from main repo — never a stale worktree
WT="${1:-$REPO}"

echo "▶ Restarting SHC from: $WT"

# Checkpoint DuckDB WAL via the running API before killing (preserves all in-flight writes)
if lsof -ti :8000 &>/dev/null; then
  echo "▶ Checkpointing DuckDB WAL..."
  curl -sf -X POST http://127.0.0.1:8000/api/internal/checkpoint 2>/dev/null && echo "  WAL checkpointed" || echo "  Checkpoint skipped (API not ready)"
  sleep 0.3
fi

# Kill anything on the ports AND any stale uvicorn processes (prevents DuckDB lock conflicts)
lsof -ti :3000 -ti :8000 2>/dev/null | xargs kill -9 2>/dev/null || true
pkill -9 -f "uvicorn shc" 2>/dev/null || true
sleep 2

# ── Canonical data dir ────────────────────────────────────────────────────────
# Must live in the main repo, not inside an ephemeral worktree.
# One-time migration: if backend/data is still a symlink, promote it to a real dir.
CANONICAL_DATA="$REPO/backend/data"

if [[ -L "$CANONICAL_DATA" ]]; then
  echo "▶ Promoting $CANONICAL_DATA from symlink → real directory..."
  LINK_TARGET="$(readlink "$CANONICAL_DATA")"
  mkdir -p "${CANONICAL_DATA}_tmp"
  cp -a "$LINK_TARGET/." "${CANONICAL_DATA}_tmp/"
  unlink "$CANONICAL_DATA"
  mv "${CANONICAL_DATA}_tmp" "$CANONICAL_DATA"
  echo "  Migrated from $LINK_TARGET"
fi

mkdir -p "$CANONICAL_DATA/logs"
touch "$CANONICAL_DATA/logs/shc.log"

# Symlink this worktree's backend/data → canonical dir (skip for main repo itself)
if [[ "$WT" != "$REPO" && ! -e "$WT/backend/data" ]]; then
  ln -sf "$CANONICAL_DATA" "$WT/backend/data"
fi

# ── WAL checkpoint ────────────────────────────────────────────────────────────
# uvicorn --reload kills the Python process without cleanly closing DuckDB,
# leaving a dirty WAL. Checkpoint (or delete) it before uvicorn binds.
DB="$CANONICAL_DATA/shc.duckdb"
WAL="$CANONICAL_DATA/shc.duckdb.wal"

if [[ -f "$DB" ]]; then
  (
    cd "$WT/backend"
    export _SHC_DB="$DB" _SHC_WAL="$WAL"
    uv run python - <<'PYEOF'
import duckdb, os, sys

db  = os.environ["_SHC_DB"]
wal = os.environ["_SHC_WAL"]

try:
    conn = duckdb.connect(db)
    conn.execute("CHECKPOINT")
    conn.close()
    print("  WAL checkpointed")
except Exception as e:
    print(f"  WAL replay failed ({e}); removing stale WAL", file=sys.stderr)
    if os.path.exists(wal):
        os.unlink(wal)
PYEOF
  )
fi

# ── Clean up orphan worktree WALs ─────────────────────────────────────────────
# Stale WALs left by deleted sessions can be replayed if they happen to share
# the canonical DB path recorded in the header. Safe to remove when no process
# owns them (uvicorn is already dead at this point).
for orphan_wal in "$REPO"/.claude/worktrees/*/backend/data/shc.duckdb.wal; do
  [[ -f "$orphan_wal" ]] || continue
  # Skip the canonical WAL (it lives in the main repo, not a worktree)
  orphan_dir="$(dirname "$orphan_wal")"
  [[ "$orphan_dir" == "$CANONICAL_DATA" ]] && continue
  echo "  Removing orphan WAL: $orphan_wal"
  rm -f "$orphan_wal"
done

# ── Clinical profile ingest ───────────────────────────────────────────────────
# Idempotent: wipes the kaiser_summary rows and reloads from YAML on every
# restart. Runs while the DB is unlocked (between API kill and uvicorn start).
if [[ -f "$CANONICAL_DATA/clinical_profile.yml" ]]; then
  (cd "$WT/backend" && uv run shc ingest-clinical-profile 2>&1 | sed 's/^/  /') || \
    echo "  Clinical ingest failed (non-fatal)"
fi

# ── Frontend deps ─────────────────────────────────────────────────────────────
if [[ ! -d "$WT/frontend/node_modules" ]]; then
  echo "▶ Installing frontend deps..."
  (cd "$WT/frontend" && npm install --silent)
fi

# ── Start backend ─────────────────────────────────────────────────────────────
(cd "$WT/backend" && nohup uv run uvicorn shc.api.main:app \
  --host 127.0.0.1 --port 8000 --reload \
  --log-config ../logging.yaml \
  > "$CANONICAL_DATA/logs/api.log" 2>&1 &)
echo "  API PID $!"

# ── Start frontend ────────────────────────────────────────────────────────────
(cd "$WT/frontend" && nohup npm run dev > "$CANONICAL_DATA/logs/web.log" 2>&1 &)
echo "  Web PID $!"

# Wait for ports
for i in {1..20}; do
  sleep 1
  API=$(lsof -ti :8000 2>/dev/null | head -1)
  WEB=$(lsof -ti :3000 2>/dev/null | head -1)
  [[ -n "$API" && -n "$WEB" ]] && break
done

echo ""
echo "✓ API  → http://127.0.0.1:8000  (PID $API)"
echo "✓ Web  → http://localhost:3000   (PID $WEB)"
