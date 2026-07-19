from __future__ import annotations

import pytest

from shc.training.load_mechanics import (
    MAX_PER_HAND_LB,
    LoadType,
    classify_load,
    exceeds_per_hand_max,
    is_per_hand,
    load_unit_label,
    per_hand_kg,
    per_hand_sql,
)


@pytest.mark.parametrize(
    "name,expected",
    [
        ("Hammer Curl (Dumbbell)", LoadType.DUMBBELL_PAIR),
        ("Dumbbell Bench Press", LoadType.DUMBBELL_PAIR),
        ("Chest Fly (Dumbbell)", LoadType.DUMBBELL_PAIR),
        ("Single Arm Dumbbell Row", LoadType.DUMBBELL_SINGLE),
        ("One Arm Dumbbell Row", LoadType.DUMBBELL_SINGLE),
        ("Concentration Curl", LoadType.DUMBBELL_SINGLE),
        ("Cable Crossover", LoadType.CABLE_PAIR),
        ("Cable Fly", LoadType.CABLE_PAIR),
        ("Single Arm Cable Bicep Curl", LoadType.CABLE_SINGLE),
        ("Cable Rope Hammer Curls", LoadType.BILATERAL),  # single-stack, both hands
        ("Hammer Curls", LoadType.DUMBBELL_PAIR),  # un-suffixed Fitbod name → DB pair
        ("Zottman Curl", LoadType.DUMBBELL_PAIR),
        ("Tricep Pushdown (Cable)", LoadType.BILATERAL),
        ("Bench Press (Barbell)", LoadType.BILATERAL),
        # Ambiguous (machine vs seated DB pair); "hammer curl" movement default
        # halves it — the safe direction, since a too-low ceiling can't prescribe
        # an unsafe load.
        ("Seated Hammer Curls", LoadType.DUMBBELL_PAIR),
        ("Leg Press", LoadType.BILATERAL),
    ],
)
def test_classify_load(name: str, expected: LoadType) -> None:
    assert classify_load(name) == expected


def test_per_hand_is_identity_hevy_logs_per_hand() -> None:
    # Hevy logs the weight of ONE dumbbell/stack, so the logged number already IS
    # the per-hand load — per_hand_kg must NOT halve it. A 20 lb lateral raise
    # (9.07 kg) stays 20 lb; halving it to 10 was the ceiling-corruption bug.
    assert per_hand_kg("Lateral Raise (Dumbbell)", 9.07) == pytest.approx(9.07)
    assert per_hand_kg("Hammer Curl (Dumbbell)", 15.9) == pytest.approx(15.9)  # ~35 lb
    assert per_hand_kg("Cable Crossover", 40.0) == pytest.approx(40.0)
    assert per_hand_kg("Cable Fly Crossovers", 45.4) == pytest.approx(45.4)  # ~100 lb


def test_per_hand_halves_verified_combined_logged_lifts() -> None:
    # RDL is the one verified exception: Rob enters the two-dumbbell TOTAL, so
    # 150 lb (68 kg) is 75 lb / 34 kg per hand. The single-leg variant is logged
    # per-hand (one bell) and must NOT halve.
    assert per_hand_kg("Romanian Deadlift (Dumbbell)", 68.0) == pytest.approx(34.0)
    assert per_hand_kg("Single Leg Romanian Deadlift (Dumbbell)", 13.6) == pytest.approx(13.6)


def test_per_hand_leaves_bilateral_lifts_alone() -> None:
    assert per_hand_kg("Bench Press (Barbell)", 100.0) == 100.0
    assert per_hand_kg("Single Arm Dumbbell Row", 40.0) == 40.0
    assert per_hand_kg("Tricep Pushdown (Cable)", 45.0) == 45.0


def test_unit_label() -> None:
    assert is_per_hand("Hammer Curl (Dumbbell)") is True
    assert load_unit_label("Hammer Curl (Dumbbell)") == "each hand"
    assert load_unit_label("Bench Press (Barbell)") == ""


# ── per-hand ceiling guard ────────────────────────────────────────────────────


def test_ceiling_flags_impossible_per_hand_loads() -> None:
    # 130 lb (59 kg) in one hand on a curl — above Rob's confirmed 105 lb max.
    assert exceeds_per_hand_max("Hammer Curl (Dumbbell)", 59.0) is True
    assert exceeds_per_hand_max("Incline Bench Press (Dumbbell)", 72.6) is True


def test_ceiling_halves_combined_logged_lifts_before_testing() -> None:
    """The regression migration 0071 shipped: RDL logs the two-dumbbell TOTAL.

    150 lb logged is 75 lb per hand — legal. Testing the raw logged value instead
    quarantined six legitimate working sets.
    """
    assert exceeds_per_hand_max("Romanian Deadlift (Dumbbell)", 68.0) is False
    # Only above 2x the ceiling does the combined-logged lift actually breach it.
    assert exceeds_per_hand_max("Romanian Deadlift (Dumbbell)", 100.0) is True


def test_ceiling_ignores_bilateral_lifts() -> None:
    # Whole-implement loads are not bounded by a per-hand number: Rob's calf
    # raise runs 495 lb and his incline press 250 lb.
    assert exceeds_per_hand_max("Standing Calf Raise (Machine)", 224.5) is False
    assert exceeds_per_hand_max("Hammerstrength Incline Chest Press", 113.4) is False
    assert exceeds_per_hand_max("Lat Pulldown - Close Grip (Cable)", 65.8) is False


def test_ceiling_tolerates_missing_weight() -> None:
    assert exceeds_per_hand_max("Hammer Curl (Dumbbell)", None) is False
    assert MAX_PER_HAND_LB == 105.0


# ── per_hand_sql parity with per_hand_kg ────────────────────────────────────
# Any SQL-side aggregation (the progression e1RM/tonnage pipeline) must halve
# exactly the same names the Python-side ceiling/e1RM path halves, or the two
# paths silently disagree on unit for the same lift.


@pytest.mark.parametrize(
    "name,logged_kg",
    [
        ("Romanian Deadlift (Dumbbell)", 68.0),  # the one _LOGGED_AS_COMBINED member
        ("romanian deadlift (dumbbell)", 68.0),  # case-insensitivity
        ("Single Leg Romanian Deadlift (Dumbbell)", 13.6),  # control: NOT combined
        ("Hammer Curl (Dumbbell)", 15.9),  # control: per-hand as logged
        ("Bench Press (Barbell)", 100.0),  # control: bilateral
    ],
)
def test_per_hand_sql_matches_per_hand_kg(conn, name: str, logged_kg: float) -> None:
    expected = per_hand_kg(name, logged_kg)
    expr = per_hand_sql("$w", "$n")
    got = conn.execute(f"SELECT {expr}", {"w": logged_kg, "n": name}).fetchone()[0]
    assert got == pytest.approx(expected)
