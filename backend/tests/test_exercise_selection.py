from __future__ import annotations

from datetime import date, timedelta

import duckdb
import pytest

from shc.training.autoregulation import _exercise_menu, _progress_info, _select_grounded


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
    picks, _ = _select_grounded(cands, per_muscle=1, region_volume=region_volume)
    assert picks[0][0] == "Hammer Curl"


def test_covers_every_head_when_slots_allow() -> None:
    cands = [
        _cand("Incline Curl", "long_head"),
        _cand("Preacher Curl", "short_head"),
        _cand("Hammer Curl", "brachialis"),
    ]
    picks, _ = _select_grounded(cands, per_muscle=3)
    assert {p[2] for p in picks} == {"long_head", "short_head", "brachialis"}


def test_selection_is_stable_without_a_plateau() -> None:
    # Same head, same length/SFR, no progression signal: ordering is deterministic
    # (name tiebreak) and carries NO time term, so the same pick recurs every week
    # instead of churning. Fixed selection ≥ variation for hypertrophy (Balsalobre).
    cands = [
        _cand("Curl A", "short_head"),
        _cand("Curl B", "short_head"),
    ]
    assert _select_grounded(cands, per_muscle=1)[0][0][0] == "Curl A"
    # Re-running yields the identical pick — no rotation on a clock.
    assert _select_grounded(cands, per_muscle=1)[0][0][0] == "Curl A"


def test_swaps_only_when_the_current_pick_plateaus() -> None:
    # Same head, same length/SFR. When the alphabetically-leading option has
    # plateaued (rank 2) and the alternative is progressing (rank 0), the
    # progressing lift is promoted — the evidence-based swap-on-plateau trigger.
    cands = [
        _cand("Curl A", "short_head"),
        _cand("Curl B", "short_head"),
    ]
    progress = {"Curl A": 2, "Curl B": 0}  # A stalled, B progressing
    picks, _ = _select_grounded(cands, per_muscle=1, progress_rank=progress)
    assert picks[0][0] == "Curl B"


def test_progressing_staple_is_kept_over_an_untried_option() -> None:
    # A lift Rob is progressing on (rank 0) is kept ahead of an untried
    # alternative (rank 1) of equal quality — no rotation for novelty's sake.
    cands = [
        _cand("Proven Curl", "short_head"),
        _cand("Novel Curl", "short_head"),
    ]
    progress = {"Proven Curl": 0}  # Novel Curl absent → neutral rank 1
    picks, _ = _select_grounded(cands, per_muscle=1, progress_rank=progress)
    assert picks[0][0] == "Proven Curl"


def test_quality_outranks_plateau() -> None:
    # A plateaued lengthened/high-SFR exercise is NOT displaced by a fresh mid/low
    # one — the alternative is out of the science band (SFR drops two tiers), so
    # quality is never sacrificed for novelty. The lead is held.
    cands = [
        _cand("Mid Curl", "short_head", length="mid", sfr="low"),
        _cand("Stretch Curl", "short_head", length="lengthened", sfr="high"),
    ]
    progress = {"Stretch Curl": 2, "Mid Curl": 0}  # best exercise plateaued
    picks, notes = _select_grounded(cands, per_muscle=1, progress_rank=progress)
    assert picks[0][0] == "Stretch Curl"
    assert notes["Stretch Curl"] == "held: plateaued, no in-band alternative"


def test_quality_still_wins_within_a_head() -> None:
    # No region signal: lengthened + high-SFR must outrank a mid/low option.
    cands = [
        _cand("Mid Curl", "short_head", length="mid", sfr="low"),
        _cand("Stretch Curl", "short_head", length="lengthened", sfr="high"),
    ]
    picks, _ = _select_grounded(cands, per_muscle=1)
    assert picks[0][0] == "Stretch Curl"


