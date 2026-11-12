from __future__ import annotations

import json
from datetime import date

from shc.ai.workout_planner import _rep_bounds
from shc.training.session_design import check_session, scheduled_session


def _plan(day: str, exercises: list[tuple[str, str]]) -> dict:
    return {
        "session_day": day,
        "blocks": [{"label": "main", "exercises": [{"name": n, "reps": r} for n, r in exercises]}],
    }


def _trained(conn, seed, day: date, plan: dict) -> None:
    conn.execute(
        "INSERT INTO workout_plans (date, plan_json, source) VALUES (?, ?, 'test')",
        [day, json.dumps(plan)],
    )
    for ex in plan["blocks"][0]["exercises"]:
        seed.workout(day, ex["name"], [(50.0, 10)])


def _filler(seed, n: int) -> None:
    """n logged lifting days in October, enough to set the 28-day frequency."""
    for i in range(n):
        seed.workout(date(2026, 10, 10 + i), "Leg Extension (Machine)", [(40.0, 12)])


def test_three_day_rotation_below_four_sessions(conn, seed) -> None:
    upper_a = _plan("Upper-A", [("Incline Bench Press (Dumbbell)", "6-8")])
    lower_a = _plan("Lower-A", [("Hack Squat (Machine)", "8-10")])
    _trained(conn, seed, date(2026, 11, 2), upper_a)
    _trained(conn, seed, date(2026, 11, 3), lower_a)

    s = scheduled_session(conn, {}, date(2026, 11, 5), date(2026, 11, 1))
    assert s is not None and s.day == "Full Body" and s.region == "full"
    assert "3-day" in s.reason

    full = _plan(
        "Full Body",
        [
            ("Hammerstrength Decline Chest Press", "10-12"),
            ("Leg Press (Machine)", "10-12"),
            ("Cable Fly Crossovers", "15"),
        ],
    )
    assert check_session(conn, full, s, _rep_bounds) is None
    reuse = _plan("Full Body", [("Hack Squat (Machine)", "8-10")])
    assert "another day in the rotation" in check_session(conn, reuse, s, _rep_bounds)

    # Legs gated on the Full Body day: Upper-A moves up rather than a half-gated full day.
    gated = scheduled_session(conn, {"forbid_muscle_groups": ["legs"]}, date(2026, 11, 5), None)
    assert gated is not None and gated.day == "Upper-A"

    _trained(conn, seed, date(2026, 11, 5), full)
    s2 = scheduled_session(conn, {}, date(2026, 11, 7), date(2026, 11, 1))
    assert s2 is not None and s2.day == "Upper-A"
    assert s2.anchor == "Incline Bench Press (Dumbbell)"


