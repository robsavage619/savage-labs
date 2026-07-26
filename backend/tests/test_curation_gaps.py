"""alias_audit.curation_gap_report — logged volume the selector cannot see.

The inverse of test_alias_audit: not "a curated name with no history" but "real
training the engine is blind to". Lives in its own file because test_alias_audit
shadows conftest's `conn` with a minimal stub that has no workouts table.
"""

from __future__ import annotations

from datetime import date


def test_curation_gap_report_surfaces_high_volume_invisible_movements(conn, seed) -> None:
    """The report exists because nothing told Rob a 1,541-set staple was invisible
    to selection. A logged movement with no exercise_science row must show up,
    ranked by volume, and a curated one must not."""
    from shc.training.alias_audit import curation_gap_report

    conn.execute(
        "INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, citation) "
        "VALUES ('Curated Move', 'traps', 'primary', 1.0, 'note.md')"
    )
    conn.execute(
        "INSERT INTO exercise_muscle (exercise_name, muscle, role, credit) "
        "VALUES ('Invisible Move', 'traps', 'primary', 1.0)"
    )
    seed.workout(date.today(), "Invisible Move", [(20.0, 10)] * 12)
    seed.workout(date.today(), "Curated Move", [(20.0, 10)] * 12)

    gaps = {g["exercise"]: g for g in curation_gap_report(conn, min_sets=10)}
    assert "Invisible Move" in gaps, "a movement with no science row must surface"
    assert gaps["Invisible Move"]["verdict"] == "mapped_uncurated"
    assert gaps["Invisible Move"]["muscle"] == "traps"
    assert "Curated Move" not in gaps, "a curated movement is not a gap"


def test_curation_gap_report_separates_unmapped_from_uncurated(conn, seed) -> None:
    """The two verdicts need different fixes — a curation migration vs the muscle
    map — so collapsing them would send the reader to the wrong repair."""
    from shc.training.alias_audit import curation_gap_report

    seed.workout(date.today(), "Totally Unknown Move", [(20.0, 10)] * 12)
    gaps = {g["exercise"]: g for g in curation_gap_report(conn, min_sets=10)}
    assert gaps["Totally Unknown Move"]["verdict"] == "unmapped"
    assert gaps["Totally Unknown Move"]["muscle"] is None
