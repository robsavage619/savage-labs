from __future__ import annotations

from shc.metrics import BodyComposition, _body_comp_note


def _bc(direction: str) -> BodyComposition:
    return BodyComposition(trend_direction=direction)


def test_leaner_with_weight_up_flags_conflict_not_recomp():
    """M9: waist-leaner while weight rises must NOT read as 'recomp on track'.

    This is the exact (Δwaist↓, Δweight↑) the photo endpoint calls a conflict —
    the two paths must agree.
    """
    note = _body_comp_note(_bc("leaner"), weight_trend_4wk=2.5)
    assert note is not None
    assert "disagree" in note
    assert "recomp on track" not in note


def test_leaner_with_weight_held_is_recomp():
    note = _body_comp_note(_bc("leaner"), weight_trend_4wk=0.3)
    assert note is not None
    assert "recomp on track" in note


def test_leaner_with_weight_down_is_leaning_out():
    note = _body_comp_note(_bc("leaner"), weight_trend_4wk=-2.0)
    assert note is not None
    assert "leaning out" in note


def test_none_when_no_trend_or_weight():
    assert _body_comp_note(_bc("leaner"), None) is None
    assert _body_comp_note(BodyComposition(trend_direction=None), 1.0) is None
