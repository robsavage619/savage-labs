from __future__ import annotations

"""Tests for Phase 3 self-learning: volume landmark fitting and ACWR band fitting."""

import uuid
from datetime import date, datetime, timedelta

import pytest

import shc.training.self_learning as sl
from shc.training.self_learning import (
    _percentile,
    _retroactive_accuracy_all,
    calibrate_deload_trigger,
    compute_all_muscle_signal_quality,
    compute_muscle_signal_quality,
    fit_acwr_bands,
    fit_sleep_bands,
    fit_volume_landmarks,
    materialize_signal_quality,
    persist_acwr_bands,
    persist_sleep_bands,
    persist_volume_landmarks,
    prescription_accuracy,
    read_accuracy_history,
    read_acwr_bands,
    read_deload_calibration,
    read_deload_threshold,
    read_muscle_prescription_accuracy,
    read_signal_quality_cache,
    read_sleep_bands,
    regrade_stalled_with_tonnage_blend,
    score_prescription_outcomes,
    snapshot_accuracy,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _seed_e1rm(
    conn,
    exercise: str,
    week: date,
    e1rm: float,
    sets: int,
    perf: int | None = None,
    tonnage: float | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO exercise_weekly_e1rm
            (exercise, week_start, e1rm_kg, work_sets, perf_score,
             trend, weekly_tonnage_kg, computed_at)
        VALUES (?, ?, ?, ?, ?, NULL, ?, now())
        ON CONFLICT (exercise, week_start) DO UPDATE SET
            e1rm_kg=excluded.e1rm_kg, work_sets=excluded.work_sets,
            perf_score=excluded.perf_score, weekly_tonnage_kg=excluded.weekly_tonnage_kg
        """,
        [exercise, week.isoformat(), e1rm, sets, perf, tonnage],
    )


def _seed_muscle_map(conn, exercise: str, primary: str) -> None:
    # exercise_muscle_map is now a view over exercise_muscle (migration 0066) —
    # seed the canonical table directly.
    conn.execute(
        "INSERT OR IGNORE INTO exercise_muscle (exercise_name, muscle, role, credit)"
        " VALUES (?, ?, 'primary', 1.0)",
        [exercise, primary],
    )


def _seed_workout_sets(
    conn,
    exercise: str,
    week: date,
    n_sets: int,
    weight_kg: float = 40.0,
    reps: int = 10,
) -> None:
    """Seed a hevy workout + n_sets working sets on the Monday of ``week``.

    Uses reps=10 (inside the 5–30 stimulating window) and rpe=NULL so every
    set is counted as stimulating by muscle_weekly_volume_series.
    """
    if n_sets == 0:
        return
    started_at = datetime.combine(week, datetime.min.time())
    wid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO workouts (id, source, started_at, kind, content_hash)"
        " VALUES (?, 'hevy', ?, 'strength', ?)",
        [wid, started_at, wid],
    )
    for idx in range(n_sets):
        sid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO workout_sets"
            " (id, workout_id, exercise, set_idx, reps, weight_kg, is_warmup, content_hash)"
            " VALUES (?, ?, ?, ?, ?, ?, false, ?)",
            [sid, wid, exercise, idx, reps, weight_kg, sid],
        )


# ── _percentile ───────────────────────────────────────────────────────────────


def test_percentile_median() -> None:
    assert _percentile([1.0, 2.0, 3.0, 4.0, 5.0], 0.5) == pytest.approx(3.0)


def test_percentile_min_max() -> None:
    vals = [10.0, 20.0, 30.0]
    assert _percentile(vals, 0.0) == pytest.approx(10.0)
    assert _percentile(vals, 1.0) == pytest.approx(30.0)


def test_percentile_empty_raises() -> None:
    with pytest.raises(ValueError):
        _percentile([], 0.5)


# ── fit_volume_landmarks ──────────────────────────────────────────────────────


def test_fit_volume_landmarks_insufficient_weeks_returns_none(conn) -> None:
    _seed_muscle_map(conn, "Curl", "biceps")
    # Only 5 weeks — below the 10-week minimum.
    base = _monday(date.today()) - timedelta(weeks=20)
    for i in range(5):
        week = base + timedelta(weeks=i * 2)
        _seed_e1rm(conn, "Curl", week, 40.0, 8 + i, perf=3)
        _seed_workout_sets(conn, "Curl", week, 8 + i)
    assert fit_volume_landmarks(conn, "biceps") is None


def test_fit_volume_landmarks_narrow_spread_returns_none(conn) -> None:
    _seed_muscle_map(conn, "Curl", "biceps")
    base = _monday(date.today()) - timedelta(weeks=15)
    # 12 weeks all at volume 8 sets — spread = 0
    for i in range(12):
        week = base + timedelta(weeks=i)
        _seed_e1rm(conn, "Curl", week, 40.0 + i, 8, perf=3)
        _seed_workout_sets(conn, "Curl", week, 8)
    assert fit_volume_landmarks(conn, "biceps") is None


def test_fit_volume_landmarks_returns_mev_le_mav_le_mrv(conn) -> None:
    _seed_muscle_map(conn, "Curl", "biceps")
    base = _monday(date.today()) - timedelta(weeks=20)
    # Weeks at volume 2 (regressing), 4–12 (progressing), 14 (regressing again).
    data = (
        [(2, 2), (2, 2), (2, 2), (2, 2)]  # low volume, regress → perf 2
        + [
            (6, 6),
            (8, 8),
            (8, 8),
            (8, 8),
            (10, 10),
            (10, 10),
            (12, 12),
            (12, 12),
            (12, 12),
            (14, 14),
        ]  # productive
        + [(18, 18), (18, 18), (18, 18), (18, 18)]  # over MRV, regress
    )
    for i, (sets, _) in enumerate(data):
        week = base + timedelta(weeks=i)
        perf = 2 if sets <= 2 or sets >= 18 else 4
        _seed_e1rm(conn, "Curl", week, 40.0, sets, perf=perf)
        _seed_workout_sets(conn, "Curl", week, sets)

    result = fit_volume_landmarks(conn, "biceps")
    assert result is not None, "should fit with enough spread and samples"
    assert result["mev"] <= result["mav"] <= result["mrv"]
    assert result["mev"] >= 0
    assert result["mrv"] > result["mev"]


# ── fit_acwr_bands ────────────────────────────────────────────────────────────


def test_fit_acwr_bands_insufficient_data_returns_none(conn) -> None:
    # Empty v_daily_load → no ACWR history → returns None.
    result = fit_acwr_bands(conn, min_weeks=12)
    assert result is None


def _whoop_strain(conn, day: date, strain: float) -> None:
    wid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO workouts (id, source, started_at, kind, strain, content_hash) "
        "VALUES (?, 'whoop', ?, 'running', ?, ?)",
        [wid, datetime.combine(day, datetime.min.time()), strain, wid],
    )


def _seed_dense_acwr_history(conn, seed, weeks: int = 20) -> None:
    """Dense daily hevy tonnage + WHOOP strain for `weeks` weeks — comfortably
    clears both _ACWR_MIN_WEEKS (12) and the per-week _ACWR_MIN_CHRONIC_DAYS (7)
    floor, since every day has nonzero load for both arms."""
    base = date.today() - timedelta(weeks=weeks)
    for i in range(weeks * 7):
        d = base + timedelta(days=i)
        seed.workout(d, "Bench Press (Barbell)", [(100.0, 8)])
        _whoop_strain(conn, d, 10.0)


# ── persist + read_acwr_bands ─────────────────────────────────────────────────


def test_read_acwr_bands_empty_table_returns_none(conn) -> None:
    assert read_acwr_bands(conn) is None


def test_persist_and_read_acwr_bands_roundtrip(conn) -> None:
    """Manually insert bands and verify read_acwr_bands returns the correct mapping."""
    rows = [
        ("resistance", "rest", 2.10, 50),
        ("resistance", "low", 1.75, 50),
        ("resistance", "mod", 1.45, 50),
        ("conditioning", "forbid_legs", 1.95, 30),
    ]
    for arm, name, val, n in rows:
        conn.execute(
            "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks)"
            " VALUES (?, ?, ?, ?)",
            [arm, name, val, n],
        )

    bands = read_acwr_bands(conn)
    assert bands is not None
    assert bands["RES_ACWR_REST"] == pytest.approx(2.10)
    assert bands["RES_ACWR_LOW"] == pytest.approx(1.75)
    assert bands["RES_ACWR_MOD"] == pytest.approx(1.45)
    assert bands["COND_ACWR_FORBID_LEGS"] == pytest.approx(1.95)


def test_read_acwr_bands_partial_returns_none(conn) -> None:
    """A table with only resistance rows (e.g. a pre-remediation table
    persist_acwr_bands hasn't cleaned yet) and no conditioning row returns
    None — resistance alone is never usable."""
    conn.execute(
        "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks)"
        " VALUES ('resistance', 'rest', 2.0, 10)"
    )
    assert read_acwr_bands(conn) is None


def test_read_acwr_bands_conditioning_only_is_sufficient(conn) -> None:
    """As of the 2026-07 remediation, resistance is never fitted — a table
    holding ONLY the conditioning row (the normal post-remediation state) must
    still return a usable dict, not None."""
    conn.execute(
        "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks)"
        " VALUES ('conditioning', 'forbid_legs', 1.72, 40)"
    )
    bands = read_acwr_bands(conn)
    assert bands is not None
    assert bands == {"COND_ACWR_FORBID_LEGS": pytest.approx(1.72)}


def test_persist_acwr_bands_deletes_legacy_resistance_rows(conn, seed) -> None:
    """A pre-remediation table with resistance rows gets those rows deleted on
    the next persist_acwr_bands run, so a stale "personal (fitted)" resistance
    value can't keep showing up in status surfaces no code path reads it from."""
    for name, value in (("rest", 1.9), ("low", 1.6), ("mod", 1.3)):
        conn.execute(
            "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks, fitted_at) "
            "VALUES ('resistance', ?, ?, 50, now())",
            [name, value],
        )
    _seed_dense_acwr_history(conn, seed)

    persist_acwr_bands(conn)

    remaining = conn.execute(
        "SELECT COUNT(*) FROM personal_acwr_bands WHERE arm = 'resistance'"
    ).fetchone()[0]
    assert remaining == 0


# ── conditioning tighten-rate limiter ───────────────────────────────────────


def test_conditioning_forbid_legs_tighten_is_rate_limited(conn, seed) -> None:
    """A fit that WANTS to drop forbid_legs by a full point may only move it
    down by _COND_TIGHTEN_MAX_STEP from the previously stored value — breaking
    the gate-suppresses-legs -> less data -> tighter-fit spiral."""
    from shc.training.self_learning import _COND_TIGHTEN_MAX_STEP

    _seed_dense_acwr_history(conn, seed)
    assert persist_acwr_bands(conn) is True
    natural = conn.execute(
        "SELECT value FROM personal_acwr_bands "
        "WHERE arm='conditioning' AND threshold_name='forbid_legs'"
    ).fetchone()[0]

    # Simulate a much higher PRIOR fit (as if an earlier, looser era was fitted).
    inflated_prior = natural + 1.0
    conn.execute(
        "UPDATE personal_acwr_bands SET value = ? "
        "WHERE arm='conditioning' AND threshold_name='forbid_legs'",
        [inflated_prior],
    )

    # Re-fit on the SAME (unchanged) underlying data — the natural fit is still
    # `natural`, a full 1.0 below the (simulated) prior stored value.
    assert persist_acwr_bands(conn) is True
    clamped = conn.execute(
        "SELECT value FROM personal_acwr_bands "
        "WHERE arm='conditioning' AND threshold_name='forbid_legs'"
    ).fetchone()[0]

    assert clamped == pytest.approx(inflated_prior - _COND_TIGHTEN_MAX_STEP), (
        f"expected exactly one max-step tighten from {inflated_prior}, got {clamped} "
        f"(natural fit was {natural})"
    )
    assert clamped > natural, "the clamp must prevent jumping straight to the natural value"


def test_conditioning_forbid_legs_tighten_never_crosses_hard_floor(conn, seed) -> None:
    from shc.metrics import COND_ACWR_FORBID_LEGS
    from shc.training.self_learning import _COND_TIGHTEN_FLOOR_FACTOR

    _seed_dense_acwr_history(conn, seed)
    hard_floor = COND_ACWR_FORBID_LEGS * _COND_TIGHTEN_FLOOR_FACTOR
    conn.execute(
        "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks) "
        "VALUES ('conditioning', 'forbid_legs', ?, 20)",
        [hard_floor + 0.01],
    )

    assert persist_acwr_bands(conn) is True
    value = conn.execute(
        "SELECT value FROM personal_acwr_bands "
        "WHERE arm='conditioning' AND threshold_name='forbid_legs'"
    ).fetchone()[0]
    assert value >= hard_floor


def test_conditioning_forbid_legs_loosening_is_unclamped(conn, seed) -> None:
    """Loosening (moving UP) is not rate-limited — only tightening is."""
    _seed_dense_acwr_history(conn, seed)
    assert persist_acwr_bands(conn) is True
    natural = conn.execute(
        "SELECT value FROM personal_acwr_bands "
        "WHERE arm='conditioning' AND threshold_name='forbid_legs'"
    ).fetchone()[0]

    # Simulate a much LOWER prior fit — the natural value is a big loosening move.
    conn.execute(
        "UPDATE personal_acwr_bands SET value = ? "
        "WHERE arm='conditioning' AND threshold_name='forbid_legs'",
        [natural - 1.0],
    )
    assert persist_acwr_bands(conn) is True
    value = conn.execute(
        "SELECT value FROM personal_acwr_bands "
        "WHERE arm='conditioning' AND threshold_name='forbid_legs'"
    ).fetchone()[0]
    assert value == pytest.approx(natural)


# ── outcome-gated conditioning tighten (2026-07-23 Phase C) ────────────────


def _seed_recovery_score(conn, day: date, score: float) -> None:
    conn.execute(
        "INSERT INTO recovery (id, source, date, score, content_hash) VALUES (?, 'whoop', ?, ?, ?)",
        [str(uuid.uuid4()), day.isoformat(), score, str(uuid.uuid4())],
    )


def test_acwr_outcome_supported_true_when_both_signals_worse(conn, monkeypatch) -> None:
    """Both next-week recovery AND perf must read worse after high-ACWR weeks
    for a tighten to be supported — that's the evidence bar a P80 percentile
    alone never clears."""
    base = _monday(date.today()) - timedelta(weeks=30)
    above_weeks = [base + timedelta(weeks=i) for i in range(6)]
    below_weeks = [base + timedelta(weeks=i) for i in range(10, 12)]
    monkeypatch.setattr(
        sl,
        "_historical_weekly_acwr_rows",
        lambda conn, column: [(w, 2.0) for w in above_weeks] + [(w, 1.0) for w in below_weeks],
    )
    for w in above_weeks:
        _seed_recovery_score(conn, w + timedelta(days=8), 50.0)
        _seed_e1rm(conn, "Curl", w + timedelta(weeks=1), 40.0, 5, perf=2)
    for w in below_weeks:
        _seed_recovery_score(conn, w + timedelta(days=8), 70.0)
        _seed_e1rm(conn, "Curl", w + timedelta(weeks=1), 40.0, 5, perf=4)

    result = sl._acwr_outcome_supported(conn, 1.5)
    assert result["supported"] is True
    assert result["recovery_delta"] < -sl._OUTCOME_RECOVERY_MARGIN
    assert result["perf_delta"] < -sl._OUTCOME_PERF_MARGIN


def test_acwr_outcome_supported_false_with_too_few_high_weeks(conn, monkeypatch) -> None:
    """Fewer than _OUTCOME_MIN_HIGH_WEEKS observable high-ACWR weeks — even with
    a clean adverse signal on those few — isn't enough evidence on n-of-1 data."""
    base = _monday(date.today()) - timedelta(weeks=30)
    above_weeks = [base + timedelta(weeks=i) for i in range(3)]  # below the min of 5
    below_weeks = [base + timedelta(weeks=i) for i in range(10, 12)]
    monkeypatch.setattr(
        sl,
        "_historical_weekly_acwr_rows",
        lambda conn, column: [(w, 2.0) for w in above_weeks] + [(w, 1.0) for w in below_weeks],
    )
    for w in above_weeks:
        _seed_recovery_score(conn, w + timedelta(days=8), 40.0)
    for w in below_weeks:
        _seed_recovery_score(conn, w + timedelta(days=8), 70.0)

    result = sl._acwr_outcome_supported(conn, 1.5)
    assert result["supported"] is False
    assert result["recovery_delta"] is None


def test_acwr_outcome_supported_false_when_signals_disagree(conn, monkeypatch) -> None:
    """Real live-data finding: recovery reads worse but perf does NOT — both
    signals must agree, so a single noisy metric can't shackle training."""
    base = _monday(date.today()) - timedelta(weeks=30)
    above_weeks = [base + timedelta(weeks=i) for i in range(6)]
    below_weeks = [base + timedelta(weeks=i) for i in range(10, 12)]
    monkeypatch.setattr(
        sl,
        "_historical_weekly_acwr_rows",
        lambda conn, column: [(w, 2.0) for w in above_weeks] + [(w, 1.0) for w in below_weeks],
    )
    for w in above_weeks:
        _seed_recovery_score(conn, w + timedelta(days=8), 50.0)
        _seed_e1rm(conn, "Curl", w + timedelta(weeks=1), 40.0, 5, perf=4)  # perf UNCHANGED
    for w in below_weeks:
        _seed_recovery_score(conn, w + timedelta(days=8), 70.0)
        _seed_e1rm(conn, "Curl", w + timedelta(weeks=1), 40.0, 5, perf=4)

    result = sl._acwr_outcome_supported(conn, 1.5)
    assert result["supported"] is False


def test_persist_acwr_bands_unsupported_tighten_falls_back_to_population(conn, seed) -> None:
    """The live-data finding this fix exists for: a percentile fit with no
    seeded recovery/perf outcomes has zero evidence behind a tighten, so the
    population threshold is kept instead of an evidence-free shackle."""
    from shc.metrics import COND_ACWR_FORBID_LEGS

    _seed_dense_acwr_history(conn, seed)  # constant strain -> fit wants to tighten
    assert persist_acwr_bands(conn) is True
    value = conn.execute(
        "SELECT value FROM personal_acwr_bands "
        "WHERE arm='conditioning' AND threshold_name='forbid_legs'"
    ).fetchone()[0]
    assert value == pytest.approx(COND_ACWR_FORBID_LEGS)


def test_persist_acwr_bands_supported_tighten_still_goes_through_clamp(conn, seed) -> None:
    """When outcomes DO support a tighten, the existing rate-limit/floor clamp
    pipeline must still run unchanged — the outcome gate only decides WHETHER
    to attempt a tighten, not how far it may move."""
    from shc.training.self_learning import _COND_TIGHTEN_MAX_STEP

    _seed_dense_acwr_history(conn, seed)
    monkeypatch_result = {
        "supported": True,
        "n_above": 10,
        "recovery_delta": -10.0,
        "perf_delta": -1.0,
    }
    orig = sl._acwr_outcome_supported
    sl._acwr_outcome_supported = lambda conn, candidate: monkeypatch_result
    try:
        assert persist_acwr_bands(conn) is True
        natural = conn.execute(
            "SELECT value FROM personal_acwr_bands "
            "WHERE arm='conditioning' AND threshold_name='forbid_legs'"
        ).fetchone()[0]
        inflated_prior = natural + 1.0
        conn.execute(
            "UPDATE personal_acwr_bands SET value = ? "
            "WHERE arm='conditioning' AND threshold_name='forbid_legs'",
            [inflated_prior],
        )
        assert persist_acwr_bands(conn) is True
        clamped = conn.execute(
            "SELECT value FROM personal_acwr_bands "
            "WHERE arm='conditioning' AND threshold_name='forbid_legs'"
        ).fetchone()[0]
        assert clamped == pytest.approx(inflated_prior - _COND_TIGHTEN_MAX_STEP)
    finally:
        sl._acwr_outcome_supported = orig


# ── acwr_fit_data_changed_since_last_fit ────────────────────────────────────


def test_data_changed_guard_true_with_no_prior_fit(conn) -> None:
    from shc.training.self_learning import acwr_fit_data_changed_since_last_fit

    assert acwr_fit_data_changed_since_last_fit(conn) is True


def test_data_changed_guard_false_when_nothing_new(conn) -> None:
    from shc.training.self_learning import acwr_fit_data_changed_since_last_fit

    conn.execute(
        "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks, fitted_at) "
        "VALUES ('conditioning', 'forbid_legs', 1.8, 20, now())"
    )
    assert acwr_fit_data_changed_since_last_fit(conn) is False


def test_data_changed_guard_true_after_new_workout(conn, seed) -> None:
    from shc.training.self_learning import acwr_fit_data_changed_since_last_fit

    conn.execute(
        "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks, fitted_at) "
        "VALUES ('conditioning', 'forbid_legs', 1.8, 20, now())"
    )
    # seed.workout logs at midnight of the given day — use tomorrow so its
    # timestamp is unambiguously after the fitted_at captured just above (`now()`
    # is today's current wall-clock time, later than today's midnight).
    seed.workout(date.today() + timedelta(days=1), "Bench Press (Barbell)", [(100.0, 8)])
    assert acwr_fit_data_changed_since_last_fit(conn) is True


# ── _historical_weekly_acwr: deload/illness week exclusion ─────────────────


def test_deload_week_excluded_from_acwr_fit_sample(conn, seed) -> None:
    from shc.training.self_learning import _historical_weekly_acwr

    _seed_dense_acwr_history(conn, seed, weeks=20)
    before = _historical_weekly_acwr(conn, "hevy_tonnes")

    # Flag one week (well inside the history, away from the edges so its
    # ratio is unambiguously present in `before`) as a systemic deload week —
    # a real deload prescription logs 'deload' for every targeted muscle, so a
    # single row is a faithful stand-in for "this whole week was a deload".
    weeks_present = sorted(
        {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT date_trunc('week', date)::DATE FROM v_daily_load"
            ).fetchall()
        }
    )
    target_week = weeks_present[len(weeks_present) // 2]
    conn.execute(
        "INSERT INTO muscle_prescription_log (week_start, muscle, action, target_sets) "
        "VALUES (?, 'chest', 'deload', 8)",
        [target_week],
    )

    after = _historical_weekly_acwr(conn, "hevy_tonnes")
    assert len(after) == len(before) - 1, (
        f"expected exactly one week excluded, before={len(before)} after={len(after)}"
    )


def test_illness_week_excluded_from_acwr_fit_sample(conn, seed) -> None:
    from shc.training.self_learning import _historical_weekly_acwr

    _seed_dense_acwr_history(conn, seed, weeks=20)
    before = _historical_weekly_acwr(conn, "whoop_strain")

    weeks_present = sorted(
        {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT date_trunc('week', date)::DATE FROM v_daily_load"
            ).fetchall()
        }
    )
    target_week = weeks_present[len(weeks_present) // 2]
    conn.execute(
        "INSERT INTO daily_checkin (date, illness_flag, created_at) VALUES (?, TRUE, now())",
        [target_week + timedelta(days=2)],
    )

    after = _historical_weekly_acwr(conn, "whoop_strain")
    assert len(after) == len(before) - 1, (
        f"expected exactly one week excluded, before={len(before)} after={len(after)}"
    )


def test_no_deload_or_illness_leaves_fit_sample_unchanged(conn, seed) -> None:
    """Sanity check: the exclusion doesn't fire on clean data."""
    from shc.training.self_learning import _historical_weekly_acwr

    _seed_dense_acwr_history(conn, seed, weeks=20)
    r1 = _historical_weekly_acwr(conn, "hevy_tonnes")
    r2 = _historical_weekly_acwr(conn, "hevy_tonnes")
    assert r1 == r2


# ── fit_sleep_bands ───────────────────────────────────────────────────────────


def test_fit_sleep_bands_insufficient_data_returns_none(conn) -> None:
    # Empty sleep table → no nightly history → returns None.
    result = fit_sleep_bands(conn, min_nights=30)
    assert result is None


def _insert_night(conn, night_date: date, disturbance_count: int, sleep_cycle_count: int) -> None:
    conn.execute(
        """
        INSERT INTO sleep (id, source, night_date, ts_in, ts_out,
                            disturbance_count, sleep_cycle_count, content_hash)
        VALUES (?, 'whoop', ?, ?, ?, ?, ?, ?)
        """,
        [
            f"night-{night_date.isoformat()}",
            night_date,
            datetime.combine(night_date, datetime.min.time()),
            datetime.combine(night_date, datetime.min.time()) + timedelta(hours=8),
            disturbance_count,
            sleep_cycle_count,
            f"hash-{night_date.isoformat()}",
        ],
    )


def test_fit_sleep_bands_returns_none_below_min_nights(conn) -> None:
    today = date(2026, 6, 1)
    for i in range(20):  # below the 30-night minimum
        _insert_night(conn, today - timedelta(days=i), disturbance_count=14, sleep_cycle_count=2)
    assert fit_sleep_bands(conn, min_nights=30) is None


def test_fit_sleep_bands_reflects_chronic_osa_baseline(conn) -> None:
    """A consistently high-disturbance/low-cycle history (simulated untreated
    OSA) should fit a personal band well above/below the population default,
    not just reproduce it."""
    today = date(2026, 6, 1)
    for i in range(40):
        _insert_night(conn, today - timedelta(days=i), disturbance_count=14, sleep_cycle_count=2)
    result = fit_sleep_bands(conn, min_nights=30)
    assert result is not None
    assert result["disturbance_p80"] == pytest.approx(14.0)
    assert result["cycle_p20"] == pytest.approx(2.0)
    assert result["disturbance_n"] == 40
    assert result["cycle_n"] == 40


# ── persist + read_sleep_bands ────────────────────────────────────────────────


def test_read_sleep_bands_empty_table_returns_none(conn) -> None:
    assert read_sleep_bands(conn) is None


def test_persist_and_read_sleep_bands_roundtrip(conn) -> None:
    today = date(2026, 6, 1)
    for i in range(40):
        _insert_night(conn, today - timedelta(days=i), disturbance_count=14, sleep_cycle_count=2)

    stored = persist_sleep_bands(conn, min_nights=30)
    assert stored is True

    bands = read_sleep_bands(conn)
    assert bands is not None
    assert bands["DISTURBANCE_P80"] == pytest.approx(14.0)
    assert bands["CYCLE_P20"] == pytest.approx(2.0)


def test_persist_sleep_bands_insufficient_data_returns_false(conn) -> None:
    assert persist_sleep_bands(conn, min_nights=30) is False
    assert read_sleep_bands(conn) is None


def test_read_sleep_bands_partial_returns_none(conn) -> None:
    """If only one metric is stored (e.g. partial migration), return None."""
    conn.execute(
        "INSERT INTO personal_sleep_bands (metric, threshold_name, value, sample_nights)"
        " VALUES ('disturbance_count', 'p80', 14.0, 40)"
    )
    assert read_sleep_bands(conn) is None


# ── persist_volume_landmarks ─────────────────────────────────────────────────


# ── regrade_stalled_with_tonnage_blend ───────────────────────────────────────


def test_regrade_upgrades_stalled_row_with_rising_tonnage(conn) -> None:
    _seed_muscle_map(conn, "Curl", "biceps")
    base = _monday(date.today()) - timedelta(weeks=10)
    # Seed 7 consecutive weeks with rising tonnage but flat e1RM → perf should be 3.
    # Then verify regrade upgrades the 7th week to 4.
    for i in range(7):
        tonnage = 1000.0 * (1 + i * 0.02)  # rising ~2%/week
        _seed_e1rm(conn, "Curl", base + timedelta(weeks=i), 40.0, 5, perf=3, tonnage=tonnage)

    upgraded = regrade_stalled_with_tonnage_blend(conn)
    assert upgraded > 0, "should upgrade at least one stalled row with rising tonnage"

    # All upgraded rows should now have perf=4.
    rows = conn.execute(
        "SELECT week_start, perf_score FROM exercise_weekly_e1rm "
        "WHERE exercise='Curl' ORDER BY week_start"
    ).fetchall()
    scores = [r[1] for r in rows]
    assert 4 in scores, "at least one row should be upgraded to perf=4"
    assert 3 not in scores or all(s != 3 for s in scores[3:]), (
        "later rows with rising tonnage should be upgraded"
    )


def test_regrade_does_not_touch_flat_tonnage(conn) -> None:
    _seed_muscle_map(conn, "Press", "chest")
    base = _monday(date.today()) - timedelta(weeks=8)
    # Flat tonnage — should NOT be upgraded.
    for i in range(7):
        _seed_e1rm(conn, "Press", base + timedelta(weeks=i), 80.0, 5, perf=3, tonnage=1000.0)

    upgraded = regrade_stalled_with_tonnage_blend(conn)
    assert upgraded == 0, "flat tonnage should not trigger upgrade"


def test_regrade_does_not_touch_non_stalled_rows(conn) -> None:
    _seed_muscle_map(conn, "Row", "lats")
    base = _monday(date.today()) - timedelta(weeks=8)
    # Already progressing (perf=4) with rising tonnage — must not be touched.
    for i in range(7):
        _seed_e1rm(
            conn,
            "Row",
            base + timedelta(weeks=i),
            100.0,
            5,
            perf=4,
            tonnage=2000.0 * (1 + i * 0.03),
        )

    upgraded = regrade_stalled_with_tonnage_blend(conn)
    assert upgraded == 0, "progressing rows must not be re-graded"


# ── compute_muscle_signal_quality ─────────────────────────────────────────────


def test_signal_quality_empty_returns_zero(conn) -> None:
    result = compute_muscle_signal_quality(conn, "biceps")
    assert result["confidence"] == 0.0
    assert result["scored_weeks"] == 0


def test_signal_quality_stable_signal_gives_high_stability(conn) -> None:
    _seed_muscle_map(conn, "Curl", "biceps")
    base = _monday(date.today()) - timedelta(weeks=40)
    # 35 weeks of perfectly consistent perf=4 (stable signal).
    for i in range(35):
        _seed_e1rm(conn, "Curl", base + timedelta(weeks=i), 40.0, 5, perf=4)

    result = compute_muscle_signal_quality(conn, "biceps")
    assert result["signal_stability"] >= 0.9, "perfectly stable signal should score high"
    assert result["scored_weeks"] == 35
    # size_factor is now a continuous ramp (not a step function) between the
    # n=30/0.50 and n=60/0.65 anchors; at n=35 that's ~0.525, so confidence with
    # stability=1.0 lands ~0.53 — well above a thin-data muscle, below the
    # n=60+ plateau.
    assert 0.45 <= result["confidence"] <= 0.60


def test_signal_quality_noisy_signal_gives_low_stability(conn) -> None:
    _seed_muscle_map(conn, "Squat", "quads")
    base = _monday(date.today()) - timedelta(weeks=40)
    # Alternating 1/5 — maximally noisy.
    for i in range(35):
        _seed_e1rm(conn, "Squat", base + timedelta(weeks=i), 100.0, 5, perf=5 if i % 2 == 0 else 1)

    result = compute_muscle_signal_quality(conn, "quads")
    assert result["signal_stability"] < 0.2, "alternating signal should score very low"


def test_compute_all_muscle_signal_quality_returns_all_muscles(conn) -> None:
    _seed_muscle_map(conn, "Curl", "biceps")
    _seed_muscle_map(conn, "Press", "chest")
    base = _monday(date.today()) - timedelta(weeks=5)
    for i in range(4):
        _seed_e1rm(conn, "Curl", base + timedelta(weeks=i), 40.0, 5, perf=4)
        _seed_e1rm(conn, "Press", base + timedelta(weeks=i), 80.0, 5, perf=3)

    result = compute_all_muscle_signal_quality(conn)
    assert "biceps" in result
    assert "chest" in result
    assert result["biceps"]["scored_weeks"] == 4
    assert result["chest"]["scored_weeks"] == 4


# ── persist_volume_landmarks ─────────────────────────────────────────────────


def test_persist_volume_landmarks_writes_scoped_rows(conn) -> None:
    _seed_muscle_map(conn, "Curl", "biceps")
    conn.execute(
        "INSERT OR IGNORE INTO muscle_volume_targets "
        "(muscle_group, mev_sets, mav_sets, mrv_sets, mesocycle_id) "
        "VALUES ('biceps', 6, 12, 20, '')"
    )
    base = _monday(date.today()) - timedelta(weeks=25)
    for i in range(20):
        week = base + timedelta(weeks=i)
        sets = 4 + (i % 12)
        perf = 2 if sets <= 4 else (4 if sets <= 14 else 2)
        _seed_e1rm(conn, "Curl", week, 40.0, sets, perf=perf)
        _seed_workout_sets(conn, "Curl", week, sets)

    stored = persist_volume_landmarks(conn, "test-meso-id")
    # May or may not fit depending on bin sampling, but must not crash.
    assert stored >= 0
    if stored > 0:
        row = conn.execute(
            "SELECT mev_sets, mav_sets, mrv_sets FROM muscle_volume_targets "
            "WHERE muscle_group='biceps' AND mesocycle_id='test-meso-id'"
        ).fetchone()
        assert row is not None


# ── signal quality cache ──────────────────────────────────────────────────────


def test_materialize_and_read_cache(conn) -> None:
    _seed_muscle_map(conn, "Curl", "biceps")
    base = _monday(date.today()) - timedelta(weeks=15)
    for i in range(12):
        _seed_e1rm(conn, "Curl", base + timedelta(weeks=i), 40.0, 5, perf=4)

    materialize_signal_quality(conn)
    cache = read_signal_quality_cache(conn)
    assert "biceps" in cache
    assert cache["biceps"]["scored_weeks"] == 12
    assert 0.0 <= cache["biceps"]["confidence"] <= 1.0


def test_read_cache_falls_back_to_live_when_empty(conn) -> None:
    _seed_muscle_map(conn, "Curl", "biceps")
    base = _monday(date.today()) - timedelta(weeks=8)
    for i in range(5):
        _seed_e1rm(conn, "Curl", base + timedelta(weeks=i), 40.0, 5, perf=3)

    # Cache is empty → should fall through to live computation.
    cache = read_signal_quality_cache(conn)
    assert "biceps" in cache


# ── prescription accuracy ─────────────────────────────────────────────────────


def test_retroactive_accuracy_all_with_stable_data(conn) -> None:
    _seed_muscle_map(conn, "Curl", "biceps")
    base = _monday(date.today()) - timedelta(weeks=20)
    for i in range(15):
        # Consistently progressing — model predicts "maintain" and it does.
        _seed_e1rm(conn, "Curl", base + timedelta(weeks=i), 40.0, 5, perf=4)

    result = _retroactive_accuracy_all(conn)
    assert "biceps" in result
    assert result["biceps"]["accuracy"] >= 0.7  # progressing signal stays progressing


def test_retroactive_accuracy_excludes_deload_weeks(conn) -> None:
    """A deload week's depressed perf must not be scored as a missed cut/hold —
    the drop is deliberate, not a training failure (see _muscle_confidence's
    identical exclusion)."""
    _seed_muscle_map(conn, "Curl", "biceps")
    base = _monday(date.today()) - timedelta(weeks=20)
    weeks = [base + timedelta(weeks=i) for i in range(10)]
    for w in weeks:
        _seed_e1rm(conn, "Curl", w, 40.0, 5, perf=4)
    # Deload week in the middle: perf craters by design, not by a failed call.
    deload_week = weeks[5]
    _seed_e1rm(conn, "Curl", deload_week, 40.0, 5, perf=1)
    conn.execute(
        "INSERT INTO muscle_prescription_log (week_start, muscle, action, target_sets) "
        "VALUES (?, 'biceps', 'deload', 4)",
        [deload_week],
    )

    result = _retroactive_accuracy_all(conn)
    # Every pair touching the deload week is dropped: 10 weeks -> 9 possible
    # pairs, minus the 2 pairs (in, out) that touch the excluded week -> 7.
    assert result["biceps"]["n"] == 7
    # The remaining pairs are all stable perf=4 -> perf=4, "add" call sustained.
    assert result["biceps"]["accuracy"] == 1.0


def test_prescription_accuracy_overall_in_range(conn) -> None:
    _seed_muscle_map(conn, "Curl", "biceps")
    base = _monday(date.today()) - timedelta(weeks=15)
    for i in range(10):
        _seed_e1rm(conn, "Curl", base + timedelta(weeks=i), 40.0, 5, perf=4)

    acc = prescription_accuracy(conn)
    assert acc["overall"] is not None
    assert 0.0 <= acc["overall"] <= 1.0
    assert acc["n_scored"] > 0


# ── deload calibration ────────────────────────────────────────────────────────


def test_deload_calibration_no_data_returns_insufficient(conn) -> None:
    result = calibrate_deload_trigger(conn)
    assert result["status"] == "insufficient_data"
    assert result["n_events"] == 0
    assert result["using_population_defaults"] is True
    assert read_deload_threshold(conn) is None


def _seed_deload(
    conn, started_on: date, deload_week: int, trigger: str, regressing_muscles: int
) -> None:
    """Seed a deload event plus its precursor-week perf signals.

    Creates ``regressing_muscles`` distinct muscles each with perf=1 (regressing)
    and two productive muscles (perf=4) in the ISO week before the deload.
    """
    conn.execute(
        "INSERT INTO mesocycles (started_on, planned_weeks, deload_week, deload_trigger)"
        " VALUES (?, ?, ?, ?)",
        [started_on.isoformat(), deload_week, deload_week, trigger],
    )
    deload_start = started_on + timedelta(weeks=deload_week - 1)
    precursor = _monday(deload_start) - timedelta(weeks=1)
    for i in range(regressing_muscles):
        ex = f"reg_ex_{started_on.isoformat()}_{i}"
        _seed_muscle_map(conn, ex, f"reg_muscle_{i}")
        _seed_e1rm(conn, ex, precursor, 40.0, 8, perf=1)
    for i in range(2):
        ex = f"prod_ex_{started_on.isoformat()}_{i}"
        _seed_muscle_map(conn, ex, f"prod_muscle_{i}")
        _seed_e1rm(conn, ex, precursor, 50.0, 8, perf=4)


def test_deload_calibration_fits_from_signal_deloads(conn) -> None:
    # 4 signal-driven deloads, each preceded by 3 regressing muscles → threshold 3.
    base = _monday(date.today()) - timedelta(weeks=60)
    for i in range(4):
        _seed_deload(
            conn,
            base + timedelta(weeks=i * 8),
            deload_week=5,
            trigger="hrv_drop",
            regressing_muscles=3,
        )
    result = calibrate_deload_trigger(conn)
    assert result["status"] == "fitted"
    assert result["n_events"] == 4
    assert result["threshold"] == 3
    assert result["using_population_defaults"] is False
    assert read_deload_threshold(conn) == 3


def test_deload_calibration_clamps_low_precursor_to_floor(conn) -> None:
    # Deloads taken at just 1 regressing muscle should clamp up to the floor (2),
    # not let a single regression deload the athlete.
    base = _monday(date.today()) - timedelta(weeks=60)
    for i in range(4):
        _seed_deload(
            conn,
            base + timedelta(weeks=i * 8),
            deload_week=5,
            trigger="manual",
            regressing_muscles=1,
        )
    result = calibrate_deload_trigger(conn)
    assert result["status"] == "fitted"
    assert result["threshold"] == 2


def test_deload_calibration_excludes_scheduled_deloads(conn) -> None:
    # Calendar/scheduled deloads carry no fatigue info and must not count.
    base = _monday(date.today()) - timedelta(weeks=60)
    for i in range(5):
        _seed_deload(
            conn,
            base + timedelta(weeks=i * 8),
            deload_week=5,
            trigger="scheduled",
            regressing_muscles=3,
        )
    result = calibrate_deload_trigger(conn)
    assert result["status"] == "insufficient_data"
    assert read_deload_threshold(conn) is None


def test_read_deload_calibration_reports_fitted_without_writing(conn) -> None:
    base = _monday(date.today()) - timedelta(weeks=60)
    for i in range(4):
        _seed_deload(
            conn,
            base + timedelta(weeks=i * 8),
            deload_week=5,
            trigger="hrv_drop",
            regressing_muscles=3,
        )
    calibrate_deload_trigger(conn)
    status = read_deload_calibration(conn)
    assert status["status"] == "fitted"
    assert status["threshold"] == 3
    assert status["using_population_defaults"] is False


def test_read_deload_calibration_population_default_when_unfitted(conn) -> None:
    status = read_deload_calibration(conn)
    assert status["status"] == "insufficient_data"
    assert status["threshold"] is None
    assert status["using_population_defaults"] is True


# ── accuracy history snapshot ──────────────────────────────────────────────────


def _log_rx(conn, week: date, muscle: str, action: str, target: int = 10) -> None:
    conn.execute(
        "INSERT INTO muscle_prescription_log "
        "(week_start, muscle, action, target_sets, landmark_source, confidence) "
        "VALUES (?, ?, ?, ?, 'population', 0.5) "
        "ON CONFLICT (week_start, muscle) DO UPDATE SET action = excluded.action",
        [week.isoformat(), muscle, action, target],
    )


def test_score_skips_add_against_deload_outcome_week(conn) -> None:
    # Deload-confound guard: an ADD whose outcome week the muscle was DELOADED in
    # must NOT be scored — the volume cut, not a training failure, drops perf.
    _seed_muscle_map(conn, "Curl", "biceps")
    tw = _monday(date.today())
    pweek = tw - timedelta(weeks=4)  # biceps/add lag = 3 → outcome = tw-1wk (elapsed)
    outcome = pweek + timedelta(weeks=3)
    _log_rx(conn, pweek, "biceps", "add")
    _log_rx(conn, outcome, "biceps", "deload")  # the muscle was deloaded that week
    _seed_e1rm(conn, "Curl", outcome, 40.0, 5, perf=2)  # low perf would mark add wrong
    score_prescription_outcomes(conn)
    row = conn.execute(
        "SELECT outcome_perf, correct FROM muscle_prescription_log "
        "WHERE week_start = ? AND muscle = 'biceps' AND action = 'add'",
        [pweek.isoformat()],
    ).fetchone()
    assert row == (None, None)  # skipped, not a false miss


def test_score_marks_add_wrong_without_deload(conn) -> None:
    # Control: with no deload confound, a low outcome perf correctly marks the ADD
    # wrong — the guard does not over-skip legitimate scoring.
    _seed_muscle_map(conn, "Curl", "biceps")
    tw = _monday(date.today())
    pweek = tw - timedelta(weeks=4)
    outcome = pweek + timedelta(weeks=3)
    _log_rx(conn, pweek, "biceps", "add")
    _seed_e1rm(conn, "Curl", outcome, 40.0, 5, perf=2)
    score_prescription_outcomes(conn)
    row = conn.execute(
        "SELECT correct FROM muscle_prescription_log WHERE week_start = ? AND muscle = 'biceps'",
        [pweek.isoformat()],
    ).fetchone()
    assert row[0] is False


def test_accuracy_source_logged_with_enough_outcomes(conn) -> None:
    # >=5 logged scored outcomes → source 'logged' (the only source the
    # autoregulation hedge is allowed to actuate on).
    _seed_muscle_map(conn, "Curl", "biceps")
    base = _monday(date.today()) - timedelta(weeks=30)
    for i in range(6):
        wk = base + timedelta(weeks=i)
        conn.execute(
            "INSERT INTO muscle_prescription_log "
            "(week_start, muscle, action, target_sets, landmark_source, confidence, "
            " outcome_perf, correct, scored_at) "
            "VALUES (?, 'biceps', 'add', 10, 'population', 0.5, 4, TRUE, now())",
            [wk.isoformat()],
        )
    assert read_muscle_prescription_accuracy(conn)["biceps"]["source"] == "logged"


def test_retroactive_only_muscle_labeled_retroactive(conn) -> None:
    # A muscle with no logged prescriptions but perf history is labelled
    # 'retroactive' — autoregulation ignores this source, so an inferred proxy
    # never damps a real prescription.
    _seed_muscle_map(conn, "Pushdown", "triceps")
    base = _monday(date.today()) - timedelta(weeks=20)
    for i, p in enumerate([4, 3, 4, 3, 4, 3]):
        _seed_e1rm(conn, "Pushdown", base + timedelta(weeks=i), 40.0, 6, perf=p)
    assert read_muscle_prescription_accuracy(conn).get("triceps", {}).get("source") == "retroactive"


def test_snapshot_accuracy_persists_and_reads_back(conn) -> None:
    snap = snapshot_accuracy(conn)
    assert "overall" in snap and "n_scored" in snap
    history = read_accuracy_history(conn)
    assert len(history) == 1
    assert history[0]["week_start"] == snap["week_start"]


def test_snapshot_accuracy_is_idempotent_per_week(conn) -> None:
    snapshot_accuracy(conn)
    snapshot_accuracy(conn)  # same ISO week → upsert, not a second row
    assert len(read_accuracy_history(conn)) == 1
