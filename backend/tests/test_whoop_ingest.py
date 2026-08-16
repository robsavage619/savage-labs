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
    _CARDIO_UPSERT_SQL,
    _SLEEP_UPSERT_SQL,
    _WORKOUT_UPSERT_SQL,
    _cardio_row,
    _high_water_mark,
    _parse_offset,
    _sleep_row,
    _sleep_window_mismatch,
    _utc_to_local_date,
    _workout_row,
    _workout_window_mismatch,
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


def test_sync_all_surfaces_sleep_anomalies_without_faking_a_failure() -> None:
    """Mismatches ride back on the sync result, not only the log — and the key
    they land under must not read as a failed endpoint. `failed_endpoints` scans
    for negative NUMBERS, so a list value has to be ignored by it."""
    from shc.api.routers.report import failed_endpoints

    detail = {"sleep": 968, "sleep_anomalies": ["sleep abc (night 2026-07-24): short by 246.5"]}
    assert failed_endpoints(detail) == []
    assert failed_endpoints({**detail, "workout": -1}) == ["workout"]


# ── Partial → completed workout record (2026-07-25 regression) ───────────────

# Rob's pickleball session on 2026-05-01, as it landed in the live DB: a 16.5-min
# ts window carrying 128.9 min of HR-zone durations. The workouts upsert refreshed
# the zone columns but not started_at/ended_at, so the in-progress record's window
# survived. cardio_sessions.duration_min updated correctly to 129 — which is how
# the two tables ended up disagreeing by nearly two hours about the same session.
_WORKOUT_START = "2026-05-01T23:00:00.010Z"  # 16:00:00 -07:00 on 2026-05-01


def _workout(end: str, *, z0: int, z1: int, z2: int, z3: int, z4: int, z5: int) -> dict:
    return {
        "id": "2b3a822c-bba1-4de1-81b7-65dbf9e241e0",
        "start": _WORKOUT_START,
        "end": end,
        "timezone_offset": "-07:00",
        "sport_id": 65,  # pickleball
        "score": {
            "strain": 17.084349,
            "average_heart_rate": 128,
            "max_heart_rate": 166,
            "kilojoule": 5706.5,
            "percent_recorded": 100.0,
            "zone_durations": {
                "zone_zero_milli": z0,
                "zone_one_milli": z1,
                "zone_two_milli": z2,
                "zone_three_milli": z3,
                "zone_four_milli": z4,
                "zone_five_milli": z5,
            },
        },
    }


# Polled 16.5 min in, while Rob was still on court. Zones consistent with that.
W_PARTIAL = _workout(
    "2026-05-01T23:16:29.010Z",
    z0=180_000,
    z1=300_000,
    z2=240_000,
    z3=240_000,
    z4=30_000,
    z5=0,
)

# The completed session: 128.9 min of zone time across a 128.9-min window.
W_COMPLETED = _workout(
    "2026-05-02T01:08:54.010Z",
    z0=1_176_000,
    z1=1_266_000,
    z2=1_782_000,
    z3=2_892_000,
    z4=618_000,
    z5=0,
)


def _stored_duration_min(conn: duckdb.DuckDBPyConnection) -> float:
    """The exact expression /cardio/recent derives a session's duration from."""
    return _one(conn, "SELECT epoch(ended_at - started_at) / 60.0 FROM workouts")[0]


