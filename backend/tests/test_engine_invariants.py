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

from datetime import date, timedelta

import pytest

from shc.ai.workout_planner import load_cap_pct
from shc.metrics import _apply_band, muscle_group
from shc.training.autoregulation import _decide
from shc.training.self_learning import _historical_weekly_acwr

# ── INVARIANT 1: the ACWR band-fitter measures on the SAME window the live gate
# scores against. A drift here silently biases every personalized ACWR band
# (the 2026-07-03 audit found the fitter on a 28-day chronic window while the
# live gate used 21-day). The fitter is tested against an INDEPENDENT re-
# implementation of the live uncoupled 7:21 formula (metrics.py `_arm_acwr`).


def _ref_live_uncoupled_acwr(load_by_date: dict[date, float], ws: date) -> float | None:
    """Reference impl of metrics.py `_arm_acwr` — acute [ws, ws+7)/7 over the
    contiguous 21-day chronic [ws-21, ws)/21. This is the source of truth the
    fitter must mirror; if metrics.py's live window changes, change it HERE too
    and both this test and the fitter must be reconciled."""
    acute = sum(load_by_date.get(ws + timedelta(days=d), 0.0) for d in range(0, 7)) / 7.0
    chronic = sum(load_by_date.get(ws - timedelta(days=d), 0.0) for d in range(1, 22)) / 21.0
    return round(acute / chronic, 4) if chronic > 0 else None


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


# ── INVARIANT 2b: confidence reads steady PROGRESS as a clean signal, not noise.
# The old raw-CV stability penalized a climbing perf series (3→4→5) for its
# dispersion — the muscles that were working scored as the least trustworthy.
# Stability is now measured around the OLS trend, so a steady climb beats a
# same-mean series that bounces around. Deload weeks are excluded entirely.


def test_progress_reads_as_signal_not_noise(conn) -> None:
    from datetime import date as _date

    from shc.training.self_learning import compute_muscle_signal_quality

    conn.execute(
        "INSERT INTO exercise_muscle_map (exercise_name, primary_muscle) "
        "VALUES ('ClimbLift', 'glutes'), ('NoisyLift', 'quads')"
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
        "INSERT INTO exercise_muscle_map (exercise_name, primary_muscle) "
        "VALUES ('Hip Thrust', 'glutes')"
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
        "INSERT INTO exercise_muscle_map (exercise_name, primary_muscle) "
        "VALUES ('Hip Thrust', 'glutes')"
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
