"""Last-set rep-out: which lifts, which days, and that it is stamped in code."""

from __future__ import annotations

import json
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from shc.training.prescriptor import (
    REP_OUT_NOTE,
    apply_rep_outs,
    next_prescriptions,
    rep_out_active,
    rep_out_eligible,
)

HIGH = {"max_intensity": "high"}


def _meso(week: int, planned: int = 7, deload: bool = False) -> SimpleNamespace:
    return SimpleNamespace(week_number=week, planned_weeks=planned, is_deload_week=deload)


@pytest.mark.parametrize(
    "name",
    [
        "Leg Extension (Machine)",
        "Hammerstrength Incline Chest Press",
        "Lat Pulldown - Close Grip (Cable)",
        "Seated Cable Row - V Grip (Cable)",
        "Hammer Curl (Dumbbell)",
        "Lateral Raise (Dumbbell)",
        "Overhead Triceps Extension (Cable)",
        "Triceps Pressdown",
        "Hack Squat (Machine)",
    ],
)
def test_fixed_path_and_single_joint_lifts_take_a_rep_out(name: str) -> None:
    assert rep_out_eligible(name)


@pytest.mark.parametrize(
    "name",
    [
        "Bench Press (Barbell)",
        "Split Squat (Dumbbell)",
        "Shoulder Press (Dumbbell)",
        "Bent Over Row (Barbell)",
        "Pull Up",
        "Romanian Deadlift (Dumbbell)",
        "Smith Machine Stiff-Legged Deadlift",
    ],
)
def test_free_weight_compounds_and_hinges_never_take_a_rep_out(name: str) -> None:
    """The vault applies near-failure work "more conservatively" to multi-joint
    lifts; a hinge is excluded even on a machine."""
    assert not rep_out_eligible(name)


def test_rep_outs_run_only_late_in_the_block_on_an_uncapped_day() -> None:
    """Failure density is periodized: off until the block's own effort band
    reaches RPE 9, and off on any day whose cap sits below it."""
    assert not rep_out_active(HIGH, _meso(1))
    assert not rep_out_active(HIGH, _meso(3))
    assert rep_out_active(HIGH, _meso(4))
    assert rep_out_active(HIGH, _meso(7))
    assert not rep_out_active({"max_intensity": "moderate"}, _meso(7))
    assert not rep_out_active({"max_intensity": "high", "deload_required": True}, _meso(7))
    assert not rep_out_active(HIGH, _meso(8, deload=True))
    assert not rep_out_active(HIGH, None)


def test_apply_rep_outs_stamps_eligible_lifts_and_leaves_the_rest() -> None:
    plan = {
        "blocks": [
            {
                "exercises": [
                    {"name": "Leg Extension (Machine)", "sets": 3, "weight_lbs": 180, "notes": "x"},
                    {"name": "Bench Press (Barbell)", "sets": 3, "weight_lbs": 185, "notes": ""},
                    {"name": "Cable Crunch", "sets": 1, "weight_lbs": 90, "notes": ""},
                    {"name": "Plank", "sets": 3, "weight_lbs": None, "notes": ""},
                ]
            }
        ]
    }
    assert apply_rep_outs(plan, HIGH, _meso(6)) == ["Leg Extension (Machine)"]
    leg_ext, bench, crunch, plank = plan["blocks"][0]["exercises"]
    assert leg_ext["rep_out"] is True
    assert leg_ext["notes"] == f"{REP_OUT_NOTE} x"
    assert "rep_out" not in bench and "rep_out" not in crunch and "rep_out" not in plank

    early = {"blocks": [{"exercises": [{"name": "Cable Crunch", "sets": 3, "weight_lbs": 90}]}]}
    assert apply_rep_outs(early, HIGH, _meso(2)) == []
    assert "rep_out" not in early["blocks"][0]["exercises"][0]


def test_a_plan_written_below_high_gets_no_rep_out() -> None:
    plan = {
        "recommendation": {"intensity": "moderate"},
        "blocks": [{"exercises": [{"name": "Cable Crunch", "sets": 3, "weight_lbs": 90}]}],
    }
    assert apply_rep_outs(plan, HIGH, _meso(6)) == []


def _logged_rep_out(conn, seed, reps: list[int]) -> str:
    """One session of Cable Crunch at a fixed load whose plan marked a rep-out."""
    day = date.today() - timedelta(days=2)
    plan = {"blocks": [{"exercises": [{"name": "Cable Crunch", "rep_out": True}]}]}
    conn.execute(
        "INSERT INTO workout_plans (date, plan_json, source) VALUES (?, ?, 'test')",
        [day, json.dumps(plan)],
    )
    seed.workout(day, "Cable Crunch", [(40.0, r) for r in reps])
    (rx,) = [
        n for n in next_prescriptions(conn, HIGH, date.today(), {}) if n.exercise == "Cable Crunch"
    ]
    return f"{rx.action}:{rx.next_reps}"


def test_a_rep_out_that_fills_the_window_steps_the_load(conn, seed) -> None:
    assert _logged_rep_out(conn, seed, [10, 10, 30]).startswith(("step_load", "top_of_window"))


def test_a_rep_out_short_of_the_window_does_not_become_the_straight_set_target(conn, seed) -> None:
    """Three sets at the rep-out count is not a prescription Rob can hit: the
    next target adds a rep to what the STRAIGHT sets held."""
    assert _logged_rep_out(conn, seed, [10, 10, 11]) == "add_rep:11"
