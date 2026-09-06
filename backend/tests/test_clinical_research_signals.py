"""Guards for /api/clinical-research/insights.

Every failure this suite exists to catch was live in production and invisible:
the endpoint queried three columns that do not exist (`cardio_sessions.
started_at`, `medications.generic_name`, `measurements.bp_systolic`), and two of
those were wrapped in a bare `except Exception` that turned a schema mismatch
into a rendered em-dash. A tile that silently reports "no data" for a subject
who has data is worse than one that crashes, so these tests assert on VALUES,
never merely that the call returned.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import duckdb
import pytest

from shc.api.routers.dashboard import (
    _allostatic_load,
    _ln_rmssd_trend,
    _recovery_red_streak,
    _sleep_regularity_index,
    _swc,
)

_TODAY = date(2026, 9, 6)


def _sleep(conn: duckdb.DuckDBPyConnection, night: date, bed_hour: float, hours: float) -> None:
    ts_in = datetime.combine(night - timedelta(days=1), datetime.min.time()) + timedelta(hours=bed_hour)
    conn.execute(
        "INSERT INTO sleep (id, source, night_date, ts_in, ts_out, is_nap, content_hash) "
        "VALUES (?, 'whoop', ?, ?, ?, FALSE, ?)",
        [f"s{night}{bed_hour}", night, ts_in, ts_in + timedelta(hours=hours), f"h{night}{bed_hour}"],
    )


def test_sri_scores_the_full_day_not_just_the_sleep_window(conn):
    """A perfectly regular schedule must score ~100.

    The original implementation scored only `[min(start)-30, max(end)+30]`,
    discarding the high-agreement daytime. On a real 11-night window that read
    66.3 ("moderate") where the full-day Phillips SRI was 75.8.
    """
    for i in range(14):
        _sleep(conn, _TODAY - timedelta(days=i), 22.0, 8.0)
    out = _sleep_regularity_index(conn, _TODAY)
    assert out["value"] == pytest.approx(100.0, abs=0.5)
    assert out["n_nights"] == 14


def test_sri_penalises_an_alternating_schedule(conn):
    """Alternating bedtimes 6h apart must land far below a fixed schedule."""
    for i in range(14):
        _sleep(conn, _TODAY - timedelta(days=i), 22.0 if i % 2 == 0 else 16.0, 8.0)
    out = _sleep_regularity_index(conn, _TODAY)
    assert out["value"] is not None
    assert out["value"] < 60


def _recovery(conn: duckdb.DuckDBPyConnection, day: date, hrv: float, score: float = 70.0) -> None:
    conn.execute(
        "INSERT INTO recovery (id, source, date, score, hrv, content_hash) "
        "VALUES (?, 'whoop', ?, ?, ?, ?)",
        [f"r{day}", day, score, hrv, f"rh{day}"],
    )


def test_ln_rmssd_compares_today_against_the_baseline_not_two_smoothed_series(conn):
    """A flat history then a spike today must register as today's delta.

    The previous version compared a 7d mean ending YESTERDAY against a mean of
    rolling means, so a one-day spike was invisible.
    """
    for i in range(28, 0, -1):
        _recovery(conn, _TODAY - timedelta(days=i), 100.0)
    _recovery(conn, _TODAY, 160.0)
    out = _ln_rmssd_trend(conn, _TODAY)
    assert out["delta"] is not None and out["delta"] > 0.4
    assert out["within_noise"] is False


def test_ln_rmssd_calls_a_small_wobble_noise(conn):
    """A delta inside the subject's own SWC must not be reported as a change.

    The baseline alternates 90/110 — genuinely noisy — and today lands on its
    geometric centre, so the delta is ~0 against a wide band. A threshold-only
    tile would still have to call this something; a noise-relative one calls it
    nothing, which is the correct answer.
    """
    for i in range(28, 0, -1):
        _recovery(conn, _TODAY - timedelta(days=i), 90.0 if i % 2 else 110.0)
    _recovery(conn, _TODAY, (90.0 * 110.0) ** 0.5)
    out = _ln_rmssd_trend(conn, _TODAY)
    assert out["swc"] is not None and out["swc"] > 0
    assert out["within_noise"] is True


def test_ln_rmssd_flat_baseline_reports_a_zero_swc_not_a_missing_one(conn):
    """SWC 0.0 is an answer, not an absence — `if swc` used to erase it."""
    for i in range(28, 0, -1):
        _recovery(conn, _TODAY - timedelta(days=i), 100.0)
    _recovery(conn, _TODAY, 100.0)
    out = _ln_rmssd_trend(conn, _TODAY)
    assert out["swc"] == 0.0
    assert out["within_noise"] is False


def test_swc_needs_a_real_window():
    assert _swc([1.0, 2.0, 3.0]) is None
    assert _swc([1.0] * 10) == pytest.approx(0.0)


def test_red_streak_stops_at_the_first_non_red_day(conn):
    for i, score in enumerate([20.0, 25.0, 30.0, 55.0, 20.0]):
        _recovery(conn, _TODAY - timedelta(days=i), 100.0, score)
    out = _recovery_red_streak(conn, _TODAY)
    assert out["consecutive_red_days"] == 3
    assert out["alarm"] is True
    # The vendor provenance must stay visible — this tile spent its life under a
    # blanket "peer-reviewed" badge citing a blog post.
    assert out["peer_reviewed"] is False


def _vital(conn: duckdb.DuckDBPyConnection, metric: str, value: float, when: date) -> None:
    conn.execute(
        "INSERT INTO measurements (source, metric, value_num, ts, external_id, content_hash, ingested_at) "
        "VALUES ('kaiser_summary', ?, ?, ?, ?, ?, now())",
        [metric, value, datetime.combine(when, datetime.min.time()),
         f"m{metric}{when}", f"mh{metric}{when}"],
    )


def test_allostatic_load_reads_blood_pressure(conn):
    """The regression that hid a top-band blood-pressure reading.

    The column is `blood_pressure_systolic`; the endpoint asked for
    `bp_systolic`, got nothing, and silently renormalised the score over the
    markers that happened to survive. Values here are SYNTHETIC — chosen to land
    in bands 2 and 1 — not the subject's, because this repo is public. Same
    reason `test_fib4.py` uses a synthetic date of birth.
    """
    _vital(conn, "blood_pressure_systolic", 145.0, date(2025, 1, 1))
    _vital(conn, "blood_pressure_diastolic", 85.0, date(2025, 1, 1))
    out = _allostatic_load(conn)
    assert out["components"]["bp_systolic"] == 2
    assert out["components"]["bp_diastolic"] == 1
    assert "cardiovascular" in out["axes_covered"]


def test_allostatic_load_reports_what_it_could_not_score(conn):
    """Missing markers move the score, so they must be named on the payload."""
    _vital(conn, "bmi", 30.5, date(2025, 1, 1))
    out = _allostatic_load(conn)
    assert out["n_markers"] == 1
    assert "bp_systolic" in out["missing"]
    assert out["axes_covered"] == ["metabolic"]


def test_allostatic_load_dates_every_input(conn):
    """A score blending a 2023 lipid panel with a 2026 metabolic one must say so."""
    _vital(conn, "bmi", 30.5, date(2023, 12, 3))
    out = _allostatic_load(conn)
    assert out["input_dates"]["bmi"] == "2023-12-03"


def test_no_tile_reports_missing_data_for_a_subject_who_has_it(conn):
    """The umbrella guard: with data present, nothing may come back None.

    This is the shape of every bug this module has had — a query that throws or
    matches nothing, swallowed, rendered as an em-dash.
    """
    for i in range(14):
        _sleep(conn, _TODAY - timedelta(days=i), 22.0, 8.0)
    for i in range(28, -1, -1):
        _recovery(conn, _TODAY - timedelta(days=i), 100.0)
    _vital(conn, "blood_pressure_systolic", 145.0, date(2025, 1, 1))
    _vital(conn, "bmi", 30.5, date(2025, 1, 1))

    assert _sleep_regularity_index(conn, _TODAY)["value"] is not None
    assert _ln_rmssd_trend(conn, _TODAY)["today"] is not None
    assert _allostatic_load(conn)["score_0_10"] is not None
