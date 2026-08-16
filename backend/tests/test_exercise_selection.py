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
        "CREATE TABLE workout_sets_dedup (exercise TEXT, started_at TIMESTAMP, is_warmup BOOLEAN)"
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
        " perf_score INTEGER, trend TEXT, weekly_tonnage_kg DOUBLE, "
        " weekly_avg_rpe DOUBLE, rpe_set_count INTEGER)"
    )
    c.execute(
        "CREATE TABLE workout_sets_dedup (exercise TEXT, started_at TIMESTAMP, is_warmup BOOLEAN)"
    )
    return c


def _rising_series(c, exercise, weeks_ago_start: int, n: int = 6) -> None:
    # n consecutive weeks of steadily rising e1RM (~1%/wk → clearly progressing),
    # the oldest `weeks_ago_start` weeks before today.
    base = date.today() - timedelta(weeks=weeks_ago_start)
    for i in range(n):
        wk = base + timedelta(weeks=i)
        e1rm = 100.0 + i  # +1kg/wk on a 100kg base ≈ +1%/wk
        # Name the columns: a bare positional VALUES silently re-maps every time
        # a column is added to the rollup (0079 added two and shifted tonnage
        # into weekly_avg_rpe, flipping these trends without touching the code
        # under test).
        c.execute(
            "INSERT INTO exercise_weekly_e1rm "
            "(exercise, week_start, e1rm_kg, work_sets, perf_score, trend, weekly_tonnage_kg) "
            "VALUES (?, ?, ?, ?, NULL, NULL, ?)",
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


# --- Catalog name bridge (2026-08-08) ----------------------------------------
# The engine rotated correctly and then named exercises Rob cannot log, so the
# displaced staple stayed in the plan. These lock the vocabulary shut.


def test_every_curated_movement_is_loggable(conn) -> None:
    """The selection menu may only offer exercises Rob can actually put in Hevy.

    A curated movement outside that vocabulary consumes a menu slot and, when it
    wins the 6-week rotation, kills the swap outright — the replacement cannot be
    written, so the lift it displaced stays in the plan. This was the mechanism
    behind Face Pull and Lateral Raise appearing on 23 of 49 training days.
    """
    from shc.training.autoregulation import unloggable_curated

    # Four movements are knowingly unavailable (absent from Hevy AND never
    # logged): they are filtered at runtime and reported by /training/alias-gaps.
    # The bar is that the list does not GROW — a new curated row must name a
    # loggable exercise.
    assert len(unloggable_curated(conn)) <= 4


def test_menu_never_offers_an_unloggable_movement(conn) -> None:
    """With a catalog present, an unloggable curated movement must be filtered out."""
    from shc.training.autoregulation import evidence_menu, loggable_names

    curated = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT exercise_name FROM exercise_science WHERE muscle = 'biceps'"
        ).fetchall()
    ]
    assert len(curated) > 2, "fixture has too few biceps options to prove a filter"
    # Publish every curated biceps movement to the catalog EXCEPT one.
    withheld = sorted(curated)[0]
    for name in curated:
        if name != withheld:
            conn.execute(
                "INSERT INTO hevy_exercise_templates (id, title, primary_muscle_group) "
                "VALUES (?, ?, 'biceps')",
                [name, name],
            )

    legal = loggable_names(conn)
    assert withheld not in legal

    offered = {p["exercise"] for p in evidence_menu(conn, ["biceps"])["biceps"]}
    assert offered, "menu returned nothing — fixture regression, not a real pass"
    assert withheld not in offered, "menu offered a movement Rob cannot log"
    assert not (offered - legal)


def test_empty_catalog_does_not_empty_the_menu(conn) -> None:
    """No catalog rows means the vocabulary is unknown, not that nothing is legal.

    Filtering against an empty set would silently blank every menu — a far worse
    failure than the naming gap this guards.
    """
    from shc.training.autoregulation import evidence_menu, loggable_names

    assert loggable_names(conn) == set()
    assert evidence_menu(conn, ["biceps"]).get("biceps")


def test_one_movement_cannot_occupy_two_menu_slots(conn) -> None:
    """The catalog carried the same lift under two name conventions.

    Without a movement-identity key the pair could both be picked, or one be
    'swapped in' to replace the other — burning a rotation on a pure rename
    (e.g. 'Dumbbell Bench Press' replacing 'Bench Press (Dumbbell)').
    """
    from shc.training.autoregulation import _movement_key, evidence_menu

    for muscle, picks in evidence_menu(conn, ["chest", "biceps", "triceps"]).items():
        keys = [_movement_key(p["exercise"]) for p in picks]
        assert len(keys) == len(set(keys)), f"{muscle} offers one movement twice: {picks}"


