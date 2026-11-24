"""Per-session adherence is read from the Hevy session's own notes, never assumed."""

from __future__ import annotations

from datetime import date, timedelta

from test_selflab_sessions import LIFT, _session

from shc import selflab


def _note(conn, day: date, *, workout: str | None = None, exercise: str | None = None) -> None:
    wid = f"w-{LIFT}-{day}"
    conn.execute("UPDATE workouts SET notes = ? WHERE id = ?", [workout, wid])
    conn.execute("UPDATE workout_sets SET exercise_notes = ? WHERE workout_id = ?", [exercise, wid])


def _reg(conn, started: date) -> str:
    _session(conn, date.today() - timedelta(days=1))
    return selflab.preregister(
        conn,
        slug="caf-curl",
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


def _adhered(conn, exp: str) -> list:
    return [
        r[0]
        for r in conn.execute(
            "SELECT adhered FROM experiment_log WHERE experiment_id = ? ORDER BY day", [exp]
        ).fetchall()
    ]


def test_tag_matching_assignment_is_adhered_mismatch_false_missing_null(conn) -> None:
    start = date.today() - timedelta(days=30)
    exp = _reg(conn, start)
    d = [date.today() - timedelta(days=k) for k in (12, 9, 6, 3)]
    for day in d:
        _session(conn, day)
    # session indices: 0..3 are d[0..3]; the seed session (yesterday) is index 4
    tag = {"A": "nocaf", "B": "caf"}
    wrong = {"A": "caf", "B": "nocaf"}
    _note(conn, d[0], workout=f"Arms. {tag[selflab.arm_for_session('caf-curl', 0)].upper()}!")
    _note(conn, d[1], exercise=wrong[selflab.arm_for_session("caf-curl", 1)])
    _note(conn, d[2], workout="no tag here")
    _note(conn, d[3], workout="caf nocaf")  # both tags: ambiguous, unknown
    selflab.autolog_randomized(conn, exp)
    assert _adhered(conn, exp) == [True, False, None, None, None]


def test_tag_must_be_a_whole_word(conn) -> None:
    start = date.today() - timedelta(days=30)
    exp = _reg(conn, start)
    day = date.today() - timedelta(days=5)
    _session(conn, day)
    _note(conn, day, workout="nocaf")  # 'caf' must not match inside 'nocaf'
    selflab.autolog_randomized(conn, exp)
    arm0 = selflab.arm_for_session("caf-curl", 0)
    assert _adhered(conn, exp)[0] is (arm0 == "A")


def test_a_late_tag_resolves_an_unknown_row_and_manual_rows_are_kept(conn) -> None:
    start = date.today() - timedelta(days=30)
    exp = _reg(conn, start)
    day = date.today() - timedelta(days=5)
    _session(conn, day)
    selflab.autolog_randomized(conn, exp)
    assert _adhered(conn, exp)[0] is None
    arm0 = selflab.arm_for_session("caf-curl", 0)
    _note(conn, day, workout="caf" if arm0 == "B" else "nocaf")
    selflab.autolog_randomized(conn, exp)
    assert _adhered(conn, exp)[0] is True
    selflab.log_day(conn, exp, day, adhered=False, note="manual override")
    selflab.autolog_randomized(conn, exp)
    assert _adhered(conn, exp)[0] is False


def test_scorer_excludes_unknown_and_reports_the_count(conn) -> None:
    start = date.today() - timedelta(days=60)
    exp = _reg(conn, start)
    for i in range(10):
        day = date.today() - timedelta(days=50 - i)
        arm = "A" if i % 2 == 0 else "B"
        conn.execute(
            "INSERT INTO experiment_log (experiment_id, day, assigned_arm, adhered, outcome_value) "
            "VALUES (?, ?, ?, ?, ?)",
            [exp, day.isoformat(), arm, None if i >= 6 else True, 100.0 + i],
        )
    r = selflab.score(conn, exp)
    assert r["n_a"] + r["n_b"] == 6
    assert r["n_adherence_unknown"] == 4
    assert "4 sessions with unknown adherence" in r["summary"]


def test_per_session_requires_two_distinct_tags(conn) -> None:
    import pytest

    _session(conn, date.today() - timedelta(days=1))
    kw = dict(
        slug="x",
        hypothesis="h",
        manipulated="m",
        condition_a="a",
        condition_b="b",
        outcome_metric=f"top_set_e1rm:{LIFT}",
        min_effect=2.0,
        design="randomized_per_session",
    )
    with pytest.raises(ValueError, match="adherence_tag"):
        selflab.preregister(conn, **kw)
    with pytest.raises(ValueError, match="distinct"):
        selflab.preregister(conn, **kw, adherence_tag_a="caf", adherence_tag_b="CAF")
