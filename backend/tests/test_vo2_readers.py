from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pytest

from shc import metrics
from shc.api.routers import dashboard


def _add(conn: duckdb.DuckDBPyConnection, metric: str, days_ago: int, value: float) -> None:
    day = date.today() - timedelta(days=days_ago)
    source = "whoop_private" if metric == metrics.WHOOP_VO2_METRIC else "apple_health"
    conn.execute(
        "INSERT INTO measurements (source, metric, ts, value_num, unit, external_id, content_hash) "
        "VALUES (?, ?, ?, ?, 'mL/kg/min', ?, ?)",
        [source, metric, f"{day} 12:00:00", value, f"{metric}:{day}", f"h{metric}{day}"],
    )


def test_whoop_is_read_only_once_it_has_rows(conn: duckdb.DuckDBPyConnection) -> None:
    assert metrics.vo2_metric(conn) == metrics.APPLE_VO2_METRIC
    _add(conn, metrics.WHOOP_VO2_METRIC, 7, 36.0)
    assert metrics.vo2_metric(conn) == metrics.WHOOP_VO2_METRIC


def test_the_cardio_prescription_anchors_on_whoop_and_never_blends(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    _add(conn, metrics.APPLE_VO2_METRIC, 3, 50.0)  # recent Apple row that must not leak in
    assert metrics.vo2max_series(conn) == {
        "latest": 50.0,
        "latest_date": str(date.today() - timedelta(days=3)),
        "trend_pct": 0.0,
        "change_abs": 0.0,
        "n": 1,
    }
    _add(conn, metrics.WHOOP_VO2_METRIC, 14, 38.0)
    _add(conn, metrics.WHOOP_VO2_METRIC, 7, 36.0)
    got = metrics.vo2max_series(conn)
    assert got is not None
    assert (got["latest"], got["n"], got["change_abs"]) == (36.0, 2, -2.0)


@pytest.mark.asyncio
async def test_the_body_chart_serves_whoop_and_says_so(
    conn: duckdb.DuckDBPyConnection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dashboard, "get_read_conn", lambda: conn.cursor())
    _add(conn, metrics.APPLE_VO2_METRIC, 30, 45.0)
    assert [p["source"] for p in await dashboard.body_vo2max()] == ["apple_watch"]
    _add(conn, metrics.WHOOP_VO2_METRIC, 14, 38.0)
    _add(conn, metrics.WHOOP_VO2_METRIC, 7, 36.0)
    chart = await dashboard.body_vo2max()
    assert [(p["source"], p["vo2max"]) for p in chart] == [("whoop", 38.0), ("whoop", 36.0)]
