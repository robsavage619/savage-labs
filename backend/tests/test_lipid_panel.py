"""Guards for the derived atherogenic lipid measures on /api/clinical/risk.

Everything here is exact arithmetic on one blood draw. The tests exist to stop
three specific ways that arithmetic can go quietly wrong: mixing draws, treating
a Friedewald LDL as trustworthy at high triglycerides, and losing the caveat
that makes the number safe to read.
"""

from __future__ import annotations

import pytest

from shc.api.routers.dashboard import _lipid_panel

# Rob's 2023-12-03 panel — the draw this feature was built against.
_ROB = {
    "Total Cholesterol": {"value": 210.0, "collected_at": "2023-12-03"},
    "HDL Cholesterol": {"value": 44.0, "collected_at": "2023-12-03"},
    "Triglycerides": {"value": 298.0, "collected_at": "2023-12-03"},
    "LDL Cholesterol (calc)": {"value": 106.0, "collected_at": "2023-12-03"},
}


def test_non_hdl_is_total_minus_hdl():
    out = _lipid_panel(_ROB)
    assert out["non_hdl_c"]["value"] == pytest.approx(166.0)
    assert out["non_hdl_c"]["at_target"] is False
    assert out["non_hdl_c"]["above_target_by"] == pytest.approx(36.0)


def test_remnant_cholesterol_clears_the_wadstrom_threshold():
    """60 mg/dL against a 39 mg/dL cut-point — this must not read as normal."""
    out = _lipid_panel(_ROB)
    assert out["remnant_c"]["value"] == pytest.approx(60.0)
    assert out["remnant_c"]["elevated"] is True


def test_friedewald_is_flagged_unreliable_above_150_tg():
    """The whole point: a soft LDL must announce that it is soft."""
    out = _lipid_panel(_ROB)
    est = out["ldl_estimate"]
    assert est["reliable"] is False
    assert est["valid"] is True  # unreliable, but not yet formally invalid
    assert "UNDERSTATE" in est["caveat"]


def test_friedewald_is_reliable_at_normal_triglycerides():
    panel = dict(_ROB, **{"Triglycerides": {"value": 90.0, "collected_at": "2023-12-03"}})
    est = _lipid_panel(panel)["ldl_estimate"]
    assert est["reliable"] is True
    assert est["caveat"] is None


def test_friedewald_goes_formally_invalid_at_400():
    panel = dict(_ROB, **{"Triglycerides": {"value": 420.0, "collected_at": "2023-12-03"}})
    est = _lipid_panel(panel)["ldl_estimate"]
    assert est["valid"] is False


def test_mixed_draws_are_flagged_not_silently_subtracted():
    """A 2026 total cholesterol minus a 2023 HDL is not a lipid measure."""
    panel = dict(_ROB, **{"Total Cholesterol": {"value": 210.0, "collected_at": "2026-09-04"}})
    assert _lipid_panel(panel)["single_draw"] is False


def test_absent_panel_returns_none_not_a_zero():
    assert _lipid_panel({}) is None
    assert _lipid_panel({"HDL Cholesterol": {"value": 44.0, "collected_at": "2023-12-03"}}) is None


def test_remnant_is_none_when_ldl_is_missing_rather_than_wrong():
    panel = {k: v for k, v in _ROB.items() if k != "LDL Cholesterol (calc)"}
    out = _lipid_panel(panel)
    assert out["remnant_c"] is None
    assert out["non_hdl_c"]["value"] == pytest.approx(166.0)  # still computable
