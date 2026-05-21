from __future__ import annotations

from datetime import date


def _dedup_rows(conn, exercise: str | None = None):
    sql = "SELECT exercise, source, weight_kg FROM workout_sets_dedup"
    if exercise:
        sql += f" WHERE canon_exercise = '{exercise}'"
    return conn.execute(sql).fetchall()


def test_hevy_wins_over_fitbod_same_day_same_exercise(conn, seed) -> None:
    """When both sources logged the same lift on the same day, the dedup view
    keeps only the hevy rows (source priority)."""
    day = date(2026, 5, 20)
    seed.workout(day, "Bench Press (Barbell)", [(100, 5)], source="hevy")
    seed.workout(day, "Bench Press (Barbell)", [(90, 5)], source="fitbod")
    rows = _dedup_rows(conn, "Bench Press")
    assert {r[1] for r in rows} == {"hevy"}
    assert all(r[2] == 100 for r in rows)


def test_fitbod_kept_when_no_hevy_that_day(conn, seed) -> None:
    day = date(2026, 5, 20)
    seed.workout(day, "Squat (Barbell)", [(140, 5)], source="fitbod")
    rows = _dedup_rows(conn, "Squat")
    assert {r[1] for r in rows} == {"fitbod"}


def test_different_days_both_sources_kept(conn, seed) -> None:
    seed.workout(date(2026, 5, 19), "Deadlift (Barbell)", [(180, 3)], source="fitbod")
    seed.workout(date(2026, 5, 20), "Deadlift (Barbell)", [(185, 3)], source="hevy")
    rows = _dedup_rows(conn, "Deadlift")
    assert {r[1] for r in rows} == {"fitbod", "hevy"}


def test_canonical_name_strips_equipment_suffix(conn, seed) -> None:
    # Same canonical lift ("Bench Press"), two equipment variants, one day, two
    # sources → hevy variant survives, fitbod variant dropped by source priority.
    day = date(2026, 5, 20)
    seed.workout(day, "Bench Press (Barbell)", [(100, 5)], source="hevy")
    seed.workout(day, "Bench Press (Dumbbell)", [(40, 5)], source="fitbod")
    rows = _dedup_rows(conn, "Bench Press")
    assert {r[1] for r in rows} == {"hevy"}
    assert {r[0] for r in rows} == {"Bench Press (Barbell)"}
