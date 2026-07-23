# Engine Invariants — the athlete-protection contract

The training engine's job is to train Rob **according to the science**, aggressively but safely. The failure mode that matters most is not a crash — it's a *silent* bug that quietly trains him according to the bug instead of the evidence (a stray rest day, a frozen muscle, a mis-fitted threshold). This file is the contract that prevents that class of bug from recurring. Every invariant here is enforced by an executable test in [`backend/tests/test_engine_invariants.py`](backend/tests/test_engine_invariants.py). If one fails, a change has re-opened a hole that once held the athlete back — **read the invariant before "fixing" the test.**

Origin: the 2026-07-03 soundness audit (four parallel deep-dives, each finding verified against source + live data before it was trusted). Each invariant below maps to a real defect that audit found and fixed.

## The invariants

1. **The ACWR band-fitter measures on the same window the live gate scores against.** `self_learning._historical_weekly_acwr` and `metrics._arm_acwr` must use the identical uncoupled window (acute = 7 days `[ws, ws+7)`, chronic = the contiguous 21 days before it `[ws-21, ws)`, each a per-day mean). *Why:* a personalized percentile band is only meaningful on the scale it is applied against; the audit found the fitter on a 28-day chronic window while the gate used 21-day, biasing every personal band.

2. **A measurably progressing muscle is never frozen by the confidence shrink.** For `perf ≥ 4`, recovered, below MRV, `_decide` returns `delta ≥ 1` at *any* confidence. *Why:* confidence caps ~0.34 by design and was rounding every add to zero — glutes (emphasis muscle, PRs for 8 weeks) was pinned at its grow-floor. Progress is an outcome signal; the shrink only governs *speculative* adds.

3. **The progression floor does not become a free ramp.** A muscle with no outcome signal (`perf is None`) on thin, low-confidence data still climbs only to its MEV floor, never above. Invariant 2 must not over-loosen into invariant 3's territory.

4. **No movement slips past its recovery gate.** Exercise classification never puts a pull/hinge pattern into `push` (it would pass a pull-rested day), and posterior-chain hinges (rack pull, pull-through, back extension, reverse hyper, KB swing) never fall through to `other`. `"Upright Row"` is the one deliberate row→push exception.

5. **A green day permits true top sets.** `load_cap_pct` is monotonic (`rest < low < moderate < high`) and `high ≥ 100%` of e1RM. An unset intensity must not silently fall through to a hard cap. *Why:* a silent load cap below e1RM on a green day is the "treated like a fragile 40-year-old" failure in load form.

6. **A progression-capping personal band may only loosen the population default, never tighten below it — and if a band can only ever loosen, fitting it is not worth pretending it's active.** Personal MEV is floor-only against population, enforced the same way invariant 3 is. Resistance ACWR (REST/LOW/MOD) is NOT fitted at all (as of the 2026-07 remediation): applying it floor-only meant a personal fit — a percentile of Rob's own load — sat below the population injury ceiling by construction, so `max(personal, population)` provably always resolved to population. It was computed, persisted, and reported as "personal (fitted)" while changing nothing; `self_learning.fit_acwr_bands` now only fits conditioning. *Why:* Rob's thin, noise-dominated N=1 history must never make a growth gate stricter than the population floor — the anti-progression trap — and a band that can only ever be floored isn't worth the ceremony of fitting it. Enforced end-to-end by `test_resistance_acwr_personal_bands_never_reach_the_gate`: absurdly tight resistance values written directly into `personal_acwr_bands` must not move `_gates`' thresholds off population.

   This floor-only philosophy also covers the **derived conditioning leg-HOLD threshold** (`metrics.personalized_cond_thresholds`, 2026-07-23 remediation). The hard `forbid_legs` bound is legitimately sample-gated tighten/free-loosen — it's the injury bound. But the graded `hold` was derived as `forbid − 0.3` with no floor of its own, so a well-sampled tightened `forbid` silently dragged `hold` down too even though the hold is a *volume-programming* decision, not an injury bound. With Rob's live fit (`forbid=1.53`, 37 weeks) this produced `hold=1.23` — a leg-volume hold active on ~40% of days for an athlete carrying real pickleball conditioning load, exactly the invariant-6 anti-progression trap in hold form. `hold` is now `max(forbid − 0.3, COND_ACWR_HOLD_LEGS)` (nudged inside `forbid` if a tight fit would otherwise collide with it) — it may still loosen below population when `forbid` loosens, it just never tightens below the population 1.5 floor. Enforced by `test_personalized_cond_thresholds_hold_never_tightens_below_population`, `_hold_stays_inside_a_tight_forbid`, `_hold_still_loosens_with_forbid` (test_gates.py) and `test_weekly_prescription_leg_hold_never_tighter_than_population` (test_autoregulation.py).

