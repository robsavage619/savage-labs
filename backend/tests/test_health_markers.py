from __future__ import annotations

import random
from datetime import date, datetime, timedelta

import duckdb
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from shc.ai import vault
from shc.api.routers import healthspan
from shc.health_markers import MARKERS, _trend, evaluate, names_due, seed

TODAY = date(2026, 6, 1)


def _lab(conn: duckdb.DuckDBPyConnection, name: str, value: float, days_ago: int) -> None:
    when = datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time())
    conn.execute(
        "INSERT INTO labs (id, name, value, unit, collected_at) VALUES (?, ?, ?, 'u', ?)",
        [f"{name}-{days_ago}-{value}", name, value, when],
    )


def _tape(conn: duckdb.DuckDBPyConnection, value: float, days_ago: int) -> None:
    when = datetime.combine(TODAY - timedelta(days=days_ago), datetime.min.time())
    conn.execute(
        "INSERT INTO measurements (source, metric, ts, value_num, external_id, content_hash) "
        "VALUES ('manual', 'waist_circumference_cm', ?, ?, ?, 'h')",
        [when, value, f"w{days_ago}"],
    )


def _row(conn: duckdb.DuckDBPyConnection, marker: str) -> dict:
    return next(r for r in evaluate(conn, TODAY) if r["marker"] == marker)


def test_migration_rows_match_python_definitions(conn: duckdb.DuckDBPyConnection) -> None:
    cols = (
        "marker, label, domain, source_table, source_metric, unit, target_low, "
        "target_high, target_source, retest_days, direction"
    )
    rows = conn.execute(f"SELECT {cols} FROM health_markers").fetchall()
    assert sorted(rows) == sorted(tuple(m) for m in MARKERS)


def test_on_target_and_trend_needs_three_readings(conn: duckdb.DuckDBPyConnection) -> None:
    _lab(conn, "ApoB", 40, 10)
    _lab(conn, "ApoB", 41, 100)
    r = _row(conn, "apob")
    assert r["status"] == "on target"
    assert r["trend"]["note"] == "not enough readings"
    assert r["trend"]["slope_per_30d"] is None
    _lab(conn, "ApoB", 40, 200)  # outside the 6-month window: falls back to last 3 readings
    r = _row(conn, "apob")
    assert r["trend"]["n"] == 3
    assert r["trend"]["slope_per_30d"] is not None


def test_out_of_range(conn: duckdb.DuckDBPyConnection) -> None:
    _lab(conn, "ApoB", 80, 10)
    assert _row(conn, "apob")["status"] == "out of range"


