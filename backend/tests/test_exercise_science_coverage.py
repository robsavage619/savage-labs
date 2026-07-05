from __future__ import annotations

import pytest

# Frequently-trained movements that migration 0064 curated off the recency
# fallback. Guards against a later schema change silently dropping their
# exercise_science rows (which would send them back to blind recency selection).
_CURATED_BY_0064 = [
    ("Hammerstrength Incline Chest Press", "chest"),
    ("Hammerstrength Incline Chest Press", "front_delts"),
    ("Hammerstrength Shoulder Press", "front_delts"),
    ("Seated Dumbbell Curl", "biceps"),
    ("Hammer Curls", "biceps"),
    ("Hammer Curls", "forearms"),
    ("Triceps Rope Pushdown", "triceps"),
    ("Machine Tricep Dip", "triceps"),
    ("Overhead Triceps Extension (Cable)", "triceps"),
    ("Cable Rope Overhead Triceps Extension", "triceps"),
    ("Cable Fly Crossovers", "chest"),
    ("Low Cable Fly Crossovers", "chest"),
    ("Seated Leg Curl (Machine)", "hamstrings"),
    ("Standing Machine Calf Press", "calves"),
    ("Iso-Lateral Row (Machine)", "lats"),
]


@pytest.mark.parametrize("exercise,muscle", _CURATED_BY_0064)
def test_movement_is_science_curated(conn, exercise: str, muscle: str) -> None:
    row = conn.execute(
        "SELECT region, length_bias, rep_low, rep_high, citation, citation_url "
        "FROM exercise_science WHERE exercise_name = ? AND muscle = ?",
        [exercise, muscle],
    ).fetchone()
    assert row is not None, f"{exercise} / {muscle} lost its exercise_science row"
    region, length_bias, rep_low, rep_high, citation, citation_url = row
    assert region and length_bias
    assert 1 <= rep_low <= rep_high <= 30
    # Inherited from a vetted canonical row — the citation must be real, not blank.
    assert citation and citation_url and citation_url.startswith("http")


def test_low_cable_fly_biases_upper_chest(conn) -> None:
    # A low-to-high cable fly must inherit the UPPER-chest row, not mid-chest —
    # the mechanics-matching source choice, not a blind copy.
    region = conn.execute(
        "SELECT region FROM exercise_science "
        "WHERE exercise_name = 'Low Cable Fly Crossovers' AND muscle = 'chest'"
    ).fetchone()
    assert region[0] == "upper_chest"