def test_rotation_order_and_anchors(conn, seed) -> None:
    _filler(seed, 14)  # with the plan days below: 16+ sessions in 28 days -> 4-day split
    upper_a = _plan(
        "Upper-A", [("Incline Bench Press (Dumbbell)", "6-8"), ("Cable Fly Crossovers", "12")]
    )
    lower_a = _plan(
        "Lower-A", [("Hack Squat (Machine)", "8-10"), ("Leg Extension (Machine)", "12")]
    )
    _trained(conn, seed, date(2026, 11, 2), upper_a)
    _trained(conn, seed, date(2026, 11, 3), lower_a)

    # Rotation follows executed sessions: after Upper-A then Lower-A comes Upper-B.
    s = scheduled_session(conn, {}, date(2026, 11, 5), date(2026, 11, 1))
    assert s is not None and s.day == "Upper-B" and s.anchor is None

    ok = _plan(
        "Upper-B", [("Hammerstrength Decline Chest Press", "11-14"), ("Cable Fly Crossovers", "15")]
    )
    assert check_session(conn, ok, s, _rep_bounds) is None

    iso_first = _plan(
        "Upper-B", [("Cable Fly Crossovers", "15"), ("Hammerstrength Decline Chest Press", "12")]
    )
    assert "must open with an anchor" in check_session(conn, iso_first, s, _rep_bounds)

    fly_then_row = _plan(
        "Upper-B",
        [
            ("Hammerstrength Decline Chest Press", "12"),
            ("Cable Fly Crossovers", "15"),
            ("V-Bar Pulldown", "12"),
        ],
    )
    assert check_session(conn, fly_then_row, s, _rep_bounds) is None
    pre_fatigued = _plan(
        "Upper-B",
        [
            ("Hammerstrength Decline Chest Press", "12"),
            ("Cable Fly Crossovers", "15"),
            ("Incline Bench Press (Dumbbell)", "10"),
        ],
    )
    assert "already tired" in check_session(conn, pre_fatigued, s, _rep_bounds)

    assert "out of rotation" in check_session(conn, _plan("Lower-B", []), s, _rep_bounds)

    # Next Upper-A holds the anchor executed earlier in the block.
    _trained(conn, seed, date(2026, 11, 5), ok)
    _trained(conn, seed, date(2026, 11, 6), _plan("Lower-B", [("Leg Press (Machine)", "10-12")]))
    s2 = scheduled_session(conn, {}, date(2026, 11, 9), date(2026, 11, 1))
    assert s2 is not None and s2.day == "Upper-A"
    assert s2.anchor == "Incline Bench Press (Dumbbell)"
    assert s2.anchor_reps == "6-8"
    assert "Hammerstrength Decline Chest Press" in s2.other_anchors
    swapped = _plan("Upper-A", [("Hammerstrength Decline Chest Press", "6-8")])
    assert "anchor this mesocycle" in check_session(conn, swapped, s2, _rep_bounds)
    new_reps = _plan("Upper-A", [("Incline Bench Press (Dumbbell)", "10-12")])
    assert "whole block" in check_session(conn, new_reps, s2, _rep_bounds)
    held = _plan("Upper-A", [("Incline Bench Press (Dumbbell)", "6-8")])
    assert check_session(conn, held, s2, _rep_bounds) is None

    # Upper-B may not reuse Upper-A's anchor.
    s4 = scheduled_session(conn, {}, date(2026, 11, 5), date(2026, 11, 1))
    reuse = _plan("Upper-B", [("Incline Bench Press (Dumbbell)", "10")])
    assert "another day in the rotation" in check_session(conn, reuse, s4, _rep_bounds)

    # Legs gated: the lower day yields to upper instead of skipping a template.
    s3 = scheduled_session(conn, {"forbid_muscle_groups": ["legs"]}, date(2026, 11, 4), None)
    assert s3 is not None and s3.region == "upper"


def test_leg_day_with_hinge_reads_lower_and_legs_rest_48h(conn, seed) -> None:
    # 2026-11-08: 7 leg sets + 6 arm sets, no session_day. The SLDL's lower_back
    # primary counted toward upper, the day read as upper, and 11/9 got Lower-A.
    day = date(2026, 11, 8)
    for name, n in [
        ("Split Squat (Dumbbell)", 3),
        ("Smith Machine Stiff-Legged Deadlift", 2),
        ("Standing Calf Raise (Machine)", 2),
        ("Hammer Curl (Dumbbell)", 2),
        ("Reverse Curl (Barbell)", 2),
        ("Seated Triceps Press", 2),
    ]:
        seed.workout(day, name, [(40.0, 10)] * n)
    # The day after: Full Body would be next in the 3-day cycle, but it trains legs
    # again within 24 h, so Upper-A goes first.
    s = scheduled_session(conn, {}, date(2026, 11, 9), None)
    assert s is not None and s.day == "Upper-A", s.reason
    assert "trained yesterday" in s.reason
    # Two days later the legs have had 48 h and the cycle resumes.
    s2 = scheduled_session(conn, {}, date(2026, 11, 10), None)
    assert s2 is not None and s2.day == "Full Body", s2.reason


def test_a_plan_the_session_did_not_follow_is_not_executed(conn, seed) -> None:
    upper_a = _plan("Upper-A", [("Incline Bench Press (Dumbbell)", "6-8")])
    _trained(conn, seed, date(2026, 11, 2), upper_a)
    # Full Body plan stored the same day Rob trained something else entirely.
    ignored = _plan("Full Body", [("Leg Press (Machine)", "8-10"), ("Cable Fly Crossovers", "12")])
    conn.execute(
        "INSERT INTO workout_plans (date, plan_json, source) VALUES (?, ?, 'test')",
        [date(2026, 11, 3), json.dumps(ignored)],
    )
    seed.workout(date(2026, 11, 3), "Lat Pulldown (Cable)", [(100.0, 10)])
    seed.workout(date(2026, 11, 3), "Seated Cable Row - Bar Grip", [(100.0, 10)])

    s = scheduled_session(conn, {}, date(2026, 11, 5), date(2026, 11, 1))
    assert s is not None
    assert s.other_anchors == ("Incline Bench Press (Dumbbell)",)
    assert "Leg Press (Machine)" not in s.other_anchors