def test_movement_key_keeps_equipment_distinct() -> None:
    """Punctuation collapses; equipment never does — a machine press is not a
    dumbbell press, and an earlier fuzzy pass that ignored this paired seated
    with standing calf raises."""
    from shc.training.autoregulation import _movement_key

    assert _movement_key("Bench Press (Dumbbell)") == _movement_key("Dumbbell Bench Press")
    assert _movement_key("Chin-Up") == _movement_key("Chin Up")
    assert _movement_key("Machine Bench Press") != _movement_key("Bench Press (Dumbbell)")
    assert _movement_key("Seated Calf Raise (Machine)") != _movement_key(
        "Standing Calf Raise (Machine)"
    )


def test_sparse_catalog_does_not_blank_a_muscle(conn) -> None:
    """A partial template sync must not read as 'nothing to train here'.

    `loggable_names` is non-empty but covers none of the biceps options; keeping
    the candidates is strictly better than emptying the muscle's menu.
    """
    from shc.training.autoregulation import evidence_menu

    conn.execute(
        "INSERT INTO hevy_exercise_templates (id, title, primary_muscle_group) "
        "VALUES ('t1', 'Some Unrelated Machine', 'calves')"
    )
    assert evidence_menu(conn, ["biceps"]).get("biceps")


def test_every_muscle_can_rotate(conn) -> None:
    """A muscle needs MORE distinct movements than menu slots, or it never rotates.

    With exactly 4 curated movements against 4 slots the coverage pass takes one
    and the fill pass takes the rest — the same four every week, and no plateau
    or tenure trigger can act because there is no alternative to swap to. Rear
    and side delts sat exactly there (migration 0091). Guards against a future
    merge quietly dropping a muscle back to the floor.
    """
    from shc.training.autoregulation import _movement_key, loggable_names

    legal = loggable_names(conn)
    if not legal:  # fixture without a catalog — vocabulary filter is a no-op
        legal = {
            r[0]
            for r in conn.execute("SELECT DISTINCT exercise_name FROM exercise_muscle").fetchall()
        }
    thin = {}
    for (muscle,) in conn.execute("SELECT DISTINCT muscle FROM exercise_science").fetchall():
        names = [
            r[0]
            for r in conn.execute(
                "SELECT exercise_name FROM exercise_science WHERE muscle = ?", [muscle]
            ).fetchall()
            if r[0] in legal
        ]
        movements = {_movement_key(n) for n in names}
        if len(movements) <= 4:
            thin[muscle] = sorted(movements)
    assert not thin, f"muscles that cannot rotate (need >4 distinct movements): {thin}"


def test_duplicate_twins_rank_by_recency_not_lifetime_volume(conn) -> None:
    """The live name must win, not the one with the biggest historical pile.

    'Dumbbell Lateral Raise' carries 438 Fitbod-era sets against 57 for
    'Lateral Raise (Dumbbell)', the string Rob logs today. Ranking on lifetime
    count surfaced the dead name — tagged "stale: not trained in >6wk" — and hid
    a lift performed three days earlier.
    """
    from datetime import date, timedelta

    from shc.training.autoregulation import _logged_recency

    recency = _logged_recency(conn, ["nonexistent-exercise"])
    assert recency == {} or "nonexistent-exercise" not in recency
    # Ordering contract: (last hevy date desc, then count desc).
    fresh_small = (date.today(), 5)
    stale_big = (date.today() - timedelta(days=200), 500)
    assert fresh_small[0].toordinal() > stale_big[0].toordinal()


def test_alias_never_overrides_fresher_own_history(conn, seed) -> None:
    """A stale or inverted alias row must degrade to a no-op, not corrupt selection.

    An alias redirects the plateau/recency lookup from the curated name to the
    string Rob logs it under, and it only helps while the curated name has no
    history of its own. Once he logs the curated string directly, following the
    redirect reads the OLDER name and reports a lift done days ago as
    "stale: not trained in >6wk" — handing its slot to a worse option.
    """
    from datetime import date, timedelta

    from shc.training.autoregulation import _progress_info

    today = date.today()
    curated, dead = "Lateral Raise (Dumbbell)", "Dumbbell Lateral Raise"
    seed.workout(today - timedelta(days=200), dead, [(10.0, 12)] * 3)
    seed.workout(today - timedelta(days=3), curated, [(10.0, 12)] * 3)

    info = _progress_info(conn, {curated}, {curated: dead})
    assert info[curated]["last_done"] == (today - timedelta(days=3)).isoformat()
    assert info[curated]["trend"] != "stale"


