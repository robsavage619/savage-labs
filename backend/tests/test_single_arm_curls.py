from __future__ import annotations

from datetime import date, timedelta

from shc.ai.workout_planner import _planned_primary_sets_by_muscle, _planned_sets_by_muscle
from shc.training.load_mechanics import exceeds_per_hand_max, per_hand_kg, set_weight
from shc.training.mesocycle import direct_sets_by_week, weekly_budget_block
from shc.training.volume import weekly_muscle_volume, weekly_muscle_volume_by_week

LEFT = "Single Arm Dumbbell Curl (Left)"
RIGHT = "Single Arm Dumbbell Curl (Right)"
MONDAY = date(2026, 11, 30)


def _arms(seed, left: int, right: int) -> None:
    seed.workout(MONDAY + timedelta(days=1), LEFT, [(10.0, 10)] * left)
    seed.workout(MONDAY + timedelta(days=2), RIGHT, [(10.0, 10)] * right)


def test_both_names_seeded_as_biceps_primary(conn) -> None:
    for name in (LEFT, RIGHT):
        rows = conn.execute(
            "SELECT muscle, role FROM exercise_muscle WHERE exercise_name = ?", [name]
        ).fetchall()
        assert ("biceps", "primary") in rows


def test_set_weight_is_half_only_for_side_tagged_names() -> None:
    assert set_weight(LEFT) == set_weight(RIGHT) == 0.5
    assert set_weight("Seated Dumbbell Curl") == 1.0
    assert set_weight("Single Arm Cable Row") == 1.0


def test_left8_right14_reads_11_direct_and_11_credited(conn, seed) -> None:
    _arms(seed, 8, 14)
    assert weekly_muscle_volume(conn, MONDAY)["biceps"] == 11.0
    assert weekly_muscle_volume_by_week(conn, [MONDAY])[MONDAY]["biceps"] == 11.0
    assert direct_sets_by_week(conn, MONDAY)[("biceps", MONDAY)] == 11.0
    assert "- biceps: 11/8 done, 0 left" in weekly_budget_block(conn, MONDAY)


def test_left8_right8_reads_8(conn, seed) -> None:
    _arms(seed, 8, 8)
    assert weekly_muscle_volume(conn, MONDAY)["biceps"] == 8.0
    assert "- biceps: 8/8 done, 0 left" in weekly_budget_block(conn, MONDAY)


def test_three_single_arm_slots_count_half_in_plan_caps(conn) -> None:
    plan = {
        "blocks": [
            {"exercises": [{"name": LEFT, "sets": 4}, {"name": RIGHT, "sets": 4}]},
            {"exercises": [{"name": RIGHT, "sets": 4}]},
        ]
    }
    assert _planned_primary_sets_by_muscle(conn, plan)["biceps"] == 6.0
    assert _planned_sets_by_muscle(conn, plan)["biceps"] == 6.0


def test_per_hand_load_is_identity_and_not_quarantined() -> None:
    assert per_hand_kg(LEFT, 20.0, date(2026, 12, 1)) == 20.0
    assert not exceeds_per_hand_max(RIGHT, 20.0, date(2026, 12, 1))
    assert exceeds_per_hand_max(RIGHT, 60.0, date(2026, 12, 1))  # 132 lb in one hand


def test_arms_keep_separate_canon_exercise(conn, seed) -> None:
    _arms(seed, 2, 2)
    canon = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT canon_exercise FROM workout_sets_dedup "
            "WHERE exercise LIKE 'Single Arm Dumbbell Curl%'"
        ).fetchall()
    }
    assert len(canon) == 2
