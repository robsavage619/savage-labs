from __future__ import annotations

import asyncio
from datetime import date

from shc.ai.workout_planner import e1rm_by_exercise
from shc.ingest.hevy import _map_workout_to_db, _upsert_workout
from shc.training.session_notes import classify, context_lines

TODAY = date(2026, 11, 25)


def _workout(wid: str, day: str, kg: float, *, description: str = "", ex_note: str | None = None):
    return {
        "id": wid,
        "title": "Savage Labs WOD — x",
        "description": description,
        "start_time": f"{day}T13:00:00+00:00",
        "end_time": f"{day}T14:00:00+00:00",
        "updated_at": "t1",
        "exercises": [
            {
                "index": 0,
                "title": "Barbell Row",
                "notes": ex_note,
                "exercise_template_id": "T1",
                "superset_id": None,
                "sets": [{"index": 0, "type": "normal", "weight_kg": kg, "reps": 8, "rpe": 8}],
            }
        ],
    }


def _sync(conn, w: dict) -> None:
    row, sets, _ = _map_workout_to_db(w)
    asyncio.run(_upsert_workout(conn, row, sets))


def test_classify_tags_and_ignores_negations() -> None:
    assert classify("No wraps") == {"grip"}
    assert classify("forgot my wraps for the last set") == {"grip"}
    assert classify("Felt sick, super sluggish") == {"sick", "low_energy"}
    assert classify("no pain, felt great") == set()
    assert classify("Savage Labs WOD") == set()


def test_flagged_sessions_leave_e1rm_but_clean_ones_stay(conn) -> None:
    _sync(conn, _workout("a", "2026-11-10", 100.0))
    _sync(conn, _workout("b", "2026-11-17", 120.0, ex_note="No wraps"))
    _sync(conn, _workout("c", "2026-11-20", 130.0, description="I was feeling sick"))
    heavy = 100.0 * (1 + 10 / 30)  # 8 reps at RPE 8 -> 10 effective reps
    assert abs(e1rm_by_exercise(conn, TODAY)["Barbell Row"] - heavy) < 0.5


def test_notes_reach_planner_context_but_auto_titles_do_not(conn) -> None:
    _sync(conn, _workout("b", "2026-11-17", 120.0, ex_note="No wraps"))
    _sync(conn, _workout("c", "2026-11-20", 130.0, description="I was feeling sick"))
    text = "\n".join(context_lines(conn, days=3650))
    assert "[sick]" in text and "[grip]" in text
    assert "Savage Labs WOD" not in text
