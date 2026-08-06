from __future__ import annotations

from datetime import date, timedelta

from shc.training.autoregulation import (
    EMPHASIS_MUSCLES,
    MusclePrescription,
    _confidence_add_factor,
    _decide,
    _protein_gate,
    _resolve_emphasis,
    _rpe_headroom,
    _session_split,
    deload_check,
    evidence_menu,
    load_emphasis,
    load_muscle_development,
    muscle_science_report,
    remaining_split,
    trainable_today,
    weekly_prescription,
)
from shc.training.mesocycle import _iso_week_start
from shc.training.volume import MuscleVolume

# Landmarks used across cases: chest 10/16/22, biceps 8/14/20, quads 8/14/20.


def _d(muscle, current, perf, soreness=0.0, cond=None, mev=10, mav=16, mrv=22, rpe_headroom=False):
    # These cases exercise the RP set-progression tree in isolation. The #1/#10
    # confidence/accuracy gate is a separate layer that shrinks adds toward zero
    # when there is no signal (confidence=0, scored_weeks=0 → factor 0.0); pass a
    # clearing confidence so the tree's add/cut/hold decision is what's asserted,
    # not the suppression layer (which has its own coverage below).
    #
    # Emphasis is now resolved by the CALLER (#3/#26 — dynamic, via
    # _resolve_emphasis) rather than inside _decide. With no physique signal the
    # caller's emphasis set is just the biceps/glutes prior, so mirror that here
    # to keep the emphasis cases (biceps/glutes) genuinely exercising the
    # emphasis branch instead of silently falling through to the default.
    return _decide(
        muscle,
        current,
        mev,
        mav,
        mrv,
        perf,
        soreness,
        cond,
        emphasis=muscle in EMPHASIS_MUSCLES,
        confidence=0.6,
        scored_weeks=4,
        rpe_headroom=rpe_headroom,
    )


def test_progressing_recovered_adds():
    rx = _d("chest", current=12, perf=5)
    assert rx.action == "add"
    assert rx.target_sets == 13  # +1, non-emphasis


def test_emphasis_muscle_adds_two():
    rx = _d("biceps", current=12, perf=5, mev=8, mav=14, mrv=20)
    assert rx.action == "add"
    assert rx.delta == 2  # emphasis ramps faster


def test_regressing_cuts():
    rx = _d("chest", current=18, perf=2)
    assert rx.action == "cut"
    assert rx.target_sets < 18


def test_under_recovered_backs_off():
    rx = _d("chest", current=16, perf=4, soreness=2.5)
    assert rx.action == "cut"


def test_at_mrv_holds():
    rx = _d("chest", current=22, perf=5)
    assert rx.action == "hold"
    assert rx.target_sets == 22


def test_stalled_without_headroom_still_ramps():
    """Baseline (unchanged behavior): a stalled muscle with no RPE-headroom
    signal ramps a set, exactly as before this remediation."""
    rx = _d("chest", current=12, perf=3, rpe_headroom=False)
    assert rx.action == "add"
    assert rx.delta == 1
    assert rx.rpe_headroom is False
    assert "raise load" not in rx.reason


def test_stalled_with_headroom_holds_sets_and_asks_for_load():
    """Stalled + sustained under-target RPE: the remedy is load, not volume —
    hold sets (no add) and say so, with the machine-readable flag set."""
    rx = _d("chest", current=12, perf=3, rpe_headroom=True)
    assert rx.action == "hold"
    assert rx.target_sets == 12
    assert rx.delta == 0
    assert rx.rpe_headroom is True
    assert "raise load" in rx.reason


def test_headroom_flag_does_not_affect_progressing_muscle():
    """Invariant 2 (a measurably progressing muscle is never frozen) must
    survive untouched — rpe_headroom only redirects the STALLED (perf==3)
    branch, not perf>=4."""
    rx = _d("chest", current=12, perf=5, rpe_headroom=True)
    assert rx.action == "add"
    assert rx.delta == 1
    assert rx.rpe_headroom is False


def test_headroom_flag_does_not_affect_regressing_muscle():
    rx = _d("chest", current=18, perf=2, rpe_headroom=True)
    assert rx.action == "cut"
    assert rx.rpe_headroom is False


# ── _rpe_headroom ─────────────────────────────────────────────────────────────


def _seed_adherence(conn, days_ago_to_diff: dict[int, tuple[float, float]]) -> None:
    """Insert plan_adherence rows: {days_ago: (avg_rpe_actual, avg_rpe_target)}."""
    today = date.today()
    for days_ago, (actual, target) in days_ago_to_diff.items():
        d = today - timedelta(days=days_ago)
        conn.execute(
            "INSERT INTO plan_adherence (date, plan_date, avg_rpe_actual, avg_rpe_target) "
            "VALUES (?, ?, ?, ?)",
            [d, d, actual, target],
        )


def test_rpe_headroom_true_when_sustained_under_target(conn) -> None:
    rows = {i: (6.0, 8.0) for i in range(1, 8)}  # -2.0 diff, 7 sessions
    _seed_adherence(conn, rows)
    assert _rpe_headroom(conn) is True


def test_rpe_headroom_false_when_on_target(conn) -> None:
    rows = {i: (7.5, 8.0) for i in range(1, 8)}  # -0.5 diff — below the 0.75 bar
    _seed_adherence(conn, rows)
    assert _rpe_headroom(conn) is False


def test_rpe_headroom_false_with_insufficient_sessions(conn) -> None:
    rows = {i: (6.0, 8.0) for i in range(1, 4)}  # only 3 sessions — needs >= 5
    _seed_adherence(conn, rows)
    assert _rpe_headroom(conn) is False


def test_rpe_headroom_false_when_over_rpe(conn) -> None:
    """Over-RPE (working harder than target, positive diff) is the OTHER
    direction that _rpe_drift_factor already handles — it must not also
    read as headroom."""
    rows = {i: (9.0, 7.0) for i in range(1, 8)}  # +2.0 diff, 7 sessions
    _seed_adherence(conn, rows)
    assert _rpe_headroom(conn) is False


def test_leg_interference_holds_volume():
    rx = _d("quads", current=12, perf=5, cond=1.6, mev=8, mav=14, mrv=20)
    assert rx.action == "hold"
    assert "ACWR" in rx.reason


def test_emphasis_below_floor_ramps_up():
    # Emphasis floor is the MEV-MAV midpoint (6+3=9), NOT MAV; ramp capped at
    # +2/week (MAX_WEEKLY_ADD), so 4 → 6 this week, not a jump to the floor.
    rx = _d("glutes", current=4, perf=None, mev=6, mav=12, mrv=16)
    assert rx.action == "add"
    assert rx.delta == 2


def test_emphasis_does_not_start_at_mav():
    # Regression guard for M3: an emphasis muscle sitting AT its midpoint floor
    # (8 + (14-8)//2 = 11) with no signal must HOLD — not chase MAV (14).
    rx = _d("biceps", current=11, perf=None, mev=8, mav=14, mrv=20)
    assert rx.action == "hold"
    assert rx.target_sets == 11