def test_alias_still_followed_when_curated_name_is_unlogged(conn, seed) -> None:
    """The guard must not break the case the alias exists for."""
    from datetime import date, timedelta

    from shc.training.autoregulation import _progress_info

    today = date.today()
    seed.workout(today - timedelta(days=3), "Cable Tricep Pushdown", [(30.0, 10)] * 3)
    info = _progress_info(
        conn, {"Tricep Pushdown (Cable)"}, {"Tricep Pushdown (Cable)": "Cable Tricep Pushdown"}
    )
    assert info["Tricep Pushdown (Cable)"]["last_done"] == (today - timedelta(days=3)).isoformat()


# ── Rotation tenure: the value production actually passes ────────────────────


def test_tenure_measures_slot_occupancy_not_evidence_depth(conn, seed) -> None:
    """The bug this locks: `_progress_info` handed selection `len(e1rm history)`
    as tenure. That counts weeks with e1RM data anywhere in history, capped at
    14, so a lift last trained in 2019 reported six weeks of "tenure" and read as
    an incumbent due for rotation. 60% of candidates were flagged that way.

    Testing `_select_grounded` with a synthetic tenure dict — which is all the
    suite did before — cannot catch this: the mechanism was always correct, the
    number fed into it was not.
    """
    from datetime import date, timedelta

    from shc.training.autoregulation import _progress_info

    today = date.today()
    abandoned = "Abandoned Press"
    # Deep history, none of it recent: eight weeks of real training, two years ago.
    for wk in range(8):
        seed.workout(today - timedelta(weeks=104 + wk), abandoned, [(40.0, 10)] * 3)

    info = _progress_info(conn, {abandoned})
    assert info[abandoned]["tenure"] == 0, (
        "a lift not trained in two years holds no slot and cannot be 'due for rotation'"
    )


def test_tenure_survives_a_skipped_week(conn, seed) -> None:
    """Exposure, not a streak.

    A consecutive-week counter resets on every missed week, and Rob trains a lift
    twice one week then skips the next. Measured against his real history a
    streak fired on 5 of 16 monopoly lifts and missed the worst of them — triceps
    at streak 1 while one exercise owned 63% of its sets.
    """
    from datetime import date, timedelta

    from shc.training.autoregulation import _ROTATE_AFTER_WEEKS, _progress_info

    today = date.today()
    staple = "Skipping Staple"
    # Trained most weeks across the window, with a gap that would zero a streak.
    for wk in (0, 1, 2, 4, 5, 6, 7):
        seed.workout(today - timedelta(weeks=wk), staple, [(40.0, 10)] * 3)

    info = _progress_info(conn, {staple})
    assert info[staple]["tenure"] >= _ROTATE_AFTER_WEEKS, (
        "a lift trained 7 of the last 8 weeks holds its slot despite the skipped week"
    )


def test_a_benched_lift_stops_claiming_tenure(conn, seed) -> None:
    """The cooldown. Rotating a lift out must not leave it flagged forever, or it
    can never come back; equally it must not free up instantly, or it re-wins the
    slot the following week and the rotation ping-pongs.
    """
    from datetime import date, timedelta

    from shc.training.autoregulation import _progress_info

    today = date.today()
    benched = "Benched Staple"
    for wk in range(4, 12):  # ran for eight weeks, then benched a month ago
        seed.workout(today - timedelta(weeks=wk), benched, [(40.0, 10)] * 3)

    assert _progress_info(conn, {benched})[benched]["tenure"] == 0


# ── Availability: what may LEAD a head ───────────────────────────────────────


def test_an_unverified_movement_never_leads_a_head_that_has_a_verified_option() -> None:
    """Nine of seventeen muscles led with a movement never logged or last touched
    in 2018 — chest with a 2019 barbell bench, lats with a Chin Up carrying no
    logged set at all. The quality keys are indifferent to whether the equipment
    exists, so a paper-perfect option outranked everything Rob can actually do,
    and the menu read as noise.
    """
    # The unverified option genuinely outranks on the quality keys — lengthened
    # and high-SFR against mid and moderate — so only availability can displace
    # it. That is the real shape of the bug: the paper-best option was winning.
    unlogged = _cand("Chin Up", "long_head", length="lengthened", sfr="high")
    real = _cand("Cable Curl", "long_head", length="mid", sfr="moderate")

    picks, _ = _select_grounded([unlogged, real], per_muscle=1)
    assert picks[0][0] == "Chin Up", "without availability data the paper option wins"

    picks, _ = _select_grounded(
        [unlogged, real], per_muscle=1, verified={"Chin Up": False, "Cable Curl": True}
    )
    assert picks[0][0] == "Cable Curl", "a verified option must take the head"


