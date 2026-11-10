from __future__ import annotations

import random
from datetime import date, timedelta

from shc import lab, selflab


def _ar1(n: int, rho: float, seed: int) -> list[tuple[date, float]]:
    rng = random.Random(seed)
    x, out = 0.0, []
    for i in range(n):
        x = rho * x + rng.gauss(0, 1)
        out.append((date(2025, 1, 1) + timedelta(days=i), x))
    return out


def test_design_effect_tracks_autocorrelation() -> None:
    assert selflab._design_effect(_ar1(2000, 0.0, 1)) < 1.15
    # (1 + 0.5) / (1 - 0.5) = 3
    assert 2.4 < selflab._design_effect(_ar1(2000, 0.5, 2)) < 3.6
    # Gaps break the chain: no consecutive pairs, no inflation.
    sparse = [(date(2025, 1, 1) + timedelta(days=2 * i), float(i % 3)) for i in range(50)]
    assert selflab._design_effect(sparse) == 1.0


def test_inflated_p_and_ci_get_wider_never_narrower() -> None:
    assert selflab._inflate_p(0.04, 1.0) == 0.04
    assert selflab._inflate_p(0.04, 2.0) > 0.04
    lo, hi = selflab._inflate_ci(2.0, 1.0, 3.0, 4.0)
    assert (lo, hi) == (0.0, 4.0)


def test_days_needed_per_arm_matches_the_textbook_formula() -> None:
    # 2 * ((1.645 + 0.842) * 25 / 5)^2 * 1.5 ≈ 464
    assert 455 <= selflab._needed_per_arm(sd=25.0, min_effect=5.0, design_effect=1.5) <= 470


def _finding(effect: float | None, p: float | None) -> lab.LabFinding:
    return lab.LabFinding("q", 100, effect, "ms", p, "refuted", "s", [])


def test_wrong_sign_estimate_with_a_wide_range_is_not_refuted() -> None:
    q = {"threshold": 5.0, "direction": "positive"}
    f = _finding(-0.8, 0.89)
    lab._gate_refuted(f, q)
    assert f.verdict == "inconclusive"


def test_range_that_excludes_the_hypothesised_effect_stays_refuted() -> None:
    q = {"threshold": 5.0, "direction": "positive"}
    f = _finding(-10.0, 0.001)
    lab._gate_refuted(f, q)
    assert f.verdict == "refuted"


def test_refuted_without_a_p_value_cannot_rule_anything_out() -> None:
    f = _finding(0.14, None)
    lab._gate_refuted(f, {"threshold": 0.3, "direction": "positive"})
    assert f.verdict == "inconclusive"