def test_below_mev_seeds_to_mev_in_one_step():
    # Block init / post-deload: a muscle well below MEV is re-seeded straight to
    # its minimum effective volume, not crawled +2/wk (which left a fresh athlete
    # with a 1-set-per-muscle session). The climb TO MEV is exempt from the step.
    rx = _d("chest", current=2, perf=None, mev=10, mav=16, mrv=22)
    assert rx.action == "add"
    assert rx.target_sets == 10  # 2 → MEV(10) in one step
    assert "initialize at minimum productive volume" in rx.reason
    assert "final weekly target: 2→10 sets (+8)" in rx.reason


def test_above_mev_ramp_still_capped_at_two():
    # Once AT/above MEV, the weekly add stays rate-limited to MAX_WEEKLY_ADD even
    # for an emphasis muscle — only the climb up to MEV is exempt.
    rx = _d("glutes", current=10, perf=5, mev=6, mav=14, mrv=20)
    assert rx.action == "add"
    assert rx.delta == 2  # emphasis ramp +2, not a jump to MAV


def test_action_never_contradicts_delta():
    # A held muscle must report delta 0 (the bug the endpoint surfaced).
    rx = _d("quads", current=0, perf=5, cond=1.9, mev=8, mav=14, mrv=20)
    assert rx.action == "hold"
    assert rx.delta == 0


# --- Emphasis persistence (DB lever) ------------------------------------------


def test_load_emphasis_reads_seeded_prior(conn):
    # Migration 0056 seeds the biceps/glutes/traps prior; load_emphasis surfaces it.
    em = load_emphasis(conn)
    assert {"biceps", "glutes", "traps"} <= set(em)


def test_resolve_emphasis_honors_db_over_prior(conn):
    # Persisting a new muscle (side_delts) must put it in the live emphasis set —
    # this is the path that lets what Rob sets actually reach the prescription,
    # instead of being a hardcoded frozenset he can't change.
    conn.execute("INSERT INTO muscle_emphasis (muscle) VALUES ('side_delts')")
    emphasis, _ = _resolve_emphasis(physique_bias=None, db_emphasis=load_emphasis(conn))
    assert "side_delts" in emphasis


def test_resolve_emphasis_falls_back_to_prior_when_empty():
    # No DB rows → fall back to the frozenset prior so the engine stays robust
    # whether or not the migration has run.
    emphasis, _ = _resolve_emphasis(physique_bias=None, db_emphasis={})
    assert emphasis == set(EMPHASIS_MUSCLES)


# --- Lagging-emphasis actuation (regression test for Rob's complaint) ---------


def test_lagging_emphasis_climbs_despite_low_confidence():
    # The core bug: a LAGGING priority muscle (no perf≥4 signal, thin direct
    # history → low confidence) sat at MEV and got locked there, because the
    # confidence throttle shrank its add to zero. Emphasis must still climb it
    # toward the productive floor. Without the fix this returned delta 0 (hold).
    rx = _decide(
        "biceps",
        current=8,
        mev=8,
        mav=14,
        mrv=20,
        perf=None,
        soreness=0.0,
        conditioning_acwr=None,
        emphasis=True,
        confidence=0.1,  # below _LARGE_ADD_CONFIDENCE_BAR
        scored_weeks=2,
    )
    assert rx.action == "add"
    assert rx.delta >= 2


def test_emphasis_outpaces_non_emphasis_when_both_lagging():
    # Same starting point and (low) confidence; only emphasis differs. The
    # emphasized muscle must advance; the non-emphasis one holds at MEV.
    common = dict(
        current=8,
        mev=8,
        mav=14,
        mrv=20,
        perf=None,
        soreness=0.0,
        conditioning_acwr=None,
        confidence=0.1,
        scored_weeks=2,
    )
    emph = _decide("biceps", emphasis=True, **common)
    plain = _decide("chest", emphasis=False, **common)
    assert emph.delta > plain.delta
    assert plain.delta == 0  # at MEV, no signal → hold


def test_emphasis_does_not_override_safety_cut():
    # Emphasis accelerates growth; it must NOT blunt a safety response. A
    # regressing emphasis muscle still cuts toward MEV.
    rx = _decide(
        "biceps",
        current=18,
        mev=8,
        mav=14,
        mrv=20,
        perf=2,  # regressing
        soreness=0.0,
        conditioning_acwr=None,
        emphasis=True,
        confidence=0.6,
        scored_weeks=4,
    )
    assert rx.action == "cut"
    assert rx.target_sets < 18


def test_emphasis_under_recovered_still_backs_off():
    # An acutely sore emphasis muscle backs off regardless of priority.
    rx = _decide(
        "glutes",
        current=12,
        mev=8,
        mav=14,
        mrv=20,
        perf=4,
        soreness=2.5,  # under-recovered
        conditioning_acwr=None,
        emphasis=True,
        confidence=0.6,
        scored_weeks=4,
    )
    assert rx.action == "cut"


# --- Confidence/accuracy ADD factor (previously untested) ---------------------


def test_confidence_factor_suppresses_with_no_signal():
    assert _confidence_add_factor(0.0, 0, None) == 0.0


def test_confidence_factor_scales_below_full():
    # Below _CONFIDENCE_FULL (0.30) the add is scaled by confidence/0.30.
    assert _confidence_add_factor(0.15, 4, None) == 0.5


def test_confidence_factor_full_at_and_above_ceiling():
    assert _confidence_add_factor(0.30, 8, None) == 1.0
    assert _confidence_add_factor(0.45, 8, None) == 1.0


def test_confidence_factor_accuracy_hedge():
    # Accuracy 0 halves the add; at the hedge threshold the hedge is a no-op.
    assert _confidence_add_factor(0.30, 8, 0.0) == 0.5
    assert _confidence_add_factor(0.30, 8, 0.55) == 1.0


# --- Sports-science exercise selection (the guiding light) --------------------


def test_biceps_menu_is_evidence_grounded(conn):
    # Selection must be driven by the science, not recency: lead with a
    # lengthened-position movement and cover every head across the picks.
    menu = evidence_menu(conn, ["biceps"])
    assert "biceps" in menu
    picks = menu["biceps"]
    assert picks[0]["length_bias"] == "lengthened"  # lengthened leads
    regions = {p["region"] for p in picks}
    assert {"long_head", "short_head", "brachialis"} <= regions  # all heads covered
    # Every pick is legible: it carries its plateau state + a one-line rank reason.
    for p in picks:
        assert p["trend"] in {
            "progressing",
            "stalled",
            "regressing",
            "young",
            "stale",
            "untrained",
        }
        assert p["status"]
        assert "weeks" in p and "last_done" in p


def test_biceps_picks_carry_citation_and_rep_target(conn):
    # Every prescribed movement must be defensible: a citation + a rep range.
    for p in evidence_menu(conn, ["biceps"])["biceps"]:
        assert p["citation"]
        assert p["citation_url"]
        assert 1 <= p["rep_low"] < p["rep_high"] <= 40


