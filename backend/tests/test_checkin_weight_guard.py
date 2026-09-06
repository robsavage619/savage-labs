from __future__ import annotations

import duckdb
import pytest

from shc.api.routers.dashboard import (
    _WEIGHT_ABS_MAX_KG,
    _WEIGHT_ABS_MIN_KG,
    _latest_prior_weight_kg,
    check_weight_plausible,
)

# The rows this guard exists to have stopped: a leading-digit slip put 138 lb
# into a run of 233-239 lb on 2026-05-19 and 2026-05-21.
_TYPO_KG = 62.6  # 138.0 lb
_REAL_KG = 108.4  # 239.0 lb


def test_the_may_2026_typo_is_rejected():
    problem = check_weight_plausible(_TYPO_KG, _REAL_KG)
    assert problem is not None
    assert "138" in problem and "239" in problem


def test_a_plausible_weighing_passes():
    assert check_weight_plausible(107.0, _REAL_KG) is None


def test_absolute_band_catches_nonsense_with_no_history():
    """No prior is the only case the relative test cannot run, so the band must hold."""
    assert check_weight_plausible(_WEIGHT_ABS_MIN_KG - 1, None) is not None
    assert check_weight_plausible(_WEIGHT_ABS_MAX_KG + 1, None) is not None


def test_first_ever_weighing_is_accepted():
    """A value with nothing to be inconsistent with must not be blocked."""
    assert check_weight_plausible(_REAL_KG, None) is None


def test_a_valid_weight_is_not_rejected_on_its_own_merits():
    """62.6 kg is a real human weight — only the neighbours make it impossible."""
    assert check_weight_plausible(_TYPO_KG, None) is None


@pytest.mark.parametrize("prior", [0.0, -1.0])
def test_a_nonpositive_prior_cannot_divide(prior: float):
    assert check_weight_plausible(_REAL_KG, prior) is None


def test_the_boundary_is_inclusive_at_25_percent():
    assert check_weight_plausible(_REAL_KG * 1.25, _REAL_KG) is None
    assert check_weight_plausible(_REAL_KG * 1.2501, _REAL_KG) is not None


def _seeded_conn() -> duckdb.DuckDBPyConnection:
    conn = duckdb.connect(":memory:")
    conn.execute("CREATE TABLE daily_checkin (date DATE, body_weight_kg DOUBLE)")
    conn.execute("CREATE TABLE measurements (ts TIMESTAMP, metric VARCHAR, value_num DOUBLE)")
    return conn


def test_prior_lookup_reads_both_sources_and_takes_the_latest():
    conn = _seeded_conn()
    conn.execute("INSERT INTO daily_checkin VALUES (DATE '2026-05-15', 108.4)")
    conn.execute(
        "INSERT INTO measurements VALUES (TIMESTAMP '2026-05-17 07:00', 'body_mass_kg', 107.0)"
    )
    assert _latest_prior_weight_kg(conn, "2026-05-19") == pytest.approx(107.0)


def test_prior_lookup_excludes_the_target_date_itself():
    """Re-submitting a day must compare against history, not against itself."""
    conn = _seeded_conn()
    conn.execute("INSERT INTO daily_checkin VALUES (DATE '2026-05-15', 108.4)")
    conn.execute("INSERT INTO daily_checkin VALUES (DATE '2026-05-19', 62.6)")
    assert _latest_prior_weight_kg(conn, "2026-05-19") == pytest.approx(108.4)


def test_prior_lookup_ignores_weighings_older_than_the_window():
    conn = _seeded_conn()
    conn.execute("INSERT INTO daily_checkin VALUES (DATE '2020-01-01', 95.0)")
    assert _latest_prior_weight_kg(conn, "2026-05-19") is None


def test_prior_lookup_returns_none_on_an_empty_history():
    assert _latest_prior_weight_kg(_seeded_conn(), "2026-05-19") is None
