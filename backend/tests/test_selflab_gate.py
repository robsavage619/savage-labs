"""Placebo-replay gate: a design is run on the outcome's own history with no effect."""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

import pytest

from shc import selflab

LIFT = "Seated Dumbbell Curl"


def _history(conn, *, noise: float, per_week: int = 2, weeks: int = 25, seed: int = 1) -> None:
    rng = random.Random(seed)
    step = 7 // per_week
    for i in range(weeks * per_week):
        day = date.today() - timedelta(days=2 + i * step)
        e1rm = 50.0 + rng.gauss(0, noise)
        wid = f"w{i}"
        conn.execute(
            "INSERT INTO workouts (id, source, started_at, kind, content_hash) "
            "VALUES (?, 'hevy', ?, 'strength', ?)",
            [wid, datetime.combine(day, datetime.min.time()), wid],
        )
        conn.execute(
            "INSERT INTO workout_sets (id, workout_id, set_idx, exercise, weight_kg, reps, "
            "rpe, is_warmup, content_hash) VALUES (?, ?, 0, ?, ?, 10, 8.0, FALSE, ?)",
            [f"{wid}s", wid, LIFT, e1rm / (1 + 10 / 30.0), wid],
        )


def _reg(conn, *, slug="g", min_effect=3.0, design="randomized_per_session"):
    return selflab.preregister(
        conn,
        slug=slug,
        hypothesis="h",
        manipulated="m",
        condition_a="a",
        condition_b="b",
        outcome_metric=f"top_set_e1rm:{LIFT}",
        min_effect=min_effect,
        design=design,
        adherence_tag_a="nocaf",
        adherence_tag_b="caf",
    )


def test_quiet_lift_passes_and_reports_calibration(conn) -> None:
    _history(conn, noise=1.0)
    gate = selflab.placebo_gate(
        conn,
        slug="g",
        outcome_metric=f"top_set_e1rm:{LIFT}",
        min_effect=3.0,
        design="randomized_per_session",
    )
    assert gate is not None
    assert gate["false_fire_rate"] <= 2 * selflab._ALPHA
    assert gate["detectable_120d"] <= 3.0 and gate["sessions_per_week"] == pytest.approx(2, abs=0.5)
    _reg(conn)


def test_noisy_lift_is_refused_with_the_numbers(conn) -> None:
    _history(conn, noise=6.0)
    with pytest.raises(ValueError, match=r"smallest detectable .* in 120 days.*min_effect 3"):
        _reg(conn)


def test_miscalibrated_design_is_refused(conn, monkeypatch) -> None:
    _history(conn, noise=1.0)
    monkeypatch.setattr(selflab, "_permutation_p", lambda *a, **k: 0.01)
    with pytest.raises(ValueError, match="miscalibrated"):
        _reg(conn)


def test_one_active_study_per_outcome_exercise(conn) -> None:
    _history(conn, noise=1.0)
    _reg(conn, slug="first")
    with pytest.raises(ValueError, match="already has an active study"):
        _reg(conn, slug="second")
    selflab.abandon(conn, "first", "replaced by a better design for this lift")
    _reg(conn, slug="second")


def test_detectable_effect_inverts_needed_per_arm() -> None:
    for sd, de, n in [(1.0, 1.0, 12), (2.5, 1.8, 30)]:
        e = selflab._detectable_effect(sd, n, de)
        assert selflab._needed_per_arm(sd, e, de) <= n < selflab._needed_per_arm(sd, e * 0.95, de)
