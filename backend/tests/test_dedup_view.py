from __future__ import annotations

from datetime import date


def _dedup_rows(conn, canon: str | None = None):
    """Rows from the dedup view, optionally narrowed to one canonical movement.

    ``canon`` is the NORMALIZED key (lowercased, punctuation dropped, tokens
    singularized and sorted) — e.g. "Bench Press (Barbell)" keys as
    ``"bench pres"``. Migration 0102 made the key normalized rather than
    human-readable so that twins like "T-Bar Row"/"T Bar Row" collapse; every
    production consumer groups by it and displays ``exercise`` instead.
    """
    sql = "SELECT exercise, source, weight_kg FROM workout_sets_dedup"
    if canon:
        sql += f" WHERE canon_exercise = '{canon}'"
    return conn.execute(sql).fetchall()


def test_hevy_wins_over_fitbod_same_day_same_exercise(conn, seed) -> None:
    """When both sources logged the same lift on the same day, the dedup view
    keeps only the hevy rows (source priority)."""
    day = date(2026, 5, 20)
    seed.workout(day, "Bench Press (Barbell)", [(100, 5)], source="hevy")
    seed.workout(day, "Bench Press (Barbell)", [(90, 5)], source="fitbod")
    rows = _dedup_rows(conn, "bench pres")
    assert {r[1] for r in rows} == {"hevy"}
    assert all(r[2] == 100 for r in rows)


def test_fitbod_kept_when_no_hevy_that_day(conn, seed) -> None:
    day = date(2026, 5, 20)
    seed.workout(day, "Squat (Barbell)", [(140, 5)], source="fitbod")
    rows = _dedup_rows(conn, "squat")
    assert {r[1] for r in rows} == {"fitbod"}


def test_different_days_both_sources_kept(conn, seed) -> None:
    seed.workout(date(2026, 5, 19), "Deadlift (Barbell)", [(180, 3)], source="fitbod")
    seed.workout(date(2026, 5, 20), "Deadlift (Barbell)", [(185, 3)], source="hevy")
    rows = _dedup_rows(conn, "deadlift")
    assert {r[1] for r in rows} == {"fitbod", "hevy"}


def test_canonical_name_strips_equipment_suffix(conn, seed) -> None:
    # Same canonical lift ("Bench Press"), two equipment variants, one day, two
    # sources → hevy variant survives, fitbod variant dropped by source priority.
    day = date(2026, 5, 20)
    seed.workout(day, "Bench Press (Barbell)", [(100, 5)], source="hevy")
    seed.workout(day, "Bench Press (Dumbbell)", [(40, 5)], source="fitbod")
    rows = _dedup_rows(conn, "bench pres")
    assert {r[1] for r in rows} == {"hevy"}
    assert {r[0] for r in rows} == {"Bench Press (Barbell)"}


# ── Migration 0102: movement identity ───────────────────────────────────────
#
# The Fitbod history was imported into Hevy, so the same physical session exists
# twice under two names. The old canonical key only stripped a trailing
# parenthetical and caught 1 of 17 real twin pairs.


def test_word_order_and_plural_collapse(conn, seed) -> None:
    """"Hammer Curls" and "Hammer Curl (Dumbbell)" both key as "curl hammer".

    Caught by the normalizer alone: dropping the trailing parenthetical leaves
    the same token bag once each token is singularized and the bag is sorted.
    """
    day = date(2026, 5, 20)
    seed.workout(day, "Hammer Curl (Dumbbell)", [(20, 10)], source="hevy")
    seed.workout(day, "Hammer Curls", [(20, 10)], source="fitbod")
    rows = _dedup_rows(conn, "curl hammer")
    assert {r[1] for r in rows} == {"hevy"}, "word-order twin was not deduplicated"


