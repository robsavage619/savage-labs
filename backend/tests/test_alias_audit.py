from __future__ import annotations

import duckdb
import pytest

from shc.training.alias_audit import alias_gap_report


@pytest.fixture
def conn() -> duckdb.DuckDBPyConnection:
    """Minimal in-memory schema covering only what alias_gap_report reads."""
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE exercise_science (exercise_name TEXT, muscle TEXT)")
    c.execute("CREATE TABLE exercise_alias (canonical_name TEXT, logged_name TEXT)")
    c.execute("CREATE TABLE exercise_muscle_map (exercise_name TEXT, primary_muscle TEXT)")
    c.execute(
        "CREATE TABLE workout_sets_dedup "
        "(exercise TEXT, started_at TIMESTAMP, is_warmup BOOLEAN)"
    )
    return c


def _log(c, exercise, muscle, n=10, day="2026-06-01"):
    for _ in range(n):
        c.execute(
            "INSERT INTO workout_sets_dedup VALUES (?, ?, FALSE)",
            [exercise, f"{day} 10:00:00"],
        )
    if muscle is not None:
        c.execute(
            "INSERT INTO exercise_muscle_map VALUES (?, ?)", [exercise, muscle]
        )


def test_muscle_veto_blocks_cross_muscle_false_pair(conn) -> None:
    # The known false pair: a rear_delts gap must never propose a chest fly, even
    # though "Dumbbell Fly" shares the "fly" token and the same equipment.
    conn.execute(
        "INSERT INTO exercise_science VALUES ('Rear Delt Fly (Dumbbell)', 'rear_delts')"
    )
    _log(conn, "Dumbbell Fly", "chest")
    report = alias_gap_report(conn)
    row = next(r for r in report if r["canonical_name"] == "Rear Delt Fly (Dumbbell)")
    assert all(c["logged_name"] != "Dumbbell Fly" for c in row["candidates"])
    assert row["verdict"] == "likely_untried_or_no_equipment"


def test_equipment_guard_blocks_conflicting_implement(conn) -> None:
    # "Curl (Dumbbell)" and "Cable Bicep Curl" overlap on movement tokens but name
    # conflicting equipment, so the candidate must be rejected.
    conn.execute("INSERT INTO exercise_science VALUES ('Curl (Dumbbell)', 'biceps')")
    _log(conn, "Cable Bicep Curl", "biceps")
    report = alias_gap_report(conn)
    row = next(r for r in report if r["canonical_name"] == "Curl (Dumbbell)")
    assert row["candidates"] == []


def test_finds_real_candidate_with_implied_equipment(conn) -> None:
    # "Concentration Curl (Dumbbell)" logged as "Concentration Curl" (equipment
    # omitted) is a valid alias: empty equipment is unspecified, not a conflict.
    conn.execute(
        "INSERT INTO exercise_science VALUES ('Concentration Curl (Dumbbell)', 'biceps')"
    )
    _log(conn, "Concentration Curl", "biceps", n=42, day="2026-07-01")
    report = alias_gap_report(conn)
    row = next(r for r in report if r["canonical_name"] == "Concentration Curl (Dumbbell)")
    assert row["verdict"] == "candidates_found"
    assert row["candidates"][0]["logged_name"] == "Concentration Curl"
    assert row["candidates"][0]["set_count"] == 42
    assert row["candidates"][0]["last_logged"] == "2026-07-01"


def test_exact_and_aliased_names_are_not_gaps(conn) -> None:
    conn.execute("INSERT INTO exercise_science VALUES ('Incline Curl (Dumbbell)', 'biceps')")
    conn.execute("INSERT INTO exercise_science VALUES ('Cable Curl', 'biceps')")
    conn.execute(
        "INSERT INTO exercise_alias VALUES ('Incline Curl (Dumbbell)', 'Incline Dumbbell Curl')"
    )
    _log(conn, "Incline Dumbbell Curl", "biceps")  # resolvable via alias
    _log(conn, "Cable Curl", "biceps")  # resolvable by exact name
    report = alias_gap_report(conn)
    names = {r["canonical_name"] for r in report}
    assert "Incline Curl (Dumbbell)" not in names
    assert "Cable Curl" not in names


def test_zero_candidate_gap_flagged_untried(conn) -> None:
    conn.execute("INSERT INTO exercise_science VALUES ('Nordic Curl', 'hamstrings')")
    _log(conn, "Leg Press (Machine)", "quads")
    report = alias_gap_report(conn)
    row = next(r for r in report if r["canonical_name"] == "Nordic Curl")
    assert row["verdict"] == "likely_untried_or_no_equipment"
    assert row["candidates"] == []


def test_warmup_only_exercise_does_not_resolve(conn) -> None:
    # A name logged solely as warmups has no working history → still a gap.
    conn.execute("INSERT INTO exercise_science VALUES ('Cable Curl', 'biceps')")
    conn.execute(
        "INSERT INTO workout_sets_dedup VALUES ('Cable Curl', '2026-06-01 10:00:00', TRUE)"
    )
    report = alias_gap_report(conn)
    assert any(r["canonical_name"] == "Cable Curl" for r in report)
