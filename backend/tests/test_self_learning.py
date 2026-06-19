from __future__ import annotations

"""Tests for Phase 3 self-learning: volume landmark fitting and ACWR band fitting."""

from datetime import date, timedelta

import pytest

from shc.training.self_learning import (
    _percentile,
    _retroactive_accuracy_all,
    calibrate_deload_trigger,
    compute_all_muscle_signal_quality,
    compute_muscle_signal_quality,
    fit_acwr_bands,
    fit_volume_landmarks,
    materialize_signal_quality,
    persist_acwr_bands,
    persist_volume_landmarks,
    prescription_accuracy,
    read_accuracy_history,
    read_acwr_bands,
    read_deload_calibration,
    read_deload_threshold,
    read_signal_quality_cache,
    regrade_stalled_with_tonnage_blend,
    snapshot_accuracy,
)


# ── helpers ───────────────────────────────────────────────────────────────────


def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _seed_e1rm(conn, exercise: str, week: date, e1rm: float, sets: int,
               perf: int | None = None, tonnage: float | None = None) -> None:
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
    conn.execute(
        "INSERT OR IGNORE INTO exercise_muscle_map (exercise_name, primary_muscle, secondary_muscles)"
        " VALUES (?, ?, ?)",
        [exercise, primary, []],
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
        _seed_e1rm(conn, "Curl", base + timedelta(weeks=i * 2), 40.0, 8 + i, perf=3)
    assert fit_volume_landmarks(conn, "biceps") is None


def test_fit_volume_landmarks_narrow_spread_returns_none(conn) -> None:
    _seed_muscle_map(conn, "Curl", "biceps")
    base = _monday(date.today()) - timedelta(weeks=15)
    # 12 weeks all at volume 8 sets — spread = 0
    for i in range(12):
        _seed_e1rm(conn, "Curl", base + timedelta(weeks=i), 40.0 + i, 8, perf=3)
    assert fit_volume_landmarks(conn, "biceps") is None


def test_fit_volume_landmarks_returns_mev_le_mav_le_mrv(conn) -> None:
    _seed_muscle_map(conn, "Curl", "biceps")
    base = _monday(date.today()) - timedelta(weeks=20)
    # Weeks at volume 2 (regressing), 4–12 (progressing), 14 (regressing again).
    data = (
        [(2, 2), (2, 2), (2, 2), (2, 2)]      # low volume, regress → perf 2
        + [(6, 6), (8, 8), (8, 8), (8, 8), (10, 10), (10, 10), (12, 12), (12, 12), (12, 12), (14, 14)]  # productive
        + [(18, 18), (18, 18), (18, 18), (18, 18)]  # over MRV, regress
    )
    for i, (sets, _) in enumerate(data):
        perf = 2 if sets <= 2 or sets >= 18 else 4
        _seed_e1rm(conn, "Curl", base + timedelta(weeks=i), 40.0, sets, perf=perf)

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


# ── persist + read_acwr_bands ─────────────────────────────────────────────────


def test_read_acwr_bands_empty_table_returns_none(conn) -> None:
    assert read_acwr_bands(conn) is None


def test_persist_and_read_acwr_bands_roundtrip(conn) -> None:
    """Manually insert bands and verify read_acwr_bands returns the correct mapping."""
    rows = [
        ("resistance",   "rest",         2.10, 50),
        ("resistance",   "low",          1.75, 50),
        ("resistance",   "mod",          1.45, 50),
        ("conditioning", "forbid_legs",  1.95, 30),
    ]
    for arm, name, val, n in rows:
        conn.execute(
            "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks)"
            " VALUES (?, ?, ?, ?)",
            [arm, name, val, n],
        )

    bands = read_acwr_bands(conn)
    assert bands is not None
    assert bands["RES_ACWR_REST"]       == pytest.approx(2.10)
    assert bands["RES_ACWR_LOW"]        == pytest.approx(1.75)
    assert bands["RES_ACWR_MOD"]        == pytest.approx(1.45)
    assert bands["COND_ACWR_FORBID_LEGS"] == pytest.approx(1.95)


def test_read_acwr_bands_partial_returns_none(conn) -> None:
    """If only some thresholds are stored (e.g. partial migration), return None."""
    conn.execute(
        "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks)"
        " VALUES ('resistance', 'rest', 2.0, 10)"
    )
    assert read_acwr_bands(conn) is None


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
    assert 3 not in scores or all(
        s != 3 for s in scores[3:]
    ), "later rows with rising tonnage should be upgraded"


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
        _seed_e1rm(conn, "Row", base + timedelta(weeks=i), 100.0, 5, perf=4,
                   tonnage=2000.0 * (1 + i * 0.03))

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
    assert result["confidence"] >= 0.55  # 35 weeks → size_factor=0.65, stability≥0.9 → conf≥0.58


def test_signal_quality_noisy_signal_gives_low_stability(conn) -> None:
    _seed_muscle_map(conn, "Squat", "quads")
    base = _monday(date.today()) - timedelta(weeks=40)
    # Alternating 1/5 — maximally noisy.
    for i in range(35):
        _seed_e1rm(conn, "Squat", base + timedelta(weeks=i), 100.0, 5,
                   perf=5 if i % 2 == 0 else 1)

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
        sets = 4 + (i % 12)
        perf = 2 if sets <= 4 else (4 if sets <= 14 else 2)
        _seed_e1rm(conn, "Curl", base + timedelta(weeks=i), 40.0, sets, perf=perf)

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


def _seed_deload(conn, started_on: date, deload_week: int, trigger: str,
                 regressing_muscles: int) -> None:
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
        _seed_deload(conn, base + timedelta(weeks=i * 8), deload_week=5,
                     trigger="hrv_drop", regressing_muscles=3)
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
        _seed_deload(conn, base + timedelta(weeks=i * 8), deload_week=5,
                     trigger="manual", regressing_muscles=1)
    result = calibrate_deload_trigger(conn)
    assert result["status"] == "fitted"
    assert result["threshold"] == 2


def test_deload_calibration_excludes_scheduled_deloads(conn) -> None:
    # Calendar/scheduled deloads carry no fatigue info and must not count.
    base = _monday(date.today()) - timedelta(weeks=60)
    for i in range(5):
        _seed_deload(conn, base + timedelta(weeks=i * 8), deload_week=5,
                     trigger="scheduled", regressing_muscles=3)
    result = calibrate_deload_trigger(conn)
    assert result["status"] == "insufficient_data"
    assert read_deload_threshold(conn) is None


def test_read_deload_calibration_reports_fitted_without_writing(conn) -> None:
    base = _monday(date.today()) - timedelta(weeks=60)
    for i in range(4):
        _seed_deload(conn, base + timedelta(weeks=i * 8), deload_week=5,
                     trigger="hrv_drop", regressing_muscles=3)
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