def test_twin_map_carries_equipment_prefix_renames(conn, seed) -> None:
    """"Dumbbell Shrug" vs "Shrug (Dumbbell)" is NOT a normalizer win.

    Stripping the trailing parenthetical removes the equipment word from one
    side only ("shrug") but not the other ("dumbbell shrug"), so the two keys
    differ. The twin map is what pairs them — which is precisely why both
    mechanisms are needed.
    """
    day = date(2026, 5, 20)
    seed.workout(day, "Shrug (Dumbbell)", [(30, 10)], source="hevy")
    seed.workout(day, "Dumbbell Shrug", [(30, 10)], source="fitbod")
    rows = _dedup_rows(conn, "shrug")
    assert {r[1] for r in rows} == {"hevy"}
    assert {r[0] for r in rows} == {"Shrug (Dumbbell)"}


def test_hyphen_variants_collapse(conn, seed) -> None:
    day = date(2026, 5, 20)
    seed.workout(day, "T Bar Row", [(60, 8)], source="hevy")
    seed.workout(day, "T-Bar Row", [(60, 8)], source="fitbod")
    assert {r[1] for r in _dedup_rows(conn, "bar row t")} == {"hevy"}


def test_plural_variants_collapse(conn, seed) -> None:
    day = date(2026, 5, 20)
    seed.workout(day, "Air Squat", [(0, 20)], source="hevy")
    seed.workout(day, "Air Squats", [(0, 20)], source="fitbod")
    assert {r[1] for r in _dedup_rows(conn, "air squat")} == {"hevy"}


def test_twin_table_collapses_word_choice_renames(conn, seed) -> None:
    """No string normalizer can reach these — they come from the evidence table.

    "Low Cable Chest Fly" (Fitbod) and "Low Cable Fly Crossovers" (Hevy) share
    no normalizable form; `exercise_source_twin` carries the pairing, which was
    derived from identical same-day set sequences rather than name similarity.
    """
    day = date(2026, 5, 20)
    seed.workout(day, "Low Cable Fly Crossovers", [(25, 12)], source="hevy")
    seed.workout(day, "Low Cable Chest Fly", [(25, 12)], source="fitbod")
    rows = conn.execute(
        "SELECT exercise, source FROM workout_sets_dedup WHERE lower(exercise) LIKE '%cable%fly%'"
    ).fetchall()
    assert {r[1] for r in rows} == {"hevy"}
    assert {r[0] for r in rows} == {"Low Cable Fly Crossovers"}


def test_twin_map_only_redirects_legacy_names(conn) -> None:
    """Every twin maps a legacy name onto a DIFFERENT current name, no cycles.

    A self-map is a no-op row; a name appearing on both sides would make the
    canonical key depend on join order.
    """
    rows = conn.execute(
        "SELECT legacy_name, current_name FROM exercise_source_twin"
    ).fetchall()
    assert rows, "twin map is empty — migration 0102 did not load"
    legacy = {r[0] for r in rows}
    current = {r[1] for r in rows}
    assert not any(r[0] == r[1] for r in rows), "self-mapping twin row"
    assert not (legacy & current), f"name on both sides of the map: {legacy & current}"


def test_same_source_collision_loses_nothing(conn, seed) -> None:
    """Two DIFFERENT lifts that token-sort together must both survive.

    "Cable Twist (Down to up)" and "Cable Twist (Up to down)" normalize to the
    same key. The view elects a SOURCE, not a name, so when the colliding rows
    share a source both are kept — which is what makes a stronger key safe.
    """
    day = date(2026, 5, 20)
    seed.workout(day, "Cable Twist (Down to up)", [(20, 12)], source="hevy")
    seed.workout(day, "Cable Twist (Up to down)", [(20, 12)], source="hevy")
    rows = _dedup_rows(conn, "cable twist")
    assert {r[0] for r in rows} == {"Cable Twist (Down to up)", "Cable Twist (Up to down)"}


def test_hevy_only_day_is_untouched_by_dedup(conn, seed) -> None:
    """The live windows carry no Fitbod rows, so dedup must be a no-op there."""
    day = date(2026, 9, 15)
    seed.workout(day, "Hammer Curl (Dumbbell)", [(20, 10), (20, 9)], source="hevy")
    seed.workout(day, "Front Raise (Dumbbell)", [(12, 12)], source="hevy")
    rows = conn.execute(
        "SELECT COUNT(*) FROM workout_sets_dedup WHERE day_d = ? AND is_warmup = FALSE",
        [day],
    ).fetchone()[0]
    assert rows == 3