def test_plateaued_lead_displaced_by_in_band_alternative() -> None:
    # Plateaued lengthened/high lead, progressing lengthened/moderate alternative:
    # one SFR step down, same length → in band → the alternative is swapped in as
    # the lead even though the plateaued lift still sorts first on keys 1–3.
    cands = [
        _cand("Stretch Curl", "short_head", length="lengthened", sfr="high"),
        _cand("Bayesian Curl", "short_head", length="lengthened", sfr="moderate"),
    ]
    progress = {"Stretch Curl": 2, "Bayesian Curl": 0}
    picks, notes = _select_grounded(cands, per_muscle=1, progress_rank=progress)
    assert picks[0][0] == "Bayesian Curl"
    assert notes["Bayesian Curl"].startswith("swapped in")
    assert notes["Stretch Curl"] == "swap candidate: plateaued"


def test_plateaued_lead_not_displaced_out_of_band_on_length() -> None:
    # Progressing alternative is shortened — stepping lengthened→shortened is out
    # of band (length bias is a hard floor), so the plateaued lead is held.
    cands = [
        _cand("Stretch Curl", "short_head", length="lengthened", sfr="high"),
        _cand("Spider Curl", "short_head", length="shortened", sfr="high"),
    ]
    progress = {"Stretch Curl": 2, "Spider Curl": 0}
    picks, notes = _select_grounded(cands, per_muscle=1, progress_rank=progress)
    assert picks[0][0] == "Stretch Curl"
    assert notes["Stretch Curl"] == "held: plateaued, no in-band alternative"


def test_untried_alternative_can_displace_a_plateaued_lead() -> None:
    # An untried (rank 1) in-band alternative counts as non-plateaued and displaces
    # a plateaued lead — after alias repair the untried set is honest, and the menu
    # flags it for equipment verification. The lead wins keys 1–3 (higher SFR) so
    # only the displacement pass can surface the untried option.
    cands = [
        _cand("Stretch Curl", "short_head", length="lengthened", sfr="high"),
        _cand("Fresh Curl", "short_head", length="lengthened", sfr="moderate"),
    ]
    progress = {"Stretch Curl": 2}  # Fresh Curl absent → neutral rank 1
    picks, notes = _select_grounded(cands, per_muscle=1, progress_rank=progress)
    assert picks[0][0] == "Fresh Curl"
    assert notes["Fresh Curl"].startswith("swapped in")


def test_displaced_lead_still_appears_in_the_menu() -> None:
    # With room for both, the displaced plateaued lead resurfaces in the fill pass
    # (tagged) rather than vanishing, so its history stays visible.
    cands = [
        _cand("Stretch Curl", "short_head", length="lengthened", sfr="high"),
        _cand("Bayesian Curl", "short_head", length="lengthened", sfr="moderate"),
    ]
    progress = {"Stretch Curl": 2, "Bayesian Curl": 0}
    picks, notes = _select_grounded(cands, per_muscle=2, progress_rank=progress)
    names = [p[0] for p in picks]
    assert names[0] == "Bayesian Curl"
    assert "Stretch Curl" in names
    assert notes["Stretch Curl"] == "swap candidate: plateaued"


@pytest.fixture
def fallback_conn() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE exercise_preferences (exercise TEXT, status TEXT)")
    c.execute("CREATE TABLE exercise_muscle_map (exercise_name TEXT, primary_muscle TEXT)")
    c.execute(
        "CREATE TABLE workout_sets_dedup "
        "(exercise TEXT, started_at TIMESTAMP, is_warmup BOOLEAN)"
    )
    return c


def _map(c, exercise, muscle="delts"):
    c.execute("INSERT INTO exercise_muscle_map VALUES (?, ?)", [exercise, muscle])


def _set(c, exercise, day, warmup=False):
    c.execute(
        "INSERT INTO workout_sets_dedup VALUES (?, ?, ?)",
        [exercise, f"{day} 10:00:00", warmup],
    )


def test_fallback_menu_is_stale_first_with_never_done_last(fallback_conn) -> None:
    c = fallback_conn
    for ex in ("Stale Raise", "Mid Raise", "Recent Raise", "Never Raise"):
        _map(c, ex)
    _set(c, "Stale Raise", "2026-01-01")
    _set(c, "Mid Raise", "2026-04-01")
    _set(c, "Recent Raise", "2026-07-10")
    # "Never Raise" has no working sets logged.
    menu = _exercise_menu(c, ["delts"], per_muscle=4)
    names = [e["exercise"] for e in menu["delts"]]
    # Everything fits: stalest first, never-logged genuinely last.
    assert names == ["Stale Raise", "Mid Raise", "Recent Raise", "Never Raise"]
    never = next(e for e in menu["delts"] if e["exercise"] == "Never Raise")
    assert never["last_done"] is None


