from __future__ import annotations

from datetime import UTC, datetime, timedelta

import duckdb

from shc import places

# Synthetic coordinates: two spots ~1.1 km apart.
A = (10.0, 20.0)
B = (10.01, 20.0)
T0 = datetime(2026, 1, 5, 16, 0, tzinfo=UTC)


def _pt(
    conn: duckdb.DuckDBPyConnection, minutes: float, where: tuple[float, float], acc: float = 20
) -> bool:
    tst = int((T0 + timedelta(minutes=minutes)).timestamp())
    return places.ingest_owntracks(
        conn, {"_type": "location", "tst": tst, "lat": where[0], "lon": where[1], "acc": acc}
    )


def test_ingest_ignores_other_types_and_bad_fixes(conn: duckdb.DuckDBPyConnection) -> None:
    assert not places.ingest_owntracks(conn, {"_type": "transition", "event": "enter", "desc": "x"})
    assert not _pt(conn, 0, A, acc=900)
    assert _pt(conn, 0, A)
    assert _pt(conn, 0, A)  # a resend is accepted and deduplicated
    assert conn.execute("SELECT count(*) FROM location_points").fetchone() == (1,)


def test_stays_cluster_into_places_and_open_stay_waits(conn: duckdb.DuckDBPyConnection) -> None:
    _pt(conn, 0, A)
    _pt(conn, 30, A)
    _pt(conn, 60, B)  # left A: stay 0-60 at A
    _pt(conn, 65, (B[0] + 0.0004, B[1]))  # drift within B
    _pt(conn, 120, A)  # left B: stay 60-120 at B; A is open until the next point
    places.update_stays(conn, now=T0)
    stays = conn.execute(
        "SELECT place_id, left_at - arrived_at FROM place_stays ORDER BY 1"
    ).fetchall()
    assert stays == [(1, timedelta(minutes=60)), (2, timedelta(minutes=60))]

    _pt(conn, 200, (A[0] + 0.03, A[1]))
    assert places.update_stays(conn, now=T0) == 1
    rows = conn.execute(
        "SELECT place_id, count(*) FROM place_stays GROUP BY 1 ORDER BY 1"
    ).fetchall()
    assert rows == [(1, 2), (2, 1)]  # the second A stay joined place 1


def test_passing_through_is_not_a_stay(conn: duckdb.DuckDBPyConnection) -> None:
    for minutes, where in ((0, A), (5, B), (8, (10.02, 20.0)), (9, A)):
        _pt(conn, minutes, where)
    assert places.update_stays(conn, now=T0) == 0


def test_long_silence_is_capped_and_not_resplit(conn: duckdb.DuckDBPyConnection) -> None:
    _pt(conn, 0, A)
    _pt(conn, 60 * 20, A)  # still at A 20 h later
    _pt(conn, 60 * 21, B)
    places.update_stays(conn, now=T0)
    _pt(conn, 60 * 23, A)
    places.update_stays(conn, now=T0)
    first = conn.execute(
        "SELECT left_at - arrived_at FROM place_stays ORDER BY arrived_at"
    ).fetchone()
    assert first == (places.MAX_STAY,)
    assert conn.execute("SELECT count(*) FROM place_stays").fetchone() == (2,)


def test_place_stress_is_against_same_hour_elsewhere_and_skips_workouts(
    conn: duckdb.DuckDBPyConnection,
) -> None:
    # Two days, same hour. Day 1 at the place (stress 2.0), day 2 elsewhere (1.0).
    conn.execute("INSERT INTO places (id, lat, lon, first_seen) VALUES (1, 10, 20, ?)", [T0])
    conn.execute("INSERT INTO place_stays VALUES (?, ?, 1)", [T0, T0 + timedelta(minutes=30)])
    for day, value in ((0, 2.0), (1, 1.0)):
        for m in range(30):
            ts = T0 + timedelta(days=day, minutes=m)
            conn.execute(
                "INSERT INTO whoop_stress_timeline (date, sampled_at, value) VALUES (?, ?, ?)",
                [ts.date(), ts, value],
            )
    # A workout covering the first 15 place minutes (plus 30 min tail) hides them all.
    conn.execute(
        "INSERT INTO workouts (id, source, started_at, ended_at, content_hash) VALUES ('w', 'whoop', ?, ?, 'h')",
        [T0 - timedelta(hours=1), T0 - timedelta(minutes=35)],
    )
    out = places.place_stress(conn)
    assert out[1]["effect"] == 1.0
    assert out[1]["n_visits"] == 1

    conn.execute("UPDATE workouts SET ended_at = ?", [T0 + timedelta(minutes=10)])
    assert places.place_stress(conn) == {}  # fewer than 10 stress minutes left


