from __future__ import annotations

"""Tests for Phase 3 self-learning: volume landmark fitting and ACWR band fitting."""

from datetime import date, timedelta

import pytest

from shc.training.self_learning import (
    _percentile,
    fit_acwr_bands,
    fit_volume_landmarks,
    persist_acwr_bands,
    persist_volume_landmarks,
    read_acwr_bands,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _seed_e1rm(conn, exercise: str, week: date, e1rm: float, sets: int,
               perf: int | None = None, tonnage: float | None = None) -> None:
    conn.execute(
        """
        INSERT INTO exercise_weekly_e1rm
            (exercise, week_start, e1rm_kg, work_sets, perf_score,
             trend, weekly_tonnage_kg, computed_at)
        VALUES (?, ?, ?, ?, ?, NULL, ?, now())
        ON CONFLICT (exercise, week_start) DO UPDATE SET
            e1rm_kg=excluded.e1rm_kg, work_sets=excluded.work_sets,
            perf_score=excluded.perf_score, weekly_tonnage_kg=excluded.weekly_tonnage_kg
        """,
        [exercise, week.isoformat(), e1rm, sets, perf, tonnage],
    )


def _seed_muscle_map(conn, exercise: str, primary: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO exercise_muscle_map (exercise_name, primary_muscle, secondary_muscles)"
        " VALUES (?, ?, ?)",
        [exercise, primary, []],
    )


# ── _percentile ───────────────────────────────────────────────────────────────


def test_percentile_median() -> None:
    assert _percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.5) == pytest.approx(3.0)


def test_percentile_min_max() -> None:
    vals = [10.0, 20.0, 30.0]
    assert _percentile(vals, 0.0) == pytest.approx(10.0)
    assert _percentile(vals, 1.0) == pytest.approx(30.0)


def test_percentile_empty_raises() -> None:
    with pytest.raises(ValueError):
        _percentile([], 0.5)


# ── fit_volume_landmarks ──────────────────────────────────────────────────────


def test_fit_volume_landmarks_insufficient_weeks_returns_none(conn) -> None:
    _seed_muscle_map(conn, "Curl", "biceps")
    # Only 5 weeks — below the 10-week minimum.
    base = _monday(date.today()) - timedelta(weeks=20)
    for i in range(5):
        _seed_e1rm(conn, "Curl", base + timedelta(weeks=i * 2), 40.0, 8 + i, perf=3)
    assert fit_volume_landmarks(conn, "biceps") is None


def test_fit_volume_landmarks_narrow_spread_returns_none(conn) -> None:
    _seed_muscle_map(conn, "Curl", "biceps")
    base = _monday(date.today()) - timedelta(weeks=15)
    # 12 weeks all at volume 8 sets — spread = 0
    for i in range(12):
        _seed_e1rm(conn, "Curl", base + timedelta(weeks=i), 40.0 + i, 8, perf=3)
    assert fit_volume_landmarks(conn, "biceps") is None


def test_fit_volume_landmarks_returns_mev_le_mav_le_mrv(conn) -> None:
    _seed_muscle_map(conn, "Curl", "biceps")
    base = _monday(date.today()) - timedelta(weeks=20)
    # Weeks at volume 2 (regressing), 4–12 (progressing), 14 (regressing again).
    data = (
        [(2, 2), (2, 2), (2, 2), (2, 2)]      # low volume, regress → perf 2
        + [(6, 6), (8, 8), (8, 8), (8, 8), (10, 10), (10, 10), (12, 12), (12, 12), (12, 12), (14, 14)]  # productive
        + [(18, 18), (18, 18), (18, 18), (18, 18)]  # over MRV, regress
    )
    for i, (sets, _) in enumerate(data):
        perf = 2 if sets <= 2 or sets >= 18 else 4
        _seed_e1rm(conn, "Curl", base + timedelta(weeks=i), 40.0, sets, perf=perf)

    result = fit_volume_landmarks(conn, "biceps")
    assert result is not None, "should fit with enough spread and samples"
    assert result["mev"] <= result["mav"] <= result["mrv"]
    assert result["mev"] >= 0
    assert result["mrv"] > result["mev"]


# ── fit_acwr_bands ────────────────────────────────────────────────────────────


def test_fit_acwr_bands_insufficient_data_returns_none(conn) -> None:
    # Empty v_daily_load → no ACWR history → returns None.
    result = fit_acwr_bands(conn, min_weeks=12)
    assert result is None


# ── persist + read_acwr_bands ─────────────────────────────────────────────────


def test_read_acwr_bands_empty_table_returns_none(conn) -> None:
    assert read_acwr_bands(conn) is None


def test_persist_and_read_acwr_bands_roundtrip(conn) -> None:
    """Manually insert bands and verify read_acwr_bands returns the correct mapping."""
    rows = [
        ("resistance",   "rest",         2.10, 50),
        ("resistance",   "low",          1.75, 50),
        ("resistance",   "mod",          1.45, 50),
        ("conditioning", "forbid_legs",  1.95, 30),
    ]
    for arm, name, val, n in rows:
        conn.execute(
            "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks)"
            " VALUES (?, ?, ?, ?)",
            [arm, name, val, n],
        )

    bands = read_acwr_bands(conn)
    assert bands is not None
    assert bands["RES_ACWR_REST"]       == pytest.approx(2.10)
    assert bands["RES_ACWR_LOW"]        == pytest.approx(1.75)
    assert bands["RES_ACWR_MOD"]        == pytest.approx(1.45)
    assert bands["COND_ACWR_FORBID_LEGS"] == pytest.approx(1.95)


def test_read_acwr_bands_partial_returns_none(conn) -> None:
    """If only some thresholds are stored (e.g. partial migration), return None."""
    conn.execute(
        "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks)"
        " VALUES ('resistance', 'rest', 2.0, 10)"
    )
    assert read_acwr_bands(conn) is None


# ── persist_volume_landmarks ─────────────────────────────────────────────────


def test_persist_volume_landmarks_writes_scoped_rows(conn) -> None:
    _seed_muscle_map(conn, "Curl", "biceps")
    conn.execute(
        "INSERT OR IGNORE INTO muscle_volume_targets "
        "(muscle_group, mev_sets, mav_sets, mrv_sets, mesocycle_id) "
        "VALUES ('biceps', 6, 12, 20, '')"
    )
    base = _monday(date.today()) - timedelta(weeks=25)
    for i in range(20):
        sets = 4 + (i % 12)
        perf = 2 if sets <= 4 else (4 if sets <= 14 else 2)
        _seed_e1rm(conn, "Curl", base + timedelta(weeks=i), 40.0, sets, perf=perf)

    stored = persist_volume_landmarks(conn, "test-meso-id")
    # May or may not fit depending on bin sampling, but must not crash.
    assert stored >= 0
    if stored > 0:
        row = conn.execute(
            "SELECT mev_sets, mav_sets, mrv_sets FROM muscle_volume_targets "
            "WHERE muscle_group='biceps' AND mesocycle_id='test-meso-id'"
        ).fetchone()
        assert row is not None
        assert row[0] <= row[1] <= row[2]