def test_uncurated_muscle_falls_back(conn):
    # A muscle with no exercise_science rows is omitted (caller uses recency menu).
    assert "totally_made_up_muscle" not in evidence_menu(conn, ["totally_made_up_muscle"])


def test_avoid_list_failure_logs_warning_not_silent(conn, caplog):
    # A failed exercise_preferences lookup must not silently resurface exercises
    # Rob marked 'no' — it should fail visibly (log a warning), not just degrade.
    conn.execute("DROP TABLE exercise_preferences")
    import logging

    with caplog.at_level(logging.WARNING):
        evidence_menu(conn, ["biceps"])
    assert any("exercise_preferences unavailable" in r.message for r in caplog.records)


def test_muscle_science_report_assembles_and_is_honest(conn):
    # The build-up surface: cited brief + grounded exercises + targets, plus an
    # HONEST data-coverage read (no logged history → population default, not faked
    # as personalized).
    rep = muscle_science_report(conn, "biceps")
    assert len(rep) == 1
    r = rep[0]
    assert r["grounded"] and r["brief"] and r["exercises"]
    assert r["targets"]["mev"] and r["targets"]["source"] == "population"
    assert r["data_coverage"]["personalized"] is False
    assert "population default" in r["data_coverage"]["note"]
    assert all(e["citation"] for e in r["exercises"])


def test_muscle_science_report_covers_all_muscles(conn):
    rep = muscle_science_report(conn)
    assert {r["muscle"] for r in rep} >= {
        "biceps",
        "glutes",
        "quads",
        "chest",
        "triceps",
        "forearms",
        "adductors",
    }


def test_all_targeted_muscles_are_grounded(conn):
    # Standing guard: every muscle the engine targets must be curated + cited,
    # every prescribed exercise must exist in the catalog, every row cited.
    targeted = [
        r[0]
        for r in conn.execute("SELECT DISTINCT muscle_group FROM muscle_volume_targets").fetchall()
    ]
    dev = load_muscle_development(conn)
    catalog = {
        r[0] for r in conn.execute("SELECT exercise_name FROM exercise_muscle_map").fetchall()
    }
    menu = evidence_menu(conn, targeted)
    for m in targeted:
        assert m in dev, f"{m} has no muscle_development brief"
        picks = menu.get(m, [])
        assert picks, f"{m} returns no grounded exercises"
        for p in picks:
            assert p["exercise"] in catalog, f"{m}: {p['exercise']} not in catalog"
            assert p["citation"] and p["citation_url"], f"{m}: {p['exercise']} uncited"
            assert 1 <= p["rep_low"] < p["rep_high"] <= 40


def test_muscle_development_brief_loaded(conn):
    dev = load_muscle_development(conn)
    assert "biceps" in dev
    assert dev["biceps"]["length_priority"] == "lengthened"
    assert set(dev["biceps"]["regions"]) == {"long_head", "short_head", "brachialis"}
    assert dev["biceps"]["freq_per_week"] == 2


def test_glutes_menu_is_evidence_grounded(conn):
    # Pass-2 muscle: lengthened lead, both regions covered, every pick cited.
    picks = evidence_menu(conn, ["glutes"])["glutes"]
    assert picks[0]["length_bias"] == "lengthened"
    assert {"gluteus_maximus", "gluteus_medius"} <= {p["region"] for p in picks}
    for p in picks:
        assert p["citation"] and p["citation_url"]


def test_glutes_selection_reaches_across_primary_mapping(conn):
    # The science layer must be able to prescribe squat/BSS/RDL for glutes even
    # though those are quad/hamstring-PRIMARY in exercise_muscle_map.
    names = {p["exercise"] for p in evidence_menu(conn, ["glutes"])["glutes"]}
    assert names & {
        "Bulgarian Split Squat (Dumbbell)",
        "Romanian Deadlift (Barbell)",
        "Squat (Barbell)",
    }


def test_stall_breaks_with_one_set():
    rx = _d("chest", current=14, perf=3)
    assert rx.action == "add"
    assert rx.delta == 1


def _mv(muscle, actual, mev=10, mav=16, mrv=22):
    return MuscleVolume(muscle, actual, mev, mav, mrv, "in range")


def test_deload_fires_on_broad_regression():
    perfs = {"chest": 2, "lats": 1, "quads": 2, "biceps": 4}
    report = [_mv(m, 12) for m in perfs]
    dl = deload_check(perfs, report)
    assert dl["recommended"] is True
    assert "regressing" in dl["reason"]


def test_deload_fires_when_many_at_mrv():
    perfs = {"chest": 4, "lats": 4, "quads": 4}
    report = [_mv("chest", 22), _mv("lats", 22), _mv("quads", 23)]
    dl = deload_check(perfs, report)
    assert dl["recommended"] is True
    assert "MRV" in dl["reason"]


def test_no_deload_without_systemic_signal():
    perfs = {"chest": 4, "lats": 2, "quads": 5}  # one regressing — below threshold
    report = [_mv(m, 12) for m in perfs]
    assert deload_check(perfs, report)["recommended"] is False


def test_regressing_below_mev_adds_not_cuts():
    # current=4 < MEV=10 while regressing (perf=2) → action must be add (toward MEV),
    # not cut (which would drive volume negative). Reason must not say "cut".
    rx = _d("traps", current=4, perf=2, mev=10, mav=16, mrv=22)
    assert rx.action == "add", f"expected add, got {rx.action}"
    assert rx.target_sets > 4, "target should be higher than current when below MEV"
    assert "cut" not in rx.reason.lower() or "build" in rx.reason.lower()


def test_regressing_above_mev_cuts():
    rx = _d("chest", current=18, perf=2)
    assert rx.action == "cut"
    assert rx.target_sets < 18


def test_decide_deload_halves_volume():
    rx = _d("chest", current=18, perf=5, mev=10, mav=16, mrv=22)
    assert rx.action == "add"  # sanity: normally it would grow
    dl = _decide("chest", 18, 10, 16, 22, perf=5, soreness=0.0, conditioning_acwr=None, deload=True)
    assert dl.action == "deload"
    # Bug 2 fix: floor is round(mev*0.4)=4, not mev=10.
    # round(18*0.5)=9, max(4, 9)=9 — real deload below MEV so fatigue clears.
    assert dl.target_sets == 9


def test_weekly_prescription_flags_missing_soreness_data(conn, seed) -> None:
    """No soreness check-in data at all this week means the under-recovery
    hold can't actuate for ANY muscle — visible enough to warrant a data_gaps
    note, unlike a single missing muscle key (soreness.get(muscle, 0.0))."""
    today = date.today()
    seed.workout(today, "Bicep Curl (Barbell)", [(20.0, 10)] * 4)
    rx = weekly_prescription(conn)
    assert any("soreness" in gap.lower() for gap in rx.data_gaps), rx.data_gaps


