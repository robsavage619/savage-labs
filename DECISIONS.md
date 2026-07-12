# Savage Labs — Decisions

ADR log for architecture choices. Most recent first. One section per decision.

When adding: include **Context**, **Decision**, **Why**, **Consequences**. Skip the ceremony if it's a small choice — three sentences is fine. The point is that future-you (or Claude) can answer "why did we do it this way?" without re-deriving from code.

---

## 2026-07-12 — Hevy logs per-hand; load mechanics no longer halves

**Context.** `load_mechanics.per_hand_kg` halved every dumbbell/cable-crossover lift on the premise (stated in its own docstring) that "Rob logs two-implement lifts as the COMBINED weight." That premise is false — Hevy logs the weight of a *single* implement (one dumbbell / one cable stack). The halving therefore corrupted every dumbbell ceiling: a real **20 lb Lateral Raise** (logged 20, done at RPE 7) was halved to a phantom "10 lb each hand", dropping its e1RM from 28 to 14 and prescribing an absurd **7.5 lb** — flagged by Rob against a lift he moves easily. Audit found **12 exercises** being wrongly halved (lateral raise, hammer curl, rear-delt fly, split squat, shrug, incline curl, crossovers, RDLs); for 11 of 12 the halved figure was physically too light to be real.

**Decision.** `per_hand_kg` is now the **identity** — the logged Hevy weight already IS the per-hand load. The `LoadType` taxonomy is retained for the per-hand *label* ("each hand") only, not for any weight math. `e1rm_by_exercise` was already Hevy-only, so no source mixing. The working-weights display shows the physical whole-body total as "N lbs total both hands" (2× per-hand) instead of the old (wrong) parenthetical.

**Why.** The logged number and the e1RM/ceiling must share one unit; Hevy's unit is per-hand, so any conversion is a corruption. Halving "down" felt safe (a low ceiling can't prescribe an unsafe load) but silently *under*-trained Rob on every dumbbell lift — the opposite of the training goal.

**Consequences.** Tests updated in `test_load_mechanics.py` and `test_e1rm_by_exercise.py` (the old `test_dumbbell_pair_is_halved` asserted the bug). CLAUDE.md invariant corrected. **Exposed a separate, pre-existing bug** the halving had been masking: contaminated all-time max rows now show as physically-impossible per-hand dumbbell loads — **Hammer Curl (Dumbbell) 170**, **Romanian Deadlift (Dumbbell) 150** — inflating those two ceilings. These are bad data rows (no such dumbbells exist), pending Rob's confirmation on whether RDL is logged as a total, then quarantine/correction. Cable Fly 160 is a plausible cable-stack value and left as-is.

---

## 2026-07-12 — Illness gate requires corroboration (allergy vs infection)

**Context.** `_gates` capped intensity to LOW whenever `skin_temp_delta ≥ 0.9°F` **alone**, and downgraded to MODERATE on `respiratory_rate_delta ≥ 1.0` alone. For a chronic allergic-rhinitis + asthma athlete (Rob, on year-round grass SLIT), those two signals are inflated by H1-mediated peripheral vasodilation and sleep-disordered breathing **without systemic infection**. On Rob's own history the skin-temp gate fired on **~15–20% of all days**, and **~52% of the days it fired were GREEN-recovery days** — the athlete told to go easy on a lone, confounded signal. The wearable literature agrees single-model illness detection is low-specificity: a validated RHR+RR+HRV algorithm had a **4–10% positive predictive value**, with exercise/poor-sleep/stress logged as false-positive drivers (grounded in `savage_vault/wiki/allergic-rhinitis-confounds-recovery-metrics.md`).

**Decision.** A skin-temp / resp-rate rise caps intensity only when **corroborated** by an independent signal — HRV < −1.0σ, WHOOP recovery < 50, or RHR ≥ 8% above baseline — OR when recovery evidence is absent (fail conservative). A **fever-range spike (≥2.0°F)** still caps standalone (no peripheral vasodilation produces that). On a green-recovery, normal-HRV day, an isolated temp/RR bump reads as allergy/environment and does **not** cap. Implemented as `_illness_gate_corroborated(rec)` in `metrics.py`.

**Why.** The gate's job is to stop training for *infection*, not for allergic inflammation — which sports-medicine consensus (ARIA/EAACI/IOC) treats as a train-through condition. A high-sensitivity/low-specificity lone-signal trip was systematically holding a recovered athlete back, contrary to the "train like an athlete, not a fragile 40-year-old" directive.

**Consequences.** New tests in `test_gates.py` (green-day no-cap, fever-range still caps, HRV-corroborated caps, resp-rate no-cap on green). Missing-recovery-data still caps (conservative), so the fresh-user path is unchanged. Today (2026-07-12) this moved Rob from LOW → MODERATE on a green day.

