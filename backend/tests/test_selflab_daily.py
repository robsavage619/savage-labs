"""Daily outcomes (WP 2.1): extractors and the placebo gate on a daily design."""

from __future__ import annotations

import math
import random
from datetime import date, timedelta

import pytest

from shc import selflab

DAILY = ("deep_sleep_min", "sleep_efficiency_pct", "rhr_next_morning")


def _nights(conn, *, days: int, sd: float = 3.0, seed: int = 1) -> None:
    rng = random.Random(seed)
    for k in range(1, days + 1):
        d = (date.today() - timedelta(days=k)).isoformat()
        conn.execute(
            "INSERT INTO sleep (id, source, night_date, content_hash, sws_min, "
            "sleep_efficiency_pct, is_nap) VALUES (?, 'whoop', ?, ?, ?, ?, FALSE)",
            [f"s{k}", d, f"s{k}", 80 + rng.gauss(0, sd), 90 + rng.gauss(0, sd)],
        )
        conn.execute(
            "INSERT INTO recovery (id, source, date, rhr, content_hash) "
            "VALUES (?, 'whoop', ?, ?, ?)",
            [f"r{k}", d, round(55 + rng.gauss(0, sd)), f"r{k}"],
        )


def test_extractors_read_the_night_after_the_behaviour_day(conn) -> None:
    day = date(2026, 1, 10)
    nxt = (day + timedelta(days=1)).isoformat()
    conn.execute(
        "INSERT INTO sleep (id, source, night_date, content_hash, sws_min, "
        "sleep_efficiency_pct, is_nap) VALUES ('a', 'whoop', ?, 'a', 77, 91.5, FALSE)",
        [nxt],
    )
    conn.execute(
        "INSERT INTO sleep (id, source, night_date, content_hash, sws_min, "
        "sleep_efficiency_pct, is_nap) VALUES ('n', 'whoop', ?, 'n', 99, 99, TRUE)",
        [nxt],
    )
    conn.execute(
        "INSERT INTO recovery (id, source, date, rhr, content_hash) "
        "VALUES ('r', 'whoop', ?, 52, 'r')",
        [nxt],
    )
    assert selflab._outcome_value(conn, "deep_sleep_min", day) == 77
    assert selflab._outcome_value(conn, "sleep_efficiency_pct", day) == 91.5
    assert selflab._outcome_value(conn, "rhr_next_morning", day) == 52
    assert selflab._outcome_value(conn, "deep_sleep_min", day + timedelta(days=5)) is None
    assert set(DAILY) <= selflab.SUPPORTED_OUTCOME_METRICS


def test_gate_detectable_effect_matches_closed_form(conn) -> None:
    _nights(conn, days=170, sd=3.0)
    gate = selflab.placebo_gate(
        conn,
        slug="d",
        outcome_metric="deep_sleep_min",
        min_effect=3.0,
        design="randomized_alternating",
    )
    assert gate is not None
    per_arm = gate["sessions_per_week"] / 7 * selflab._ADHERENCE / 2
    expected = (
        selflab._POWER_Z
        * gate["sd"]
        * math.sqrt(2 * gate["design_effect"] / (per_arm * selflab.MAX_DAYS_TO_ANSWER))
    )
    assert gate["detectable_120d"] == pytest.approx(expected, abs=0.01)


@pytest.mark.parametrize("metric", DAILY)
def test_short_history_is_refused_not_skipped(conn, metric) -> None:
    _nights(conn, days=6)
    with pytest.raises(ValueError, match="fewer than 10"):
        selflab._check_answerable(
            conn, outcome_metric=metric, min_effect=5.0, design="randomized_alternating"
        )


def test_min_effect_below_four_months_is_refused(conn) -> None:
    _nights(conn, days=170, sd=3.0)
    with pytest.raises(ValueError, match="smallest detectable"):
        selflab._check_answerable(
            conn,
            outcome_metric="deep_sleep_min",
            min_effect=0.1,
            design="randomized_alternating",
        )
    selflab._check_answerable(
        conn,
        outcome_metric="deep_sleep_min",
        min_effect=6.0,
        design="randomized_alternating",
    )
