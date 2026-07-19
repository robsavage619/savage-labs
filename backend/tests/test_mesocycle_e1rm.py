from __future__ import annotations

from datetime import date, timedelta

from shc.ai.workout_planner import e1rm_by_exercise
from shc.training.mesocycle import (
    _score_series,
    backfill_perf_scores,
    backfill_weekly_e1rm,
    score_exercise,
)

_RDL = "Romanian Deadlift (Dumbbell)"


def test_progression_e1rm_excludes_fitbod_and_quarantined_sets(conn, seed) -> None:
    """The progression e1RM basis must match the ceiling basis: hevy-only,
    non-warmup, per-hand normalized. A logged-as-combined RDL at 68 kg (150 lb)
    is 34 kg (75 lb) per hand — the value BOTH paths must agree on, ignoring a
    Fitbod row and a quarantined (is_warmup) row at wildly different weights
    that would spike the max if either leaked through."""
    today = date.today()
    weeks = [today - timedelta(weeks=w) for w in range(4)]
    for wk in weeks:
        seed.workout(wk, _RDL, [(68.0, 8)], source="hevy", is_warmup=False)
        # Fitbod history at a much higher weight — must not contaminate the trend.
        seed.workout(wk, _RDL, [(200.0, 8)], source="fitbod", is_warmup=False)
        # A quarantined (impossible per-hand) hevy set — must not contaminate it.
        seed.workout(wk, _RDL, [(300.0, 8)], source="hevy", is_warmup=True)

    backfill_weekly_e1rm(conn)

    rows = conn.execute(
        "SELECT week_start, e1rm_kg FROM exercise_weekly_e1rm "
        "WHERE exercise = ? ORDER BY week_start",
        [_RDL],
    ).fetchall()
    assert len(rows) == 4, "expected exactly one row per hevy/non-warmup week"
    expected_e1rm = 34.0 * (1 + 8 / 30.0)  # per-hand 34kg, Epley at 8 reps
    for _week_start, e1rm_kg in rows:
        assert abs(e1rm_kg - expected_e1rm) < 0.01, (
            f"e1rm_kg {e1rm_kg} contaminated by Fitbod/quarantined rows "
            f"(expected clean per-hand {expected_e1rm})"
        )

    ceiling = e1rm_by_exercise(conn, today, days=90)
    assert _RDL in ceiling
    assert abs(ceiling[_RDL] - expected_e1rm) < 0.01, (
        "progression e1RM and ceiling e1RM disagree on the same clean basis"
    )


def test_backfill_perf_scores_matches_live_score_exercise(conn) -> None:
    """_score_series must produce identical (perf_score, trend) whether reached
    via score_exercise (live) or backfill_perf_scores (historical) — the audit
    found the backfill using a fixed 7-week window with no contamination guard
    and only the ps==3 tonnage branch, silently diverging from live scoring."""
    ex = "Bicep Curl (Barbell)"
    base = date(2025, 1, 6)  # a Monday
    weeks = [base + timedelta(weeks=w) for w in range(10)]
    # A kinked (non-linear) e1RM series — a plateau then a drop — so a window-size
    # mismatch between the two paths would actually change the fitted slope
    # (a purely linear series is invariant to a one-week window shift and would
    # mask exactly the bug this test exists to catch).
    e1rm_by_week = [100.0, 100.0, 99.0, 101.0, 100.0, 99.0, 90.0, 85.0, 80.0, 76.0]
    tonnage_by_week = [1000.0 + 50.0 * i for i in range(10)]  # steadily rising tonnage

    for i, ws in enumerate(weeks):
        conn.execute(
            "INSERT INTO exercise_weekly_e1rm "
            "(exercise, week_start, e1rm_kg, work_sets, weekly_tonnage_kg, "
            " perf_score, trend, computed_at) "
            "VALUES (?, ?, ?, 4, ?, NULL, NULL, now())",
            [ex, ws, e1rm_by_week[i], tonnage_by_week[i]],
        )

    # Score "as of" the LAST seeded week (index 9): score_exercise reads history
    # strictly BEFORE as_of, i.e. weeks[0:9] — the exact same slice
    # backfill_perf_scores uses to score row i=9 (e1rms[max(0, 9-14):9]).
    live = score_exercise(conn, ex, as_of=weeks[9])
    assert live is not None

    backfill_perf_scores(conn)
    backfilled = conn.execute(
        "SELECT perf_score, trend FROM exercise_weekly_e1rm "
        "WHERE exercise = ? AND week_start = ?",
        [ex, weeks[9].isoformat()],
    ).fetchone()
    assert backfilled is not None
    assert backfilled[0] == live.perf_score
    assert backfilled[1] == live.trend


def test_score_series_reclassifies_regressing_e1rm_with_rising_tonnage() -> None:
    """The ps<=2 tonnage-reclassify branch — present in score_exercise but
    missing from the original backfill_perf_scores — must fire through the
    shared core."""
    e1rms = [100.0 - 3.0 * i for i in range(9)]  # regressing e1RM
    tonnages = [1000.0 + 60.0 * i for i in range(9)]  # tonnage rising >=0.5%/wk
    result = _score_series(e1rms, tonnages)
    assert result is not None
    perf_score, trend = result
    assert perf_score >= 3, "regressing e1RM with rising tonnage must be rescued"
    assert trend in ("progressing", "stalled")
