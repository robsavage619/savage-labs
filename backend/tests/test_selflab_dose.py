"""Guards for the weekly set-dose study type.

Two things in this design can be confidently wrong: the arm classifier can
multiply one week's observation into seven correlated rows, and an observational
study can be registered under the default randomized design and then silently
refuse to backfill. Both are tested here.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest

from shc import selflab

_EX = "Hammer Curl (Dumbbell)"
_MON = date(2026, 1, 5)  # a Monday


def _sets(conn, day: date, n: int, weight: float = 20.0) -> None:
    wid = f"w{day}"
    conn.execute(
        "INSERT INTO workouts (id, source, started_at, kind, content_hash) VALUES (?,'hevy',?,'strength',?)",
        [wid, datetime.combine(day, datetime.min.time()), f"h{day}"],
    )
    for i in range(n):
        conn.execute(
            "INSERT INTO workout_sets (id, workout_id, set_idx, exercise, weight_kg, reps, rpe, is_warmup, content_hash) "
            "VALUES (?,?,?,?,?,10,8.0,FALSE,?)",
            [f"{wid}s{i}", wid, i, _EX, weight, f"c{wid}{i}"],
        )


def test_dose_arms_split_on_the_declared_bands(conn):
    _sets(conn, _MON, 4)
    assert selflab._classify_weekly_set_dose(conn, _EX, _MON) == "A"


def test_high_dose_week_lands_in_arm_b(conn):
    _sets(conn, _MON, 7)
    assert selflab._classify_weekly_set_dose(conn, _EX, _MON) == "B"


def test_doses_between_and_beyond_the_bands_are_excluded(conn):
    """The gap is deliberate: adjacent doses carry noise and no contrast."""
    _sets(conn, _MON, 2)
    assert selflab._classify_weekly_set_dose(conn, _EX, _MON) is None
    conn.execute("DELETE FROM workout_sets")
    conn.execute("DELETE FROM workouts")
    _sets(conn, _MON, 14)
    assert selflab._classify_weekly_set_dose(conn, _EX, _MON) is None


def test_only_monday_classifies_so_one_week_is_one_observation(conn):
    """Seven rows per week would inflate n sevenfold with correlated data."""
    _sets(conn, _MON, 4)
    assert selflab._classify_weekly_set_dose(conn, _EX, _MON) == "A"
    for offset in range(1, 7):
        assert selflab._classify_weekly_set_dose(conn, _EX, _MON + timedelta(days=offset)) is None


def test_classifier_is_scoped_to_its_own_exercise(conn):
    _sets(conn, _MON, 4)
    assert selflab._classify_weekly_set_dose(conn, "Bench Press", _MON) is None


def test_parametric_classifier_resolves_by_kind_and_arg(conn):
    resolved = selflab._resolve_classifier(f"weekly_set_dose:{_EX}")
    assert resolved is not None
    _sets(conn, _MON, 4)
    assert resolved(conn, _MON) == "A"
    assert selflab._resolve_classifier("weekly_set_dose") is None
    assert selflab._resolve_classifier("no_such_thing:x") is None
    # plain (non-parametric) registrations must keep working
    assert selflab._resolve_classifier("sleep_hours") is not None


def _weekly(conn, week: date, e1rm: float, sets: int = 4) -> None:
    conn.execute(
        "INSERT INTO exercise_weekly_e1rm (exercise, week_start, e1rm_kg, work_sets, computed_at) "
        "VALUES (?,?,?,?,now())",
        [_EX, week.isoformat(), e1rm, sets],
    )


def test_outcome_is_the_two_week_change_not_the_level(conn):
    """Levels drift upward over a block; only the change answers a dose question."""
    _weekly(conn, _MON, 50.0)
    _weekly(conn, _MON + timedelta(weeks=2), 53.5)
    assert selflab._e1rm_delta_2wk(conn, _EX, _MON) == pytest.approx(3.5)


def test_outcome_is_none_when_either_endpoint_is_missing(conn):
    _weekly(conn, _MON, 50.0)
    assert selflab._e1rm_delta_2wk(conn, _EX, _MON) is None


def test_design_must_be_declared_and_validated(conn):
    """The column defaults to randomized; an observational study must say so."""
    with pytest.raises(ValueError, match="design must be one of"):
        selflab.preregister(
            conn,
            slug="bad-design",
            hypothesis="h",
            manipulated="sleep_hours",
            condition_a="a",
            condition_b="b",
            outcome_metric="hrv_next_morning",
            min_effect=1.0,
            design="whatever",
        )


def test_observational_design_survives_preregistration(conn):
    exp_id = selflab.preregister(
        conn,
        slug="dose-test",
        hypothesis="h",
        manipulated=f"weekly_set_dose:{_EX}",
        condition_a="3-5",
        condition_b="6-9",
        outcome_metric=f"e1rm_delta_2wk:{_EX}",
        min_effect=0.5,
        design="observational",
        started_on=_MON,
    )
    exp = selflab.load(conn, exp_id)
    assert exp is not None and exp.design == "observational"
    # and therefore backfill accepts it rather than refusing a randomized study
    _sets(conn, _MON, 4)
    counts = selflab.backfill_observational(conn, exp_id, through=_MON + timedelta(days=6))
    assert counts["A"] == 1