## 2026-07-12 — Progression trend is contamination- and rep-range-robust

**Context.** The fatigue deload (`deload_check`) fires when ≥3 muscles read "regressing" (perf ≤ 2), where perf is an OLS slope of weekly estimated-1RM. Two artifacts drove a **~6-week false deload**: (1) load-logging contamination — a per-hand dumbbell lift logged as combined-stack total (e.g. a 130 lb "hammer curl") put one impossible point in the 12-week window and anchored the slope steeply negative; (2) rep-range periodization — shifting from a low-rep strength block into a higher-rep hypertrophy block mechanically lowers the Epley e1RM even as **volume-load rises** (Iso-Lateral Row: e1RM −27% while tonnage +46%). The controller read planned hypertrophy work as strength loss and prescribed a permanent deload.

**Decision.** In `score_exercise`: (a) `_drop_contaminated_e1rm` removes weekly points >35% off the series median before the trend fit (physiologically-impossible excursions are logging artifacts, not physiology; genuine progression sits within ±35% of its median); if <3 trustworthy weeks remain, return None rather than a spurious call. (b) A "regressing" e1RM call is **corroborated against the tonnage trend** — real regression is e1RM down **and** volume-load down; e1RM down with tonnage flat/rising is a rep-range shift and is reclassified (not regressing).

**Why.** For a hypertrophy-primary goal, weekly volume-load is the truer progress signal than a rep-capped 1RM proxy. A deload controller must not fire on its own measurement artifacts, and it especially must not use e1RM as the trigger while prescribing an e1RM reduction as the treatment (a self-perpetuating loop).

**Consequences.** New tests in `test_scoring.py` (contamination drop preserves genuine progression; declining-e1RM-with-rising-tonnage is not regression; both-falling is). Live effect: the false deload cleared (24 progressing / 8 genuinely regressing / 4 excluded) and the prescription returned to accumulation. Genuine regression (both signals down) still fires the deload.

---

## 2026-07-10 — Emphasis lower-body muscles keep an MEV floor under conditioning interference

**Context.** `weekly_prescription`'s `leg_interference` branch holds every `LOWER_BODY` muscle in place when conditioning ACWR > 1.5 (pickleball/cardio load debits leg recovery). That branch was evaluated before the MEV-floor branch, and the floor clamp explicitly listed `leg_interference` as a "hold below MEV" case. So glutes — an ★ emphasis/lagging muscle with `perf=None`, ~9% confidence, and `cur=0` — got frozen at 0 sets for any week ACWR > 1.5. Given Rob plays 1000+ min/mo, that's most weeks: the prioritized bring-up muscle trained at zero indefinitely, a silent under-train contrary to the stated hypertrophy goal.

**Decision.** Under `leg_interference` (and not genuinely under-recovered), an **emphasis** lower-body muscle floors at **MEV** (not the emphasis MEV–MAV midpoint — conservative while sport load is high). Non-emphasis legs (quads/hams/adductors) still hold in place. The +2/wk step clamp eases the climb to MEV over ~2–3 weeks rather than dumping full volume in one week.

**Why.** Court load damages the big eccentric leg tissues (quads/hams) — holding them is correct. Glutes are a lagging priority that pickleball does not heavily damage, and low-fatigue isolation (hip thrust, abduction) fits inside the recovery budget. Codified as **invariant 7** in [ENGINE_INVARIANTS.md](ENGINE_INVARIANTS.md); the pre-existing MEV-floor logic already promised this for perf=None muscles (invariant 3), so this closes the one branch that bypassed it.

**Consequences.** New test `test_conditioning_interference_never_freezes_emphasis_below_mev` enforces both halves (glutes climb, quads still hold). Downstream, this also unblocks glute volume against validator #22 (`workout_planner`), which rejects any plan exceeding a muscle's target — glutes were capped at ~1 set whenever interference was active. The scope is glutes-today because it's the only emphasis lower-body muscle; if hamstrings become an emphasis muscle, the same floor applies to it automatically.

---

## 2026-07-03 — ACWR uses a 21-day uncoupled chronic window (deliberate deviation from Gabbett 28-day)

**Context.** The 2026-07-03 soundness audit flagged that the live ACWR gate uses a 7-day acute over a 21-day *uncoupled* chronic window `[today-27, today-7)`, while Gabbett/Malone's classic 1.5/1.8/2.0 injury thresholds were derived on a 28-day *coupled* chronic (acute ⊂ chronic). The band-fitter had drifted to a 28-day window and was corrected to match live (commit 5015e29).

**Decision.** Keep the **21-day uncoupled** window as the standard. The population thresholds (`RES_ACWR_REST/LOW/MOD = 2.0/1.8/1.5`) stay as-is — they were deliberately shifted up (panel review M2) for the uncoupled scale, which runs higher than the coupled form.