def test_completed_workout_overwrites_the_partial_records_timestamps(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """The regression: a completed record must replace started_at/ended_at, not
    just the zone columns. Leaving them at the partial values showed a 129-minute
    pickleball session as 16.5 minutes in the Cardio & Sports panel."""
    conn.execute(_WORKOUT_UPSERT_SQL, _workout_row(W_PARTIAL))
    assert round(_stored_duration_min(conn), 1) == 16.5  # the truncated window, as polled

    conn.execute(_WORKOUT_UPSERT_SQL, _workout_row(W_COMPLETED))
    assert round(_stored_duration_min(conn), 1) == 128.9

    row = _one(conn, "SELECT zone_three_min, strain, kind FROM workouts")
    assert row[0] == 48.2
    assert round(row[1], 1) == 17.1
    assert row[2] == "pickleball"


def test_workout_upsert_leaves_one_row_and_stays_internally_consistent(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    for record in (W_PARTIAL, W_COMPLETED):
        conn.execute(_WORKOUT_UPSERT_SQL, _workout_row(record))
    assert _one(conn, "SELECT count(*) FROM workouts")[0] == 1
    zone_sum = _one(
        conn,
        "SELECT zone_zero_min + zone_one_min + zone_two_min "
        "+ zone_three_min + zone_four_min + zone_five_min FROM workouts",
    )[0]
    assert abs(_stored_duration_min(conn) - zone_sum) < 2.0


def test_workouts_and_cardio_sessions_agree_on_duration(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """The two tables are written from the same record and must not drift apart.
    Before the fix cardio_sessions.duration_min refreshed to 129 while the
    workouts window stayed at 16.5 — the live DB held exactly that disagreement."""
    for record in (W_PARTIAL, W_COMPLETED):
        conn.execute(_WORKOUT_UPSERT_SQL, _workout_row(record))
        conn.execute(_CARDIO_UPSERT_SQL, _cardio_row(record))
    cardio_min = _one(conn, "SELECT duration_min FROM cardio_sessions")[0]
    assert cardio_min == 129
    assert abs(_stored_duration_min(conn) - cardio_min) < 2.0


def test_cardio_upsert_never_re_dates_a_stored_session(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    """`date` stays at whatever the row was first written with — the same call
    e7930b9 made for sleep.night_date. It routes through _utc_to_local_date, whose
    meaning changed on 2026-07-19: 59 of 389 stored rows hold a UTC truncation of
    `start`, a day ahead of the local date for evening sessions. Refreshing it
    re-dates them rather than correcting them, and cardio_min_28d windows on it."""
    conn.execute(_CARDIO_UPSERT_SQL, _cardio_row(W_PARTIAL))
    conn.execute("UPDATE cardio_sessions SET date = DATE '2026-05-02'")  # old convention

    conn.execute(_CARDIO_UPSERT_SQL, _cardio_row(W_COMPLETED))
    assert str(_one(conn, "SELECT date FROM cardio_sessions")[0]) == "2026-05-02"
    assert _one(conn, "SELECT duration_min FROM cardio_sessions")[0] == 129  # still updates


def test_workout_window_guard_is_quiet_on_self_consistent_records() -> None:
    assert _workout_window_mismatch(_workout_row(W_PARTIAL)) is None
    assert _workout_window_mismatch(_workout_row(W_COMPLETED)) is None


def test_workout_window_guard_flags_the_mixed_version_row() -> None:
    """The bug's signature: the in-progress record's timestamps carrying the
    completed record's zone durations — the live 2026-05-01 row exactly."""
    mixed = _workout_row(W_COMPLETED)
    mixed["ended_at"] = W_PARTIAL["end"]
    msg = _workout_window_mismatch(mixed)
    assert msg is not None
    assert "16.5" in msg and "128.9" in msg


def test_workout_window_guard_is_one_sided() -> None:
    """A window running LONGER than the zone totals is normal (12 of 785 synced
    WHOOP workouts) — only a window too short to contain them is impossible."""
    longer = _workout_row(W_COMPLETED)
    longer["ended_at"] = "2026-05-02T01:23:54.010Z"  # 15 min past the zone total
    assert _workout_window_mismatch(longer) is None


def test_workout_window_guard_tolerates_missing_data() -> None:
    no_end = _workout_row(W_COMPLETED)
    no_end["ended_at"] = None
    assert _workout_window_mismatch(no_end) is None

    no_zones = _workout_row({**W_COMPLETED, "score": {"strain": 5.0}})
    assert _workout_window_mismatch(no_zones) is None


# --- Refresh-token rotation (2026-08-12) -------------------------------------
#
# WHOOP rotates the refresh token on every use, so a refresh that succeeds
# server-side without handing back a usable replacement strands the connection
# permanently. Two ways that happened here, both invisible for ~an hour (the
# access-token lifetime) and then fatal — which is what made it look like a
# mysterious "WHOOP logs out every day".


def _refresh_body(monkeypatch, response) -> dict:
    """Run `_refresh` against a stubbed WHOOP and return the POST body it sent."""
    import asyncio

    from shc.ingest import whoop as w

    sent: dict = {}
    stored: dict[str, str] = {"refresh_token": "OLD_REFRESH", "access_token": "OLD_ACCESS"}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, url, data=None, **_):
            sent.update(data or {})
            return response

    monkeypatch.setattr(w.httpx, "AsyncClient", lambda *a, **k: _Client())
    monkeypatch.setattr(w, "load_token", lambda src, kind: stored.get(kind))
    monkeypatch.setattr(w, "store_token", lambda src, kind, val: stored.__setitem__(kind, val))
    monkeypatch.setattr(w, "_client_id", lambda: "cid")
    monkeypatch.setattr(w, "_client_secret", lambda: "secret")

    asyncio.run(w._refresh())
    return {"sent": sent, "stored": stored}


def test_refresh_sends_offline_scope(monkeypatch) -> None:
    """Omitting scope=offline spends the refresh token and gets no replacement.

    WHOOP's refresh tutorial lists `scope` as a body parameter: "The offline
    scope allows you to get a new refresh token and an access token." Without
    it the connection dies one access-token lifetime after each refresh.
    """
    import httpx

    resp = httpx.Response(
        200,
        json={"access_token": "NEW_ACCESS", "refresh_token": "NEW_REFRESH", "expires_in": 3600},
        request=httpx.Request("POST", "https://api.prod.whoop.com/oauth/oauth2/token"),
    )
    result = _refresh_body(monkeypatch, resp)
    assert result["sent"].get("scope") == "offline"
    assert result["stored"]["refresh_token"] == "NEW_REFRESH"


def test_refresh_keeps_old_token_when_response_omits_a_new_one(monkeypatch) -> None:
    """A missing refresh_token must not crash mid-rotation and strand the access token."""
    import httpx

    resp = httpx.Response(
        200,
        json={"access_token": "NEW_ACCESS", "expires_in": 3600},
        request=httpx.Request("POST", "https://api.prod.whoop.com/oauth/oauth2/token"),
    )
    result = _refresh_body(monkeypatch, resp)
    assert result["stored"]["refresh_token"] == "OLD_REFRESH"
    assert result["stored"]["access_token"] == "NEW_ACCESS"


async def _instant_sleep(*_a, **_k) -> None:
    return None


def test_refresh_5xx_is_not_reported_as_needing_reauth(monkeypatch) -> None:
    """Two straight 502s leave rotation state unknown — not an auth failure.

    Raising WHOOPAuthError here would flip needs_reauth and send Rob through a
    consent flow over a transient gateway blip. _refresh retries once on 5xx
    (patched to skip the real sleep), so this asserts the behavior AFTER that
    retry also 5xxs: still WHOOPTransientError, never WHOOPAuthError.
    """
    import asyncio

    import httpx
    import pytest

    from shc.ingest import whoop as w

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, *a, **k):
            return httpx.Response(502, text="Bad Gateway")

    monkeypatch.setattr(w.httpx, "AsyncClient", lambda *a, **k: _Client())
    monkeypatch.setattr(w, "load_token", lambda src, kind: "OLD_REFRESH")
    monkeypatch.setattr(w, "store_token", lambda *a, **k: None)
    monkeypatch.setattr(w, "_client_id", lambda: "cid")
    monkeypatch.setattr(w, "_client_secret", lambda: "secret")
    monkeypatch.setattr(w.asyncio, "sleep", _instant_sleep)

    with pytest.raises(w.WHOOPTransientError):
        asyncio.run(w._refresh())


def test_refresh_retries_once_and_recovers_from_a_single_502(monkeypatch) -> None:
    """The deliberate in-call retry is what a genuinely transient blip needs.

    First POST 502s, second succeeds — this must NOT surface as any kind of
    failure, and the retry must reuse the same refresh token (nothing rotated
    on the failed attempt, so there is nothing else to send).
    """
    import asyncio

    import httpx

    from shc.ingest import whoop as w

    calls = {"n": 0}
    stored: dict[str, str] = {"refresh_token": "OLD_REFRESH"}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, url, data=None, **_):
            calls["n"] += 1
            assert data["refresh_token"] == "OLD_REFRESH"
            if calls["n"] == 1:
                return httpx.Response(502, text="Bad Gateway")
            return httpx.Response(
                200,
                json={
                    "access_token": "NEW_ACCESS",
                    "refresh_token": "NEW_REFRESH",
                    "expires_in": 3600,
                },
                request=httpx.Request("POST", "https://api.prod.whoop.com/oauth/oauth2/token"),
            )

    monkeypatch.setattr(w.httpx, "AsyncClient", lambda *a, **k: _Client())
    monkeypatch.setattr(w, "load_token", lambda src, kind: stored.get(kind))
    monkeypatch.setattr(w, "store_token", lambda src, kind, val: stored.__setitem__(kind, val))
    monkeypatch.setattr(w, "_client_id", lambda: "cid")
    monkeypatch.setattr(w, "_client_secret", lambda: "secret")
    monkeypatch.setattr(w.asyncio, "sleep", _instant_sleep)

    token = asyncio.run(w._refresh())
    assert token == "NEW_ACCESS"
    assert calls["n"] == 2
    assert stored["refresh_token"] == "NEW_REFRESH"


def test_refresh_retry_getting_400_is_a_real_confirmed_dead_token(monkeypatch) -> None:
    """A 502 then a 400 on the SAME deliberate retry is real signal, not a guess.

    Unlike the 2026-08-14 incident (an uncoordinated second attempt from an
    unrelated endpoint), this 400 comes from _refresh's own controlled retry —
    so it is safe to treat as a confirmed dead token and raise WHOOPAuthError.
    """
    import asyncio

    import httpx
    import pytest

    from shc.ingest import whoop as w

    calls = {"n": 0}

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            return False

        async def post(self, *a, **k):
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(502, text="Bad Gateway")
            return httpx.Response(400, json={"error": "invalid_grant"})

    monkeypatch.setattr(w.httpx, "AsyncClient", lambda *a, **k: _Client())
    monkeypatch.setattr(w, "load_token", lambda src, kind: "OLD_REFRESH")
    monkeypatch.setattr(w, "store_token", lambda *a, **k: None)
    monkeypatch.setattr(w, "_client_id", lambda: "cid")
    monkeypatch.setattr(w, "_client_secret", lambda: "secret")
    monkeypatch.setattr(w.asyncio, "sleep", _instant_sleep)

    with pytest.raises(w.WHOOPAuthError):
        asyncio.run(w._refresh())


def test_sync_all_stops_on_transient_refresh_failure_without_hitting_more_endpoints(
    monkeypatch,
) -> None:
    """The 2026-08-14 regression: a transient refresh failure on endpoint 1 must
    stop the loop, not let endpoint 2's independent 401 fire a second, blind
    refresh attempt with the same (possibly already-rotated) token seconds later.
    That second attempt is what actually killed the connection that morning.
    """
    import asyncio

    from shc.ingest import whoop as w

    async def _recovery_hits_a_transient_refresh_failure():
        raise w.WHOOPTransientError("WHOOP refresh got 502 after retry (gateway/transient)")

    async def _sleep_must_never_be_called():
        raise AssertionError("sync_all continued past a transient refresh failure")

    written: dict = {}

    class _FakeConn:
        def execute(self, sql, params=None):
            written["sql"] = sql
            written["params"] = params

    class _WriteCtx:
        async def __aenter__(self):
            return _FakeConn()

        async def __aexit__(self, *_):
            return False

    monkeypatch.setattr(w, "sync_recovery", _recovery_hits_a_transient_refresh_failure)
    monkeypatch.setattr(w, "sync_sleep", _sleep_must_never_be_called)
    monkeypatch.setattr(w, "sync_workout", _sleep_must_never_be_called)
    monkeypatch.setattr(w, "sync_cycle", _sleep_must_never_be_called)
    monkeypatch.setattr(w, "sync_body_measurement", _sleep_must_never_be_called)
    monkeypatch.setattr(w, "sync_user_profile", _sleep_must_never_be_called)
    monkeypatch.setattr(w, "write_ctx", lambda: _WriteCtx())

    try:
        asyncio.run(w.sync_all())
        raise AssertionError("sync_all should have raised the transient failure")
    except w.WHOOPTransientError:
        pass

    # oauth_state must be untouched -- neither a needs_reauth=TRUE (this isn't a
    # confirmed dead token) nor a needs_reauth=FALSE/last_sync_at bump (most
    # endpoints never ran, so that would be a false "fully synced" signal).
    assert "sql" not in written


# ── Incremental sync cursor (2026-08-16 fix) ──────────────────────────────────
#
# sync_recovery/sync_sleep/sync_workout/sync_cycle used to call `_paginate` with
# no bound, walking every page WHOOP has ever returned on every sync. DECISIONS.md
# 2026-08-12 flagged this explicitly for sync_cycle: 800+ cycles paged on every
# run, 429ing near the end — unnecessary load on the same WHOOP infrastructure
# whose 502s cause the token-desync reauth bug. These functions now resume from
# a stored per-endpoint high-water mark (`whoop_sync_cursor`) minus a safety
# overlap, because a record can carry a PENDING score at fetch time and finalize
# later (a cycle's score isn't final until the cycle ends, up to ~24h after) —
# resuming from the exact last-seen timestamp would permanently miss it.


class _WriteCtxOn:
    """Wrap a real (migrated) in-memory conn as the async write_ctx() the sync
    functions expect, so a full sync_* run can be exercised against real SQL."""

    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *_):
        return False


