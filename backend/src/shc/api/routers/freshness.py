from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import duckdb
from fastapi import APIRouter

from shc.db.schema import get_read_conn

router = APIRouter(tags=["freshness"])

# (key, label, SQL returning the newest timestamp, hours before it counts as stale).
# Each is judged against its own cadence: one fresh source must not hide a stale one.
_SOURCES = [
    ("whoop", "WHOOP", "SELECT last_sync_at FROM oauth_state WHERE source = 'whoop'", 18),
    ("hevy", "Hevy", "SELECT last_sync_at FROM oauth_state WHERE source = 'hevy'", 30),
    # Not oauth_state: DUPR stamps it on every login attempt, failed ones included.
    ("dupr", "DUPR", "SELECT max(synced_at) FROM dupr_snapshots", 8 * 24),
    ("stress", "Stress", "SELECT max(sampled_at) FROM whoop_stress_timeline", 36),
    (
        "apple",
        "Apple Health",
        "SELECT max(ts) FROM measurements WHERE source = 'apple_health'",
        36,
    ),
    ("location", "Location", "SELECT max(tst) FROM location_points", 72),
]


def freshness(conn: duckdb.DuckDBPyConnection, now: datetime | None = None) -> list[dict[str, Any]]:
    """Per-source age of the newest data and whether it is overdue."""
    now = now or datetime.now(UTC)
    out = []
    for key, label, sql, stale_h in _SOURCES:
        row = conn.execute(sql).fetchone()
        last = row[0] if row else None
        if last is None:
            state, age = "never", None
        else:
            age = (now - last).total_seconds() / 3600
            state = "stale" if age > stale_h else "ok"
        out.append(
            {
                "key": key,
                "label": label,
                "last_at": last.isoformat() if last else None,
                "age_h": round(age, 1) if age is not None else None,
                "stale_after_h": stale_h,
                "state": state,
            }
        )
    return out


@router.get("/freshness")
def get_freshness() -> list[dict[str, Any]]:
    conn = get_read_conn()
    try:
        return freshness(conn)
    finally:
        conn.close()
