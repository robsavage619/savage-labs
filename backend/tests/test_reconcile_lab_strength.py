"""The reconcile check that runs the lab's stored strength SQL against the engine e1RM."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from shc.training import reconcile
from shc.training.reconcile import (
    LAB_STRENGTH_FEATURE,
    check_lab_strength_outcome_matches_engine_e1rm,
)

# The approved feature SQL as stored today (engine literals only, no personal values).
FEATURE_SQL = """WITH d AS (
  SELECT ws.canon_exercise AS ex, ws.day_d AS day,
    MAX((CASE WHEN (lower(trim(ws.exercise)) = 'romanian deadlift (dumbbell)' AND ws.day_d < DATE '2026-07-23') OR (lower(trim(ws.exercise)) = 'seated dumbbell curl' AND ws.day_d < DATE '2026-09-24') THEN ws.weight_kg / 2.0 ELSE ws.weight_kg END)
      * (1 + LEAST(ws.reps + (CASE WHEN ws.rpe IS NULL THEN 0 ELSE GREATEST(LEAST(10 - ws.rpe, 3), 0) END), 12) / 30.0)) AS e
  FROM workout_sets_dedup ws
  WHERE ws.source = 'hevy' AND ws.weight_kg > 0 AND ws.reps > 0 AND NOT COALESCE(ws.is_warmup, FALSE) AND ws.day_d <= current_date
  GROUP BY 1, 2
), b AS (
  SELECT ex, day, e,
    AVG(e) OVER (PARTITION BY ex ORDER BY day RANGE BETWEEN INTERVAL 28 DAY PRECEDING AND INTERVAL 1 DAY PRECEDING) AS base,
    COUNT(e) OVER (PARTITION BY ex ORDER BY day RANGE BETWEEN INTERVAL 28 DAY PRECEDING AND INTERVAL 1 DAY PRECEDING) AS nb
  FROM d
)
SELECT day, AVG(100 * (e / base - 1)) AS value
FROM b WHERE nb >= 1 AND abs(e / base - 1) <= 0.35
GROUP BY day HAVING COUNT(*) >= 2
ORDER BY day"""

NO_RIR = FEATURE_SQL.replace(
    "ws.reps + (CASE WHEN ws.rpe IS NULL THEN 0 ELSE GREATEST(LEAST(10 - ws.rpe, 3), 0) END)",
    "ws.reps",
)
NO_CURL_HALVING = FEATURE_SQL.replace(
    " OR (lower(trim(ws.exercise)) = 'seated dumbbell curl' AND ws.day_d < DATE '2026-09-24')", ""
)

TODAY = date(2026, 10, 20)


def _store(conn, sql: str, status: str = "approved") -> None:
    conn.execute(
        "INSERT INTO research_custom_features (name, owner, description, unit, timing, sql, status, goal) "
        "VALUES (?, 'recovery', 'synthetic', '%', 'day', ?, ?, 'muscle')",
        [LAB_STRENGTH_FEATURE, sql, status],
    )


@pytest.fixture
def history(seed) -> None:
    """Six synthetic sessions straddling the Seated Dumbbell Curl switch date."""
    start = date(2026, 9, 8)
    for i in range(6):
        day = start + timedelta(days=5 * i)
        seed.workout(day, "Bench Press (Barbell)", [(80.0 + i, 8), (80.0 + i, 7)], rpe=8.0)
        seed.workout(day, "Leg Extension (Machine)", [(60.0 + i, 10)], rpe=None)
        curl = 40.0 + i if day < date(2026, 9, 24) else 20.0 + i / 2
        seed.workout(day, "Seated Dumbbell Curl", [(curl, 10)], rpe=7.0)


def test_correct_stored_sql_passes(conn, history) -> None:
    _store(conn, FEATURE_SQL)
    f = check_lab_strength_outcome_matches_engine_e1rm(conn, today=TODAY)
    assert f.ok, (f.detail, f.rows)
    assert "per-lift-day e1RM + final series" in f.detail
    assert "5 expected session days" in f.detail


@pytest.mark.parametrize("drifted", [NO_RIR, NO_CURL_HALVING], ids=["no-rir", "no-curl-halving"])
def test_drifted_stored_sql_fails(conn, history, drifted: str) -> None:
    assert drifted != FEATURE_SQL
    _store(conn, drifted)
    f = check_lab_strength_outcome_matches_engine_e1rm(conn, today=TODAY)
    assert not f.ok
    assert f.rows and "disagree" in f.detail


def test_missing_feature_is_reported_not_passed(conn) -> None:
    f = check_lab_strength_outcome_matches_engine_e1rm(conn, today=TODAY)
    assert not f.ok and "missing" in f.detail


def test_unapproved_feature_is_reported_not_passed(conn, history) -> None:
    _store(conn, FEATURE_SQL, status="proposed")
    f = check_lab_strength_outcome_matches_engine_e1rm(conn, today=TODAY)
    assert not f.ok and "not approved" in f.detail


def test_stored_sql_runs_under_the_read_only_guard(conn, history) -> None:
    before = conn.execute("SELECT count(*) FROM workout_sets_dedup").fetchone()
    _store(conn, "DELETE FROM workout_sets_dedup")
    f = check_lab_strength_outcome_matches_engine_e1rm(conn, today=TODAY)
    assert not f.ok and "read-only guard" in f.detail
    assert conn.execute("SELECT count(*) FROM workout_sets_dedup").fetchone() == before


def test_registered_and_independent_of_the_research_module(conn) -> None:
    import inspect

    assert check_lab_strength_outcome_matches_engine_e1rm in reconcile.ALL_CHECKS
    src = inspect.getsource(check_lab_strength_outcome_matches_engine_e1rm)
    assert "shc.research" not in src
    names = [f.check for f in reconcile.run_all(conn)]
    assert "lab strength outcome vs engine e1RM" in names
