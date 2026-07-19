"""Engine soundness invariants — the athlete-protection contract, executable.

These are NOT unit tests of one function; they encode the cross-cutting
properties the whole engine must preserve so the class of silent bug that
"trains Rob according to a bug, not the science" cannot come back. Each test
maps to a real defect found in the 2026-07-03 audit. If one of these fails, a
change has re-opened a hole that once held the athlete back — read the docstring
before "fixing the test".

See ENGINE_INVARIANTS.md for the prose contract.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest

from shc.ai.workout_planner import load_cap_pct
from shc.metrics import (
    _ACWR_MIN_CHRONIC_DAYS,
    CheckinMetrics,
    ReadinessSnapshot,
    RecoveryMetrics,
    SleepMetrics,
    TrainingLoadMetrics,
    _apply_band,
    _gates,
    muscle_group,
)
from shc.training.autoregulation import _CONFIDENCE_FULL, _decide, weekly_prescription
from shc.training.self_learning import (
    _historical_weekly_acwr,
    _signal_size_factor,
    compute_muscle_signal_quality,
)

# ── INVARIANT 1: the ACWR band-fitter measures on the SAME window the live gate
# scores against, over the SAME admissible sample. A drift here silently biases
# every personalized ACWR band (the 2026-07-03 audit found the fitter on a
# 28-day chronic window while the live gate used 21-day; the 2026-07
# remediation found the live gate treats a week whose chronic window has fewer
# than metrics._ACWR_MIN_CHRONIC_DAYS nonzero-load days as unscoreable — a
# thin-history week — but the fitter had no such floor, so it could fit a
# percentile band partly on ratios the gate itself would never produce). The
# fitter is tested against an INDEPENDENT re-implementation of the live
# uncoupled 7:21 formula (metrics.py `_arm_acwr`).


def _ref_live_uncoupled_acwr(load_by_date: dict[date, float], ws: date) -> float | None:
    """Reference impl of metrics.py `_arm_acwr` — acute [ws, ws+7)/7 over the
    contiguous 21-day chronic [ws-21, ws)/21, admissible only when the chronic
    window has >= _ACWR_MIN_CHRONIC_DAYS nonzero-load days. This is the source
    of truth the fitter must mirror; if metrics.py's live window or admissibility
    rule changes, change it HERE too and both this test and the fitter must be
    reconciled."""
    chronic_vals = [load_by_date.get(ws - timedelta(days=d), 0.0) for d in range(1, 22)]
    acute = sum(load_by_date.get(ws + timedelta(days=d), 0.0) for d in range(0, 7)) / 7.0
    chronic = sum(chronic_vals) / 21.0
    chronic_days = sum(1 for v in chronic_vals if v > 0)
    if chronic <= 0 or chronic_days < _ACWR_MIN_CHRONIC_DAYS:
        return None
    return round(acute / chronic, 4)


def test_acwr_fit_window_mirrors_live_gate(conn, seed) -> None:
    """Fitter ratios must equal the live 7:21 uncoupled formula on the same data."""
    # A non-trivial ramp so a wrong window produces a DIFFERENT ratio (a constant
    # load gives 1.0 under any window and would hide the bug).
    start = date.today() - timedelta(days=120)
    load_by_date: dict[date, float] = {}
    for i in range(110):
        d = start + timedelta(days=i)
        tonnage = 1000.0 + 40.0 * i  # linear ramp
        # one strength set whose weight*reps ≈ desired daily tonnage
        seed.workout(d, "Barbell Bench Press", [(tonnage / 5.0, 5)], rpe=8.0)
        load_by_date[d] = tonnage

    fitted = sorted(r for r in _historical_weekly_acwr(conn, "hevy_tonnes"))

    # Independent reference over every ISO-week-start present in the data.
    week_starts = {d - timedelta(days=d.weekday()) for d in load_by_date}
    ref = sorted(
        r for ws in week_starts if (r := _ref_live_uncoupled_acwr(load_by_date, ws)) is not None
    )

    # Same number of scoreable weeks, and each ratio matches within rounding.
    assert len(fitted) == len(ref), f"fitter produced {len(fitted)} weeks, live-ref {len(ref)}"
    for f, r in zip(fitted, ref, strict=False):
        assert abs(f - r) < 0.02, f"fitter ACWR {f} != live-window ref {r} — window drift"


# ── INVARIANT 2: a MEASURABLY progressing muscle is NEVER frozen by the
# confidence shrink. The audit found glutes (emphasis, PR for 8 weeks) pinned at
# the grow-floor because confidence (caps ~0.34 by design) rounded every add to
# zero. Progress is an OUTCOME signal; the shrink only governs SPECULATIVE adds.


@pytest.mark.parametrize("confidence", [0.0, 0.03, 0.08, 0.15, 0.22, 0.34])
@pytest.mark.parametrize("cur", [7, 9, 12, 15])
@pytest.mark.parametrize("emphasis", [True, False])
def test_progressing_muscle_never_frozen(confidence, cur, emphasis) -> None:
    """perf>=4, recovered, below MRV → delta>=1 at ANY confidence."""
    p = _decide(
        "glutes",
        current=cur,
        mev=4,
        mav=10,
        mrv=16,
        perf=5,  # max PR
        soreness=0.0,
        conditioning_acwr=None,
        emphasis=emphasis,
        emphasis_factor=1.0,
        confidence=confidence,
        scored_weeks=74,
        accuracy=None,
    )
    assert p.target_sets > cur, (
        f"progressing muscle FROZEN at {cur} (conf {confidence}, emphasis {emphasis}) "
        f"— target {p.target_sets}: {p.reason}"
    )
    assert p.target_sets <= 16, "must never exceed MRV"


def test_progressing_muscle_at_mrv_holds() -> None:
    """The +1 floor must not push a muscle past MRV."""
    p = _decide(
        "glutes",
        current=16,
        mev=4,
        mav=10,
        mrv=16,
        perf=5,
        soreness=0.0,
        conditioning_acwr=None,
        emphasis=True,
        emphasis_factor=1.0,
        confidence=0.08,
        scored_weeks=74,
        accuracy=None,
    )
    assert p.target_sets == 16, "at MRV a progressing muscle holds, never exceeds the ceiling"


# ── INVARIANT 3b: conditioning interference never freezes an EMPHASIS lower-body
# muscle below MEV. The leg-interference hold (cond. ACWR > 1.5) exists because
# court/cardio load debits leg RECOVERY — correct for quads/hams/adductors, the
# tissues that absorb the real eccentric court pounding. But it was checked
# before the MEV-floor branch, so glutes (emphasis, perf=None, thin data, cur=0)
# got frozen at 0 for every high-pickleball week instead of climbing to MEV —
# the silent under-train invariant 3 forbids, on the exact lagging priority
# muscle Rob wants brought up. Teeth: delete the emphasis-interference branch in
# `_decide` and the glutes assertion drops to 0.
def test_conditioning_interference_never_freezes_emphasis_below_mev() -> None:
    common = dict(
        current=0.0,
        mev=6,
        mav=11,
        mrv=16,
        perf=None,  # no outcome signal — the exact case that fell to the hold
        soreness=0.0,
        conditioning_acwr=1.65,  # > 1.5 → leg_interference active
        emphasis_factor=1.0,
        confidence=0.09,  # glutes' real thin-data confidence
        scored_weeks=8,
        accuracy=None,
    )
    glutes = _decide("glutes", emphasis=True, **common)
    assert glutes.target_sets > 0, (
        f"emphasis glutes FROZEN at 0 under conditioning interference — {glutes.reason}"
    )
    assert glutes.target_sets <= common["mev"], (
        "climb toward MEV is conservative under interference — never overshoots MEV in one step "
        f"(got {glutes.target_sets})"
    )

    # Non-emphasis legs (quads/hams) STILL hold in place — they take the court
    # load, so the interference hold is correct for them. This is the guardrail
    # that keeps the fix targeted, not a blanket removal of the hold.
    quads = _decide("quads", emphasis=False, **common)
    assert quads.target_sets == 0, (
        f"non-emphasis legs must still hold under interference (got {quads.target_sets}: {quads.reason})"
    )


# ── INVARIANT 2b: confidence reads steady PROGRESS as a clean signal, not noise.
# The old raw-CV stability penalized a climbing perf series (3→4→5) for its
# dispersion — the muscles that were working scored as the least trustworthy.
# Stability is now measured around the OLS trend, so a steady climb beats a
# same-mean series that bounces around. Deload weeks are excluded entirely.


def test_progress_reads_as_signal_not_noise(conn) -> None:
    from datetime import date as _date

    from shc.training.self_learning import compute_muscle_signal_quality

    conn.execute(
        "INSERT INTO exercise_muscle (exercise_name, muscle, role, credit) "
        "VALUES ('ClimbLift', 'glutes', 'primary', 1.0), ('NoisyLift', 'quads', 'primary', 1.0)"
    )
    base = _date(2026, 1, 5)  # a Monday
    climbing = [3, 3, 4, 4, 5, 5, 5]
    noisy = [5, 1, 5, 1, 4, 2, 5]  # same rough mean, no trend
    for i, (pc, pn) in enumerate(zip(climbing, noisy, strict=True)):
        ws = base + timedelta(weeks=i)
        conn.execute(
            "INSERT INTO exercise_weekly_e1rm (exercise, week_start, e1rm_kg, work_sets, "
            "perf_score) VALUES (?, ?, 100.0, 3, ?)",
            ["ClimbLift", ws, pc],
        )
        conn.execute(
            "INSERT INTO exercise_weekly_e1rm (exercise, week_start, e1rm_kg, work_sets, "
            "perf_score) VALUES (?, ?, 100.0, 3, ?)",
            ["NoisyLift", ws, pn],
        )
    climb = compute_muscle_signal_quality(conn, "glutes")
    noise = compute_muscle_signal_quality(conn, "quads")
    assert climb["signal_stability"] > noise["signal_stability"], (
        f"steady progress ({climb['signal_stability']}) scored no better than noise "
        f"({noise['signal_stability']}) — detrend regressed"
    )


# ── INVARIANT 3: the +1 progression floor did NOT defeat the confidence shrink
# for SPECULATIVE adds. A muscle with no outcome signal (perf None) on thin,
# low-confidence data must not get a speculative ramp above its MEV floor.


def test_speculative_add_still_shrunk() -> None:
    """No perf signal + low confidence → climbs to MEV floor only, no ramp above."""
    p = _decide(
        "lats",
        current=4,
        mev=8,
        mav=12,
        mrv=20,
        perf=None,
        soreness=0.0,
        conditioning_acwr=None,
        emphasis=False,
        emphasis_factor=1.0,
        confidence=0.05,
        scored_weeks=3,
        accuracy=None,
    )
    # It may climb toward the non-speculative MEV floor (8), but must not ramp above it.
    assert p.target_sets <= 8, f"speculative add ramped above MEV floor to {p.target_sets}"


# ── INVARIANT 4: exercise classification never lets a movement slip past its
# recovery gate. A pull/hinge pattern must never classify as push (it would pass
# a pull-rested day), and posterior-chain hinges must not fall through to "other".


@pytest.mark.parametrize(
    "exercise,expected",
    [
        ("Chest Supported Row", "pull"),
        ("Incline Chest Supported Row", "pull"),
        ("Seal Row", "pull"),
        ("T-Bar Row", "pull"),
        ("Rack Pull", "pull"),
        ("Cable Pull Through", "pull"),
        ("Reverse Hyper", "pull"),
        ("Back Extension", "pull"),
        ("45 Degree Hyperextension", "pull"),
        ("Kettlebell Swing", "pull"),
        ("Romanian Deadlift", "pull"),
        ("Barbell Bench Press", "push"),
        ("Upright Row", "push"),  # the lone row that is a delt/push movement
        ("Barbell Back Squat", "legs"),
        ("Leg Curl", "legs"),
    ],
)
def test_exercise_never_bypasses_its_gate(exercise, expected) -> None:
    assert muscle_group(exercise) == expected, (
        f"{exercise!r} classified {muscle_group(exercise)!r}, expected {expected!r} "
        "— could slip past its recovery gate"
    )


def test_no_pull_movement_classifies_as_push() -> None:
    """Blanket guard: nothing containing a row/hinge cue may be 'push' (except
    the explicit upright-row delt movement)."""
    pull_cues = ["chest supported row", "pendlay row", "meadows row", "rack pull", "pull through"]
    for name in pull_cues:
        assert muscle_group(name) != "push", f"{name!r} leaked into push gate"


# ── INVARIANT 5: the load-cap ladder is monotonic and a green ("high") day
# actually permits true top-set work (>=100% e1RM). A silent cap below e1RM on a
# green day is the "treated like a fragile 40yo" failure in load form.


def test_load_cap_monotonic_and_high_allows_top_sets() -> None:
    caps = {t: load_cap_pct({"max_intensity": t}) for t in ("rest", "low", "moderate", "high")}
    assert caps["rest"] < caps["low"] < caps["moderate"] < caps["high"], caps
    assert caps["high"] >= 100, f"high day caps below e1RM ({caps['high']}%) — no true top sets"
    # An unset/unknown intensity must not silently fall through to a hard cap.
    assert load_cap_pct({}) >= 100


# ── INVARIANT 6: a personal band that CAPS progression may only loosen the
# population default, never tighten below it. This is the anti-progression-trap
# guard: Rob's thin, noise-dominated history must never make a growth gate
# stricter than the population floor.


@pytest.mark.parametrize("personal", [0.5, 1.0, 1.5, 1.8, 2.0, 2.5])
def test_floor_only_band_never_tightens_below_population(personal) -> None:
    population = 2.0
    assert _apply_band(personal, population, floor_only=True) >= population


# ── INVARIANT 7 (BEHAVIORAL / END-TO-END): full mesocycle simulations. Where the
# invariants above test single functions, these drive the WHOLE volume loop — the
# real confidence computation feeding the real controller, week after week — the
# way the bug actually manifested. Both are teeth-checked: revert the fix and they
# fail (see the commit that added them). A behavioral fixture that passes on the
# broken engine is worthless, which is exactly the trap a naive "climbs to MRV on
# clean data" version fell into (clean data → high confidence → the shrink never
# bites → the freeze fix is never exercised).


# A realistically NOISY long history — the only thing that produces the LOW
# confidence (~0.0–0.15) under which the muscle actually froze. A clean history
# gives high confidence and would not test the fix at all.
_NOISY_PERF_HISTORY = [1, 4, 2, 5, 1, 3, 2, 4] * 4  # 32 weeks, high variance


def test_low_confidence_athlete_still_climbs_to_mrv(conn) -> None:
    """The freeze bug, reproduced end-to-end: a muscle whose long noisy history
    yields LOW confidence must still climb to MRV while progressing — the +1
    progression floor carries it where the confidence shrink would zero the add.
    Teeth: disable the floor in _decide and this fails (muscle strands ~7)."""
    from datetime import date as _date

    from shc.training.self_learning import compute_muscle_signal_quality

    conn.execute(
        "INSERT INTO exercise_muscle (exercise_name, muscle, role, credit) "
        "VALUES ('Hip Thrust', 'glutes', 'primary', 1.0)"
    )
    base = _date(2024, 1, 1)
    e1rm = 100.0
    # Phase A: seed the noisy prehistory (no controller — just build the low-conf baseline).
    for i, perf in enumerate(_NOISY_PERF_HISTORY):
        e1rm *= 0.98 if perf <= 2 else 1.005
        conn.execute(
            "INSERT INTO exercise_weekly_e1rm (exercise, week_start, e1rm_kg, work_sets, "
            "perf_score) VALUES ('Hip Thrust', ?, ?, 6, ?)",
            [base + timedelta(weeks=i), e1rm, perf],
        )

    # Phase B: a progressing block, closed loop through the real engine.
    mev, mav, mrv = 4, 10, 16
    cur = 0.0
    confs: list[float] = []
    targets: list[int] = []
    for wk in range(13):
        ws = base + timedelta(weeks=len(_NOISY_PERF_HISTORY) + wk)
        e1rm *= 1.01
        conn.execute(
            "INSERT INTO exercise_weekly_e1rm (exercise, week_start, e1rm_kg, work_sets, "
            "perf_score) VALUES ('Hip Thrust', ?, ?, ?, 5)",
            [ws, e1rm, max(1, round(cur))],
        )
        sq = compute_muscle_signal_quality(conn, "glutes")
        p = _decide(
            "glutes", current=cur, mev=mev, mav=mav, mrv=mrv, perf=5, soreness=0.0,
            conditioning_acwr=None, emphasis=True, emphasis_factor=1.0,
            confidence=sq["confidence"], scored_weeks=int(sq["scored_weeks"]), accuracy=None,
        )
        confs.append(float(sq["confidence"]))
        targets.append(p.target_sets)
        cur = float(p.target_sets)

    # The scenario must actually be low-confidence, or it isn't testing the fix.
    assert min(confs) < 0.22, f"prehistory not noisy enough — confidence {min(confs)} never low"
    # And under that low confidence the muscle still reaches MRV and never stalls.
    assert max(targets) >= mrv, f"low-confidence muscle never reached MRV: {targets}"
    for i in range(1, len(targets)):
        assert targets[i] >= targets[i - 1], f"went backwards at week {i}: {targets}"


def test_deload_week_does_not_poison_confidence(conn) -> None:
    """A deload week (low perf by design) in an otherwise-progressing block must
    not lower the muscle's confidence — the self-reinforcing suppression that
    froze glutes. Teeth: drop the deload-exclusion from the confidence query and
    this fails (the perf-2 week spikes the variance and craters confidence)."""
    from datetime import date as _date

    from shc.training.self_learning import compute_muscle_signal_quality

    conn.execute(
        "INSERT INTO exercise_muscle (exercise_name, muscle, role, credit) "
        "VALUES ('Hip Thrust', 'glutes', 'primary', 1.0)"
    )
    base = _date(2025, 1, 6)
    deload_wk = 6
    conf_before = conf_after = None
    e1rm = 100.0
    for wk in range(1, 13):
        ws = base + timedelta(weeks=wk - 1)
        if wk == deload_wk:
            perf, e1rm = 2, e1rm * 0.97
            conn.execute(
                "INSERT INTO muscle_prescription_log (week_start, muscle, action, target_sets) "
                "VALUES (?, 'glutes', 'deload', 8)",
                [ws],
            )
        else:
            perf, e1rm = 5, e1rm * 1.01
        conn.execute(
            "INSERT INTO exercise_weekly_e1rm (exercise, week_start, e1rm_kg, work_sets, "
            "perf_score) VALUES ('Hip Thrust', ?, ?, 8, ?)",
            [ws, e1rm, perf],
        )
        c = compute_muscle_signal_quality(conn, "glutes")["confidence"]
        if wk == deload_wk - 1:
            conf_before = c
        if wk == deload_wk + 1:
            conf_after = c

    assert conf_before is not None and conf_after is not None
    assert conf_after >= conf_before, (
        f"deload cratered confidence {conf_before} -> {conf_after} — the self-reinforcing trap"
    )


# ── INVARIANT 8: the safety gate and the volume controller consume ONE
# conditioning-ACWR staleness read. The audit found `_gates` printing a visible
# "BLIND" warning on stale WHOOP while `_conditioning_pressure` (the volume
# controller) kept reading the raw, un-blinded ratio — which trends toward zero
# as the chronic window fills with zeros, silently switching OFF the
# leg-interference hold in the same moment the gate says it can't see the data.
# Teeth: stop threading `state["freshness"]["whoop_stale"]` into
# `_conditioning_pressure` and this fails (the controller sees the raw ratio).


def test_gate_and_controller_agree_whoop_is_stale() -> None:
    """`_gates` fires its visible BLIND reason exactly when WHOOP is stale."""
    rec = RecoveryMetrics(score_date=(date.today() - timedelta(days=5)).isoformat())
    sleep = SleepMetrics()
    load = TrainingLoadMetrics()
    chk = CheckinMetrics()
    readiness = ReadinessSnapshot(tier="green")
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert any("BLIND" in r for r in g.reasons), "gate did not surface the stale-WHOOP warning"


def test_volume_controller_blind_when_whoop_stale(conn, seed) -> None:
    """`weekly_prescription` must not trust `conditioning_acwr` when the daily
    state it's handed says WHOOP is stale — regardless of what raw ratio happens
    to be sitting on the DTO (the real pipeline zero-fills it, but the controller
    must not rely on that incidental behavior; it must honor the blind flag)."""
    today = date.today()
    for wk in range(3):
        seed.workout(date.fromordinal(today.toordinal() - wk * 7), "Squat (Barbell)", [(60.0, 8)] * 4)

    fake_state = {
        "freshness": {"whoop_stale": True},
        # Deliberately a HIGH raw ratio — proves the blind flag wins over the
        # number, not merely over an incidentally-zeroed one.
        "training_load": {"conditioning_acwr": 2.5},
    }
    rx = weekly_prescription(conn, daily_state=fake_state)

    assert any("blind" in gap.lower() for gap in rx.data_gaps), (
        "prescription did not surface the WHOOP-stale/conditioning-blind data gap"
    )
    # With the signal blind, no muscle's HOLD reason may cite conditioning/court
    # load — that would mean the raw (untrusted) ratio leaked through anyway.
    for m in rx.muscles:
        assert "court/cardio load high" not in m.reason, (
            f"{m.muscle} cites conditioning interference despite a blind signal: {m.reason}"
        )


def test_volume_controller_sees_fresh_conditioning_signal() -> None:
    """Sanity check on the other branch: a fresh (non-blind) state's real ratio
    still reaches `_decide` normally — the fix only suppresses the STALE case."""
    from shc.training.autoregulation import _conditioning_pressure

    class _FakeConn:
        pass

    fake_state = {
        "freshness": {"whoop_stale": False},
        "training_load": {"conditioning_acwr": 1.9},
    }
    acwr, blind = _conditioning_pressure(_FakeConn(), state=fake_state)
    assert blind is False
    assert acwr == 1.9


def test_weekly_prescription_end_to_end_blind_on_stale_whoop(conn, seed) -> None:
    """Full wiring check with NO daily_state passed: `weekly_prescription`
    computes its own state via `compute_daily_state`, which must derive the
    same blind flag `_gates` derives from a genuinely stale `recovery` row."""
    today = date.today()
    for wk in range(3):
        seed.workout(date.fromordinal(today.toordinal() - wk * 7), "Squat (Barbell)", [(60.0, 8)] * 4)
    conn.execute(
        "INSERT INTO recovery (id, source, date, score, hrv, rhr, content_hash) "
        "VALUES (?, 'whoop', ?, 70.0, 60.0, 55, 'h')",
        [str(uuid.uuid4()), today - timedelta(days=5)],
    )

    rx = weekly_prescription(conn)

    assert any("blind" in gap.lower() for gap in rx.data_gaps), (
        "end-to-end prescription did not blind on a genuinely stale recovery row"
    )


# ── INVARIANT 9: an aliased curated staple never reads as "never trained". The
# 2026-07-10 audit found weekly_region_volume joining exercise_science by EXACT
# name match — a curated lift logged under its Hevy variant string (the same
# mismatch exercise_alias exists to bridge for progression scoring) read zero
# region volume forever, so its head phantom-led every rotation regardless of
# how many real sets were logged. Teeth: revert the join to exact-match and the
# aliased-name assertion below fails (falls back to zero).


def test_aliased_exercise_credits_region_volume(conn, seed) -> None:
    from shc.training.volume import weekly_region_volume

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    # 'Cable Tricep Pushdown' is the Hevy string Rob logs; the curated
    # exercise_science row lives under 'Tricep Pushdown (Cable)' (see migration
    # 0067). A set logged under the Hevy name must still credit the curated
    # muscle/region.
    seed.workout(week_start, "Cable Tricep Pushdown", [(30.0, 10)] * 3)

    regions = weekly_region_volume(conn, week_start)

    assert "triceps" in regions, f"aliased staple credited nothing: {regions}"
    assert regions["triceps"].get("lateral_head", 0.0) > 0, (
        f"aliased staple did not reach its curated region: {regions['triceps']}"
    )


def test_unaliased_exact_match_still_credits_region_volume(conn, seed) -> None:
    """Sanity check on the other branch: logging under the CANONICAL name
    directly (no alias needed) must keep working exactly as before."""
    from shc.training.volume import weekly_region_volume

    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    seed.workout(week_start, "Tricep Pushdown (Cable)", [(30.0, 10)] * 3)

    regions = weekly_region_volume(conn, week_start)

    assert regions.get("triceps", {}).get("lateral_head", 0.0) > 0


# ── INVARIANT 10: confidence CANNOT saturate on thin data. A handful of
# coincidentally-linear perf-score weeks (trivial with an integer 1-5 scale —
# "3, 4, 5" fits a line with zero residual) must not read as PERFECT signal
# stability. The audit found exactly this: 3 scored weeks could reach
# confidence == _CONFIDENCE_FULL, granting a speculative muscle the same
# +2/week ADD authority as one with hundreds of clean weeks. Teeth: remove the
# residual-dof cap or revert size_factor to the old step function and the first
# test below fails (confidence reaches/exceeds _CONFIDENCE_FULL at n=3).


def _seed_perf_series(conn, exercise: str, primary_muscle: str, perfs: list[int]) -> None:
    conn.execute(
        "INSERT INTO exercise_muscle (exercise_name, muscle, role, credit) "
        "VALUES (?, ?, 'primary', 1.0) ON CONFLICT DO NOTHING",
        [exercise, primary_muscle],
    )
    base = date.today() - timedelta(weeks=52)
    for i, p in enumerate(perfs):
        ws = base + timedelta(weeks=i)
        conn.execute(
            "INSERT INTO exercise_weekly_e1rm "
            "(exercise, week_start, e1rm_kg, work_sets, perf_score, trend, computed_at) "
            "VALUES (?, ?, 100.0, 4, ?, NULL, now())",
            [exercise, ws, p],
        )


def test_confidence_cannot_saturate_on_three_collinear_weeks(conn) -> None:
    """3 perfectly-linear weeks (3, 4, 5) must NOT reach _CONFIDENCE_FULL."""
    _seed_perf_series(conn, "Preacher Curl (Barbell)", "biceps", [3, 4, 5])
    sq = compute_muscle_signal_quality(conn, "biceps")
    assert sq["scored_weeks"] == 3
    assert sq["confidence"] < _CONFIDENCE_FULL, (
        f"3-week muscle reached confidence {sq['confidence']} >= "
        f"_CONFIDENCE_FULL ({_CONFIDENCE_FULL}) — full ADD authority on 3 data points"
    )

    # End-to-end: a SPECULATIVE add (perf below the progressing floor, so the
    # confidence shrink is the only thing standing between the muscle and a
    # full +2/week ramp) must be throttled below the unshrunk delta.
    unshrunk = _decide(
        "biceps",
        current=8,
        mev=6,
        mav=12,
        mrv=18,
        perf=3,  # stalled, not progressing — the +1 floor does not apply
        soreness=0.0,
        conditioning_acwr=None,
        confidence=1.0,
        scored_weeks=999,
        accuracy=None,
    )
    throttled = _decide(
        "biceps",
        current=8,
        mev=6,
        mav=12,
        mrv=18,
        perf=3,
        soreness=0.0,
        conditioning_acwr=None,
        confidence=sq["confidence"],
        scored_weeks=sq["scored_weeks"],
        accuracy=None,
    )
    if unshrunk.action == "add":
        assert throttled.target_sets <= unshrunk.target_sets, (
            f"thin-data confidence ({sq['confidence']}) failed to throttle the add: "
            f"throttled={throttled.target_sets} unshrunk={unshrunk.target_sets}"
        )


def test_signal_size_factor_is_monotone_and_smooth() -> None:
    """No step discontinuity in size_factor between adjacent scored-week counts —
    the old buckets jumped e.g. 0.30 -> 0.50 from n=9 to n=10 in one step."""
    prev = _signal_size_factor(0)
    for n in range(1, 700):
        cur = _signal_size_factor(n)
        assert cur >= prev - 1e-9, f"size_factor decreased at n={n}: {prev} -> {cur}"
        assert cur - prev < 0.05, f"size_factor jumped {prev} -> {cur} at n={n}"
        prev = cur
    assert _signal_size_factor(700) == _signal_size_factor(10_000) == 0.90


@pytest.mark.parametrize("n", range(0, 10))
def test_signal_size_factor_below_ten_weeks_cannot_reach_confidence_full(n: int) -> None:
    """Even PERFECT stability (1.0) must not reach _CONFIDENCE_FULL below the
    10-scored-week anchor — the n=3 case above is the concrete instance."""
    assert _signal_size_factor(n) * 1.0 < _CONFIDENCE_FULL


# ── INVARIANT 11: a thin chronic ACWR window (return from layoff / new block /
# post-deload) must not produce a spurious spike ratio. chronic is deliberately
# averaged over the FULL 21-day window length (so a real rest week reads low),
# but a nearly-empty window with even a modest acute week divides by a tiny
# denominator and reads as an absurd spike — the exact anti-progression trap
# pattern. metrics._ACWR_MIN_CHRONIC_DAYS makes that ratio None instead, visibly.


def test_layoff_week_does_not_produce_spurious_acwr_spike(conn, seed, today) -> None:
    from shc.metrics import _training_load

    # A genuine layoff: nothing in the 21-day chronic window, one solid session
    # 3 days ago (well inside the acute window).
    seed.workout(today - timedelta(days=3), "Bench Press (Barbell)", [(100.0, 8)] * 4)

    m = _training_load(conn, today)

    assert m.resistance_acwr is None, (
        f"thin/empty chronic window produced a ratio ({m.resistance_acwr}) instead of "
        "None — a return-from-layoff week would spuriously spike the fatigue gate"
    )

    rec, sleep, load, chk, readiness = (
        RecoveryMetrics(),
        SleepMetrics(),
        m,
        CheckinMetrics(),
        ReadinessSnapshot(tier="green"),
    )
    g = _gates(rec, sleep, load, chk, readiness, None)
    assert g.max_intensity == "high", (
        f"a genuinely empty chronic window must not cap intensity via a fabricated "
        f"ACWR spike: {g.reasons}"
    )
    assert any("chronic training-load window too thin" in r for r in g.reasons), (
        "gate did not surface a visible reason for the unscoreable ratio"
    )


def test_normal_history_acwr_unaffected_by_min_chronic_days_guard(conn, seed, today) -> None:
    """A well-populated chronic window (>=7 nonzero days) scores exactly as
    before — the guard only excludes genuinely thin windows."""
    from shc.metrics import _training_load

    for n in range(7, 28):  # 21 days of chronic activity, dense
        seed.workout(today - timedelta(days=n), "Bench Press (Barbell)", [(100.0, 8)])
    for n in range(0, 7):  # a full acute week at the same load
        seed.workout(today - timedelta(days=n), "Bench Press (Barbell)", [(100.0, 8)])

    m = _training_load(conn, today)
    assert m.resistance_acwr is not None
    assert m.resistance_acwr == 1.0  # constant load throughout → exactly 1.0
