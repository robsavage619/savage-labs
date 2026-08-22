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
    """Primary and secondary both credit 1.0 — the vault's ratio (2026-08-20).

    `helms-2018-qsg-program-building.md`: "count secondary at 1:1 ratio with
    primary; don't rely entirely on indirect volume for any muscle group". The
    previous 0.5 / 0.3-for-arms weights had no vault backing at all. The
    "don't rely entirely" half is enforced separately, by the direct-work floor
    in autoregulation.py — the ratio and the constraint ship together.

    'Pull-Up' maps to lats (primary) + biceps (secondary) after migration 0040
    normalizes the legacy 'back' key.
    """
    today = date.today()
    seed.workout(today, "Pull-Up", [(20.0, 8), (20.0, 8), (20.0, 8)])

    vol = weekly_muscle_volume(conn, _iso_week_start(today))

    assert vol["lats"] == 3.0  # primary
    assert vol["biceps"] == 3.0  # arm secondary — no longer discounted


def test_hammer_curl_credits_forearms(conn, seed):
    """0065: a neutral-grip curl now credits forearms (brachioradialis), not just
    biceps — the landmark-crediting gap where head coverage existed but volume
    didn't."""
    today = date.today()
    seed.workout(today, "Hammer Curl (Dumbbell)", [(20.0, 12)] * 4)
    vol = weekly_muscle_volume(conn, _iso_week_start(today))
    assert vol["biceps"] == 4.0  # primary
    assert vol["forearms"] == 4.0  # arm secondary at the 1:1 rate


def test_row_credits_mid_back(conn, seed):
    """0065: rows credit mid_back (rhomboids/mid-traps) as a genuine synergist."""
    today = date.today()
    seed.workout(today, "T-Bar Row", [(60.0, 10)] * 4)
    vol = weekly_muscle_volume(conn, _iso_week_start(today))
    assert vol["mid_back"] == 4.0  # 1:1 with primary


def test_wrist_curl_credits_forearms_not_biceps(conn, seed):
    """0065: wrist curls were misclassified as biceps by the 'curl' substring."""
    today = date.today()
    seed.workout(today, "Palms-Down Dumbbell Wrist Curl", [(15.0, 15)] * 3)
    vol = weekly_muscle_volume(conn, _iso_week_start(today))
    assert vol["forearms"] == 3.0
    assert vol.get("biceps", 0.0) == 0.0


def test_arm_and_non_arm_secondaries_credit_alike(conn, seed):
    """Arms no longer carry a separate, lower rate.

    The arm discount existed to stop compounds suppressing direct biceps work for
    the emphasis goal. That concern is now handled by the direct-work floor
    instead of by bending the ratio — see `_direct_floor` in autoregulation.py.
    """
    today = date.today()
    # Hip Thrust → glutes primary, hamstrings secondary (a genuine synergist).
    seed.workout(today, "Hip Thrust (Barbell)", [(100.0, 8)] * 4)
    vol = weekly_muscle_volume(conn, _iso_week_start(today))
    assert vol["glutes"] == 4.0
    assert vol["hamstrings"] == 4.0


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
