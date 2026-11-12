from __future__ import annotations

from datetime import UTC, datetime, timedelta

import duckdb

from shc.api.routers.freshness import freshness

NOW = datetime(2026, 3, 1, 12, tzinfo=UTC)


def test_each_source_is_judged_against_its_own_cadence(conn: duckdb.DuckDBPyConnection) -> None:
    # WHOOP fresh, DUPR a month stale, stress never synced.
    conn.execute(
        "INSERT INTO oauth_state (source, last_sync_at) VALUES ('whoop', ?)",
        [NOW - timedelta(hours=2)],
    )
    # A failed DUPR login stamps oauth_state just now; only a real snapshot counts.
    conn.execute(
        "INSERT INTO oauth_state (source, last_sync_at, needs_reauth) VALUES ('dupr', ?, TRUE)",
        [NOW],
    )
    conn.execute(
        "INSERT INTO dupr_snapshots (date, doubles, synced_at) VALUES (?, 3.6, ?)",
        [(NOW - timedelta(days=30)).date(), NOW - timedelta(days=30)],
    )
    states = {s["key"]: s["state"] for s in freshness(conn, NOW)}
    assert states["whoop"] == "ok"
    assert states["dupr"] == "stale"  # the old LiveBadge took the newest of all, hiding this
    assert states["stress"] == "never"


def test_apple_health_is_judged_by_arrival_not_by_its_day_start_stamp(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    # Yesterday's totals, stamped at midnight (~44 h before NOW), that arrived 3 h ago.
    conn.execute(
        "INSERT INTO measurements (source, metric, ts, value_num, external_id, content_hash, ingested_at) "
        "VALUES ('apple_health', 'step_count', ?, 9000, 'shortcut:step_count:x', 'h', ?)",
        [NOW - timedelta(hours=44), NOW - timedelta(hours=3)],
    )
    assert {s["key"]: s["state"] for s in freshness(conn, NOW)}["apple"] == "ok"

    conn.execute("UPDATE measurements SET ingested_at = ?", [NOW - timedelta(hours=40)])
    assert {s["key"]: s["state"] for s in freshness(conn, NOW)}["apple"] == "stale"
