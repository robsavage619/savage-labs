from __future__ import annotations

# Regression suite for live plan→session execution detection.
#
# The 2026-07-25 defect: the plan card read path had no notion of "already
# trained". Adherence linking only ran in the nightly scheduler job, so a session
# completed at 09:41 left the 09:11 plan rendering as *Today's Plan* all evening —
# with prescriptions set BEFORE the session, i.e. lighter than what was actually
# lifted (Incline Chest Press prescribed 205 lb against a logged 220×10).
# Following the card would have deloaded him for no reason.
import json
import uuid
from datetime import date, datetime, timedelta

import duckdb
import pytest

from shc.ai.workout_planner import plan_execution_status

PLAN_DAY = date(2026, 7, 25)
PLAN_CREATED = datetime(2026, 7, 25, 9, 11, 11)


def _add_plan(
    conn: duckdb.DuckDBPyConnection,
    day: date,
    *,
    created_at: datetime,
    sets_per_exercise: int = 3,
    exercises: int = 2,
) -> None:
    plan = {
        "blocks": [
            {
                "label": "Primary",
                "exercises": [
                    {"name": f"Exercise {i}", "sets": sets_per_exercise, "reps": "8"}
                    for i in range(exercises)
                ],
            }
        ]
    }
    conn.execute(
        "INSERT INTO workout_plans (date, plan_json, source, created_at) VALUES (?, ?, ?, ?)",
        [day, json.dumps(plan), "test", created_at],
    )


def _add_session(
    conn: duckdb.DuckDBPyConnection,
    started_at: datetime,
    sets: list[tuple[str, float | None]],
    *,
    source: str = "hevy",
    is_warmup: bool = False,
    ended_at: datetime | None = None,
) -> str:
    """Insert one workout with ``(exercise, rpe)`` sets. Returns its id."""
    wid = f"{source}_{uuid.uuid4()}"
    conn.execute(
        "INSERT INTO workouts (id, source, started_at, ended_at, kind, content_hash) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [wid, source, started_at, ended_at or started_at + timedelta(minutes=46), "strength", wid],
    )
    for idx, (exercise, rpe) in enumerate(sets):
        sid = str(uuid.uuid4())
        conn.execute(
            """
            INSERT INTO workout_sets
                (id, workout_id, exercise, set_idx, reps, weight_kg, rpe, is_warmup, content_hash)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [sid, wid, exercise, idx, 10, 60.0, rpe, is_warmup, sid],
        )
    return wid


# ── the regression ───────────────────────────────────────────────────────────


def test_session_after_plan_creation_marks_the_plan_executed(conn):
    """The live 2026-07-25 case: 09:11 plan, 09:41 session, checked the same evening."""
    _add_plan(conn, PLAN_DAY, created_at=PLAN_CREATED, sets_per_exercise=3, exercises=6)
    wid = _add_session(
        conn,
        datetime(2026, 7, 25, 9, 41, 20),
        [("Hammerstrength Incline Chest Press", 8.0)] * 4 + [("Lateral Raise (Dumbbell)", 8.0)] * 3,
        ended_at=datetime(2026, 7, 25, 10, 27, 53),
    )

    status = plan_execution_status(conn, PLAN_DAY.isoformat())

    assert status is not None
    assert status["executed"] is True
    assert status["workout_id"] == wid
    assert status["sets_done"] == 7
    assert status["prescribed_sets"] == 18
    assert status["completion_pct"] == pytest.approx(38.9)
    assert status["avg_rpe"] == 8.0
    assert status["exercises"] == [
        "Hammerstrength Incline Chest Press",
        "Lateral Raise (Dumbbell)",
    ]
    assert status["started_at"].startswith("2026-07-25T09:41:20")
    assert status["ended_at"].startswith("2026-07-25T10:27:53")
    assert status["plan_created_at"].startswith("2026-07-25T09:11:11")


def test_plan_regenerated_after_the_session_is_not_executed(conn):
    """A plan created after the session is the NEXT prescription, not a stale one."""
    _add_session(conn, datetime(2026, 7, 25, 9, 41, 20), [("Face Pull", 8.0)] * 4)
    _add_plan(conn, PLAN_DAY, created_at=datetime(2026, 7, 25, 18, 30, 0))

    status = plan_execution_status(conn, PLAN_DAY.isoformat())

    assert status is not None
    assert status["executed"] is False
    assert status["workout_id"] is None
    assert status["sets_done"] == 0


def test_whoop_shadow_row_alone_does_not_mark_a_plan_executed(conn):
    """WHOOP mirrors every Hevy lift as its own zero-set workout — it proves nothing."""
    _add_plan(conn, PLAN_DAY, created_at=PLAN_CREATED)
    _add_session(conn, datetime(2026, 7, 25, 9, 41, 20), [], source="whoop")

    status = plan_execution_status(conn, PLAN_DAY.isoformat())

    assert status["executed"] is False


def test_hevy_row_wins_over_the_whoop_shadow(conn):
    """Selection is by working sets, not start time — the shadow starts a second later."""
    _add_plan(conn, PLAN_DAY, created_at=PLAN_CREATED)
    hevy = _add_session(
        conn, datetime(2026, 7, 25, 9, 41, 20), [("Hammer Curl (Dumbbell)", 8.0)] * 3
    )
    _add_session(conn, datetime(2026, 7, 25, 9, 41, 21), [], source="whoop")

    status = plan_execution_status(conn, PLAN_DAY.isoformat())

    assert status["executed"] is True
    assert status["workout_id"] == hevy
    assert status["sets_done"] == 3


def test_warmup_only_session_is_not_execution(conn):
    _add_plan(conn, PLAN_DAY, created_at=PLAN_CREATED)
    _add_session(conn, datetime(2026, 7, 25, 9, 41, 20), [("Face Pull", None)] * 3, is_warmup=True)

    status = plan_execution_status(conn, PLAN_DAY.isoformat())

    assert status["executed"] is False
    assert status["sets_done"] == 0


def test_session_on_another_day_never_executes_this_plan(conn):
    _add_plan(conn, PLAN_DAY, created_at=PLAN_CREATED)
    _add_session(conn, datetime(2026, 7, 26, 9, 41, 20), [("Face Pull", 8.0)] * 4)

    status = plan_execution_status(conn, PLAN_DAY.isoformat())

    assert status["executed"] is False


def test_unexecuted_plan_still_reports_its_creation_timestamp(conn):
    """The card stamps the readiness narrative with this — it sits next to a live gauge."""
    _add_plan(conn, PLAN_DAY, created_at=PLAN_CREATED)

    status = plan_execution_status(conn, PLAN_DAY.isoformat())

    assert status["executed"] is False
    assert status["plan_created_at"].startswith("2026-07-25T09:11:11")
    assert status["prescribed_sets"] == 6


def test_no_stored_plan_returns_none(conn):
    assert plan_execution_status(conn, PLAN_DAY.isoformat()) is None