def test_fallback_menu_reserves_a_slot_for_the_freshest_staple(fallback_conn) -> None:
    # More candidates than slots: taking only the stalest would drop what Rob is
    # currently running, so the freshest staple is reserved into the last slot.
    c = fallback_conn
    _map(c, "Stale Raise")
    _map(c, "Mid Raise")
    _map(c, "Older Raise")
    _map(c, "Recent Raise")
    _set(c, "Stale Raise", "2026-01-01")
    _set(c, "Mid Raise", "2026-03-01")
    _set(c, "Older Raise", "2026-05-01")
    _set(c, "Recent Raise", "2026-07-10")
    menu = _exercise_menu(c, ["delts"], per_muscle=3)
    names = [e["exercise"] for e in menu["delts"]]
    assert names[0] == "Stale Raise"  # stalest still leads
    assert names[-1] == "Recent Raise"  # freshest reserved in
    assert "Older Raise" not in names  # dropped to make room


def test_fallback_menu_excludes_warmup_only_from_recency(fallback_conn) -> None:
    c = fallback_conn
    _map(c, "Warmup Only Raise")
    _set(c, "Warmup Only Raise", "2026-07-15", warmup=True)
    menu = _exercise_menu(c, ["delts"], per_muscle=4)
    entry = next(e for e in menu["delts"] if e["exercise"] == "Warmup Only Raise")
    assert entry["last_done"] is None  # warmups don't count as trained


@pytest.fixture
def trend_conn() -> duckdb.DuckDBPyConnection:
    c = duckdb.connect(":memory:")
    c.execute(
        "CREATE TABLE exercise_weekly_e1rm "
        "(exercise TEXT, week_start DATE, e1rm_kg DOUBLE, work_sets INTEGER, "
        " perf_score INTEGER, trend TEXT, weekly_tonnage_kg DOUBLE)"
    )
    c.execute(
        "CREATE TABLE workout_sets_dedup "
        "(exercise TEXT, started_at TIMESTAMP, is_warmup BOOLEAN)"
    )
    return c


def _rising_series(c, exercise, weeks_ago_start: int, n: int = 6) -> None:
    # n consecutive weeks of steadily rising e1RM (~1%/wk → clearly progressing),
    # the oldest `weeks_ago_start` weeks before today.
    base = date.today() - timedelta(weeks=weeks_ago_start)
    for i in range(n):
        wk = base + timedelta(weeks=i)
        e1rm = 100.0 + i  # +1kg/wk on a 100kg base ≈ +1%/wk
        c.execute(
            "INSERT INTO exercise_weekly_e1rm VALUES (?, ?, ?, ?, NULL, NULL, ?)",
            [exercise, wk.isoformat(), e1rm, 4, e1rm * 20],
        )
        c.execute(
            "INSERT INTO workout_sets_dedup VALUES (?, ?, FALSE)",
            [exercise, f"{(wk + timedelta(days=2)).isoformat()} 10:00:00"],
        )


def test_recent_progressing_trend_is_kept(trend_conn) -> None:
    # Rising e1RM through last week → live progressing signal → rank 0, "kept".
    _rising_series(trend_conn, "Fresh Lift", weeks_ago_start=6)
    info = _progress_info(trend_conn, {"Fresh Lift"})["Fresh Lift"]
    assert info["trend"] == "progressing"
    assert info["rank"] == 0


def test_stale_progressing_trend_is_demoted_to_neutral(trend_conn) -> None:
    # Same rising shape but the series ended ~1 year ago: score_exercise still
    # fits it as "progressing", but the exercise hasn't been trained in months, so
    # the signal isn't live — it must go neutral (rank 1), not pin a "kept" lead.
    _rising_series(trend_conn, "Dormant Lift", weeks_ago_start=60)
    info = _progress_info(trend_conn, {"Dormant Lift"})["Dormant Lift"]
    assert info["trend"] == "stale"
    assert info["rank"] == 1