def test_high_water_mark_picks_the_latest_timestamp() -> None:
    records = [
        {"start": "2026-08-01T00:00:00Z"},
        {"start": "2026-08-10T00:00:00Z"},
        {"start": "2026-08-05T00:00:00Z"},
    ]
    hwm = _high_water_mark(records, "start")
    assert hwm is not None
    assert hwm.isoformat() == "2026-08-10T00:00:00+00:00"


def test_high_water_mark_ignores_missing_and_malformed_timestamps() -> None:
    records = [
        {"start": "2026-08-05T00:00:00Z"},
        {"start": None},
        {},
        {"start": "not-a-timestamp"},
    ]
    hwm = _high_water_mark(records, "start")
    assert hwm is not None
    assert hwm.isoformat() == "2026-08-05T00:00:00+00:00"


def test_high_water_mark_empty_or_all_unparseable_returns_none() -> None:
    assert _high_water_mark([], "start") is None
    assert _high_water_mark([{"start": None}, {}], "start") is None


def test_sync_cursor_round_trips_and_is_independent_per_endpoint(
    monkeypatch, conn: duckdb.DuckDBPyConnection
) -> None:
    from shc.ingest import whoop as w

    monkeypatch.setattr(w, "get_read_conn", lambda: conn.cursor())

    assert w._read_sync_cursor("recovery") is None
    ts = w._parse_ts("2026-08-10T00:00:00Z")
    assert ts is not None
    w._write_sync_cursor(conn, "recovery", ts)
    assert w._read_sync_cursor("recovery") == ts
    assert w._read_sync_cursor("sleep") is None  # untouched — separate row