def test_weekly_prescription_smoke(conn, seed):
    """End-to-end: prescription emits per-muscle calls from logged volume."""
    today = date.today()
    for wk in range(3):
        seed.workout(
            date.fromordinal(today.toordinal() - wk * 7), "Bicep Curl (Barbell)", [(20.0, 10)] * 4
        )

    rx = weekly_prescription(conn)

    assert rx.week_start == _iso_week_start(today)
    biceps = next((m for m in rx.muscles if m.muscle == "biceps"), None)
    assert biceps is not None
    assert biceps.emphasis is True
    # New fields
    assert isinstance(rx.session_split, list)
    assert isinstance(rx.protein_gate, dict)
    assert "target" in rx.protein_gate


def test_weekly_prescription_reuses_passed_in_daily_state(conn, seed, monkeypatch) -> None:
    """Passing an already-computed `daily_state` must not trigger a second
    `compute_daily_state` call inside `_conditioning_pressure` — the redundant
    recompute the audit flagged (every caller that already has a state in scope
    was silently paying for it twice)."""
    import shc.metrics as metrics_mod

    calls = {"n": 0}
    real_compute = metrics_mod.compute_daily_state

    def _counting_compute(*args, **kwargs):
        calls["n"] += 1
        return real_compute(*args, **kwargs)

    monkeypatch.setattr(metrics_mod, "compute_daily_state", _counting_compute)

    today = date.today()
    seed.workout(today, "Squat (Barbell)", [(60.0, 8)] * 4)

    precomputed = metrics_mod.compute_daily_state(conn)
    assert calls["n"] == 1  # the precompute itself

    weekly_prescription(conn, daily_state=precomputed)
    assert calls["n"] == 1, "weekly_prescription recomputed daily_state despite receiving one"


def test_weekly_prescription_uses_personalized_leg_hold_loosening(conn, seed) -> None:
    """A well-sampled personal conditioning band that LOOSENS forbid must
    actually reach `_decide` via the derived hold — hold is floor-only
    against population (metrics.COND_ACWR_HOLD_LEGS = 1.5), so a fitted
    forbid of 2.0 derives hold 1.7. At cond 1.6 (below the personalized
    hold, above population) quads must NOT hold; at 1.75 (above the
    personalized hold) quads must hold. Only the personalized path explains
    the 1.6 case — population hold alone would have held it."""
    for name, value in (("rest", 1.96), ("low", 1.48), ("mod", 1.2)):
        conn.execute(
            "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks, fitted_at) "
            "VALUES ('resistance', ?, ?, 50, now())",
            [name, value],
        )
    conn.execute(
        "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks, fitted_at) "
        "VALUES ('conditioning', 'forbid_legs', 2.0, 30, now())"
    )
    today = date.today()
    seed.workout(today - timedelta(weeks=1), "Squat (Barbell)", [(60.0, 8)] * 4)

    def _quads_reason(cond_acwr: float) -> str:
        fake_state = {
            "freshness": {"whoop_stale": False},
            "training_load": {"conditioning_acwr": cond_acwr},
        }
        rx = weekly_prescription(conn, daily_state=fake_state)
        quads = next((m for m in rx.muscles if m.muscle == "quads"), None)
        assert quads is not None
        return quads.reason

    assert "court/cardio load high" not in _quads_reason(1.6), (
        "quads held at cond 1.6 under a loosened personal hold of 1.7 — the "
        "personalization did not reach _decide (population hold 1.5 would "
        "wrongly hold this too)"
    )
    assert "court/cardio load high" in _quads_reason(1.75)


def test_weekly_prescription_leg_hold_never_tighter_than_population(conn, seed) -> None:
    """Even a well-sampled fit that TIGHTENS forbid close to population must
    not drag the derived hold below metrics.COND_ACWR_HOLD_LEGS (1.5) — a
    live scenario: forbid fitted to 1.53 previously derived hold 1.23,
    freezing quads on ordinary conditioning loads. At cond 1.4 (below the
    floored hold) quads must NOT hold."""
    for name, value in (("rest", 1.96), ("low", 1.48), ("mod", 1.2)):
        conn.execute(
            "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks, fitted_at) "
            "VALUES ('resistance', ?, ?, 50, now())",
            [name, value],
        )
    conn.execute(
        "INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks, fitted_at) "
        "VALUES ('conditioning', 'forbid_legs', 1.53, 37, now())"
    )
    today = date.today()
    seed.workout(today - timedelta(weeks=1), "Squat (Barbell)", [(60.0, 8)] * 4)

    fake_state = {
        "freshness": {"whoop_stale": False},
        "training_load": {"conditioning_acwr": 1.4},
    }
    rx = weekly_prescription(conn, daily_state=fake_state)

    quads = next((m for m in rx.muscles if m.muscle == "quads"), None)
    assert quads is not None
    assert "court/cardio load high" not in quads.reason, (
        f"quads held at cond 1.4 under a tightened-forbid fit (1.53) — the "
        f"derived hold was not floored at population 1.5: {quads.reason}"
    )


def _make_rx(muscle: str, target: int, action: str = "add") -> MusclePrescription:
    return MusclePrescription(
        muscle=muscle,
        current_sets=float(target - 1),
        target_sets=target,
        delta=1,
        action=action,
        reason="test",
    )


# ── _session_split ────────────────────────────────────────────────────────────


def test_session_split_upper_muscles_on_upper_days() -> None:
    rx = [_make_rx("biceps", 12), _make_rx("chest", 10)]
    split = _session_split(rx)
    # #18 contract: label and weekday are SEPARATE keys (session="Upper-A",
    # weekday="Tue"), not a combined "Upper-A (Tue)" string.
    upper = [(s["session"], s["weekday"]) for s in split if s["region"] == "upper"]
    assert ("Upper-A", "Tue") in upper or ("Upper-B", "Thu") in upper
    # No biceps or chest on lower days
    for sess in split:
        if "Lower" in sess["session"]:
            assert all(e["muscle"] not in ("biceps", "chest") for e in sess["muscles"])


def test_session_split_lower_muscles_on_lower_days() -> None:
    rx = [_make_rx("quads", 10), _make_rx("hamstrings", 8)]
    split = _session_split(rx)
    for sess in split:
        if "Upper" in sess["session"]:
            assert all(e["muscle"] not in ("quads", "hamstrings") for e in sess["muscles"])


def test_session_split_respects_10_set_ceiling() -> None:
    # 17 biceps sets → should be split across 2 upper sessions, each ≤10.
    rx = [_make_rx("biceps", 17)]
    split = _session_split(rx)
    for sess in split:
        for entry in sess["muscles"]:
            assert entry["sets"] <= 10, f"{sess['session']} has {entry['sets']} biceps sets > 10"


def test_session_split_does_not_label_credited_volume_as_physical_sets() -> None:
    rx = [_make_rx("biceps", 12), _make_rx("chest", 10)]
    split = _session_split(rx)

    assert all("total_sets" not in session for session in split)
    assert all("credited_muscle_sets" in session for session in split)


