"""Detraining must never be answered with a deload.

The e1RM regression detector compares peak-vs-peak with no exposure term, so a
lift that got weaker because it stopped being trained looked identical to one
that got weaker from accumulated fatigue. The prescriptions are opposites. These
tests pin the classifier and, more importantly, pin the DIRECTION of its
authority: it may only ever suppress a deload, never cause one (invariant 10 —
under-training is reachable only by stated intent, never by inference).
"""

from __future__ import annotations

from datetime import date, timedelta

from shc.metrics import _regression_cause


def days_ago(today: date, n: int) -> date:
    return today - timedelta(days=n)


EX = "Bench Press (Barbell)"


def test_no_history_at_all_is_detraining(conn, today: date) -> None:
    cause, evidence = _regression_cause(conn, EX, today)
    assert cause == "detrain"
    assert "not trained at all" in evidence


def test_below_maintenance_volume_is_detraining(conn, seed, today: date) -> None:
    """The live case: 4 sessions in 8 weeks is under the MV floor.

    Modelled on Split Squat (Dumbbell) as of 2026-08-20 — the lift that was
    sitting at -11.1% and would have forced a deload the moment the 9-day
    cooldown lapsed. 10 working sets over 8 weeks is 1.25/wk, below MV (2/wk).
    """
    seed.workout(days_ago(today, 49), EX, [(60, 8)])
    seed.workout(days_ago(today, 36), EX, [(60, 8), (58, 8), (58, 8)])
    seed.workout(days_ago(today, 14), EX, [(55, 8), (55, 8), (55, 8)])
    seed.workout(days_ago(today, 11), EX, [(55, 8), (55, 8), (55, 8)])
    cause, evidence = _regression_cause(conn, EX, today)
    assert cause == "detrain"
    assert "maintenance floor" in evidence


def test_zero_exposure_gap_is_detraining_even_at_adequate_volume(conn, seed, today: date) -> None:
    """Volume can clear MV on average while still hiding a long dead stretch.

    Front-loading 8 weeks of sets into the first fortnight averages fine and is
    still three weeks of not training the lift.
    """
    for d in (56, 54, 51, 49, 47, 44):
        seed.workout(days_ago(today, d), EX, [(60, 8), (60, 8), (58, 8)])
    seed.workout(days_ago(today, 2), EX, [(55, 8), (55, 8), (55, 8)])
    cause, evidence = _regression_cause(conn, EX, today)
    assert cause == "detrain"
    assert "untrained" in evidence


def test_a_stale_tail_counts_as_a_gap(conn, seed, today: date) -> None:
    """Trained hard, then stopped 3 weeks ago — the tail is the gap."""
    for d in (56, 53, 50, 47, 44, 41, 38, 35, 32, 29, 26, 23):
        seed.workout(days_ago(today, d), EX, [(60, 8), (60, 8), (58, 8)])
    cause, evidence = _regression_cause(conn, EX, today)
    assert cause == "detrain"
    assert "untrained" in evidence


def test_maintained_exposure_reads_as_overreach(conn, seed, today: date) -> None:
    """Trained twice a week throughout with no gap — fatigue is the live story."""
    for d in range(2, 57, 3):
        seed.workout(days_ago(today, d), EX, [(60, 8), (60, 8), (58, 8)])
    cause, evidence = _regression_cause(conn, EX, today)
    assert cause == "overreach"
    assert "exposure was maintained" in evidence


def test_deload_days_do_not_count_as_exposure(conn, seed, today: date) -> None:
    """A deload week is prescribed rest, not evidence the lift was trained.

    The regression detector already excludes these rows; the exposure term must
    exclude the same ones or it would credit a deload as training and conclude
    'overreach' from sessions that were deliberately light.
    """
    for d in range(2, 57, 3):
        day = days_ago(today, d)
        seed.workout(day, EX, [(60, 8), (60, 8), (58, 8)])
        seed.plan(day, deload_prescribed=True)
    cause, _ = _regression_cause(conn, EX, today)
    assert cause == "detrain"


def test_warmups_and_light_backoffs_do_not_count_as_exposure(conn, seed, today: date) -> None:
    """Exposure counts the same working sets the regression itself scores."""
    for d in range(2, 57, 3):
        seed.workout(days_ago(today, d), EX, [(60, 8), (60, 8), (58, 8)], rpe=5.0)
    cause, _ = _regression_cause(conn, EX, today)
    assert cause == "detrain"


def test_classifier_defaults_to_overreach_so_it_cannot_invent_a_deload(
    conn, seed, today: date
) -> None:
    """The safety direction: this may suppress a deload, never cause one.

    Whatever the exposure evidence says, 'overreach' is only ever the status quo
    the detector already produced — so a wrong answer here can withhold a deload
    (Rob keeps training) but can never impose one (Rob gets rested by a bug).
    """
    for d in range(2, 57, 3):
        seed.workout(days_ago(today, d), EX, [(60, 8), (60, 8), (58, 8)])
    assert _regression_cause(conn, EX, today)[0] == "overreach"
    # And the detraining verdict is strictly a downgrade of that same state.
    seed2_ex = "Squat (Barbell)"
    assert _regression_cause(conn, seed2_ex, today)[0] == "detrain"
