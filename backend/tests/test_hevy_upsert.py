from __future__ import annotations

import asyncio

from shc.ingest.hevy import _map_workout_to_db, _upsert_workout


def _workout(weight_kg: float, updated_at: str) -> dict:
    return {
        "id": "w1",
        "title": "Upper",
        "description": "",
        "start_time": "2026-10-14T13:00:00+00:00",
        "end_time": "2026-10-14T14:00:00+00:00",
        "updated_at": updated_at,
        "exercises": [
            {
                "index": 0,
                "title": "Incline Bench Press (Dumbbell)",
                "notes": None,
                "exercise_template_id": "T1",
                "superset_id": None,
                "sets": [
                    {"index": 0, "type": "normal", "weight_kg": weight_kg, "reps": 8, "rpe": 8}
                ],
            }
        ],
    }


def _sync(conn, w: dict) -> None:
    row, sets, _ = _map_workout_to_db(w)
    asyncio.run(_upsert_workout(conn, row, sets))


def test_correcting_a_quarantined_set_at_the_source_unquarantines_it(conn) -> None:
    _sync(conn, _workout(70.0, "t1"))  # ~154 lb/hand: over the per-hand max
    assert conn.execute("SELECT is_warmup FROM workout_sets").fetchone()[0] is True

    _sync(conn, _workout(35.0, "t2"))  # fixed in Hevy
    assert conn.execute("SELECT is_warmup FROM workout_sets").fetchone()[0] is False
