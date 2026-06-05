from __future__ import annotations

"""Behavioral tests for the self-learning trend/scoring engine.

Covers:
  - _trend_pct_per_week: rising / flat / declining series
  - _score_from_trend: band boundaries → correct Israetel 1–5 score
  - score_exercise: end-to-end via DuckDB with seeded e1RM rows
"""

from datetime import date, timedelta

import pytest

from shc.training.mesocycle import (
    _score_from_trend,
    _trend_pct_per_week,
    backfill_weekly_e1rm,
    score_exercise,
)


# ── _trend_pct_per_week ───────────────────────────────────────────────────────


def test_trend_rising_series() -> None:
    # 100 → 102 → 104 → 106: slope = +2/week, mean = 103 → ~1.94%/wk > 0
    result = _trend_pct_per_week([100.0, 102.0, 104.0, 106.0])
    assert result > 0


def test_trend_flat_series() -> None:
    result = _trend_pct_per_week([100.0, 100.0, 100.0, 100.0])
    assert abs(result) < 0.01  # essentially zero


def test_trend_declining_series() -> None:
    result = _trend_pct_per_week([106.0, 104.0, 102.0, 100.0])
    assert result < 0


def test_trend_single_point_returns_zero() -> None:
    assert _trend_pct_per_week([100.0]) == 0.0


# ── _score_from_trend ─────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "pct_per_week,expected_score",
    [
        (1.5, 5),   # above +1.0 → score 5
        (1.0, 5),   # exact +1.0 boundary → score 5
        (0.75, 4),  # in [0.5, 1.0) → score 4
        (0.5, 4),   # exact +0.5 boundary → score 4
        (0.0, 3),   # stalled → score 3
        (-0.5, 3),  # exact -0.5 boundary (≥ -0.5) → score 3
        (-0.75, 2), # in (-1.0, -0.5) → score 2
        (-1.0, 2),  # exact -1.0 boundary → score 2
        (-1.5, 1),  # below -1.0 → score 1
    ],
)
def test_score_from_trend_bands(pct_per_week: float, expected_score: int) -> None:
    score, _ = _score_from_trend(pct_per_week)
    assert score == expected_score


# ── score_exercise (end-to-end via DuckDB) ────────────────────────────────────


def _monday(d: date) -> date:
    """Return the ISO Monday for the week containing d."""
    return d - timedelta(days=d.weekday())


def _seed_e1rm_weeks(
    conn,
    exercise: str,
    e1rms: list[float],
    ref_monday: date,
) -> None:
    """Insert exercise_weekly_e1rm rows for the N weeks ending BEFORE ref_monday.

    e1rms[0] is the oldest week, e1rms[-1] is the most recent completed week.
    """
    n = len(e1rms)
    for i, e1rm in enumerate(e1rms):
        week = ref_monday - timedelta(weeks=(n - i))
        conn.execute(
            """
            INSERT INTO exercise_weekly_e1rm
                (exercise, week_start, e1rm_kg, work_sets, computed_at)
            VALUES (?, ?, ?, 5, now())
            ON CONFLICT (exercise, week_start) DO UPDATE SET
                e1rm_kg = excluded.e1rm_kg,
                work_sets = excluded.work_sets
            """,
            [exercise, week.isoformat(), e1rm],
        )


def test_score_exercise_rising_returns_high_score(conn) -> None:
    today = date.today()
    this_week = _monday(today)
    _seed_e1rm_weeks(conn, "Bench Press", [80.0, 82.0, 84.0, 86.0], this_week)

    result = score_exercise(conn, "Bench Press")
    assert result is not None
    assert result.perf_score >= 4, f"expected ≥4 for rising series, got {result.perf_score}"


def test_score_exercise_declining_returns_low_score(conn) -> None:
    today = date.today()
    this_week = _monday(today)
    _seed_e1rm_weeks(conn, "Squat", [90.0, 88.0, 85.0, 82.0], this_week)

    result = score_exercise(conn, "Squat")
    assert result is not None
    assert result.perf_score <= 2, f"expected ≤2 for declining series, got {result.perf_score}"


def test_score_exercise_exactly_two_completed_weeks_returns_none(conn) -> None:
    today = date.today()
    this_week = _monday(today)
    # Insert only 2 completed weeks — below the ≥3 threshold.
    _seed_e1rm_weeks(conn, "Deadlift", [100.0, 102.0], this_week)

    result = score_exercise(conn, "Deadlift")
    assert result is None, "should return None with < 3 completed weeks"


def test_score_exercise_via_backfill(conn, seed) -> None:
    """Verify score_exercise works when rows come through backfill_weekly_e1rm."""
    today = date.today()
    this_week = _monday(today)

    ex = "Overhead Press (Barbell)"
    # Seed 4 workouts on Mondays in PAST weeks (not this week).
    weights = [50.0, 52.5, 55.0, 57.5]
    for i, w in enumerate(weights):
        day = this_week - timedelta(weeks=len(weights) - i)
        seed.workout(day, ex, [(w, 8)])

    backfill_weekly_e1rm(conn)
    result = score_exercise(conn, ex)
    assert result is not None
    assert result.perf_score >= 4
