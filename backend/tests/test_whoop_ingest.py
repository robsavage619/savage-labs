"""shc.ingest.whoop — the I/O-free pieces (no network/OAuth needed).

Date conversion covers the 2026-07-19 fix: sleep/workout/cycle records carry a
real timezone_offset and must use it instead of a hardcoded Pacific-time
assumption, which silently mis-dates a session logged while traveling outside
Pacific time.

Row building + the upsert SQL cover the 2026-07-25 fix: WHOOP sends an early
partial record for a night still in progress and a completed one later, and the
upsert used to refresh the stage durations while leaving ts_in/ts_out at the
partial version — so DailyState.sleep.last_hours (derived from ts_out - ts_in)
understated the night by hours.
"""

from __future__ import annotations

import duckdb

from shc.ingest.whoop import (
    _SLEEP_UPSERT_SQL,
    _parse_offset,
    _sleep_row,
    _sleep_window_mismatch,
    _utc_to_local_date,
)


def test_parse_offset_negative() -> None:
    tz = _parse_offset("-07:00")
    assert tz is not None
    assert tz.utcoffset(None).total_seconds() == -7 * 3600


def test_parse_offset_positive() -> None:
    tz = _parse_offset("+09:00")
    assert tz is not None
    assert tz.utcoffset(None).total_seconds() == 9 * 3600


def test_parse_offset_partial_hour() -> None:
    # India Standard Time — a real-world non-whole-hour offset.
    tz = _parse_offset("+05:30")
    assert tz is not None
    assert tz.utcoffset(None).total_seconds() == 5.5 * 3600


def test_parse_offset_none_or_malformed_returns_none() -> None:
    assert _parse_offset(None) is None
    assert _parse_offset("") is None
    assert _parse_offset("garbage") is None
    assert _parse_offset("07:00") is None  # missing sign


def test_local_date_uses_the_records_own_offset_not_a_hardcoded_zone() -> None:
    """The regression case: the SAME UTC instant must land on a DIFFERENT
    calendar date depending on which offset is supplied — proof the fix
    actually consults the per-record offset instead of a fixed zone."""
    ts = "2026-07-19T06:30:00Z"
    pacific = _utc_to_local_date(ts, "-07:00")
    tokyo = _utc_to_local_date(ts, "+09:00")
    assert pacific == "2026-07-18"
    assert tokyo == "2026-07-19"
    assert pacific != tokyo


def test_local_date_falls_back_to_pacific_when_no_offset_given() -> None:
    """Recovery records carry no timezone_offset at all — must not raise or
    return an empty/garbage date, just use the documented fallback."""
    ts = "2026-07-19T06:30:00Z"
    assert _utc_to_local_date(ts) == _utc_to_local_date(ts, "-07:00")  # PDT in July
    assert _utc_to_local_date(ts, None) == _utc_to_local_date(ts)
    assert _utc_to_local_date(ts, "not-a-real-offset") == _utc_to_local_date(ts)


def test_local_date_empty_timestamp() -> None:
    assert _utc_to_local_date("") == ""


def test_cycle_style_raw_truncation_was_the_bug_this_fixes() -> None:
    """Documents the exact regression: naively slicing the first 10 chars of
    a UTC timestamp (what sync_cycle did before this fix) gives the WRONG
    calendar date for a late-evening-local / early-morning-UTC session."""
    ts = "2026-07-19T06:30:00Z"
    raw_truncation = ts[:10]  # what the old, buggy code computed
    correct = _utc_to_local_date(ts, "-07:00")
    assert raw_truncation == "2026-07-19"
    assert correct == "2026-07-18"
    assert raw_truncation != correct


# ── Partial → completed sleep record (2026-07-25 regression) ─────────────────

# The night of 2026-07-24, as WHOOP actually reported it. The first payload is
# the in-progress record polled mid-night; the second is the completed one.
_SLEEP_START = "2026-07-25T05:26:37.000Z"  # 22:26:37 -07:00 on 2026-07-24


def _record(end: str, *, sws: int, rem: int, light: int, awake: int, in_bed: int) -> dict:
    return {
        "id": "0a4be8be-0844-436a-b8e5-5d8fabc9ec6c",
        "start": _SLEEP_START,
        "end": end,
        "timezone_offset": "-07:00",
        "nap": False,
        "score": {
            "respiratory_rate": 15.2,
            "sleep_performance_percentage": 92.0,
            "sleep_efficiency_percentage": 94.0,
            "sleep_consistency_percentage": 71.0,
            "stage_summary": {
                "total_slow_wave_sleep_time_milli": sws,
                "total_rem_sleep_time_milli": rem,
                "total_light_sleep_time_milli": light,
                "total_awake_time_milli": awake,
                "total_in_bed_time_milli": in_bed,
                "total_no_data_time_milli": 0,
                "disturbance_count": 14,
                "sleep_cycle_count": 7,
            },
            "sleep_needed": {"baseline_milli": 33_240_000},
        },
    }


