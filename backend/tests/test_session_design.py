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


def test_rotation_order_and_anchors(conn, seed) -> None:
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
    assert s2.sibling_anchor == "Hammerstrength Decline Chest Press"
    swapped = _plan("Upper-A", [("Hammerstrength Decline Chest Press", "6-8")])
    assert "anchor this mesocycle" in check_session(conn, swapped, s2, _rep_bounds)
    new_reps = _plan("Upper-A", [("Incline Bench Press (Dumbbell)", "10-12")])
    assert "whole block" in check_session(conn, new_reps, s2, _rep_bounds)
    held = _plan("Upper-A", [("Incline Bench Press (Dumbbell)", "6-8")])
    assert check_session(conn, held, s2, _rep_bounds) is None

    # Upper-B may not reuse Upper-A's anchor.
    s4 = scheduled_session(conn, {}, date(2026, 11, 5), date(2026, 11, 1))
    reuse = _plan("Upper-B", [("Incline Bench Press (Dumbbell)", "10")])
    assert "other upper day" in check_session(conn, reuse, s4, _rep_bounds)

    # Legs gated: the lower day yields to upper instead of skipping a template.
    s3 = scheduled_session(conn, {"forbid_muscle_groups": ["legs"]}, date(2026, 11, 4), None)
    assert s3 is not None and s3.region == "upper"
