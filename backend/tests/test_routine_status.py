from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from shc.ai.workout_planner import routine_status


def _session(conn, started_at: datetime) -> str:
    wid = f"hevy_{started_at.isoformat()}"
    conn.execute(
        "INSERT INTO workouts (id, source, started_at, ended_at, kind, content_hash) "
        "VALUES (?, 'hevy', ?, ?, 'strength', ?)",
        [wid, started_at, started_at + timedelta(minutes=45), wid],
    )
    conn.execute(
        "INSERT INTO workout_sets "
        "(id, workout_id, exercise, set_idx, reps, weight_kg, rpe, is_warmup, content_hash) "
        "VALUES (?, ?, 'Exercise 0', 0, 10, 60.0, 7, FALSE, ?)",
        [wid, wid, wid],
    )
    return wid


def test_plan_waits_for_todays_recovery_then_comes_due(conn, seed):
    today = date.today()
    seed.recovery(today - timedelta(days=1), score=70)
    held = routine_status(conn)
    assert not held["plan_due"]
    assert "recovery" in held["plan_hold"]

    seed.recovery(today, score=70)
    assert routine_status(conn)["plan_due"]

    conn.execute(
        "INSERT INTO workout_plans (date, plan_json, source, created_at) VALUES (?, ?, 'test', ?)",
        [today, json.dumps({"blocks": []}), datetime.now()],
    )
    assert not routine_status(conn)["plan_due"]


def test_after_training_grade_is_due_and_tomorrows_plan_is_held(conn, seed):
    today = date.today()
    seed.recovery(today, score=70)
    wid = _session(conn, datetime.combine(today, datetime.min.time()) + timedelta(hours=7))

    status = routine_status(conn)
    assert status["grade_due"]
    assert status["workout_id"] == wid
    assert status["planning_date"] == (today + timedelta(days=1)).isoformat()
    assert not status["plan_due"]

    conn.execute(
        "INSERT INTO workout_retrospectives (workout_id, summary) VALUES (?, 'done')", [wid]
    )
    assert not routine_status(conn)["grade_due"]


def test_stale_ungraded_session_is_not_backfilled(conn):
    _session(conn, datetime.now() - timedelta(days=3))
    assert not routine_status(conn)["grade_due"]