def test_session_split_zero_target_excluded() -> None:
    rx = [_make_rx("abs", 0)]
    split = _session_split(rx)
    for sess in split:
        assert not any(e["muscle"] == "abs" for e in sess["muscles"])


# ── trainable_today (2026-07-23 remediation) ─────────────────────────────────
# The daily projection of the weekly split onto today's live gates — the fix
# for the "glutes-only" collapse where abs/lower_back/forearms had positive
# targets, were legally trainable, but sat on a session-split day-label that
# didn't surface them.


def test_trainable_today_abs_and_forearms_surface_under_push_pull_gate() -> None:
    """abs/lower_back/forearms are outside MUSCLE_TO_GROUP's push/pull/legs
    membership — a push+pull forbid must not touch them."""
    rx = [
        _make_rx("chest", 10),  # push
        _make_rx("lats", 10),  # pull
        _make_rx("abs", 6),
        _make_rx("forearms", 4),
    ]
    gates = {"forbid_muscle_groups": ["push", "pull"], "forbid_muscles": []}
    today = trainable_today(rx, gates)
    by_muscle = {t["muscle"]: t for t in today}
    assert by_muscle["chest"]["status"] == "group_gated"
    assert by_muscle["lats"]["status"] == "group_gated"
    assert by_muscle["abs"]["status"] == "available"
    assert by_muscle["forearms"]["status"] == "available"


def test_trainable_today_quads_group_gated_under_legs_forbid() -> None:
    rx = [_make_rx("quads", 8)]
    gates = {"forbid_muscle_groups": ["legs"], "forbid_muscles": []}
    today = trainable_today(rx, gates)
    assert today[0]["status"] == "group_gated"
    assert "legs" in today[0]["detail"]


def test_trainable_today_rest_gated_muscle_takes_priority_over_group() -> None:
    """A muscle individually rest-gated is rest_gated even if its group also
    happens to be forbidden — rest_gated is checked first (more specific)."""
    rx = [_make_rx("chest", 10)]
    gates = {"forbid_muscle_groups": ["push"], "forbid_muscles": ["chest"]}
    recovery = {"chest": {"days_since": 1, "last_rpe": 8.0, "last_dose_sets": 5}}
    today = trainable_today(rx, gates, recovery)
    assert today[0]["status"] == "rest_gated"
    assert "1d" in today[0]["detail"]


def test_trainable_today_held_is_not_available() -> None:
    """A HOLD action (e.g. the leg-interference hold, MRV ceiling, protein
    gate) is trainable at current volume but must not read as 'available' —
    the point is to distinguish 'don't add' from 'clear to add'."""
    rx = [_make_rx("quads", 6, action="hold")]
    gates = {"forbid_muscle_groups": [], "forbid_muscles": []}
    today = trainable_today(rx, gates)
    assert today[0]["status"] == "held"
    assert today[0]["status"] != "available"


def test_trainable_today_zero_target_never_surfaces() -> None:
    rx = [_make_rx("calves", 0)]
    gates = {"forbid_muscle_groups": [], "forbid_muscles": []}
    today = trainable_today(rx, gates)
    assert today == []


def test_trainable_today_clear_muscle_is_available() -> None:
    rx = [_make_rx("biceps", 12)]
    gates = {"forbid_muscle_groups": [], "forbid_muscles": []}
    today = trainable_today(rx, gates)
    assert today[0]["status"] == "available"
    assert today[0]["detail"] is None


# ── _protein_gate ─────────────────────────────────────────────────────────────


def test_protein_gate_no_data_returns_none_adequate(conn) -> None:
    result = _protein_gate(conn)
    assert result["adequate"] is None
    assert result["days_logged"] == 0
    assert "note" in result


def test_protein_gate_adequate_when_above_target(conn) -> None:
    from datetime import timedelta

    today = date.today()
    for i in range(5):
        conn.execute(
            "INSERT INTO daily_checkin (date, created_at, protein_grams) VALUES (?, now(), ?)",
            [(today - timedelta(days=i)).isoformat(), 250],
        )
    result = _protein_gate(conn)
    assert result["adequate"] is True
    assert result["avg_7d"] == 250


def test_protein_gate_inadequate_when_below_target(conn) -> None:
    from datetime import timedelta

    today = date.today()
    for i in range(6):
        conn.execute(
            "INSERT INTO daily_checkin (date, created_at, protein_grams) VALUES (?, now(), ?)",
            [(today - timedelta(days=i)).isoformat(), 150],  # 150g < 80% of 239 = 191g
        )
    result = _protein_gate(conn)
    assert result["adequate"] is False
    assert "note" in result and result["note"]


# ── Rotation: plateau is not the only trigger (2026-07-25) ───────────────────


# (exercise, muscle, region, length_bias, rep_low, rep_high, sfr_tier, ...)
def _cand(name, region, length="lengthened", sfr="high"):
    return (name, "side_delts", region, length, 10, 20, sfr, "", "", "")


def test_a_progressing_lead_still_rotates_after_the_tenure_window() -> None:
    """The regression this fixes: selection rotated ONLY on plateau, justified by
    citing Rauch as evidence that fixed selection beats variation. The vault
    records Rauch as the opposite result, and prescribes a 4-6 week rotation for
    trained lifters. A lift that is progressing but has led its head for 6+ weeks
    is now swap-eligible."""
    from shc.training.autoregulation import _select_grounded

    lead, alt = (
        _cand("Lateral Raise (Cable)", "lateral_deltoid"),
        _cand("Lateral Raise (Dumbbell)", "lateral_deltoid"),
    )
    ranks = {lead[0]: 0, alt[0]: 0}  # BOTH progressing — no plateau anywhere

    picks, _ = _select_grounded([lead, alt], 1, None, ranks, {lead[0]: 2})
    assert picks[0][0] == lead[0], "inside the window the productive lift is kept"

    picks, notes = _select_grounded([lead, alt], 1, None, ranks, {lead[0]: 6})
    assert picks[0][0] == alt[0], "past the window an in-band alternative takes over"
    assert "6wk" in notes[alt[0]]


def test_tenure_rotation_still_respects_the_science_bands() -> None:
    """Rotation may not buy variety by degrading the stimulus: a lengthened lead
    never rotates into a shortened option, however long its tenure."""
    from shc.training.autoregulation import _select_grounded

    lead = _cand("Lateral Raise (Cable)", "lateral_deltoid", length="lengthened")
    bad = _cand("Upright Row (Barbell)", "lateral_deltoid", length="shortened")
    picks, notes = _select_grounded([lead, bad], 1, None, {lead[0]: 0, bad[0]: 0}, {lead[0]: 99})
    assert picks[0][0] == lead[0]
    assert "no in-band alternative" in notes[lead[0]]


