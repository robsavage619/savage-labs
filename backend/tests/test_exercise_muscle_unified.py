from __future__ import annotations

"""Contract for the unified exercise_muscle table + its back-compat views (0066)."""


def test_old_tables_are_views_over_exercise_muscle(conn) -> None:
    kinds = {
        name: kind
        for name, kind in conn.execute(
            "SELECT table_name, table_type FROM information_schema.tables "
            "WHERE table_name IN ('exercise_muscle', 'exercise_muscle_map', 'exercise_science')"
        ).fetchall()
    }
    assert kinds.get("exercise_muscle") == "BASE TABLE"
    assert kinds.get("exercise_muscle_map") == "VIEW"
    assert kinds.get("exercise_science") == "VIEW"


def test_map_view_reconstructs_primary_and_secondaries(conn) -> None:
    conn.execute(
        "INSERT INTO exercise_muscle (exercise_name, muscle, role, credit) VALUES "
        "('UnifyLift', 'chest', 'primary', 1.0), "
        "('UnifyLift', 'triceps', 'secondary', 0.3), "
        "('UnifyLift', 'front_delts', 'secondary', 0.5)"
    )
    row = conn.execute(
        "SELECT primary_muscle, secondary_muscles FROM exercise_muscle_map "
        "WHERE exercise_name = 'UnifyLift'"
    ).fetchone()
    assert row[0] == "chest"
    assert set(row[1]) == {"triceps", "front_delts"}


def test_science_view_shows_only_curated_rows(conn) -> None:
    # A row with no citation is a plain crediting row → must NOT surface as science.
    conn.execute(
        "INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region) VALUES "
        "('PlainLift', 'chest', 'primary', 1.0, NULL)"
    )
    assert (
        conn.execute(
            "SELECT COUNT(*) FROM exercise_science WHERE exercise_name = 'PlainLift'"
        ).fetchone()[0]
        == 0
    )


def test_crediting_and_anatomy_share_one_row(conn) -> None:
    # The whole point: a curated movement carries role/credit AND region/citation
    # in the SAME row, so the two can never disagree again.
    row = conn.execute(
        "SELECT role, credit, region, citation FROM exercise_muscle "
        "WHERE exercise_name = 'Hammer Curl (Dumbbell)' AND muscle = 'biceps'"
    ).fetchone()
    assert row == ("primary", 1.0, "brachialis", "Schoenfeld 2015")
