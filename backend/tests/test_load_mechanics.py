from __future__ import annotations

import pytest

from shc.training.load_mechanics import (
    LoadType,
    classify_load,
    is_per_hand,
    load_unit_label,
    per_hand_kg,
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


def test_per_hand_leaves_bilateral_lifts_alone() -> None:
    assert per_hand_kg("Bench Press (Barbell)", 100.0) == 100.0
    assert per_hand_kg("Single Arm Dumbbell Row", 40.0) == 40.0
    assert per_hand_kg("Tricep Pushdown (Cable)", 45.0) == 45.0


def test_unit_label() -> None:
    assert is_per_hand("Hammer Curl (Dumbbell)") is True
    assert load_unit_label("Hammer Curl (Dumbbell)") == "each hand"
    assert load_unit_label("Bench Press (Barbell)") == ""
