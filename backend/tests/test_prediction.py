from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from shc import prediction, research

TODAY = date(2026, 6, 30)
DAYS = 400


def _days() -> list[date]:
    return [TODAY - timedelta(days=i) for i in range(DAYS, -1, -1)]


def _world(seed: int, effect: float, same_day_leak: bool = False):
    """Target is `effect` x last evening's feature plus noise; the rest is noise."""
    rng = np.random.default_rng(seed)
    days = _days()
    sig = {d: float(rng.normal()) for d in days}
    feats = {
        "sig": sig,
        "noise_a": {d: float(rng.normal()) for d in days},
        "noise_b": {d: float(rng.normal()) for d in days},
    }
    target = {
        d: 50 + effect * sig.get(d - timedelta(days=1), 0.0) + float(rng.normal()) for d in days
    }
    if same_day_leak:
        feats["leak"] = dict(target)
    return feats, target


def test_planted_signal_is_recovered_and_credited_to_its_feature() -> None:
    feats, target = _world(1, effect=2.0)
    r = prediction.backtest_series(feats, target, TODAY, min_scored=30)
    assert r["verdict"] == "skill"
    assert r["feeds"] is True
    assert r["skill_best"] > 0.5
    assert max(r["gains"], key=r["gains"].get) == "sig"
    assert r["gains"]["sig"] > 0.5 > max(r["gains"]["noise_a"], r["gains"]["noise_b"])


@pytest.mark.parametrize("seed", [2, 3, 4])
def test_pure_noise_is_a_tie_and_feeds_nothing(seed: int) -> None:
    feats, target = _world(seed, effect=0.0)
    r = prediction.backtest_series(feats, target, TODAY, min_scored=30)
    assert r["verdict"].startswith("no skill")
    assert r["feeds"] is False


def test_a_same_day_value_cannot_leak_into_the_forecast() -> None:
    feats, target = _world(5, effect=0.0, same_day_leak=True)
    r = prediction.backtest_series(feats, target, TODAY, min_scored=30)
    assert r["feeds"] is False


def test_too_few_unseen_points_withholds_skill() -> None:
    feats, target = _world(6, effect=2.0)
    short = {d: v for d, v in target.items() if d > TODAY - timedelta(days=70)}
    r = prediction.backtest_series(feats, short, TODAY, min_scored=30)
    assert r["skill"] is None and r["feeds"] is False and r["reason"]


def test_unknown_target_is_refused(conn) -> None:
    with pytest.raises(research.SpecError):
        prediction.backtest(conn, "hrv_ms")


def test_empty_database_reports_no_skill_without_crashing(conn) -> None:
    r = prediction.backtest(conn, "recovery_score", TODAY)
    assert r["feeds"] is False and r["skill"] is None