# Polled at 04:35 local — 369.0 min elapsed, stages consistent with that window.
PARTIAL = _record(
    "2026-07-25T11:35:38.000Z",
    sws=2_700_000,
    rem=3_300_000,
    light=15_000_000,
    awake=1_140_000,
    in_bed=22_140_000,
)

# The completed night: 615.5 min in bed, 578.5 min asleep (9h38m).
COMPLETED = _record(
    "2026-07-25T15:42:09.350Z",
    sws=4_356_000,
    rem=5_616_000,
    light=24_744_000,
    awake=2_220_000,
    in_bed=36_932_350,
)


def _one(conn: duckdb.DuckDBPyConnection, sql: str) -> tuple:
    row = conn.execute(sql).fetchone()
    assert row is not None
    return row


def _stored_hours(conn: duckdb.DuckDBPyConnection) -> float:
    """The exact expression DailyState.sleep.last_hours is derived from."""
    return _one(conn, "SELECT epoch(ts_out - ts_in) / 3600.0 FROM sleep")[0]


def test_completed_record_overwrites_the_partial_records_timestamps(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """The regression: a completed record must replace ts_in/ts_out, not just the
    stage columns. Leaving ts_out at the partial value reported 6.15h for a night
    Rob slept 9h38m, and that number feeds the readiness composite."""
    conn.execute(_SLEEP_UPSERT_SQL, _sleep_row(PARTIAL))
    assert round(_stored_hours(conn), 2) == 6.15  # the truncated window, as polled

    conn.execute(_SLEEP_UPSERT_SQL, _sleep_row(COMPLETED))
    assert round(_stored_hours(conn), 2) == 10.26  # 615.5 min in bed

    row = _one(conn, "SELECT in_bed_min, awake_min, night_date FROM sleep")
    assert row[0] == 615.5
    assert round((row[0] - row[1]) / 60, 2) == 9.64  # 9h38m asleep
    assert str(row[2]) == "2026-07-24"


def test_upsert_never_re_dates_a_stored_night(conn: duckdb.DuckDBPyConnection) -> None:
    """night_date stays at whatever the row was first written with, even when the
    record's own start says otherwise. Refreshing it re-dated 682 rows by a day on
    2026-07-25 (migration 0075 restored them): pre-2026-07-19 rows hold a UTC
    truncation of `start` — the WAKE date — while _utc_to_local_date returns the
    ONSET date, and `sleep.night_date = recovery.date` is built on the former."""
    conn.execute(_SLEEP_UPSERT_SQL, _sleep_row(PARTIAL))
    conn.execute("UPDATE sleep SET night_date = DATE '2026-07-25'")  # the old convention

    conn.execute(_SLEEP_UPSERT_SQL, _sleep_row(COMPLETED))
    assert str(_one(conn, "SELECT night_date FROM sleep")[0]) == "2026-07-25"
    assert round(_stored_hours(conn), 2) == 10.26  # the durations still update


def test_upsert_leaves_one_row_and_stays_internally_consistent(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    for record in (PARTIAL, COMPLETED):
        conn.execute(_SLEEP_UPSERT_SQL, _sleep_row(record))
    assert _one(conn, "SELECT count(*) FROM sleep")[0] == 1
    elapsed = _stored_hours(conn) * 60
    in_bed = _one(conn, "SELECT in_bed_min FROM sleep")[0]
    assert abs(elapsed - in_bed) < 2.0


def test_window_guard_is_quiet_on_self_consistent_records() -> None:
    assert _sleep_window_mismatch(_sleep_row(PARTIAL)) is None
    assert _sleep_window_mismatch(_sleep_row(COMPLETED)) is None


def test_window_guard_flags_the_mixed_version_row() -> None:
    """The bug's signature: the partial record's timestamps carrying the
    completed record's durations."""
    mixed = _sleep_row(COMPLETED)
    mixed["ts_out"] = PARTIAL["end"]
    msg = _sleep_window_mismatch(mixed)
    assert msg is not None
    assert "369.0" in msg and "615.5" in msg


def test_window_guard_is_one_sided() -> None:
    """A window that runs LONGER than the stage totals is normal in the history
    (178 of Rob's 968 synced nights) — only a window too short to contain the
    reported in-bed time is impossible, and that's the bug's direction."""
    longer = _sleep_row(COMPLETED)
    longer["ts_out"] = "2026-07-25T16:42:09.350Z"  # an hour past the stage total
    assert _sleep_window_mismatch(longer) is None


def test_window_guard_tolerates_missing_timestamps() -> None:
    row = _sleep_row(COMPLETED)
    row["ts_out"] = None
    assert _sleep_window_mismatch(row) is None
