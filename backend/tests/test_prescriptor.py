"""Deterministic per-lift prescription (double progression) + PR re-anchor policy.

The engine now writes the next load×rep number itself; the planning LLM copies
it. These tests pin the advancement rules — the exact arithmetic that used to
be re-derived (and got wrong) in chat every session.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta

from shc.training.loadable import LoadableGrids
from shc.training.mesocycle import _iso_week_start
from shc.training.prescriptor import _advance, next_prescriptions, pr_reanchor_due

_EX = "Leg Extension (Machine)"


def _grids(notches: list[float], sets: int = 20) -> LoadableGrids:
    key = _EX.strip().lower()
    return LoadableGrids(
        by_exercise={key: notches},
        set_counts={key: sets},
        dumbbell_rack=[],
        rack_sets=0,
        _canon={"leg extension": key},
        overrides={},
    )


def _no_ceiling(_reps: int) -> float | None:
    return None


GRID = _grids([170.0, 185.0, 200.0, 215.0])


def test_mid_window_adds_a_rep_at_the_same_load() -> None:
    action, w, reps, _ = _advance(_EX, 200.0, 10, 8.0, 8, 12, GRID, _no_ceiling)
    assert (action, w, reps) == ("add_rep", 200.0, 11)


def test_filled_window_steps_one_real_notch_and_resets_reps() -> None:
    """The step is the implement's actual increment, not a blanket +5."""
    action, w, reps, _ = _advance(_EX, 200.0, 12, 8.0, 8, 12, GRID, _no_ceiling)
    assert (action, w, reps) == ("step_load", 215.0, 8)


def test_ceiling_blocks_the_step_and_holds_the_window_top() -> None:
    """A capped day never loads up past its own effort ceiling."""
    action, w, reps, note = _advance(_EX, 200.0, 12, 8.0, 8, 12, GRID, lambda _r: 205.0)
    assert (action, w, reps) == ("top_of_window", 200.0, 12)
    assert "ceiling" in note


def test_a_grind_is_repeated_not_advanced() -> None:
    """Advancing off an RPE 9.5+ set programs a missed rep."""
    action, w, reps, _ = _advance(_EX, 200.0, 12, 10.0, 8, 12, GRID, _no_ceiling)
    assert (action, w, reps) == ("hold_grind", 200.0, 12)


def test_ceiling_below_last_weight_prescribes_the_snapped_ceiling() -> None:
    """A reduced day works AT today's ceiling — snapped DOWN to a loadable notch."""
    action, w, reps, _ = _advance(_EX, 200.0, 10, 8.0, 8, 12, GRID, lambda _r: 190.0)
    assert (action, w, reps) == ("reduce_ceiling", 185.0, 10)


def test_missing_e1rm_still_prescribes_double_progression() -> None:
    """No e1RM → no ceiling claim, not no prescription."""
    action, w, reps, _ = _advance(_EX, 200.0, 12, None, 8, 12, GRID, _no_ceiling)
    assert (action, w, reps) == ("step_load", 215.0, 8)


def test_next_prescriptions_reads_the_top_set_of_the_last_session(conn, seed) -> None:
    """End-to-end: last session's top working set drives the next target.

    200 lb × 10 @RPE 8 mid-window with a generous e1RM → 200 × 11. The earlier
    session and the earlier lighter set must not leak into the basis.
    """
    kg200, kg185 = 200 / 2.20462, 185 / 2.20462
    seed.workout(date.today() - timedelta(days=6), _EX, [(kg185, 10), (kg185, 10)], rpe=8.0)
    seed.workout(date.today() - timedelta(days=2), _EX, [(kg185, 8), (kg200, 10)], rpe=8.0)
    out = next_prescriptions(conn, {"max_intensity": "high"}, date.today(), {_EX: 120.0})
    (rx,) = out
    assert rx.exercise == _EX
    assert rx.last_weight_lbs == 200.0
    assert rx.last_reps == 10
    assert (rx.action, rx.next_weight_lbs, rx.next_reps) == ("add_rep", 200.0, 11)
    # The window resolved from the CURATED exercise_science row (10-15 for this
    # lift as of migration 0057+), not the 8-12 default — curation reaches the
    # prescription without an alias hop for an exact-name match.
    assert (rx.rep_low, rx.rep_high) == (10, 15)


def _seed_weekly_e1rm(conn, exercise: str, series: list[float]) -> None:
    """Insert completed-week e1RM rows, oldest first, ending last week."""
    this_week = _iso_week_start(date.today())
    n = len(series)
    for i, e1 in enumerate(series):
        wk = this_week - timedelta(weeks=n - i)
        conn.execute(
            "INSERT INTO exercise_weekly_e1rm "
            "(exercise, week_start, e1rm_kg, work_sets, computed_at) "
            "VALUES (?, ?, ?, 4, now())",
            [exercise, wk, e1],
        )


def _seed_recent_set(conn, exercise: str) -> None:
    wid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO workouts (id, source, started_at, kind, content_hash) "
        "VALUES (?, 'hevy', ?, 'strength', ?)",
        [wid, datetime.combine(date.today() - timedelta(days=3), datetime.min.time()), wid],
    )
    sid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO workout_sets "
        "(id, workout_id, exercise, set_idx, reps, weight_kg, rpe, is_warmup, content_hash) "
        "VALUES (?, ?, ?, 0, 8, 100.0, 8.0, FALSE, ?)",
        [sid, wid, exercise, sid],
    )


def test_pr_reanchor_flags_a_progressing_lift_with_a_stale_peak(conn) -> None:
    """Progressing by slope, but the recorded peak is 4wk old → re-anchor is due.

    Every load ceiling is a percentage of that peak; a lift that keeps climbing
    without re-registering it is being capped against yesterday's strength.
    """
    ex = "Bench Press (Barbell)"
    _seed_weekly_e1rm(conn, ex, [100.0, 101.0, 102.0, 103.0, 110.0, 108.0, 108.5, 109.0])
    _seed_recent_set(conn, ex)
    due = pr_reanchor_due(conn, date.today(), {"max_intensity": "high"})
    assert [d["exercise"] for d in due] == [ex]
    assert due[0]["weeks_since_peak"] == 4
    assert due[0]["trend"] == "progressing"


def test_pr_reanchor_only_fires_on_a_true_high_day(conn) -> None:
    """The only day whose effort cap permits the attempt is the only day that asks."""
    ex = "Bench Press (Barbell)"
    _seed_weekly_e1rm(conn, ex, [100.0, 101.0, 102.0, 103.0, 110.0, 108.0, 108.5, 109.0])
    _seed_recent_set(conn, ex)
    assert pr_reanchor_due(conn, date.today(), {"max_intensity": "moderate"}) == []
    assert (
        pr_reanchor_due(conn, date.today(), {"max_intensity": "high", "deload_required": True})
        == []
    )


def test_pr_reanchor_skips_fresh_peaks_and_regressing_lifts(conn) -> None:
    """A fresh reference needs no re-anchor; a regressing lift is never asked for a max."""
    fresh = "Squat (Barbell)"
    _seed_weekly_e1rm(conn, fresh, [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0])
    _seed_recent_set(conn, fresh)
    regressing = "Overhead Press (Barbell)"
    _seed_weekly_e1rm(conn, regressing, [110.0, 108.0, 106.0, 104.0, 102.0, 100.0, 98.0, 96.0])
    _seed_recent_set(conn, regressing)
    assert pr_reanchor_due(conn, date.today(), {"max_intensity": "high"}) == []
