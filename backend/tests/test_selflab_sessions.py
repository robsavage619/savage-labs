"""Per-session randomization (Design A): assignment counts sessions, not days."""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from shc import selflab

LIFT = "Preacher Curl (Dumbbell)"


def _session(conn, day: date, exercise: str = LIFT) -> None:
    wid = f"w-{exercise}-{day}"
    conn.execute(
        "INSERT OR IGNORE INTO workouts (id, source, started_at, kind, content_hash) "
        "VALUES (?, 'hevy', ?, 'strength', ?)",
        [wid, datetime.combine(day, datetime.min.time()), f"h{wid}"],
    )
    conn.execute(
        "INSERT OR IGNORE INTO workout_sets (id, workout_id, set_idx, exercise, weight_kg, "
        "reps, rpe, is_warmup, content_hash) VALUES (?, ?, 0, ?, 20, 10, 8.0, FALSE, ?)",
        [f"{wid}s0", wid, exercise, f"c{wid}"],
    )


def _history(conn, n: int = 10) -> None:
    """Enough constant-load history (older than any test study) for the gate to size."""
    for k in range(n):
        _session(conn, date.today() - timedelta(days=70 + 7 * k))


def _reg(conn, started: date, slug: str = "caf-curl") -> str:
    _history(conn)
    _session(conn, date.today() - timedelta(days=2))
    return selflab.preregister(
        conn,
        slug=slug,
        hypothesis="Caffeine raises curl e1RM.",
        manipulated="pre_lift_caffeine",
        condition_a="none",
        condition_b="200mg",
        outcome_metric=f"top_set_e1rm:{LIFT}",
        min_effect=2.0,
        design="randomized_per_session",
        started_on=started,
        adherence_tag_a="nocaf",
        adherence_tag_b="caf",
    )


def test_arm_for_session_is_pair_balanced_and_deterministic() -> None:
    arms = [selflab.arm_for_session("s", n) for n in range(30)]
    assert arms == [selflab.arm_for_session("s", n) for n in range(30)]
    for i in range(0, 30, 2):
        assert {arms[i], arms[i + 1]} == {"A", "B"}
    assert arms != [
        selflab.arm_for_day("s", date(2025, 1, 1), date(2025, 1, 1) + timedelta(days=i))
        for i in range(30)
    ]


def test_session_assignment_counts_sessions_not_calendar_days(conn) -> None:
    start = date.today() - timedelta(days=30)
    _reg(conn, start)
    for d in (10, 8, 5):  # three sessions in 30 calendar days, plus one before start
        _session(conn, date.today() - timedelta(days=d))
    _session(conn, start - timedelta(days=3))
    nxt = selflab.session_assignment(conn, "caf-curl", date.today() + timedelta(days=1))
    # sessions since start: the registration-seed session (2 days ago) + 3 = 4
    assert nxt == selflab.arm_for_session("caf-curl", 4)
    # a day with its own logged session gets that session's index
    assert selflab.session_assignment(conn, "caf-curl", date.today() - timedelta(days=8)) == (
        selflab.arm_for_session("caf-curl", 1)
    )


def test_todays_assignments_includes_per_session_and_autolog_is_unknown(conn) -> None:
    start = date.today() - timedelta(days=20)
    exp = _reg(conn, start)
    _session(conn, date.today() - timedelta(days=9))
    out = {a["slug"]: a for a in selflab.todays_assignments(conn)}
    a = out["caf-curl"]
    assert a["design"] == "randomized_per_session" and a["exercise"] == LIFT
    assert a["arm"] == selflab.arm_for_session("caf-curl", 2)
    assert selflab.autolog_randomized(conn, exp) == 2
    rows = conn.execute(
        "SELECT assigned_arm, adhered FROM experiment_log WHERE experiment_id = ? ORDER BY day",
        [exp],
    ).fetchall()
    assert [r[0] for r in rows] == [selflab.arm_for_session("caf-curl", i) for i in range(2)]
    assert all(r[1] is None for r in rows)


def test_per_session_with_too_little_history_is_refused(conn) -> None:
    _session(conn, date.today() - timedelta(days=2))
    with pytest.raises(ValueError, match="fewer than 10 sessions"):
        selflab.preregister(
            conn,
            slug="thin",
            hypothesis="h",
            manipulated="m",
            condition_a="a",
            condition_b="b",
            outcome_metric=f"top_set_e1rm:{LIFT}",
            min_effect=2.0,
            design="randomized_per_session",
            adherence_tag_a="x",
            adherence_tag_b="y",
        )


def test_per_session_needs_an_exercise_outcome(conn) -> None:
    with pytest.raises(ValueError, match="exercise outcome"):
        selflab.preregister(
            conn,
            slug="x",
            hypothesis="h",
            manipulated="m",
            condition_a="a",
            condition_b="b",
            outcome_metric="hrv_next_morning",
            min_effect=1.0,
            design="randomized_per_session",
            adherence_tag_a="nocaf",
            adherence_tag_b="caf",
        )


def test_planner_words_per_session_arm_as_conditional_on_the_lift() -> None:
    from shc.ai.workout_planner import trial_assignment_lines

    per_session = {
        "design": "randomized_per_session", "hypothesis": "H1.", "exercise": LIFT,
        "arm": "B", "condition": "cond-b",
    }
    daily = {"design": "randomized_alternating", "hypothesis": "H2.", "arm": "A", "condition": "c-a"}
    text = "\n".join(trial_assignment_lines([per_session, daily]))
    assert f"ONLY IF you program **{LIFT}**" in text and "arm B" in text
    assert "H2. Today is arm A" in text
    assert trial_assignment_lines([]) == []


def test_weekly_study_lift_is_held_out_of_rotation(conn) -> None:
    from shc.ai.workout_planner import benchmark_hold_lines
    from shc.training.autoregulation import _apply_benchmark_hold

    ranks = {LIFT: 2, "Other": 2}  # both plateaued, long tenure: swap-eligible
    tenure = {LIFT: 9, "Other": 9}
    _apply_benchmark_hold(conn, {LIFT, "Other"}, {}, ranks, tenure)
    assert (ranks[LIFT], tenure[LIFT]) == (2, 9), "no study: nothing is held"

    _reg(conn, date.today() - timedelta(days=20))
    assert selflab.held_benchmark_lifts(conn) == {LIFT}
    _apply_benchmark_hold(conn, {LIFT, "Other"}, {}, ranks, tenure)
    assert (ranks[LIFT], tenure[LIFT]) == (0, 0)
    assert (ranks["Other"], tenure["Other"]) == (2, 9)
    assert LIFT in "\n".join(benchmark_hold_lines([LIFT])) and benchmark_hold_lines([]) == []