def test_a_lone_movement_is_held_not_dropped() -> None:
    """A head with no peer (the compound case) holds its lead rather than
    emptying the slot — this is what protects heavy compounds without a
    compound/isolation flag, which the schema does not carry."""
    from shc.training.autoregulation import _select_grounded

    lead = _cand("Overhead Press (Barbell)", "lateral_deltoid")
    picks, notes = _select_grounded([lead], 1, None, {lead[0]: 0}, {lead[0]: 52})
    assert [p[0] for p in picks] == [lead[0]]
    assert "no in-band alternative" in notes[lead[0]]


# ── Maintenance tier (migration 0078) ────────────────────────────────────────
# The engine implemented 3 of the framework's 4 volume landmarks. With MEV as
# the floor for all 17 muscles the weekly demand summed to ~1.5x what Rob can
# deliver, so every muscle read "below MEV", every muscle emitted ADD, and the
# planner had to triage silently. These lock the tier's contract.

_MAINT = {
    "mav": 16,
    "mrv": 22,
    "soreness": 0.0,
    "conditioning_acwr": None,
    "confidence": 0.6,
    "scored_weeks": 4,
}


def test_maintenance_tier_tops_up_only_to_mv_not_mev() -> None:
    # Below MV: the one add a maintenance muscle gets — to MV, never to MEV.
    rx = _decide("chest", current=0, mev=10, perf=None, tier="maintain", mv=2, **_MAINT)
    assert rx.target_sets == 2
    assert rx.tier == "maintain"


def test_maintenance_tier_holds_spillover_instead_of_cutting_to_mv() -> None:
    # Above MV from compound spillover: hold exactly there. Stripping productive
    # volume that costs no dedicated budget is the opposite of the point.
    rx = _decide("chest", current=6, mev=10, perf=None, tier="maintain", mv=2, **_MAINT)
    assert rx.target_sets == 6
    assert rx.action == "hold"


def test_maintenance_tier_never_adds_to_a_progressing_muscle() -> None:
    # perf>=4 would normally ramp. A maintenance muscle is not a growth target.
    rx = _decide("chest", current=6, mev=10, perf=5, tier="maintain", mv=2, **_MAINT)
    assert rx.delta == 0


def test_emphasis_muscle_can_never_be_demoted_to_maintenance() -> None:
    # Invariant 7 in tier form: demoting a lagging bring-up to MV is the same
    # silent under-train as freezing it below MEV, through a different door.
    rx = _decide(
        "biceps", current=0, mev=10, perf=None, emphasis=True, tier="maintain", mv=2, **_MAINT
    )
    assert rx.tier == "grow"
    assert rx.target_sets > 2


def test_deload_respects_maintenance_tier_floor() -> None:
    # Regression, 2026-08-02: the deload branch returns BEFORE the tier logic and
    # derived its floor from `round(mev * 0.4)`, ignoring tier/mv entirely. Real
    # case: lats (MEV 10, MV 2) sitting at 2.0 sets were handed a deload target
    # of 4, and triceps (MEV 12, MV 2) a target of 5 — a deload week RAISING the
    # muscles the athlete explicitly moved to maintenance. Rob caught it from his
    # own training, not from the data.
    lats = _decide(
        "lats", current=2.0, mev=10, perf=None, deload=True, tier="maintain", mv=2, **_MAINT
    )
    assert lats.target_sets == 2, "maintenance muscle must deload to MV, not 0.4*MEV"

    triceps = _decide(
        "triceps", current=1.2, mev=12, perf=None, deload=True, tier="maintain", mv=2, **_MAINT
    )
    assert triceps.target_sets == 2


def test_deload_still_uses_mev_floor_for_grow_tier() -> None:
    # The fix must not weaken a GROW muscle's deload: still ~40% of MEV.
    rx = _decide("chest", current=12, mev=10, perf=None, deload=True, tier="grow", mv=2, **_MAINT)
    assert rx.target_sets == 6  # max(round(10*0.4)=4, round(12*0.5)=6)


def test_deload_emphasis_muscle_never_drops_to_mv() -> None:
    # Invariant 7: an emphasis muscle can never maintain, so even tagged
    # 'maintain' it keeps the MEV-derived deload floor rather than MV.
    rx = _decide(
        "biceps",
        current=1.0,
        mev=12,
        perf=None,
        deload=True,
        emphasis=True,
        tier="maintain",
        mv=2,
        **_MAINT,
    )
    assert rx.target_sets == 5  # round(12*0.4), not MV 2


def test_maintenance_tier_still_backs_off_when_under_recovered() -> None:
    # Safety branches are evaluated BEFORE the tier: maintenance removes volume
    # DEMAND, never recovery protection.
    args = dict(_MAINT)
    args["soreness"] = 3.0
    rx = _decide("chest", current=6, mev=10, perf=None, tier="maintain", mv=2, **args)
    assert rx.delta <= 0


def test_absent_tier_defaults_to_grow_unchanged() -> None:
    # Backward compatibility: no tier argument must behave exactly as pre-0078,
    # i.e. climb to MEV. Under-training must never be reachable by absence.
    rx = _decide("chest", current=0, mev=10, perf=None, **_MAINT)
    assert rx.tier == "grow"
    assert rx.target_sets == 10


def test_unrecognised_tier_string_grows_rather_than_maintains() -> None:
    # A typo or a future tier value this build doesn't know must fail toward
    # MORE training, never less.
    rx = _decide("chest", current=0, mev=10, perf=None, tier="mainten", mv=2, **_MAINT)
    assert rx.tier == "grow"
    assert rx.target_sets == 10


def test_per_muscle_rpe_headroom_reads_a_falling_effort_trend() -> None:
    """A muscle whose load is getting easier is flagged individually.

    `_rpe_headroom` is one cross-muscle number off `plan_adherence` (one RPE
    pair per SESSION), so one coasting muscle could unlock the load-not-volume
    remedy for every muscle in the plan. With per-exercise weekly RPE
    materialised (0079) the signal resolves per muscle.
    """
    import duckdb

    from shc.training.autoregulation import _muscle_rpe_headroom

    c = duckdb.connect(":memory:")
    c.execute(
        "CREATE TABLE exercise_weekly_e1rm "
        "(exercise TEXT, week_start DATE, weekly_avg_rpe DOUBLE, rpe_set_count INTEGER)"
    )
    c.execute("CREATE TABLE exercise_muscle_map (exercise_name TEXT, primary_muscle TEXT)")
    c.execute("INSERT INTO exercise_muscle_map VALUES ('Curl', 'biceps'), ('Press', 'chest')")

    base = date.today() - timedelta(weeks=6)
    for i, (curl, press) in enumerate([(8.5, 7.0), (8.2, 7.1), (8.0, 7.0), (7.7, 7.2), (7.4, 7.1)]):
        wk = (base + timedelta(weeks=i)).isoformat()
        c.execute("INSERT INTO exercise_weekly_e1rm VALUES ('Curl', ?, ?, 3)", [wk, curl])
        c.execute("INSERT INTO exercise_weekly_e1rm VALUES ('Press', ?, ?, 3)", [wk, press])

    hr = _muscle_rpe_headroom(c)
    assert hr.get("biceps") is True  # steadily easier
    assert "chest" not in hr  # flat — no headroom claim


