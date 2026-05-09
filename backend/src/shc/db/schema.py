from __future__ import annotations

import asyncio
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

import duckdb

from shc.config import settings

# Allow only printable ASCII without quotes/backslashes/control chars.
# Prevents PRAGMA SQL injection via the encryption key value.
_KEY_RE = re.compile(r"^[A-Za-z0-9+/=_\-.@#$%^&*()!~`:;,?<>\[\]{}|]{16,256}$")

log = logging.getLogger(__name__)

_write_lock: asyncio.Lock | None = None
_write_conn: duckdb.DuckDBPyConnection | None = None

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def _migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def _apply_migrations(conn: duckdb.DuckDBPyConnection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version "
        "(version INTEGER PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )
    applied: set[int] = {
        r[0] for r in conn.execute("SELECT version FROM schema_version").fetchall()
    }
    for path in _migration_files():
        version = int(path.stem.split("_")[0])
        if version in applied:
            continue
        log.info("applying migration %s", path.name)
        conn.execute(path.read_text())
        log.info("migration %s applied", path.name)


def init_db() -> None:
    """Open write connection, apply migrations, configure encryption key.

    If DuckDB fails to open due to a stale/corrupt WAL file (which happens when
    the process was killed mid-write or across worktree restarts), the WAL is
    removed and the connection is retried once.  This is safe because the WAL
    represents only un-checkpointed data from the previous (now-dead) process.
    To minimise data loss, ``dev-restart.sh`` calls ``POST /api/internal/checkpoint``
    before killing the process so the WAL is already flushed before removal.
    """
    global _write_conn, _write_lock
    db_path = settings.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    resolved_path = db_path.resolve()
    wal_path = resolved_path.with_suffix(".duckdb.wal")

    def _open() -> duckdb.DuckDBPyConnection:
        conn = duckdb.connect(str(resolved_path))
        encryption_key = settings.db_encryption_key
        if encryption_key:
            if not _KEY_RE.match(encryption_key):
                raise ValueError(
                    "db_encryption_key contains disallowed characters or has unsafe length; "
                    "use 16–256 chars from the safe set (no quotes, no backslashes)"
                )
            # Safe to interpolate — value is validated against an allowlist above.
            conn.execute(f"PRAGMA key='{encryption_key}'")
        return conn

    try:
        conn = _open()
    except duckdb.InternalException as exc:
        if "WAL" in str(exc) and wal_path.exists():
            log.warning("Stale DuckDB WAL detected — removing and retrying (%s)", exc)
            wal_path.unlink()
            conn = _open()
        else:
            raise

    _apply_migrations(conn)
    # Immediately checkpoint so the WAL is clean for the next restart
    conn.execute("CHECKPOINT")
    _write_conn = conn
    _write_lock = asyncio.Lock()
    log.info("DuckDB ready at %s", resolved_path)


def get_write_conn() -> duckdb.DuckDBPyConnection:
    assert _write_conn is not None, "init_db() not called"
    return _write_conn


def get_write_lock() -> asyncio.Lock:
    assert _write_lock is not None, "init_db() not called"
    return _write_lock


def get_read_conn() -> duckdb.DuckDBPyConnection:
    """Return a cursor on the shared write connection — safe for concurrent reads."""
    assert _write_conn is not None, "init_db() not called"
    return _write_conn.cursor()


@asynccontextmanager
async def write_ctx():
    """Async context manager that serializes writes through the global lock."""
    lock = get_write_lock()
    async with lock:
        yield get_write_conn()
