from __future__ import annotations

import duckdb
import pytest

from shc.api.routers.dashboard import _rolling_mean


def test_rolling_mean_ignores_gaps_without_shifting():
    """A missing night must not move the window — it just contributes nothing."""
    assert _rolling_mean([10.0, None, 20.0], 3) == [10.0, 10.0, 15.0]


def test_rolling_mean_is_none_only_when_the_window_is_empty():
    assert _rolling_mean([None, None], 2) == [None, None]


def test_rolling_mean_window_slides():
    assert _rolling_mean([1.0, 2.0, 3.0, 4.0], 2) == [1.0, 1.5, 2.5, 3.5]


def _conn() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute(
        "CREATE TABLE sleep (night_date DATE, is_nap BOOLEAN, ts_in TIMESTAMP, "
        "ts_out TIMESTAMP, respiratory_rate DOUBLE)"
    )
    c.execute("CREATE TABLE recovery (id VARCHAR, date DATE, spo2 DOUBLE)")
    return c


# The dedupe the endpoint relies on, exercised against the shape that broke it:
# 2026-08-25 carries a 7.4h night, a 1.1h afternoon nap that WHOOP did not flag
# as a nap, and an 8h night — and `recovery` had two rows for the same date.
_PICK_ONE = """
WITH one_sleep AS (
    SELECT night_date, respiratory_rate FROM sleep
    WHERE COALESCE(is_nap, FALSE) = FALSE
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY night_date ORDER BY COALESCE(epoch(ts_out - ts_in), 0) DESC
    ) = 1
),
one_recovery AS (
    SELECT date, spo2 FROM recovery
    QUALIFY ROW_NUMBER() OVER (PARTITION BY date ORDER BY spo2 IS NULL, id) = 1
)
SELECT s.night_date, r.spo2, s.respiratory_rate
FROM one_sleep s LEFT JOIN one_recovery r ON r.date = s.night_date
ORDER BY s.night_date
"""


def test_one_row_per_night_despite_mislabelled_naps_and_duplicate_recovery():
    c = _conn()
    c.execute(
        "INSERT INTO sleep VALUES "
        "(DATE '2026-08-25', FALSE, TIMESTAMP '2026-08-25 00:21', TIMESTAMP '2026-08-25 07:43', 14.0),"
        "(DATE '2026-08-25', FALSE, TIMESTAMP '2026-08-25 17:36', TIMESTAMP '2026-08-25 18:41', 16.0),"
        "(DATE '2026-08-25', FALSE, TIMESTAMP '2026-08-25 23:33', TIMESTAMP '2026-08-26 07:33', 13.0)"
    )
    c.execute(
        "INSERT INTO recovery VALUES ('a', DATE '2026-08-25', 94.0), ('b', DATE '2026-08-25', 91.0)"
    )
    rows = c.execute(_PICK_ONE).fetchall()
    assert len(rows) == 1, "one night must yield one row, not the cross product"
    # The 8h session is the night; the 1.1h afternoon one is the mislabelled nap.
    assert rows[0][2] == pytest.approx(13.0)


def test_a_recovery_row_without_spo2_loses_to_one_that_has_it():
    c = _conn()
    c.execute(
        "INSERT INTO sleep VALUES (DATE '2026-08-25', FALSE, "
        "TIMESTAMP '2026-08-25 23:00', TIMESTAMP '2026-08-26 07:00', 13.0)"
    )
    c.execute(
        "INSERT INTO recovery VALUES ('a', DATE '2026-08-25', NULL), ('b', DATE '2026-08-25', 93.5)"
    )
    assert c.execute(_PICK_ONE).fetchone()[1] == pytest.approx(93.5)


def test_naps_flagged_as_naps_are_excluded_entirely():
    c = _conn()
    c.execute(
        "INSERT INTO sleep VALUES "
        "(DATE '2026-08-25', TRUE, TIMESTAMP '2026-08-25 13:00', TIMESTAMP '2026-08-25 14:00', 15.0)"
    )
    assert c.execute(_PICK_ONE).fetchall() == []