def test_sync_cursor_never_moves_backward(monkeypatch, conn: duckdb.DuckDBPyConnection) -> None:
    """A stale/reordered write must not regress a cursor that already advanced —
    that would re-open the whole gap the cursor exists to close."""
    from shc.ingest import whoop as w

    monkeypatch.setattr(w, "get_read_conn", lambda: conn.cursor())

    later = w._parse_ts("2026-08-10T00:00:00Z")
    earlier = w._parse_ts("2026-08-01T00:00:00Z")
    assert later is not None
    assert earlier is not None
    w._write_sync_cursor(conn, "cycle", later)
    w._write_sync_cursor(conn, "cycle", earlier)
    assert w._read_sync_cursor("cycle") == later


def test_paginate_sends_start_and_resends_it_on_every_page(monkeypatch) -> None:
    """WHOOP's docs don't confirm nextToken alone preserves the start filter, so
    _paginate resends it on every page rather than betting on that being true."""
    import asyncio

    from shc.ingest import whoop as w

    calls: list[dict] = []

    async def _fake_get(path, params=None):
        calls.append(dict(params or {}))
        if "nextToken" not in (params or {}):
            return {"records": [{"id": 1}], "next_token": "page2"}
        return {"records": [{"id": 2}], "next_token": None}

    monkeypatch.setattr(w, "_get", _fake_get)

    start = w._parse_ts("2026-08-01T00:00:00Z")
    assert start is not None
    records = asyncio.run(w._paginate("/v2/cycle", start=start))

    assert [r["id"] for r in records] == [1, 2]
    assert len(calls) == 2
    assert calls[0]["start"] == start.isoformat()
    assert calls[1]["start"] == start.isoformat()
    assert calls[1]["nextToken"] == "page2"


