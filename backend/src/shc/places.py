"""Where Rob spends time, found from OwnTracks points, and what it does to stress.

Points arrive in OwnTracks' significant-changes mode: a few per move, nothing
while still. A stay is a run of points that never strays more than
`STAY_RADIUS_M` from its centroid, lasting at least `MIN_STAY`; it ends at the
first point outside. Stays cluster into places by distance. Places carry no
name until Rob gives one.
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

LOCAL_TZ = ZoneInfo("America/Los_Angeles")
STAY_RADIUS_M = 150.0
# Significant-change fixes land up to a few hundred metres from where Rob stops,
# so stays at one place scatter wider than a single stay does.
PLACE_RADIUS_M = 250.0
MIN_STAY = timedelta(minutes=10)
MAX_STAY = timedelta(hours=12)
MAX_ACCURACY_M = 500.0
RETAIN_POINTS = timedelta(days=90)
MIN_VISITS = 8
MIN_SPAN = timedelta(days=21)
MIN_STRESS_MINUTES = 10
EXERCISE_TAIL = timedelta(minutes=30)

# Two-sided 95% t critical values; the visit counts here are small.
_T95 = {7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 12: 2.179, 15: 2.131, 20: 2.086, 30: 2.042}


def _t95(df: int) -> float:
    eligible = [k for k in _T95 if k <= df]
    return _T95[max(eligible)] if eligible and df <= 30 else 1.96


def distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(a))


def ingest_owntracks(conn: duckdb.DuckDBPyConnection, msg: dict[str, Any]) -> bool:
    """Store one OwnTracks `location` message. Returns whether a point was kept.

    Every other message type, and fixes too inaccurate to place, is ignored.
    """
    if msg.get("_type") != "location":
        return False
    try:
        tst = datetime.fromtimestamp(int(msg["tst"]), UTC)
        lat, lon = float(msg["lat"]), float(msg["lon"])
    except (KeyError, TypeError, ValueError):
        return False
    acc = msg.get("acc")
    if isinstance(acc, int | float) and acc > MAX_ACCURACY_M:
        return False
    conn.execute(
        "INSERT INTO location_points (tst, lat, lon, acc) VALUES (?, ?, ?, ?) "
        "ON CONFLICT (tst) DO NOTHING",
        [tst, lat, lon, acc],
    )
    return True


def _stays(
    points: list[tuple[datetime, float, float]],
) -> list[tuple[datetime, datetime, float, float]]:
    """Closed stays as (arrived, left, lat, lon). A run still open at the end is skipped."""
    out = []
    i, n = 0, len(points)
    while i < n:
        lats, lons = [points[i][1]], [points[i][2]]
        j = i + 1
        while (
            j < n
            and distance_m(
                statistics.fmean(lats), statistics.fmean(lons), points[j][1], points[j][2]
            )
            <= STAY_RADIUS_M
        ):
            lats.append(points[j][1])
            lons.append(points[j][2])
            j += 1
        if j == n:
            break
        arrived, left = points[i][0], points[j][0]
        if left - arrived >= MIN_STAY:
            out.append(
                (
                    arrived,
                    min(left, arrived + MAX_STAY),
                    statistics.fmean(lats),
                    statistics.fmean(lons),
                )
            )
        i = j
    return out


def update_stays(conn: duckdb.DuckDBPyConnection, now: datetime | None = None) -> int:
    """Turn points since the last closed stay into stays and places; prune old points.

    Returns the number of new stays.
    """
    now = now or datetime.now(UTC)
    # From the last stay's arrival, not its departure: a capped stay ends before
    # its departure point, so starting later would re-split it. Re-detecting the
    # last stay is a no-op on its primary key.
    last = conn.execute("SELECT max(arrived_at) FROM place_stays").fetchone()
    since = last[0] if last and last[0] else datetime(1970, 1, 1, tzinfo=UTC)
    before = conn.execute("SELECT count(*) FROM place_stays").fetchone()
    points = conn.execute(
        "SELECT tst, lat, lon FROM location_points WHERE tst >= ? ORDER BY tst", [since]
    ).fetchall()
    places = conn.execute("SELECT id, lat, lon, merged_into FROM places").fetchall()
    for arrived, left, lat, lon in _stays(points):
        near = min(places, key=lambda p: distance_m(lat, lon, p[1], p[2]), default=None)
        if near is not None and distance_m(lat, lon, near[1], near[2]) <= PLACE_RADIUS_M:
            place_id = near[3] or near[0]
        else:
            row = conn.execute(
                "INSERT INTO places (lat, lon, first_seen) VALUES (?, ?, ?) RETURNING id",
                [lat, lon, arrived],
            ).fetchone()
            assert row is not None
            place_id = row[0]
            places.append((place_id, lat, lon, None))
        conn.execute(
            "INSERT INTO place_stays (arrived_at, left_at, place_id) VALUES (?, ?, ?) "
            "ON CONFLICT (arrived_at) DO NOTHING",
            [arrived, left, place_id],
        )
    conn.execute("DELETE FROM location_points WHERE tst < ?", [now - RETAIN_POINTS])
    after = conn.execute("SELECT count(*) FROM place_stays").fetchone()
    return (after[0] if after else 0) - (before[0] if before else 0)


def daily_hours(conn: duckdb.DuckDBPyConnection, place_id: int) -> dict[date, float]:
    """Hours at a place per local arrival date, zero-filled across the tracked span."""
    rows = conn.execute(
        "SELECT arrived_at, left_at, place_id FROM place_stays ORDER BY arrived_at"
    ).fetchall()
    if not rows:
        return {}
    local = [(a.astimezone(LOCAL_TZ).date(), (b - a).total_seconds() / 3600, p) for a, b, p in rows]
    d, end = local[0][0], local[-1][0]
    out: dict[date, float] = {}
    while d <= end:
        out[d] = 0.0
        d += timedelta(days=1)
    for day, hours, p in local:
        if p == place_id:
            out[day] += hours
    return out


def place_stress(conn: duckdb.DuckDBPyConnection) -> dict[int, dict[str, Any]]:
    """Per place: visit-level mean of (stress − same-hour baseline elsewhere), with a 95% interval.

    Minutes inside a workout or its 30-minute tail are excluded from both sides.
    """
    rows = conn.execute(
        """
        SELECT t.sampled_at, t.value, s.place_id, s.arrived_at
        FROM whoop_stress_timeline t
        LEFT JOIN place_stays s ON t.sampled_at >= s.arrived_at AND t.sampled_at < s.left_at
        WHERE t.value IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM workouts w
              WHERE t.sampled_at >= w.started_at
                AND t.sampled_at < COALESCE(w.ended_at, w.started_at) + ?
          )
        """,
        [EXERCISE_TAIL],
    ).fetchall()
    tot: dict[int, list[float]] = defaultdict(lambda: [0.0, 0])
    by_place_hour: dict[tuple[int, int], list[float]] = defaultdict(lambda: [0.0, 0])
    visits: dict[tuple[int, datetime], list[tuple[int, float]]] = defaultdict(list)
    for ts, v, place, arrived in rows:
        h = ts.astimezone(LOCAL_TZ).hour
        tot[h][0] += v
        tot[h][1] += 1
        if place is not None:
            by_place_hour[(place, h)][0] += v
            by_place_hour[(place, h)][1] += 1
            visits[(place, arrived)].append((h, v))

    diffs: dict[int, list[float]] = defaultdict(list)
    for (place, _), minutes in visits.items():
        if len(minutes) < MIN_STRESS_MINUTES:
            continue
        per_min = []
        for h, v in minutes:
            s, c = by_place_hour[(place, h)]
            rest_n = tot[h][1] - c
            if rest_n > 0:
                per_min.append(v - (tot[h][0] - s) / rest_n)
        if per_min:
            diffs[place].append(statistics.fmean(per_min))

    out = {}
    for place, ds in diffs.items():
        mean = statistics.fmean(ds)
        if len(ds) < 2:
            out[place] = {
                "n_visits": len(ds),
                "effect": round(mean, 3),
                "ci_low": None,
                "ci_high": None,
            }
            continue
        half = _t95(len(ds) - 1) * statistics.stdev(ds) / math.sqrt(len(ds))
        out[place] = {
            "n_visits": len(ds),
            "effect": round(mean, 3),
            "ci_low": round(mean - half, 3),
            "ci_high": round(mean + half, 3),
        }
    return out


def place_morning(conn: duckdb.DuckDBPyConnection, place_id: int) -> dict[str, Any]:
    """Next-morning HRV on days with 2h+ at the place against days with none, via the Lab."""
    from shc import research

    spec = {
        "exposure": {"feature": f"place:{place_id}", "a": {"max": 0.01}, "b": {"min": 2}},
        "outcome": "lnhrv_dev_pct",
        "lag": 1,
        "expected_sign": "-",
        "min_effect": 3,
        "window_days": 365,
    }
    return research.estimate(conn, spec)


def summary(conn: duckdb.DuckDBPyConnection, limit: int = 12) -> dict[str, Any]:
    """Every place with two or more visits, its pattern, and its effects once there is enough data."""
    stays = conn.execute(
        "SELECT place_id, arrived_at, left_at FROM place_stays ORDER BY arrived_at"
    ).fetchall()
    meta = {
        r[0]: r[1:]
        for r in conn.execute(
            "SELECT id, lat, lon, name FROM places WHERE merged_into IS NULL AND NOT COALESCE(hidden, FALSE)"
        ).fetchall()
    }
    by_place: dict[int, list[tuple[datetime, datetime]]] = defaultdict(list)
    for p, a, b in stays:
        by_place[p].append((a, b))

    ranked = sorted(
        (p for p, v in by_place.items() if len(v) >= 2 and p in meta),
        key=lambda p: -sum((b - a).total_seconds() for a, b in by_place[p]),
    )[:limit]
    stress = place_stress(conn) if ranked else {}
    out = []
    for p in ranked:
        v = by_place[p]
        lat, lon, name = meta[p]
        local = [a.astimezone(LOCAL_TZ) for a, _ in v]
        days = defaultdict(int)
        for a in local:
            days[a.strftime("%a")] += 1
        ready = len(v) >= MIN_VISITS and v[-1][0] - v[0][0] >= MIN_SPAN
        out.append(
            {
                "id": p,
                "name": name,
                "lat": round(lat, 5),
                "lon": round(lon, 5),
                "visits": len(v),
                "hours": round(sum((b - a).total_seconds() for a, b in v) / 3600, 1),
                "first": v[0][0].isoformat(),
                "last": v[-1][0].isoformat(),
                "usual_days": [
                    d for d, c in sorted(days.items(), key=lambda x: -x[1]) if c >= 0.3 * len(v)
                ],
                "usual_arrival_hour": round(
                    statistics.median(a.hour + a.minute / 60 for a in local), 1
                ),
                "status": "ready" if ready else "collecting",
                "stress": stress.get(p) if ready else None,
                "morning": place_morning(conn, p) if ready else None,
            }
        )
    last_point = conn.execute("SELECT max(tst) FROM location_points").fetchone()
    stress_days = conn.execute(
        "SELECT count(DISTINCT date) FROM whoop_stress_timeline WHERE sampled_at >= ?",
        [stays[0][1] if stays else datetime.now(UTC)],
    ).fetchone()
    return {
        "places": out,
        "stays": len(stays),
        "last_point_at": last_point[0].isoformat() if last_point and last_point[0] else None,
        "tracked_days": (stays[-1][1] - stays[0][1]).days + 1 if stays else 0,
        "stress_days": stress_days[0] if stress_days else 0,
        "min_visits": MIN_VISITS,
        "min_span_days": MIN_SPAN.days,
    }


def away_nights(conn: duckdb.DuckDBPyConnection) -> dict[date, float]:
    """1.0 for nights slept away from the usual place, 0.0 for home, keyed to the wake date.

    Home is the place most nights began at. Nights with no stay covering sleep
    onset are left out rather than guessed.
    """
    rows = conn.execute(
        "WITH n AS (SELECT night_date, arg_max(ts_in, epoch(ts_out - ts_in)) AS ts_in FROM sleep "
        "WHERE NOT COALESCE(is_nap, FALSE) AND ts_in IS NOT NULL AND ts_out IS NOT NULL "
        "GROUP BY night_date) "
        "SELECT n.night_date, s.place_id FROM n JOIN place_stays s "
        "ON n.ts_in >= s.arrived_at AND n.ts_in < s.left_at"
    ).fetchall()
    counts: dict[int, int] = defaultdict(int)
    for _, place in rows:
        counts[place] += 1
    if not counts or max(counts.values()) < 3:
        return {}
    home = max(counts, key=lambda p: counts[p])
    return {night: float(place != home) for night, place in rows}


def _minute_of_day(ts: datetime, day: date) -> float:
    """Minutes from local midnight of `day`, clamped to the 24 h around it."""
    local = ts.astimezone(LOCAL_TZ)
    midnight = datetime(day.year, day.month, day.day, tzinfo=LOCAL_TZ)
    return max(0.0, min(1440.0, (local - midnight).total_seconds() / 60))


def day_view(conn: duckdb.DuckDBPyConnection, day: date, bin_min: int = 10) -> dict[str, Any]:
    """One local day: stress in `bin_min`-minute means, with the workouts and stays around it.

    Times are minutes from local midnight so the chart needs no timezone logic.
    """
    start = datetime(day.year, day.month, day.day, tzinfo=LOCAL_TZ)
    end = start + timedelta(days=1)
    bins: dict[int, list[float]] = defaultdict(list)
    for ts, v in conn.execute(
        "SELECT sampled_at, value FROM whoop_stress_timeline "
        "WHERE sampled_at >= ? AND sampled_at < ? AND value IS NOT NULL",
        [start, end],
    ).fetchall():
        bins[int(_minute_of_day(ts, day) // bin_min)].append(v)
    names = {r[0]: r[1] for r in conn.execute("SELECT id, name FROM places").fetchall()}
    workouts = conn.execute(
        "SELECT started_at, COALESCE(ended_at, started_at), kind FROM workouts "
        "WHERE started_at < ? AND COALESCE(ended_at, started_at) > ? ORDER BY started_at",
        [end, start],
    ).fetchall()
    stays = conn.execute(
        "SELECT arrived_at, left_at, place_id FROM place_stays "
        "WHERE arrived_at < ? AND left_at > ? ORDER BY arrived_at",
        [end, start],
    ).fetchall()
    return {
        "date": day.isoformat(),
        "stress": [
            {"m": b * bin_min + bin_min / 2, "v": round(statistics.fmean(vs), 2)}
            for b, vs in sorted(bins.items())
        ],
        "workouts": [
            {"from": _minute_of_day(a, day), "to": _minute_of_day(b, day), "kind": k}
            for a, b, k in workouts
        ],
        "stays": [
            {
                "from": _minute_of_day(a, day),
                "to": _minute_of_day(b, day),
                "place": p,
                "name": names.get(p),
            }
            for a, b, p in stays
        ],
    }


def rhythm(
    conn: duckdb.DuckDBPyConnection, days: int = 28, min_samples: int = 20
) -> dict[str, Any]:
    """Mean stress by weekday and hour over the last `days`, workouts and their tail left out."""
    since = datetime.now(UTC) - timedelta(days=days)
    rows = conn.execute(
        "SELECT t.sampled_at, t.value FROM whoop_stress_timeline t "
        "WHERE t.sampled_at >= ? AND t.value IS NOT NULL AND NOT EXISTS ("
        "SELECT 1 FROM workouts w WHERE t.sampled_at >= w.started_at "
        "AND t.sampled_at < COALESCE(w.ended_at, w.started_at) + INTERVAL 30 MINUTE)",
        [since],
    ).fetchall()
    cells: dict[tuple[int, int], list[float]] = defaultdict(list)
    covered: set[date] = set()
    for ts, v in rows:
        local = ts.astimezone(LOCAL_TZ)
        cells[(local.weekday(), local.hour)].append(v)
        covered.add(local.date())
    return {
        "days": len(covered),
        "cells": [
            {"dow": d, "hour": h, "mean": round(statistics.fmean(vs), 2), "n": len(vs)}
            for (d, h), vs in sorted(cells.items())
            if len(vs) >= min_samples
        ],
    }


def merge_places(conn: duckdb.DuckDBPyConnection, src: int, dst: int) -> int:
    """Fold place `src` into `dst`. Returns the number of stays moved.

    `src` stays in the table as an alias, so a later stay near it resolves to `dst`.
    """
    if src == dst:
        raise ValueError("cannot merge a place into itself")
    row = conn.execute("SELECT merged_into FROM places WHERE id = ?", [dst]).fetchone()
    if row is None or conn.execute("SELECT 1 FROM places WHERE id = ?", [src]).fetchone() is None:
        raise LookupError("no such place")
    root = row[0] or dst
    if root == src:
        raise ValueError("that place was merged into this one")
    moved = conn.execute(
        "UPDATE place_stays SET place_id = ? WHERE place_id = ?", [root, src]
    ).fetchone()
    conn.execute(
        "UPDATE places SET merged_into = ? WHERE id = ? OR merged_into = ?", [root, src, src]
    )
    return int(moved[0]) if moved else 0