def test_per_muscle_rpe_headroom_is_empty_without_the_0079_columns() -> None:
    # Pre-0079 schema must fall back to the session signal, not crash and not
    # fabricate headroom.
    import duckdb

    from shc.training.autoregulation import _muscle_rpe_headroom

    c = duckdb.connect(":memory:")
    c.execute("CREATE TABLE exercise_weekly_e1rm (exercise TEXT, week_start DATE)")
    assert _muscle_rpe_headroom(c) == {}


# ── Effort as a deload input ─────────────────────────────────────────────────
# deload_check saw only OUTPUT signals (perf regression, at-MRV), which fire
# once damage is done. Effort is the input side and moves first.

_REPORT: list[MuscleVolume] = []


def test_effort_overreach_alone_does_not_trigger_a_deload() -> None:
    """Grinding with output still rising is productive overreaching.

    A deload here would interrupt a working block for no reason, so effort is
    corroborating evidence, never a standalone trigger.
    """
    out = deload_check(
        {"chest": 4, "lats": 5},  # nothing regressing
        _REPORT,
        effort={"overreaching": True, "recent_rpe": 8.6, "baseline_rpe": 7.2},
    )
    assert out["recommended"] is False


def test_effort_overreach_with_regression_triggers_a_deload() -> None:
    """ "Working harder AND getting less" — the overreaching signature.

    One regressing muscle is below the 3-muscle threshold and would not trigger
    on its own; paired with elevated effort it does.
    """
    out = deload_check(
        {"chest": 2, "lats": 4},
        _REPORT,
        effort={"overreaching": True, "recent_rpe": 8.6, "baseline_rpe": 7.2},
    )
    assert out["recommended"] is True
    assert any("effort overreach" in t for t in out["triggers"])


def test_absent_effort_signal_leaves_deload_behaviour_unchanged() -> None:
    out = deload_check({"chest": 2}, _REPORT, effort=None)
    assert out["recommended"] is False
    assert out == deload_check({"chest": 2}, _REPORT)


def test_effort_overreach_needs_both_a_rise_and_an_absolute_level() -> None:
    """Either bound alone misreads the athlete.

    A climb from 6.0 to 6.6 is a return to normal training, not grinding; a flat
    8.5 with no rise is simply how someone trains.
    """
    import duckdb

    from shc.training.autoregulation import _effort_overreach

    def _conn(weekly: list[float]):
        c = duckdb.connect(":memory:")
        c.execute(
            "CREATE TABLE exercise_weekly_e1rm "
            "(week_start DATE, weekly_avg_rpe DOUBLE, rpe_set_count INTEGER)"
        )
        for i, rpe in enumerate(weekly):  # index 0 = most recent
            wk = date.today() - timedelta(weeks=i)
            c.execute("INSERT INTO exercise_weekly_e1rm VALUES (?, ?, 10)", [wk, rpe])
        return c

    # Big rise, but the absolute level is still easy training.
    assert _effort_overreach(_conn([6.6, 6.0, 6.0, 6.0]))["overreaching"] is False
    # High absolute level, but it is simply his norm — no rise.
    assert _effort_overreach(_conn([8.5, 8.5, 8.5, 8.5]))["overreaching"] is False
    # Both: a real climb into hard territory.
    assert _effort_overreach(_conn([8.6, 7.2, 7.1, 7.2]))["overreaching"] is True
    # Not enough history to claim anything.
    assert _effort_overreach(_conn([9.9, 6.0]))["overreaching"] is False


def test_effort_rpe_band_never_asks_for_more_than_the_day_allows() -> None:
    """The prompt must not request effort the validator rejects.

    `EFFORT_RPE_BAND` tells the planner what RPE to target; `RPE_CAP_BY_INTENSITY`
    is the hard ceiling. `rest` was (6, 7) against a cap of 6 — the prompt asked
    for an RPE the same session's validator would refuse.
    """
    from shc.ai.workout_planner import EFFORT_RPE_BAND, RPE_CAP_BY_INTENSITY

    for intensity, (lo, hi) in EFFORT_RPE_BAND.items():
        cap = RPE_CAP_BY_INTENSITY[intensity]
        assert lo <= hi, f"{intensity} band is inverted"
        assert hi <= cap, f"{intensity} band targets RPE {hi} but the day caps at {cap}"


def _meso_state(week_number: int, planned_weeks: int = 7, deload: bool = False):
    from shc.training.mesocycle import MesocycleState

    return MesocycleState(
        id="test",
        started_on=date.today() - timedelta(weeks=week_number - 1),
        planned_weeks=planned_weeks,
        status="active",
        week_number=week_number,
        weeks_remaining=max(0, planned_weeks - week_number + 1),
        is_deload_week=deload,
        deload_trigger=None,
        notes=None,
    )


def test_meso_rpe_band_ramps_across_the_block() -> None:
    """Week 1 and the final accumulation week must not prescribe identical effort.

    The RIR periodization axis: sets already ramp across the block; effort now
    does too — ~RPE 7-8 in week 1 climbing to ~8.5-9.5 in the final week, in
    half-point steps, monotonically.
    """
    from shc.training.mesocycle import meso_rpe_band

    assert meso_rpe_band(1, 7) == (7.0, 8.0)
    assert meso_rpe_band(7, 7) == (8.5, 9.5)
    # Past the accumulation weeks = the shed week — flat deload band.
    assert meso_rpe_band(8, 7) == (6.0, 6.0)
    # A one-week block has no ramp to run.
    assert meso_rpe_band(1, 1) == (7.0, 8.0)
    prev = (0.0, 0.0)
    for wk in range(1, 8):
        lo, hi = meso_rpe_band(wk, 7)
        assert lo <= hi
        assert (lo, hi) >= prev, "band must never step DOWN mid-accumulation"
        assert lo * 2 == int(lo * 2) and hi * 2 == int(hi * 2), "RPE resolves in halves"
        prev = (lo, hi)


def test_effort_band_is_clamped_by_the_day_cap_and_never_exceeds_it() -> None:
    """The ramp asks; the day's gates answer. The gate cap always wins when lower.

    A late-block 8.5-9.5 target on a MODERATE day must collapse to the day's cap
    (8), and on any intensity the band top must stay at or under
    RPE_CAP_BY_INTENSITY — the same invariant the static band test enforces.
    """
    from shc.ai.workout_planner import RPE_CAP_BY_INTENSITY, effort_band_for

    late = _meso_state(7)
    assert effort_band_for({"max_intensity": "high"}, late) == (8.5, 9.5)
    assert effort_band_for({"max_intensity": "moderate"}, late) == (8.0, 8.0)
    assert effort_band_for({"max_intensity": "low"}, late) == (7.0, 7.0)
    assert effort_band_for({"max_intensity": "rest"}, late) == (6.0, 6.0)
    # No meso state (or a deload week) → the static per-intensity band, unchanged.
    assert effort_band_for({"max_intensity": "high"}, None) == (8.0, 9.0)
    assert effort_band_for({"max_intensity": "high"}, _meso_state(8, deload=True)) == (8.0, 9.0)
    for wk in range(1, 8):
        for intensity, cap in RPE_CAP_BY_INTENSITY.items():
            lo, hi = effort_band_for({"max_intensity": intensity}, _meso_state(wk))
            assert lo <= hi <= cap, f"wk{wk} {intensity}: band ({lo},{hi}) breaches cap {cap}"