def test_daily_hours_feeds_the_lab_feature(conn: duckdb.DuckDBPyConnection) -> None:
    from shc import research

    conn.execute("INSERT INTO places (id, lat, lon, first_seen) VALUES (1, 10, 20, ?)", [T0])
    conn.execute("INSERT INTO places (id, lat, lon, first_seen) VALUES (2, 11, 20, ?)", [T0])
    conn.execute("INSERT INTO place_stays VALUES (?, ?, 1)", [T0, T0 + timedelta(hours=3)])
    conn.execute(
        "INSERT INTO place_stays VALUES (?, ?, 2)",
        [T0 + timedelta(days=2), T0 + timedelta(days=2, hours=1)],
    )
    hours = research.series(conn, "place:1")
    assert list(hours.values()) == [3.0, 0.0, 0.0]


def test_owntracks_webhook_needs_the_key_as_basic_password(monkeypatch) -> None:  # noqa: ANN001
    from fastapi import Depends, FastAPI
    from fastapi.testclient import TestClient

    from shc.api.routers.location import _require_webhook_key
    from shc.config import settings

    monkeypatch.setattr(settings, "apple_webhook_key", "k")
    app = FastAPI()

    @app.post("/x", dependencies=[Depends(_require_webhook_key)])
    def x() -> list[int]:
        return []

    c = TestClient(app)
    assert c.post("/x").status_code == 401
    assert c.post("/x", auth=("rob", "nope")).status_code == 401
    assert c.post("/x", auth=("anyone", "k")).status_code == 200


def test_day_view_reports_minutes_from_local_midnight(conn: duckdb.DuckDBPyConnection) -> None:
    from datetime import date

    from shc.places import LOCAL_TZ

    day = date(2026, 1, 6)
    noon = datetime(2026, 1, 6, 12, 0, tzinfo=LOCAL_TZ)
    for m in range(20):
        ts = noon + timedelta(minutes=m)
        conn.execute(
            "INSERT INTO whoop_stress_timeline (date, sampled_at, value) VALUES (?, ?, ?)",
            [day, ts, 1.0 if m < 10 else 3.0],
        )
    conn.execute(
        "INSERT INTO places (id, lat, lon, name, first_seen) VALUES (1, 0, 0, 'x', ?)", [noon]
    )
    conn.execute(
        "INSERT INTO place_stays VALUES (?, ?, 1)",
        [noon - timedelta(hours=2), noon + timedelta(hours=1)],
    )
    view = places.day_view(conn, day)
    assert [(p["m"], p["v"]) for p in view["stress"]] == [(725.0, 1.0), (735.0, 3.0)]
    assert view["stays"] == [{"from": 600.0, "to": 780.0, "place": 1, "name": "x"}]


def test_rhythm_drops_thin_cells(conn: duckdb.DuckDBPyConnection) -> None:
    now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0) - timedelta(days=1)
    for m in range(30):
        ts = now + timedelta(minutes=m)
        conn.execute(
            "INSERT INTO whoop_stress_timeline (date, sampled_at, value) VALUES (?, ?, 2.0)",
            [ts.date(), ts],
        )
    ts = now + timedelta(hours=5)
    conn.execute(
        "INSERT INTO whoop_stress_timeline (date, sampled_at, value) VALUES (?, ?, 2.0)",
        [ts.date(), ts],
    )
    out = places.rhythm(conn, days=7)
    assert len(out["cells"]) == 1 and out["cells"][0]["n"] == 30
