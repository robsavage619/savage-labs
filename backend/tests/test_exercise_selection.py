from __future__ import annotations

from shc.training.autoregulation import _select_grounded


def _cand(name: str, region: str, length: str = "mid", sfr: str = "moderate"):
    """Build an exercise_science candidate tuple matching evidence_menu's SELECT.

    Columns: name, muscle, region, length_bias, rep_low, rep_high, sfr_tier,
    rationale, citation, citation_url.
    """
    return (name, "biceps", region, length, 8, 12, sfr, "why", "Cite 2020", "url")


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


def test_selection_is_stable_without_a_plateau() -> None:
    # Same head, same length/SFR, no progression signal: ordering is deterministic
    # (name tiebreak) and carries NO time term, so the same pick recurs every week
    # instead of churning. Fixed selection ≥ variation for hypertrophy (Balsalobre).
    cands = [
        _cand("Curl A", "short_head"),
        _cand("Curl B", "short_head"),
    ]
    assert _select_grounded(cands, per_muscle=1)[0][0] == "Curl A"
    # Re-running yields the identical pick — no rotation on a clock.
    assert _select_grounded(cands, per_muscle=1)[0][0] == "Curl A"


def test_swaps_only_when_the_current_pick_plateaus() -> None:
    # Same head, same length/SFR. When the alphabetically-leading option has
    # plateaued (rank 2) and the alternative is progressing (rank 0), the
    # progressing lift is promoted — the evidence-based swap-on-plateau trigger.
    cands = [
        _cand("Curl A", "short_head"),
        _cand("Curl B", "short_head"),
    ]
    progress = {"Curl A": 2, "Curl B": 0}  # A stalled, B progressing
    assert _select_grounded(cands, per_muscle=1, progress_rank=progress)[0][0] == "Curl B"


def test_progressing_staple_is_kept_over_an_untried_option() -> None:
    # A lift Rob is progressing on (rank 0) is kept ahead of an untried
    # alternative (rank 1) of equal quality — no rotation for novelty's sake.
    cands = [
        _cand("Proven Curl", "short_head"),
        _cand("Novel Curl", "short_head"),
    ]
    progress = {"Proven Curl": 0}  # Novel Curl absent → neutral rank 1
    assert _select_grounded(cands, per_muscle=1, progress_rank=progress)[0][0] == "Proven Curl"


def test_quality_outranks_plateau() -> None:
    # Plateau is only a tiebreak: a plateaued lengthened/high-SFR exercise still
    # beats a fresh mid/low one — science quality is never sacrificed for novelty.
    cands = [
        _cand("Mid Curl", "short_head", length="mid", sfr="low"),
        _cand("Stretch Curl", "short_head", length="lengthened", sfr="high"),
    ]
    progress = {"Stretch Curl": 2, "Mid Curl": 0}  # best exercise plateaued
    assert _select_grounded(cands, per_muscle=1, progress_rank=progress)[0][0] == "Stretch Curl"


def test_quality_still_wins_within_a_head() -> None:
    # No region signal: lengthened + high-SFR must outrank a mid/low option.
    cands = [
        _cand("Mid Curl", "short_head", length="mid", sfr="low"),
        _cand("Stretch Curl", "short_head", length="lengthened", sfr="high"),
    ]
    picks = _select_grounded(cands, per_muscle=1)
    assert picks[0][0] == "Stretch Curl"
