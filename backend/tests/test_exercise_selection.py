from __future__ import annotations

from datetime import datetime

from shc.training.autoregulation import _select_grounded


def _cand(name: str, region: str, length: str = "mid", sfr: str = "moderate", last=None):
    """Build an exercise_science candidate tuple matching evidence_menu's SELECT.

    Columns: name, muscle, region, length_bias, rep_low, rep_high, sfr_tier,
    rationale, citation, citation_url, last_done (index 10).
    """
    return (name, "biceps", region, length, 8, 12, sfr, "why", "Cite 2020", "url", last)


def test_leads_with_least_trained_head() -> None:
    cands = [
        _cand("Incline Curl", "long_head", length="lengthened"),
        _cand("Preacher Curl", "short_head", length="lengthened"),
        _cand("Hammer Curl", "brachialis"),
    ]
    # brachialis untrained, long/short already hit → brachialis must lead.
    region_volume = {"long_head": 6.0, "short_head": 4.0, "brachialis": 0.0}
    picks = _select_grounded(cands, per_muscle=1, region_volume=region_volume)
    assert picks[0][0] == "Hammer Curl"


def test_covers_every_head_when_slots_allow() -> None:
    cands = [
        _cand("Incline Curl", "long_head"),
        _cand("Preacher Curl", "short_head"),
        _cand("Hammer Curl", "brachialis"),
    ]
    picks = _select_grounded(cands, per_muscle=3)
    assert {p[2] for p in picks} == {"long_head", "short_head", "brachialis"}


def test_rotates_among_equal_quality_options() -> None:
    # Same head, same length/SFR: the least-recently-trained one is picked so
    # selection rotates week to week instead of freezing (the dead-recency bug).
    recent = datetime(2026, 7, 1)
    stale = datetime(2026, 1, 1)
    cands = [
        _cand("Curl A", "short_head", last=recent),
        _cand("Curl B", "short_head", last=stale),
    ]
    picks = _select_grounded(cands, per_muscle=1)
    assert picks[0][0] == "Curl B"  # older → rotate to it


def test_quality_still_wins_within_a_head() -> None:
    # No region signal: lengthened + high-SFR must outrank a mid/low option.
    cands = [
        _cand("Mid Curl", "short_head", length="mid", sfr="low"),
        _cand("Stretch Curl", "short_head", length="lengthened", sfr="high"),
    ]
    picks = _select_grounded(cands, per_muscle=1)
    assert picks[0][0] == "Stretch Curl"
