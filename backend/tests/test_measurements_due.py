"""Growth-review cadence: scale 3x/week, all four tape sites every 28 days, photos every 56."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from shc.api.routers.dashboard import measurements_due

TODAY = date(2026, 11, 13)


def _due(conn) -> dict[str, bool]:
    return {i["key"]: i["due"] for i in measurements_due(conn, TODAY)["items"]}


def _m(conn, metric: str, day: date, source: str = "manual") -> None:
    conn.execute(
        "INSERT INTO measurements (source, metric, ts, value_num, unit, external_id, content_hash) "
        "VALUES (?, ?, ?, 1, 'x', ?, ?)",
        [
            source,
            metric,
            datetime.combine(day, datetime.min.time()),
            f"{metric}{day}",
            f"{metric}{day}",
        ],
    )


def test_empty_store_is_all_due(conn) -> None:
    assert _due(conn) == {"scale": True, "tape": True, "photos": True}


def test_three_weigh_ins_satisfy_scale_from_either_source(conn) -> None:
    _m(conn, "body_mass_kg", TODAY, "apple_health")
    _m(conn, "body_mass_kg", TODAY - timedelta(days=2), "apple_health")
    conn.execute(
        "INSERT INTO daily_checkin (date, body_weight_kg) VALUES (?, 107)",
        [TODAY - timedelta(days=4)],
    )
    assert _due(conn)["scale"] is False


def test_tape_needs_all_four_sites_and_ages_by_the_oldest(conn) -> None:
    for site in ("waist", "arm", "thigh"):
        _m(conn, f"{site}_circumference_cm", TODAY - timedelta(days=1))
    assert _due(conn)["tape"] is True
    _m(conn, "chest_circumference_cm", TODAY - timedelta(days=30))
    assert _due(conn)["tape"] is True
    _m(conn, "chest_circumference_cm", TODAY - timedelta(days=2))
    assert _due(conn)["tape"] is False
