# Engine Invariants — the athlete-protection contract

The training engine's job is to train Rob **according to the science**, aggressively but safely. The failure mode that matters most is not a crash — it's a *silent* bug that quietly trains him according to the bug instead of the evidence (a stray rest day, a frozen muscle, a mis-fitted threshold). This file is the contract that prevents that class of bug from recurring. Every invariant here is enforced by an executable test in [`backend/tests/test_engine_invariants.py`](backend/tests/test_engine_invariants.py). If one fails, a change has re-opened a hole that once held the athlete back — **read the invariant before "fixing" the test.**

Origin: the 2026-07-03 soundness audit (four parallel deep-dives, each finding verified against source + live data before it was trusted). Each invariant below maps to a real defect that audit found and fixed.

## The invariants

1. **The ACWR band-fitter measures on the same window the live gate scores against.** `self_learning._historical_weekly_acwr` and `metrics._arm_acwr` must use the identical uncoupled window (acute = 7 days `[ws, ws+7)`, chronic = the contiguous 21 days before it `[ws-21, ws)`, each a per-day mean). *Why:* a personalized percentile band is only meaningful on the scale it is applied against; the audit found the fitter on a 28-day chronic window while the gate used 21-day, biasing every personal band.

2. **A measurably progressing muscle is never frozen by the confidence shrink.** For `perf ≥ 4`, recovered, below MRV, `_decide` returns `delta ≥ 1` at *any* confidence. *Why:* confidence caps ~0.34 by design and was rounding every add to zero — glutes (emphasis muscle, PRs for 8 weeks) was pinned at its grow-floor. Progress is an outcome signal; the shrink only governs *speculative* adds.

3. **The progression floor does not become a free ramp.** A muscle with no outcome signal (`perf is None`) on thin, low-confidence data still climbs only to its MEV floor, never above. Invariant 2 must not over-loosen into invariant 3's territory.

4. **No movement slips past its recovery gate.** Exercise classification never puts a pull/hinge pattern into `push` (it would pass a pull-rested day), and posterior-chain hinges (rack pull, pull-through, back extension, reverse hyper, KB swing) never fall through to `other`. `"Upright Row"` is the one deliberate row→push exception.

5. **A green day permits true top sets.** `load_cap_pct` is monotonic (`rest < low < moderate < high`) and `high ≥ 100%` of e1RM. An unset intensity must not silently fall through to a hard cap. *Why:* a silent load cap below e1RM on a green day is the "treated like a fragile 40-year-old" failure in load form.

6. **A progression-capping personal band may only loosen the population default, never tighten below it.** Resistance REST/LOW/MOD bands and personal MEV are floor-only against population. *Why:* Rob's thin, noise-dominated N=1 history must never make a growth gate stricter than the population floor — the anti-progression trap.

## The rule for changing the engine

Any change to a gate, threshold, band-fit, volume decision, or classifier **must keep this suite green**, or must update an invariant *deliberately* — with the reasoning recorded here and in [DECISIONS.md](DECISIONS.md). "The test failed so I changed the assertion" is how the athlete gets quietly held back again. The test encodes the intent; the code serves it.

## Known-open items (audit 2026-07-03, deferred — not yet invariants)

These were found and judged real but left for a follow-up decision rather than an in-place fix:

- **ACWR window: 21-day (uncoupled) vs 28-day (Gabbett).** The live gate uses a 21-day uncoupled chronic; Gabbett's 1.5/1.8/2.0 thresholds were derived on 28-day. The M2 review shifted the thresholds up for the uncoupled scale deliberately, so this is a *science-calibration* question, not a bug — flagged for Rob.
- **Deload-week contamination of confidence variance.** Deload weeks (low perf by design) inflate the perf CV → depress confidence. Invariant 2 neutralizes the *symptom* (progressing muscles no longer freeze); the root-cause fix (exclude deload weeks from the CV, or detrend the series) is a self-learning redesign pending review.
- **`metrics` e1RM-regression deload not OR'd into `weekly_prescription`.** The planner still surfaces it as a hard constraint, so it is not a silent under-train; low priority.
- **Missing e1RM silently skips the load-cap check** for that exercise (`workout_planner`). Fail-open; should surface a warning.
- **Low-severity readiness items:** HRV gate at −1.5σ vs the vault's −1.0σ; RHR subscore on a coupled window (near-inert); sleep sub-components inheriting the duration score when stage/SpO₂ data is absent. All lean toward *over*-training on sparse data, not holding back.
