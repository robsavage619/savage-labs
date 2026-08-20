# Savage Labs — Project Conventions

Personal health intelligence platform. Single user (Rob). Always push to main directly — no PRs, no feature branches.

## Pre-flight (every session, before previewing or claiming results)

1. `git fetch origin && git log HEAD..origin/main --oneline` — if any commits, the worktree is stale.
2. If stale: `git stash && git merge origin/main && git stash pop` (or `git stash drop` if conflict-free). **Then `./dev-restart.sh`** — a merged fix is not a running fix, and the API serves whatever was loaded at boot. On 2026-08-19 the WHOOP cursor fix (9fc59b5) sat in `origin/main` for 3 days while the running server kept hitting the bug it fixed; `git reflog main` shows when local main actually last moved.
3. Spot-check `frontend/app/page.tsx` and `frontend/app/layout.tsx` against the main repo before screenshotting — they're the most-edited files and the ones Rob can see.
4. Backend tests in a worktree need `PYTHONPATH=$PWD/src` — the shared `backend/.venv` resolves `shc` to the **main repo**, so a suite can pass green against source you never changed. See [feedback_worktree_pytest_resolves_main](~/.claude/projects/-Users-robsavage-Projects-savage-health-center/memory/feedback_worktree_pytest_resolves_main.md).
5. If the task cites a commit SHA as already-landed, confirm it: `git merge-base --is-ancestor <sha> HEAD`. Parallel sessions leave commits on sibling worktree branches that a clean `origin/main` check won't catch.

## Architecture invariants

- **DailyState is the single source of truth** for readiness, HRV, sleep, training-load, beta-blocker gate. Frontend reads `/api/state/today`. Never recompute these client-side.
- **Beta-blocker gate** lives in `DailyStateGates` (`hr_zone_shift_bpm`, `kcal_multiplier`). Components consume; they don't infer from medications list.
- **HRmax = measured first, Tanaka as fallback** — `max_hr_measured` (183) if present, else Tanaka (208 − 0.7 × age, = 180); never 220 − age. `cardio-panel.tsx` already resolved it this way; the old "HRmax = Tanaka" wording was stale. The vault agrees the measured max is the correct anchor for zone percentages ([[seiler-2010-polarized-training]]), and WHOOP's own stored zone minutes are computed off 183.
- **HR zones come from WHOOP, not from percentages.** WHOOP does NOT use the textbook 50/60/70/80/90% cutoffs — its Z5 starts at ~93% of max and Z4 at ~85%. Deriving a zone label from a percentage put sessions a full zone hotter than the zone MINUTES WHOOP reported for the same session. Real boundaries live in `whoop_hr_zones` and reach the frontend as `training_load.hr_zone_bounds`; percentages are the fallback only when that table is empty.
- **Two "Zone 2" definitions exist — don't merge them.** `cardio_z2_min_7d` is WHOOP's own Z2 band (70–77% of max here) and is what the gates/planner read. `cardio_aerobic_base_min_7d` is the METABOLIC zone-2 dose (~70–85% of max, lactate 1.7–2.0) that [[zone-2-training]] prescribes ~180 min/wk of — it spans WHOOP Z2 **and** Z3, so reporting WHOOP Z2 alone undercounts the aerobic base by ~40%. Use the aerobic-base field for "am I getting enough Z2?" narratives.
- **Migrations**: numeric prefix `NNNN_<name>.sql`. Two files with the same prefix → silently skipped. Always check the highest applied version before adding.
- **Apple Health XML**: `<Workout>` elements → `cardio_sessions`; `<Record>` elements → metrics. Strength/flexibility workout types skipped (handled by Hevy).
- **Load semantics are per-hand**: Hevy logs dumbbell/cable lifts as the per-hand (single-implement) weight — the logged number IS the per-hand load, NOT a combined total. `training/load_mechanics.py` labels the unit; `per_hand_kg` is the IDENTITY (no halving — halving on the false "combined" premise corrupted every dumbbell ceiling, e.g. a real 20 lb lateral raise prescribed as 7.5). `e1rm_by_exercise` is Hevy-only. A physically-impossible per-hand dumbbell value (e.g. 150 lb) is a contaminated row to fix at the source, never a combined total to halve. **Rob's max is 105 lb in one hand** (confirmed 2026-07-18). Test it with `exceeds_per_hand_max()`, never against the raw logged weight — it routes through `per_hand_kg`, so the `_LOGGED_AS_COMBINED` lifts (currently just Romanian Deadlift (Dumbbell), where a logged 150 lb is 75/hand) halve first. Migration 0071 compared the raw value and quarantined six legitimate RDL sets; 0072 reverted it. The bound does NOT apply to bilateral lifts, where the logged number is a whole-implement load (Standing Calf Raise at 495 lb is real). Enforced at Hevy ingest, which flags breaching sets as warmups and reports them under `quarantined` on the sync result. Pre-2026 dumbbell history reads as combined totals (maxima are clean 2× doubles) but is deliberately left unquarantined — see 0071; both e1RM and the WORKING WEIGHTS display use a 90d window, so it no longer reaches any live ceiling.
- **ACWR windows are coupled**: the 21-day chronic window `[today-21, today-7)` must match between `metrics._arm_acwr()` (live gate) and `self_learning._historical_weekly_acwr()` (fitting). Test enforces; changing one without the other biases every gate.
- **Deload trigger is not yet personalized**: `calibrate_deload_trigger()` can return `using_population_defaults: True`. Don't treat its output as fitted without checking that flag.
- **Engine contract**: [ENGINE_INVARIANTS.md](ENGINE_INVARIANTS.md) — 6 enforced invariants, tests in `backend/tests/test_engine_invariants.py`. Read before touching `training/` or `metrics.py`.

## Servers

- Always use `dev-restart.sh` to start API + frontend. Never start manually.
- Preview server (when a screenshot is needed): see [feedback_preview_server](~/.claude/projects/-Users-robsavage-Projects-savage-health-center/memory/feedback_preview_server.md).
- API runs on `:8000`, frontend on `:3000`.

## Git

- Conventional commits, push to main directly.
- `git push origin main` — don't ask, this is authorized.
- Never amend commits that have been pushed.

## Where things live

- Architecture/decision history: [DECISIONS.md](DECISIONS.md)
- Per-session learning: `~/.claude/projects/-Users-robsavage-Projects-savage-health-center/memory/`
- Skills: `~/.claude/skills/shc-workout/` for plan generation; `session-debrief` for end-of-session lesson capture.
- Health data sources: see [project_health_profile](~/.claude/projects/-Users-robsavage-Projects-savage-health-center/memory/project_health_profile.md)
