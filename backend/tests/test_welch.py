from __future__ import annotations

import pytest

from shc.stats.welch import welch_t


def test_welch_t_matches_the_known_two_sample_result() -> None:
    t, p = welch_t([1.0, 2.0, 3.0, 4.0, 5.0], [3.0, 4.0, 5.0, 6.0, 7.0])
    assert t == pytest.approx(-2.0)
    assert p == pytest.approx(0.0805, abs=1e-3)


def test_welch_t_is_undefined_without_variance_or_samples() -> None:
    assert welch_t([1.0], [1.0, 2.0]) is None
    assert welch_t([2.0, 2.0], [2.0, 2.0]) is None