def test_drifting_when_the_trend_crosses_the_limit_within_one_retest_period(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    for value, ago in ((24, 60), (26, 30), (28, 1)):
        _lab(conn, "ALT", value, ago)
    r = _row(conn, "alt")
    assert r["status"] == "drifting"
    assert r["trend"]["slope_per_30d"] > 0


def test_flat_in_range_is_not_drifting(conn: duckdb.DuckDBPyConnection) -> None:
    for ago in (60, 30, 1):
        _lab(conn, "ALT", 20, ago)
    assert _row(conn, "alt")["status"] == "on target"


def test_old_value_is_stale_even_when_in_range(conn: duckdb.DuckDBPyConnection) -> None:
    _lab(conn, "ApoB", 40, 200)  # cadence is 180 days
    r = _row(conn, "apob")
    assert r["status"] == "stale"
    assert r["age_days"] == 200


def test_no_target_is_never_on_target(conn: duckdb.DuckDBPyConnection) -> None:
    _tape(conn, 80, 3)
    r = _row(conn, "waist")
    assert r["status"] == "no target set"
    assert r["target"]["source"] == "no target set"
    assert all(
        x["status"] != "on target"
        for x in evaluate(conn, TODAY)
        if x["target"]["low"] is None and x["target"]["high"] is None
    )


def test_no_data(conn: duckdb.DuckDBPyConnection) -> None:
    r = _row(conn, "grip")
    assert r["status"] == "no data"
    assert r["value"] is None


def test_names_due_returns_labels_only(conn: duckdb.DuckDBPyConnection) -> None:
    _lab(conn, "ApoB", 80, 10)  # out of range
    _lab(conn, "ALT", 20, 5)  # fine
    due = names_due(conn, TODAY)
    assert due == ["ApoB (artery-clogging particle count)"]
    assert all(isinstance(x, str) for x in due)


def test_steps_exclude_the_partial_current_day(conn: duckdb.DuckDBPyConnection) -> None:
    for ago, v in ((0, 100), (1, 9000)):
        conn.execute(
            "INSERT INTO measurements (source, metric, ts, value_num, external_id, content_hash) "
            "VALUES ('apple_health', 'step_count', ?, ?, ?, 'h')",
            [datetime.combine(TODAY - timedelta(days=ago), datetime.min.time()), v, f"s{ago}"],
        )
    r = _row(conn, "steps")
    assert r["value"] == 9000


def test_seed_rejects_a_citation_that_is_not_a_vault_note(
    conn: duckdb.DuckDBPyConnection, monkeypatch
) -> None:
    monkeypatch.setattr(vault, "valid_citation_filenames", lambda: {"some-other-note.md"})
    with pytest.raises(ValueError, match="not a vault note"):
        seed(conn)


def test_seed_accepts_real_citations_and_is_idempotent(
    conn: duckdb.DuckDBPyConnection, monkeypatch
) -> None:
    cited = {m.target_source for m in MARKERS if m.target_source}
    monkeypatch.setattr(vault, "valid_citation_filenames", lambda: set(cited))
    assert seed(conn) == len(MARKERS)
    assert seed(conn) == len(MARKERS)
    count = conn.execute("SELECT count(*) FROM health_markers").fetchall()
    assert count == [(len(MARKERS),)]


def test_seed_fails_visibly_when_the_vault_is_unavailable(
    conn: duckdb.DuckDBPyConnection, monkeypatch
) -> None:
    monkeypatch.setattr(vault, "valid_citation_filenames", lambda: set())
    with pytest.raises(RuntimeError):
        seed(conn)


def test_every_cited_note_exists_in_the_real_vault() -> None:
    real = vault.valid_citation_filenames()
    if not real:
        pytest.skip("vault not available")
    for m in MARKERS:
        if m.target_source:
            assert m.target_source in real


def test_endpoint_returns_every_marker(conn: duckdb.DuckDBPyConnection, monkeypatch) -> None:
    monkeypatch.setattr(healthspan.schema, "get_read_conn", lambda: conn.cursor())
    app = FastAPI()
    app.include_router(healthspan.router, prefix="/api")
    body = TestClient(app).get("/api/healthspan").json()
    assert {r["marker"] for r in body} == {m.marker for m in MARKERS}
    assert all(r["status"] == "no data" for r in body)


def _weigh(conn: duckdb.DuckDBPyConnection, lb: list[float], status: str = "approved") -> None:
    conn.execute(
        "INSERT INTO research_custom_features (name, owner, description, unit, timing, sql, "
        "status, goal) VALUES ('custom:weighin_lb', 'metabolic', 'synthetic', 'lb', 'day', "
        "'SELECT date, body_weight_kg FROM daily_checkin WHERE body_weight_kg IS NOT NULL', "
        "?, 'body')",
        [status],
    )
    start = TODAY - timedelta(days=len(lb) - 1)
    conn.executemany(
        "INSERT INTO daily_checkin (date, body_weight_kg) VALUES (?, ?)",
        [(start + timedelta(days=i), v) for i, v in enumerate(lb)],
    )


def _noisy(slope_per_day: float, n: int, seed: int) -> list[float]:
    rng = random.Random(seed)
    return [230.0 + slope_per_day * i + rng.gauss(0, 1.0) for i in range(n)]


def test_body_weight_reports_a_planted_loss_with_its_range(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    _weigh(conn, _noisy(-0.5 / 7, 60, seed=1))
    t = _row(conn, "body_weight")["trend"]
    low, high = t["range_per_30d"]
    assert t["note"] == "falling"
    assert low <= -0.5 / 7 * 30 <= high
    assert 0.7 < t["noise_sd"] < 1.3


def test_body_weight_flat_reads_as_no_clear_trend(conn: duckdb.DuckDBPyConnection) -> None:
    _weigh(conn, _noisy(0.0, 30, seed=2))
    assert _row(conn, "body_weight")["trend"]["note"] == "no clear trend"


def test_body_weight_from_an_unapproved_measurement_is_no_data(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    _weigh(conn, [230.0] * 10, status="proposed")
    assert _row(conn, "body_weight")["status"] == "no data"


def test_trend_range_covers_the_true_slope_about_90_percent_of_the_time() -> None:
    true = -0.05
    hits = 0
    for draw in range(300):
        rng = random.Random(draw)
        noise, series = 0.0, []
        for i in range(56):
            noise = 0.4 * noise + rng.gauss(0, 1.0)  # autocorrelated day-to-day water
            series.append((TODAY - timedelta(days=55 - i), 230.0 + true * i + noise))
        low, high = _trend(series, TODAY)["range_per_30d"]
        hits += low <= true * 30 <= high
    assert 0.84 <= hits / 300 <= 0.96