**Why.** Uncoupling (acute disjoint from chronic) removes the mathematical artifact where the acute window inflates its own chronic baseline and compresses ratios toward 1.0 (Windt & Gabbett 2019). For an N=1 athlete these thresholds are heuristic priors either way — not validated injury cutoffs — so re-deriving them for a 28-day window buys no rigor and risks miscalibration. Convention (the shipped, internally-consistent 21-day system) beats novelty. The personal bands are percentiles of Rob's own distribution, so they self-calibrate to whichever window is used, provided the fitter mirrors live — which is now enforced by `test_engine_invariants.test_acwr_fit_window_mirrors_live_gate`.

**Consequences.** The window is now a documented invariant, not an accident. If it ever changes, change it in `metrics._arm_acwr`, `self_learning._historical_weekly_acwr`, and the test's reference impl together, and re-confirm the population thresholds. Revisit only if a personal injury/overreaching history gives real calibration data.

---

## 2026-06-03 — Sports-science panel review: muscle taxonomy + signal-quality decisions

**Context.** A panel of sports-science reviewers audited the self-learning hypertrophy engine and flagged a cluster of modeling choices that needed to be either fixed or documented as intentional.

**Decisions (the ones worth recording — the fixes live in code/migrations 0040–0045):**
- **Muscle taxonomy folds are intentional.** `abductors → glutes` (hip abduction ≈ glute medius), `brachialis → biceps` (elbow flexor trained with biceps, not a body-diagram region), Hevy `shoulders → side_delts` as the generic-delt fallback (specific presses overridden to `front_delts` in 0043). These collapse a few distinct muscles to keep the volume vocabulary aligned with the frontend BodyDiagram / `daily_checkin` soreness keys. Accepted loss of granularity.
- **Conditioning interference is graded, not a single cliff.** The autoregulation controller *holds* leg volume when `conditioning_acwr > 1.3` (graded debit), and the metrics gate *forbids* legs only at `> 1.5` (a genuine spike). Two tiers by design — don't collapse them.
- **e1RM is a strength proxy used as a coarse productivity signal, not a hypertrophy measurement.** It feeds add/hold/cut only as a multi-week trend with a ≥3-week minimum and a noise-aware dead-band; the physique pipeline (waist:shoulder) is the body-composition signal, treated as multi-month confirmatory, not a primary driver.

**Why.** Future-me will re-encounter these as "bugs" and try to un-fold them. They're deliberate trade-offs grounded in the panel review.

**Consequences.** Per-muscle volume vocabulary is fixed at the BodyDiagram set; new exercises map into it. Roadmap items 3/4 (individualized landmarks, physique outer loop) still pending.

---

## 2026-05-24 — Vault retrieval: semantic (model2vec) + lexical, with citation validation

**Context.** Vault retrieval (`shc.ai.vault`) was purely lexical — tag→signal maps and substring matching over ~529 notes. Vocabulary mismatch silently dropped relevant research ("parasympathetic withdrawal" never matched the `hrv_anomaly` signal). The briefing path retrieved blind (no hints). And `vault_insights` citations were never validated — the model (or the decorative fallback) could cite any filename, real or invented.

**Decision.** (1) Blend `model2vec` static embeddings (`minishlab/potion-base-8M`, torch-free, ~30MB) into `VaultIndex.query` via cosine similarity, with a similarity floor so vocabulary-mismatched notes still surface. Lexical scoring stays as a **graceful fallback** if the model can't load. (2) `validate_plan(..., allowed_citations=...)` rejects any `*.md` citation not in the real vault and requires ≥1 real citation; wired into `POST /api/workout/plan`. (3) Trimmed the injected context — catalog is titles-only, excerpts capped at 10, research fenced as `⟪BEGIN/END RESEARCH⟫` data. (4) Added `shc.ai.quality` (RPE-calibration, adherence trend, citation-validity rate) for no-API output-quality measurement.

**Why.** Lexical-only under-recalled and there was no way to prove citations were grounded. model2vec was chosen over sentence-transformers to avoid a ~1GB torch dependency in a DuckDB+FastAPI app. Citation validation is opt-in (off by default) so existing schema-only tests are unaffected.

**Consequences.** New dependency: `model2vec` (pulls `numpy`, `tokenizers`, `safetensors` — all torch-free). First retrieval call loads the model (~0.6s) and pings HF to check the model revision; offline-with-cache works, offline-without-cache falls back to lexical. `validate_plan` now raises `CitationError` (subclass of `ValueError`, returns HTTP 422) on a bad citation.

---

## 2026-04-25 — DuckDB WAL corruption recovery

**Symptom.** API fails to start with `INTERNAL Error: Failure while replaying WAL file`. Happens after force-killing uvicorn mid-transaction.