def test_paginate_omits_start_when_none(monkeypatch) -> None:
    """First-time sync / force_full path: no cursor yet, so no start filter is
    sent — this is what preserves the full-history walk for a fresh connection."""
    import asyncio

    from shc.ingest import whoop as w

    calls: list[dict] = []

    async def _fake_get(path, params=None):
        calls.append(dict(params or {}))
        return {"records": [], "next_token": None}

    monkeypatch.setattr(w, "_get", _fake_get)
    asyncio.run(w._paginate("/v2/cycle"))
    assert "start" not in calls[0]


def test_sync_cycle_resumes_from_stored_cursor_minus_overlap(
    monkeypatch, conn: duckdb.DuckDBPyConnection
) -> None:
    """The exact endpoint DECISIONS.md 2026-08-12 flagged: sync_cycle must stop
    walking 800+ cycles on every run and instead fetch from near its cursor."""
    import asyncio

    from shc.ingest import whoop as w

    stored_cursor = w._parse_ts("2026-08-10T00:00:00Z")
    assert stored_cursor is not None
    w._write_sync_cursor(conn, "cycle", stored_cursor)

    seen_start: dict = {}

    async def _fake_paginate(path, start=None):
        seen_start["value"] = start
        return []

    monkeypatch.setattr(w, "get_read_conn", lambda: conn.cursor())
    monkeypatch.setattr(w, "_paginate", _fake_paginate)
    monkeypatch.setattr(w, "write_ctx", lambda: _WriteCtxOn(conn))

    asyncio.run(w.sync_cycle())

    assert seen_start["value"] == stored_cursor - w._SYNC_OVERLAP


