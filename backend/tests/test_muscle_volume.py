from __future__ import annotations

from datetime import date

from shc.training.mesocycle import _iso_week_start, volume_targets
from shc.training.volume import (
    build_muscle_report,
    unmapped_exercises,
    weekly_muscle_volume,
)


def test_secondary_muscle_credit(conn, seed):
    """A working set credits primary 1.0 and each secondary 0.5.

    'Pull-Up' maps to lats (primary) + biceps (secondary) after migration 0040
    normalizes the legacy 'back' key.
    """
    today = date.today()
    seed.workout(today, "Pull-Up", [(20.0, 8), (20.0, 8), (20.0, 8)])

    vol = weekly_muscle_volume(conn, _iso_week_start(today))

    assert vol["lats"] == 3.0  # primary, full credit
    assert vol["biceps"] == 1.5  # secondary, 0.5 × 3 sets


def test_warmups_and_empty_sets_excluded(conn, seed):
    today = date.today()
    seed.workout(today, "Bicep Curl (Barbell)", [(0.0, 0)])  # junk set
    seed.workout(today, "Bicep Curl (Barbell)", [(15.0, 10)], is_warmup=True)

    vol = weekly_muscle_volume(conn, _iso_week_start(today))

    assert vol.get("biceps", 0.0) == 0.0


def test_unmapped_exercise_surfaced(conn, seed):
    today = date.today()
    seed.workout(today, "Totally Made Up Lift", [(50.0, 5)])

    assert "Totally Made Up Lift" in unmapped_exercises(conn, _iso_week_start(today))


def test_targets_join_for_biceps_and_glutes(conn):
    """Migration 0040 must give biceps and glutes real landmarks (the old bug)."""
    targets = volume_targets(conn, None)

    for muscle in ("biceps", "glutes"):
        assert muscle in targets
        t = targets[muscle]
        assert t.mev < t.mav < t.mrv


def test_build_report_status(conn, seed):
    today = date.today()
    # 9 glute sets — between MEV (6) and MAV (12) → "in range"
    seed.workout(today, "Hip Thrust (Barbell)", [(100.0, 8)] * 9)

    actuals = weekly_muscle_volume(conn, _iso_week_start(today))
    report = {r.muscle: r for r in build_muscle_report(actuals, volume_targets(conn, None))}

    assert report["glutes"].status == "in range"
