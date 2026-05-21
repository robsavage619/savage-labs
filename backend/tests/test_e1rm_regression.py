from __future__ import annotations

from datetime import date, timedelta

from shc.metrics import _deload_in_cooldown, _e1rm_regression


def days_ago(today: date, n: int) -> date:
    return today - timedelta(days=n)


def test_returns_none_with_no_data(conn, today: date) -> None:
    assert _e1rm_regression(conn, today) is None


# Two sets per session so the candidate-selection floor (>=6 sets) is met and
# the exclusion/RPE logic is genuinely exercised (not bypassed as no-data).

def test_ignores_cable_isolation_as_primary(conn, seed, today: date) -> None:
    """The original bug: most-frequent lift was a cable fly. It must not be
    chosen as the strength primary, so no regression is computed off it."""
    for i in range(8):
        seed.workout(days_ago(today, 50 - i * 5), "Low Cable Fly Crossovers",
                     [(40, 12), (35, 12)])
    assert _e1rm_regression(conn, today) is None


def test_picks_free_weight_compound_and_detects_real_regression(conn, seed, today: date) -> None:
    ex = "Bench Press (Barbell)"
    # Prior half: strong. Recent half: clearly weaker (peak ~105 → ~84).
    seed.workout(days_ago(today, 50), ex, [(90, 5), (85, 5)])   # peak 90*1.167=105
    seed.workout(days_ago(today, 44), ex, [(88, 6), (85, 6)])   # peak 88*1.2 =105.6
    seed.workout(days_ago(today, 14), ex, [(70, 5), (68, 5)])   # peak 70*1.167=81.7
    seed.workout(days_ago(today, 7), ex, [(72, 5), (70, 5)])    # peak 72*1.167=84
    pct = _e1rm_regression(conn, today)
    assert pct is not None
    val, lift = pct
    assert lift == ex
    assert val < -3.0


def test_excludes_deload_prescribed_days(conn, seed, today: date) -> None:
    """A light deload day must not manufacture a phantom regression."""
    ex = "Bench Press (Barbell)"
    seed.workout(days_ago(today, 50), ex, [(90, 5), (88, 5)])
    seed.workout(days_ago(today, 44), ex, [(90, 5), (88, 5)])
    seed.workout(days_ago(today, 30), ex, [(90, 5), (88, 5)])
    # Recent sessions are light — but they were prescribed deloads.
    light1, light2 = days_ago(today, 10), days_ago(today, 5)
    seed.workout(light1, ex, [(50, 5), (50, 5)])
    seed.workout(light2, ex, [(50, 5), (50, 5)])
    seed.plan(light1, deload_prescribed=True)
    seed.plan(light2, deload_prescribed=True)
    # Candidate floor met (10 sets), but with deload days excluded only 3 clean
    # sessions remain (<4) → None. No phantom regression from the light loads.
    assert _e1rm_regression(conn, today) is None


def test_excludes_light_backoff_sets_by_rpe(conn, seed, today: date) -> None:
    ex = "Bench Press (Barbell)"
    seed.workout(days_ago(today, 50), ex, [(90, 5), (88, 5)], rpe=9)
    seed.workout(days_ago(today, 44), ex, [(90, 5), (88, 5)], rpe=9)
    # Recent low-RPE technique sets at light load should be ignored.
    seed.workout(days_ago(today, 10), ex, [(40, 5), (40, 5)], rpe=4)
    seed.workout(days_ago(today, 5), ex, [(40, 5), (40, 5)], rpe=4)
    # Candidate floor met, but RPE filter leaves only 2 clean sessions → None.
    assert _e1rm_regression(conn, today) is None


def test_no_regression_when_strength_held(conn, seed, today: date) -> None:
    ex = "Bench Press (Barbell)"
    for i in range(6):
        seed.workout(days_ago(today, 50 - i * 8), ex, [(90, 5), (88, 5)])  # flat
    result = _e1rm_regression(conn, today)
    # Peak is flat → either None (no trigger) or a ~0% non-regression.
    assert result is None or result[0] >= -3.0


# ── _deload_in_cooldown ──────────────────────────────────────────────────────

def test_cooldown_false_with_no_plans(conn, today: date) -> None:
    assert _deload_in_cooldown(conn, today) is False


def test_cooldown_true_after_recent_deload(conn, seed, today: date) -> None:
    seed.plan(days_ago(today, 3), deload_prescribed=True)
    assert _deload_in_cooldown(conn, today) is True


def test_cooldown_ignores_non_deload_plans(conn, seed, today: date) -> None:
    seed.plan(days_ago(today, 3), deload_prescribed=False)
    assert _deload_in_cooldown(conn, today) is False


def test_cooldown_expires_outside_window(conn, seed, today: date) -> None:
    seed.plan(days_ago(today, 20), deload_prescribed=True)  # > 9d
    assert _deload_in_cooldown(conn, today) is False


def test_cooldown_excludes_today(conn, seed, today: date) -> None:
    """Today's own plan must not suppress today's evaluation."""
    seed.plan(today, deload_prescribed=True)
    assert _deload_in_cooldown(conn, today) is False
