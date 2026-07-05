from __future__ import annotations

from datetime import date

from shc.training.mesocycle import _iso_week_start, volume_targets
from shc.training.volume import (
    build_muscle_report,
    unmapped_exercises,
    weekly_muscle_volume,
    weekly_region_volume,
)


def test_region_volume_credits_each_head(conn, seed):
    """A set credits the specific head(s) exercise_science maps, across muscles.

    Hammer Curl carries two science rows (biceps/brachialis + forearms/
    brachioradialis), so it must credit a head under EACH muscle — the crediting
    that was invisible when only exercise_muscle_map (biceps, no secondaries)
    drove volume.
    """
    today = date.today()
    seed.workout(today, "Incline Curl (Dumbbell)", [(15.0, 12)] * 2)  # biceps/long_head
    seed.workout(today, "Bicep Curl (Barbell)", [(30.0, 10)])  # biceps/short_head
    seed.workout(today, "Hammer Curl (Dumbbell)", [(20.0, 12)] * 3)  # brachialis + brachioradialis

    rv = weekly_region_volume(conn, _iso_week_start(today))

    assert rv["biceps"]["long_head"] == 2.0
    assert rv["biceps"]["short_head"] == 1.0
    assert rv["biceps"]["brachialis"] == 3.0
    assert rv["forearms"]["brachioradialis"] == 3.0  # credited under forearms too


def test_secondary_muscle_credit(conn, seed):
    """Primary gets 1.0; an ARM secondary gets the reduced 0.3 (panel review M1).

    'Pull-Up' maps to lats (primary) + biceps (secondary) after migration 0040
    normalizes the legacy 'back' key.
    """
    today = date.today()
    seed.workout(today, "Pull-Up", [(20.0, 8), (20.0, 8), (20.0, 8)])

    vol = weekly_muscle_volume(conn, _iso_week_start(today))

    assert vol["lats"] == 3.0  # primary, full credit
    assert vol["biceps"] == round(0.3 * 3, 1)  # arm secondary, reduced credit


def test_hammer_curl_credits_forearms(conn, seed):
    """0065: a neutral-grip curl now credits forearms (brachioradialis), not just
    biceps — the landmark-crediting gap where head coverage existed but volume
    didn't."""
    today = date.today()
    seed.workout(today, "Hammer Curl (Dumbbell)", [(20.0, 12)] * 4)
    vol = weekly_muscle_volume(conn, _iso_week_start(today))
    assert vol["biceps"] == 4.0  # primary, full credit
    assert vol["forearms"] == round(0.3 * 4, 1)  # arm secondary, reduced credit


def test_row_credits_mid_back(conn, seed):
    """0065: rows credit mid_back (rhomboids/mid-traps) as a genuine synergist."""
    today = date.today()
    seed.workout(today, "T-Bar Row", [(60.0, 10)] * 4)
    vol = weekly_muscle_volume(conn, _iso_week_start(today))
    assert vol["mid_back"] == 2.0  # 0.5 × 4


def test_wrist_curl_credits_forearms_not_biceps(conn, seed):
    """0065: wrist curls were misclassified as biceps by the 'curl' substring."""
    today = date.today()
    seed.workout(today, "Palms-Down Dumbbell Wrist Curl", [(15.0, 15)] * 3)
    vol = weekly_muscle_volume(conn, _iso_week_start(today))
    assert vol["forearms"] == 3.0
    assert vol.get("biceps", 0.0) == 0.0


def test_non_arm_secondary_keeps_half_credit(conn, seed):
    today = date.today()
    # Hip Thrust → glutes primary, hamstrings secondary (a genuine synergist).
    seed.workout(today, "Hip Thrust (Barbell)", [(100.0, 8)] * 4)
    vol = weekly_muscle_volume(conn, _iso_week_start(today))
    assert vol["glutes"] == 4.0
    assert vol["hamstrings"] == 2.0  # 0.5 × 4, not reduced


def test_rep_window_excludes_heavy_singles(conn, seed):
    """Sets below 5 reps don't count toward hypertrophy landmarks (M1)."""
    today = date.today()
    seed.workout(today, "Bicep Curl (Barbell)", [(40.0, 3), (40.0, 3)])  # heavy, <5 reps
    seed.workout(today, "Bicep Curl (Barbell)", [(25.0, 10)])  # in window
    vol = weekly_muscle_volume(conn, _iso_week_start(today))
    assert vol["biceps"] == 1.0  # only the 10-rep set counts


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