**Fix.** `python3 -c "import os; os.remove('<data-dir>/shc.duckdb.wal')"` then restart. The WAL file is at `zealous-pascal-9be780/backend/data/shc.duckdb.wal` (canonical data dir, symlinked from other worktrees). Check `find /Users/robsavage/Projects/savage-health-center -name "*.wal"` to confirm all locations.

**Prevention.** Let uvicorn shut down cleanly (`kill -TERM`, not `-9`) when possible.

---

## 2026-04-25 — Orbitron font via browser `<link>`, not `next/font/google`

**Context.** `next/font/google` downloads woff2 server-side at dev startup. Server can't reach Google Fonts in this env, so the font silently fell back to Geist. Burned a session debugging.

**Decision.** Load Orbitron via `<link rel="stylesheet">` in `app/layout.tsx` `<head>`, with `--font-orbitron` CSS variable in `globals.css`. The browser fetches it directly.

**Why.** Bypasses server-side network constraint. Works even when the dev server can't reach Google. Tradeoff: no automatic woff2 self-hosting / FOUT mitigation, but acceptable for one font weight.

**Consequences.** Don't add `next/font/google` for any font that isn't already cached in the build. Prefer `<link>` or `next/font/local` with the woff2 committed.

---

## 2026-04-24 — Migration numbering: never reuse a prefix

**Context.** Created `0007_metrics_and_checkin.sql` while `0007_workout_plans.sql` already existed and was marked applied. DuckDB's migration runner silently skipped the new file because version 7 was done. `v_daily_load` was missing in production for hours.

**Decision.** New migrations always use the next free numeric prefix. Check `SELECT MAX(version) FROM schema_migrations` before naming.

**Why.** The runner is version-keyed by integer prefix, not filename. Two files with the same prefix → second one is silently skipped, no warning.

**Consequences.** When two branches add migrations in parallel, the merger renumbers the second one before merging.

---

## 2026-04-23 — DailyState as single source of truth

**Context.** Readiness, HRV, beta-blocker awareness, and training load were being computed in 4+ places: backend planner, frontend `readiness.ts`, individual pillar components, briefing card. Numbers diverged across the dashboard.

**Decision.** Backend `shc.metrics` builds a single `DailyState` per day. Exposed via `/api/state/today`. Frontend components consume; no recomputation client-side. Beta-blocker behavior expressed as `DailyStateGates` (`hr_zone_shift_bpm`, `kcal_multiplier`).

**Why.** Numbers must agree across the dashboard. Computing in one place + caching is simpler than reconciling N implementations.

**Consequences.** `frontend/lib/readiness.ts` was slimmed to a single `hasBetaBlocker()` helper (kept for legacy pillar). New metrics → add to DailyState, never to a component.

---

## 2026-04-22 — HRmax via Tanaka, not Fox (220 − age)

**Context.** WHOOP/Apple show HR data in absolute bpm; we need a max to compute zones. The Fox formula (220 − age) overestimates HRmax for adults 35+ by ~5–10 bpm, which pushes everything down a zone.

**Decision.** Use Tanaka: `HRmax = 208 − 0.7 × age`. Applied in `cardio-panel.tsx` as the constant for zone calculation.

**Why.** Better fit for adults 30–60 per the underlying meta-analysis. The 5–10 bpm difference matters for Z2 vs Z3 boundary, which is where most of Rob's training sits.

**Consequences.** Beta-blocker `hr_zone_shift_bpm` from DailyState is subtracted from this max on dosing days.

---

## 2026-04-21 — Push to main, no PRs

**Context.** Single-user personal project. PR review adds friction with no benefit.

**Decision.** Always push directly to `main`. No feature branches except for Claude session worktrees (auto-created, throwaway).

**Consequences.** Every session worktree starts behind main. Sync protocol in `CLAUDE.md` and `feedback_worktree_sync` memory.
## 2026-07-12 — Fail conservative on missing/stale signals; one deload authority

**Context.** The audit found three decision-path splits: no recovery data retained the default HIGH gate, stale sleep architecture could still cap a later day, and weekly/calendar deloads were not promoted into `DailyState`. The session allocator also labeled summed per-muscle credit as physical sets, producing apparent 60+ set sessions.

**Decision.** Missing recovery caps intensity at MODERATE pending manual verification. Sleep architecture only gates when its source night is at most two days old. Weekly/calendar/systemic deload status is computed once and promoted into `DailyState.gates`, including the existing post-deload cooldown. Session allocation exposes `credited_muscle_sets`, never `total_sets`, because compound-set muscle credits overlap. Final volume rationales always state the actual post-floor target and delta.

**Consequences.** Unknown data can no longer authorize HIGH work, stale sleep cannot suppress a current day, and every validator/persistence/UI consumer sees the same deload flag. Regression coverage lives in `test_compute_daily_state.py` and `test_autoregulation.py`.

---
