"""Weekly card: a delta inside the personal noise floor must read steady."""

from __future__ import annotations

from datetime import date, timedelta

from shc.stats.weekly_card import weekly_card

TODAY = date(2026, 6, 15)


def _recovery(conn, hrv_of, rhr_of=lambda i: 55):
    for i in range(35):
        d = TODAY - timedelta(days=i)
        conn.execute(
            "INSERT INTO recovery (id, source, date, hrv, rhr, content_hash) "
            "VALUES (?, 'whoop', ?, ?, ?, ?)",
            [f"r{i}", d, hrv_of(i), rhr_of(i), f"h{i}"],
        )


def _by_key(card):
    return {d["key"]: d for d in card["domains"]}


def test_within_noise_is_steady(conn):
    # Baseline alternates 40/60 (SD ~10, floor ~5); week mean sits at 51.
    _recovery(conn, lambda i: 40 + 20 * (i % 2) + (1 if i < 7 else 0))
    assert _by_key(weekly_card(conn, TODAY))["hrv"]["status"] == "steady"


def test_real_rise_in_hrv_is_better_and_real_rise_in_rhr_is_worse(conn):
    _recovery(
        conn,
        lambda i: 70 if i < 7 else 40 + 4 * (i % 2),
        lambda i: 65 if i < 7 else 52 + (i % 2),
    )
    d = _by_key(weekly_card(conn, TODAY))
    assert d["hrv"]["status"] == "better"
    assert d["rhr"]["status"] == "worse"


def test_short_week_is_unknown_not_guessed(conn):
    for i in range(30):
        d = TODAY - timedelta(days=i + 5)  # only 2 days inside the week
        conn.execute(
            "INSERT INTO recovery (id, source, date, hrv, content_hash) "
            "VALUES (?, 'whoop', ?, 50, ?)",
            [f"s{i}", d, f"h{i}"],
        )
    assert _by_key(weekly_card(conn, TODAY))["hrv"]["status"] == "unknown"


def test_rpe_gap_counts_working_sets_without_rpe(conn, seed):
    seed.workout(TODAY - timedelta(days=1), "Leg Extension (Machine)", [(50, 10)] * 3, rpe=None)
    seed.workout(TODAY - timedelta(days=2), "V-Bar Pulldown", [(50, 10)] * 4, rpe=8.0)
    gap = weekly_card(conn, TODAY)["rpe_gap"]
    assert (gap["sets"], gap["missing"], gap["pct_missing"]) == (7, 3, 43)
    assert gap["sessions"][0]["date"] == str(TODAY - timedelta(days=1))
