"""shc.ingest.whoop — pure date-conversion logic (no network/OAuth needed).

_utc_to_local_date/_parse_offset are the only I/O-free pieces of the WHOOP
ingest module, so this is the only part of it that's unit-testable without
mocking httpx + the keychain. Covers the 2026-07-19 fix: sleep/workout/cycle
records carry a real timezone_offset and must use it instead of a hardcoded
Pacific-time assumption, which silently mis-dates a session logged while
traveling outside Pacific time.
"""

from __future__ import annotations

from shc.ingest.whoop import _parse_offset, _utc_to_local_date


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