def test_sync_cycle_force_full_ignores_stored_cursor(
    monkeypatch, conn: duckdb.DuckDBPyConnection
) -> None:
    """A deliberate backfill must still be able to re-walk full history even
    once a cursor exists — force_full bypasses it for one call."""
    import asyncio

    from shc.ingest import whoop as w

    stored_cursor = w._parse_ts("2026-08-10T00:00:00Z")
    assert stored_cursor is not None
    w._write_sync_cursor(conn, "cycle", stored_cursor)

    seen_start: dict = {}

    async def _fake_paginate(path, start=None):
        seen_start["value"] = start
        return []

    monkeypatch.setattr(w, "get_read_conn", lambda: conn.cursor())
    monkeypatch.setattr(w, "_paginate", _fake_paginate)
    monkeypatch.setattr(w, "write_ctx", lambda: _WriteCtxOn(conn))

    asyncio.run(w.sync_cycle(force_full=True))

    assert seen_start["value"] is None


def test_sync_cycle_first_ever_sync_has_no_cursor_and_walks_full_history(
    monkeypatch, conn: duckdb.DuckDBPyConnection
) -> None:
    """No stored cursor yet — a brand-new connection must still fetch everything,
    not silently sync nothing."""
    import asyncio

    from shc.ingest import whoop as w

    seen_start: dict = {}

    async def _fake_paginate(path, start=None):
        seen_start["value"] = start
        return []

    monkeypatch.setattr(w, "get_read_conn", lambda: conn.cursor())
    monkeypatch.setattr(w, "_paginate", _fake_paginate)
    monkeypatch.setattr(w, "write_ctx", lambda: _WriteCtxOn(conn))

    asyncio.run(w.sync_cycle())

    assert seen_start["value"] is None


def test_sync_recovery_advances_cursor_past_an_unscored_record(
    monkeypatch, conn: duckdb.DuckDBPyConnection
) -> None:
    """The cursor must move forward from the newest record actually fetched,
    including one WHOOP hasn't scored yet — that record is what re-syncs on the
    next run inside the overlap window instead of being permanently missed."""
    import asyncio

    from shc.ingest import whoop as w

    scored = {
        "cycle_id": 1,
        "sleep_id": 1,
        "created_at": "2026-08-01T00:00:00Z",
        "score": {"recovery_score": 71},
    }
    pending = {
        "cycle_id": 2,
        "sleep_id": 2,
        "created_at": "2026-08-05T00:00:00Z",
        "score": {},
    }

    async def _fake_paginate(path, start=None):
        return [scored, pending]

    monkeypatch.setattr(w, "get_read_conn", lambda: conn.cursor())
    monkeypatch.setattr(w, "_paginate", _fake_paginate)
    monkeypatch.setattr(w, "write_ctx", lambda: _WriteCtxOn(conn))

    count = asyncio.run(w.sync_recovery())

    assert count == 1  # the pending-score record is skipped, not stored
    assert w._read_sync_cursor("recovery") == w._parse_ts(pending["created_at"])
