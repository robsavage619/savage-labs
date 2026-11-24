"""Invariant 26: abduction work is not glute-max work.

Hip abduction reaches the gluteus medius; hip thrust, squats and hinges reach the
gluteus maximus. The engine has one `glutes` muscle, so abduction used to satisfy
the glutes direct-set counters as fully as a hip thrust. These tests pin the
split: abduction stays primary credit (menus, ceilings, "trained at all") but is
not a DIRECT glutes set for the budget and the floor.
"""

from __future__ import annotations

import pathlib
from datetime import date, datetime

from shc.training.mesocycle import direct_sets_by_week, weekly_budget_block
from shc.training.volume import weekly_muscle_volume

MONDAY = date(2026, 11, 2)
ABDUCTORS = ("Machine Hip Abductor", "Machine Thigh Abductor", "Mini Loop Band Fire Hydrant")
MIGRATION = (
    pathlib.Path(__file__).parents[1] / "src/shc/db/migrations/0122_glute_abductor_head_region.sql"
)


def _seed_rows(conn) -> None:
    for name in (*ABDUCTORS, "Test Hip Thrust"):
        conn.execute(
            "INSERT INTO exercise_muscle (exercise_name, muscle, role) "
            "VALUES (?, 'glutes', 'primary') ON CONFLICT DO NOTHING",
            [name],
        )
    conn.execute(
        "UPDATE exercise_muscle SET region = NULL WHERE exercise_name IN (?, ?, ?)",
        list(ABDUCTORS),
    )
    conn.execute(MIGRATION.read_text())


def _log(conn, exercise: str, sets: int, wid: str) -> None:
    conn.execute(
        "INSERT INTO workouts (id, source, started_at, kind, content_hash) "
        "VALUES (?, 'hevy', ?, 'strength', ?)",
        [wid, datetime(2026, 11, 3), wid],
    )
    for i in range(sets):
        conn.execute(
            "INSERT INTO workout_sets (id, workout_id, set_idx, exercise, weight_kg, reps, "
            "is_warmup, content_hash) VALUES (?, ?, ?, ?, 50, 12, FALSE, ?)",
            [f"{wid}{i}", wid, i, exercise, f"{wid}c{i}"],
        )


def _direct_glutes(conn) -> float:
    return direct_sets_by_week(conn, MONDAY).get(("glutes", MONDAY), 0.0)


def test_migration_tags_abductors_and_changes_nothing_else(conn) -> None:
    _seed_rows(conn)
    before = conn.execute(
        "SELECT exercise_name, muscle, role, credit, citation FROM exercise_muscle "
        "WHERE exercise_name NOT IN (?, ?, ?) ORDER BY 1, 2",
        list(ABDUCTORS),
    ).fetchall()
    conn.execute(MIGRATION.read_text())
    after = conn.execute(
        "SELECT exercise_name, muscle, role, credit, citation FROM exercise_muscle "
        "WHERE exercise_name NOT IN (?, ?, ?) ORDER BY 1, 2",
        list(ABDUCTORS),
    ).fetchall()
    assert before == after
    rows = conn.execute(
        "SELECT region, role, credit FROM exercise_muscle WHERE exercise_name IN (?, ?, ?)",
        list(ABDUCTORS),
    ).fetchall()
    assert rows and all(r == ("gluteus_medius", "primary", 1.0) for r in rows)


def test_abduction_only_week_owes_glute_max_work(conn) -> None:
    _seed_rows(conn)
    _log(conn, "Machine Hip Abductor", 8, "wa")
    assert _direct_glutes(conn) == 0.0
    assert "- glutes: 0/6 done, 6 left" in weekly_budget_block(conn, MONDAY)
    # Still primary credit: the muscle is trained at all (invariants 10/23).
    assert weekly_muscle_volume(conn, MONDAY)["glutes"] == 8.0


def test_week_with_hip_thrust_meets_the_budget(conn) -> None:
    _seed_rows(conn)
    _log(conn, "Machine Hip Abductor", 8, "wa")
    _log(conn, "Test Hip Thrust", 6, "wt")
    assert _direct_glutes(conn) == 6.0
    assert "- glutes: 6/6 done, 0 left" in weekly_budget_block(conn, MONDAY)