def test_late_block_planned_effort_rise_is_not_read_as_overreach() -> None:
    """Following the ramp must not trip the grind detector.

    The overreach check compares recent weekly RPE to the trailing baseline; a
    late-accumulation week is SUPPOSED to sit above it by the planned ramp
    delta. The same +1.4 rise that reads as grinding in week 1 (planned rise 0)
    is inside the plan's own ask in the final week (planned rise 1.5) — while a
    rise that blows through plan + threshold still fires.
    """
    import duckdb

    from shc.training.autoregulation import _effort_overreach

    def _conn(weekly: list[float]):
        c = duckdb.connect(":memory:")
        c.execute(
            "CREATE TABLE exercise_weekly_e1rm "
            "(week_start DATE, weekly_avg_rpe DOUBLE, rpe_set_count INTEGER)"
        )
        for i, rpe in enumerate(weekly):  # index 0 = most recent
            wk = date.today() - timedelta(weeks=i)
            c.execute("INSERT INTO exercise_weekly_e1rm VALUES (?, ?, 10)", [wk, rpe])
        return c

    grind = [8.6, 7.2, 7.1, 7.2]  # +1.4 over baseline, above the 8.0 floor
    assert _effort_overreach(_conn(grind), meso_state=_meso_state(1))["overreaching"] is True
    out = _effort_overreach(_conn(grind), meso_state=_meso_state(7))
    assert out["overreaching"] is False
    assert out["planned_rise"] == 1.5
    # Effort beyond even the plan's final-week ask is still grinding.
    beyond = [9.5, 7.2, 7.1, 7.2]
    assert _effort_overreach(_conn(beyond), meso_state=_meso_state(7))["overreaching"] is True
    # A deload/shed week has no planned rise — the detector reverts to baseline.
    assert (
        _effort_overreach(_conn(grind), meso_state=_meso_state(8, deload=True))["overreaching"]
        is True
    )


def _rx(muscle: str, target: int, current: float, emphasis: bool = False) -> MusclePrescription:
    delta = target - round(current)
    return MusclePrescription(
        muscle=muscle,
        current_sets=current,
        target_sets=target,
        delta=delta,
        action="add" if delta > 0 else ("cut" if delta < 0 else "hold"),
        reason="test",
        emphasis=emphasis,
    )


def test_remaining_split_reflows_what_the_week_still_owes() -> None:
    """A missed day's sets land on the remaining sessions, not the floor.

    Thursday, chest owes 3 more sets: the only upper session left is Upper-B
    (Thu), so all 3 land there — the Tuesday allocation is not silently lost.
    Quads owe 4 with only Lower-B (Fri) left. A muscle already at target has
    nothing to place.
    """
    thursday = date(2026, 8, 6)
    assert thursday.weekday() == 3
    out = remaining_split(
        [_rx("chest", 8, 5.0), _rx("quads", 10, 6.0), _rx("biceps", 6, 6.0)],
        thursday,
    )
    assert out["days_left"] == 2
    by_label = {s["session"]: s for s in out["sessions"]}
    assert set(by_label) == {"Upper-B", "Lower-B"}
    assert by_label["Upper-B"]["muscles"] == [{"muscle": "chest", "sets": 3, "over_cap": False}]
    assert by_label["Lower-B"]["muscles"] == [{"muscle": "quads", "sets": 4, "over_cap": False}]
    assert out["unplaceable"] == []


def test_remaining_split_on_monday_matches_the_full_week() -> None:
    """With nothing trained yet and every session ahead, reflow IS the skeleton."""
    monday = date(2026, 8, 3)
    assert monday.weekday() == 0
    out = remaining_split([_rx("chest", 8, 0.0)], monday)
    assert out["days_left"] == 4
    allocs = {s["session"]: s["muscles"][0]["sets"] for s in out["sessions"]}
    assert allocs == {"Upper-A": 4, "Upper-B": 4}


def test_remaining_split_surfaces_an_unreachable_target_instead_of_dropping_it() -> None:
    """After Friday a leg target has no session left — it must be SAID, not lost.

    And a single-session pile-up past the per-session cap is flagged over_cap,
    mirroring _session_split's never-silently-truncate rule.
    """
    saturday = date(2026, 8, 8)
    assert saturday.weekday() == 5
    out = remaining_split([_rx("glutes", 8, 2.0, emphasis=True)], saturday)
    assert out["sessions"] == []
    assert out["unplaceable"] == [{"muscle": "glutes", "remaining": 6, "emphasis": True}]

    friday = date(2026, 8, 7)
    crammed = remaining_split([_rx("quads", 14, 2.0)], friday)
    (lower,) = crammed["sessions"]
    assert lower["muscles"] == [{"muscle": "quads", "sets": 12, "over_cap": True}]


def test_remaining_split_places_nothing_for_cut_or_satisfied_muscles() -> None:
    """A cut/deload target below current volume owes nothing forward."""
    tuesday = date(2026, 8, 4)
    out = remaining_split([_rx("lats", 4, 9.0), _rx("chest", 6, 6.0)], tuesday)
    assert out["sessions"] == []
    assert out["unplaceable"] == []


def test_progressibility_flags_a_coarse_pitch_and_stays_silent_on_thin_evidence() -> None:
    """A 40 lb pitch on a 270 lb stack is a rep-progression lift; 3 logged
    notches may not claim a pitch at all (the snapper's own evidence bar)."""
    from shc.training.autoregulation import _progressibility
    from shc.training.loadable import LoadableGrids

    def _g(notches, sets=20):
        return LoadableGrids(
            by_exercise={"hip thrust (machine)": notches},
            set_counts={"hip thrust (machine)": sets},
            dumbbell_rack=[],
            rack_sets=0,
            _canon={"hip thrust": "hip thrust (machine)"},
            overrides={},
        )

    coarse = _progressibility(_g([190.0, 230.0, 270.0]), "Hip Thrust (Machine)")
    assert coarse == {"increment_lb": 40.0, "pct_of_top": 14.8, "coarse": True}
    fine = _progressibility(_g([180.0, 185.0, 190.0, 195.0, 200.0]), "Hip Thrust (Machine)")
    assert fine is not None and fine["coarse"] is False
    # Thin evidence (under the prove-a-gap set floor) → no claim, not a guess.
    assert _progressibility(_g([190.0, 230.0, 270.0], sets=5), "Hip Thrust (Machine)") is None
