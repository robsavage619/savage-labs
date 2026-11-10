from __future__ import annotations

import math
import random
from datetime import date, timedelta

import pytest

from shc import research

TODAY = date(2026, 6, 30)


def _seed(conn, effect_pct: float, days: int = 360, seed: int = 3) -> None:
    """Strain on day d moves day d+1's HRV by `effect_pct` when strain is high."""
    rng = random.Random(seed)
    start = TODAY - timedelta(days=days)
    high_prev = False
    for i in range(days + 1):
        d = start + timedelta(days=i)
        high = rng.random() < 0.5
        strain = rng.uniform(14, 18) if high else rng.uniform(4, 9)
        ln = math.log(100) + rng.gauss(0, 0.18) + (effect_pct / 100 if high_prev else 0.0)
        conn.execute(
            "INSERT INTO recovery (id, source, date, score, hrv, rhr, content_hash) VALUES (?, 'whoop', ?, 60, ?, 50, ?)",
            [f"r{i}", d, math.exp(ln), f"h{i}"],
        )
        conn.execute(
            "INSERT INTO daily_cycle (id, date, strain, content_hash) VALUES (?, ?, ?, ?)",
            [f"c{i}", d, strain, f"k{i}"],
        )
        high_prev = high


SPEC = {
    "exposure": {"feature": "strain", "a": {"max": 10}, "b": {"min": 14}},
    "outcome": "lnhrv_dev_pct",
    "lag": 1,
    "unit": "day",
    "expected_sign": "-",
    "min_effect": 3,
}


def test_recovers_a_planted_effect_inside_its_range(conn) -> None:
    _seed(conn, effect_pct=-10)
    res = research.estimate(conn, SPEC, today=TODAY)
    assert res["ci_low"] <= -10 <= res["ci_high"]
    assert res["verdict"] == "supported"
    assert res["power"]["needed_per_arm"] > 0


def test_null_effect_is_not_supported(conn) -> None:
    _seed(conn, effect_pct=0)
    res = research.estimate(conn, SPEC, today=TODAY)
    assert res["ci_low"] < 0 < res["ci_high"]
    assert res["verdict"] in ("inconclusive", "ruled_out")


def test_belief_posterior_sits_between_prior_and_data_and_narrows(conn) -> None:
    _seed(conn, effect_pct=-10)
    bid = research.add_belief(
        conn,
        "Hard days lower tomorrow's HRV",
        "lnhrv_dev_pct",
        -3.0,
        5.0,
        "test prior",
        None,
        "test",
    )
    research.register(
        conn, "strain-hrv", "Does a hard day lower tomorrow's HRV?", SPEC, bid, "test"
    )
    res = research.run(conn, "strain-hrv")
    b = next(x for x in research.beliefs(conn) if x["id"] == bid)
    assert min(-3.0, res["effect"]) <= b["post_mean"] <= max(-3.0, res["effect"])
    assert b["post_sd"] < 5.0
    # Re-running must not count the same days twice.
    research.run(conn, "strain-hrv")
    again = next(x for x in research.beliefs(conn) if x["id"] == bid)
    assert again["post_sd"] == pytest.approx(b["post_sd"], rel=0.05)


def test_specs_are_immutable_and_validated(conn) -> None:
    _seed(conn, effect_pct=0, days=60)
    research.register(conn, "s1", "q", SPEC, None, "test")
    with pytest.raises(research.SpecError):
        research.register(conn, "s1", "q", SPEC, None, "test")
    bad = SPEC | {"exposure": {"feature": "strain", "a": {"max": 12}, "b": {"min": 10}}}
    with pytest.raises(research.SpecError, match="overlap"):
        research.validate_spec(conn, bad)
    with pytest.raises(research.SpecError, match="unknown feature"):
        research.validate_spec(conn, SPEC | {"outcome": "made_up"})


def test_notebook_records_each_step(conn) -> None:
    _seed(conn, effect_pct=0, days=60)
    research.register(conn, "s2", "Short trial", SPEC, None, "analyst")
    research.run(conn, "s2", author="runner")
    kinds = [n["kind"] for n in research.notebook(conn)]
    assert kinds[:2] == ["result", "proposal"]