def test_a_head_with_no_verified_option_leads_tagged_as_trial() -> None:
    """Blanking the head would be worse than surfacing a trial: a dead pool is
    real information, and forearms/lower_back genuinely have nothing live.
    """
    a = _cand("Dead Curl A", "long_head")
    b = _cand("Dead Curl B", "long_head")
    picks, notes = _select_grounded(
        [a, b], per_muscle=1, verified={"Dead Curl A": False, "Dead Curl B": False}
    )
    assert len(picks) == 1
    assert notes[picks[0][0]].startswith("TRIAL")


def test_rotation_never_swaps_a_working_lift_for_an_unproven_one() -> None:
    """The swap path needs the same gate as the coverage pass, or the rotation
    trigger hands a productive lift's slot to something that may not exist.
    """
    incumbent = _cand("Cable Curl", "long_head")
    unproven = _cand("Nordic Curl", "long_head")
    proven = _cand("Preacher Curl", "long_head")

    picks, notes = _select_grounded(
        [incumbent, unproven, proven],
        per_muscle=1,
        tenure_weeks={"Cable Curl": 9},
        verified={"Cable Curl": True, "Nordic Curl": False, "Preacher Curl": True},
    )
    assert picks[0][0] == "Preacher Curl"
    assert "swapped in" in notes["Preacher Curl"]


# ── Cross-muscle awareness ───────────────────────────────────────────────────


def test_cross_muscle_payoff_breaks_ties_but_never_outranks_stimulus() -> None:
    """Selection is built per-muscle, so it could not see that a Chin Up buys
    biceps volume a Lat Pulldown does not — even though the ACCOUNTING layer has
    always known (indirect work is the majority of several muscles' volume:
    forearms 100%, mid_back 76%, traps 61%, triceps 57%).

    The payoff may only settle ties. A lift chosen for what it does to ANOTHER
    muscle, at the expense of the one being programmed, is a worse lift.
    """
    # Tied on region, length and SFR — the case where the payoff is free.
    plain = _cand("Plain Curl", "short_head")
    pays = _cand("Zz Compound Curl", "short_head")  # sorts last by name
    picks, _ = _select_grounded([plain, pays], per_muscle=1)
    assert picks[0][0] == "Plain Curl", "with no payoff signal the name tiebreak stands"

    picks, _ = _select_grounded(
        [plain, pays], per_muscle=1, secondary_deficit={"Zz Compound Curl": 6.0}
    )
    assert picks[0][0] == "Zz Compound Curl", "a tie is settled by what else the lift feeds"

    # NOT tied: the payoff lift is worse for THIS muscle (shortened vs lengthened).
    better = _cand("Plain Curl", "short_head", length="lengthened", sfr="high")
    worse = _cand("Zz Compound Curl", "short_head", length="shortened", sfr="low")
    picks, _ = _select_grounded(
        [better, worse], per_muscle=1, secondary_deficit={"Zz Compound Curl": 99.0}
    )
    assert picks[0][0] == "Plain Curl", (
        "cross-muscle payoff must never buy volume elsewhere by degrading the stimulus here"
    )


def test_a_muscle_short_on_direct_work_is_not_led_by_another_synergist() -> None:
    """Synergist credit is real volume but not a substitute for training the
    muscle. Measured over eight weeks, nine of seventeen muscles had a week where
    TOTAL credited volume cleared MEV while direct work alone did not — glutes
    three times, hamstrings and traps twice. Leading such a head with yet another
    compound is how that state perpetuates itself.
    """
    synergist = _cand("Barbell Row", "rhomboids", length="lengthened", sfr="high")
    direct = _cand("Zz Rear Delt Row", "rhomboids", length="mid", sfr="moderate")

    # Not flagged: the synergist wins on the quality keys, as it should.
    picks, _ = _select_grounded([synergist, direct], per_muscle=1)
    assert picks[0][0] == "Barbell Row"

    # Flagged: this muscle needs training, not more incidental credit.
    picks, _ = _select_grounded(
        [synergist, direct],
        per_muscle=1,
        is_direct={"Barbell Row": False, "Zz Rear Delt Row": True},
    )
    assert picks[0][0] == "Zz Rear Delt Row"


def test_direct_work_gate_does_not_empty_a_head_with_no_direct_option() -> None:
    """A head whose every option is a synergist still gets programmed — blanking
    it would read downstream as "nothing to train here", which is worse.
    """
    a = _cand("Row A", "rhomboids")
    b = _cand("Row B", "rhomboids")
    picks, _ = _select_grounded([a, b], per_muscle=1, is_direct={"Row A": False, "Row B": False})
    assert len(picks) == 1
