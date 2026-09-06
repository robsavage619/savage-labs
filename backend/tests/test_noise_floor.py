"""Guards for the personal noise floor (`shc.stats.noise_floor`).

The failure this module exists to prevent is a dashboard manufacturing a trend:
rendering "improving" or "declining" for a delta the subject's own series cannot
resolve. Every test below is about refusing to answer when the data can't.
"""

from __future__ import annotations

import pytest

from shc.stats import classify_change, swc


def test_flat_baseline_gives_a_zero_floor_not_a_missing_one():
    """0.0 is an answer — any movement is outside the noise. `if swc` erases it."""
    assert swc([100.0] * 10) == 0.0
    assert swc([100.0] * 10) is not None


def test_short_window_refuses_rather_than_guessing():
    assert swc([1.0, 2.0, 3.0]) is None
    assert swc([]) is None
    assert swc([1.0] * 7) is not None  # exactly at the minimum


def test_swc_is_half_the_sample_sd():
    # SD of 1..5 (sample, n-1) is sqrt(2.5) = 1.5811; half is 0.7906.
    assert swc([1.0, 2.0, 3.0, 4.0, 5.0, 3.0, 3.0]) == pytest.approx(
        0.5 * (sum((x - 3.0) ** 2 for x in [1, 2, 3, 4, 5, 3, 3]) / 6) ** 0.5
    )


def test_a_change_inside_the_floor_reports_flat_whatever_its_sign():
    noisy = [100.0, 104.0, 96.0, 102.0, 98.0, 103.0, 97.0, 101.0, 99.0, 100.0]
    up = classify_change(101.0, noisy)
    down = classify_change(99.0, noisy)
    assert up.within_noise is True and up.direction == "flat"
    assert down.within_noise is True and down.direction == "flat"
    # The arithmetic is still reported — it is the VERDICT that is withheld.
    assert up.delta is not None and up.delta > 0


def test_a_change_outside_the_floor_keeps_its_direction():
    v = classify_change(160.0, [100.0] * 10)
    assert v.within_noise is False
    assert v.direction == "up"
    v = classify_change(40.0, [100.0] * 10)
    assert v.direction == "down"


def test_unresolvable_inputs_say_unknown_rather_than_flat():
    """Missing data must not masquerade as 'no change'."""
    assert classify_change(None, [100.0] * 10).direction == "unknown"
    assert classify_change(100.0, []).direction == "unknown"
    assert classify_change(100.0, [1.0, 2.0]).direction == "unknown"  # window too short
    assert classify_change(100.0, [1.0, 2.0]).within_noise is None


def test_payload_shape_is_stable():
    d = classify_change(160.0, [100.0] * 10).as_dict()
    assert set(d) == {"value", "baseline", "delta", "swc", "within_noise", "direction"}