7. **Conditioning interference never freezes an EMPHASIS lower-body muscle below MEV.** The `leg_interference` hold (`weekly_prescription`, cond. ACWR > 1.5) holds quads/hams/adductors in place — correct, they absorb the eccentric court load — but an emphasis lower-body muscle (glutes) still floors at MEV. *Why:* the hold was checked before the MEV-floor branch, so glutes (emphasis, `perf=None`, thin data, `cur=0`) sat at 0 for every week cond. ACWR > 1.5 — i.e. most weeks, given 1000+ min/mo of pickleball — the exact silent under-train of a lagging priority muscle that invariant 3 forbids. Non-emphasis legs still hold; the climb to MEV is rate-limited to +2/wk so it eases in while sport volume is high. Enforced by `test_conditioning_interference_never_freezes_emphasis_below_mev`.

## The rule for changing the engine

Any change to a gate, threshold, band-fit, volume decision, or classifier **must keep this suite green**, or must update an invariant *deliberately* — with the reasoning recorded here and in [DECISIONS.md](DECISIONS.md). "The test failed so I changed the assertion" is how the athlete gets quietly held back again. The test encodes the intent; the code serves it.

## Audit follow-ups — status

**Resolved:**
- **Resistance ACWR bands fitted but provably inert** (2026-07 remediation) → decided: retire the fit entirely rather than keep computing numbers `floor_only` can never apply. See invariant 6 and [DECISIONS.md](DECISIONS.md).
- **ACWR 21-day vs 28-day window** → decided: keep 21-day uncoupled, documented in [DECISIONS.md](DECISIONS.md) (2026-07-03). Fitter mirrors live, enforced by invariant 1.
- **Deload-week contamination of confidence + progress-read-as-noise** → fixed (commit 5b0ecd3): deload weeks excluded from the perf series; stability now detrended. Guarded by `test_progress_reads_as_signal_not_noise`.
- **Missing e1RM silently skipped the load-cap check** → now fail-visible: a weighted lift with no e1RM on a capped day logs a WARNING instead of skipping silently (`workout_planner`).

**Deliberately kept as-is (judged correct for the goal, not bugs):**
- **HRV gate at −1.5σ (not the vault's −1.0σ).** Tightening to −1.0σ would cap intensity LOW on ~16% of days — *more* holding back, and HRV is a weak/propranolol-corrupted signal for Rob. Only a strong suppression (−1.5σ) should cap. Kept.
- **RHR subscore on a coupled 28-day baseline (near-inert).** An uncoupled fix is neutral-direction and low-severity, but the field is surfaced on the visible readiness dashboard + DTO — not worth the blast radius for the gain. Kept.
- **Sleep sub-components inheriting the duration score when stage/SpO₂ absent.** Low stakes; fixing leans *more* conservative. Kept.

**Still deferred (low priority):**
- **`metrics` e1RM-regression deload not OR'd into `weekly_prescription`.** The planner already surfaces it as a hard constraint, so it is not a silent under-train; plumbing it into the volume controller is belt-and-suspenders with real blast radius. Left for a dedicated change.
