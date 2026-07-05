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


def test_per_hand_halves_two_implement_lifts() -> None:
    # 120 lb combined hammer curl → 60 lb each hand (54.4 kg → 27.2 kg).
    assert per_hand_kg("Hammer Curl (Dumbbell)", 54.4) == pytest.approx(27.2)
    assert per_hand_kg("Cable Crossover", 40.0) == pytest.approx(20.0)


def test_per_hand_leaves_single_implement_lifts_alone() -> None:
    assert per_hand_kg("Bench Press (Barbell)", 100.0) == 100.0
    assert per_hand_kg("Single Arm Dumbbell Row", 40.0) == 40.0  # already one hand
    assert per_hand_kg("Tricep Pushdown (Cable)", 45.0) == 45.0


def test_unit_label() -> None:
    assert is_per_hand("Hammer Curl (Dumbbell)") is True
    assert load_unit_label("Hammer Curl (Dumbbell)") == "each hand"
    assert load_unit_label("Bench Press (Barbell)") == ""
