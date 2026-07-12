# Savage Labs — Project Conventions

Personal health intelligence platform. Single user (Rob). Always push to main directly — no PRs, no feature branches.

## Pre-flight (every session, before previewing or claiming results)

1. `git fetch origin && git log HEAD..origin/main --oneline` — if any commits, the worktree is stale.
2. If stale: `git stash && git merge origin/main && git stash pop` (or `git stash drop` if conflict-free).
3. Spot-check `frontend/app/page.tsx` and `frontend/app/layout.tsx` against the main repo before screenshotting — they're the most-edited files and the ones Rob can see.

## Architecture invariants

- **DailyState is the single source of truth** for readiness, HRV, sleep, training-load, beta-blocker gate. Frontend reads `/api/state/today`. Never recompute these client-side.
- **Beta-blocker gate** lives in `DailyStateGates` (`hr_zone_shift_bpm`, `kcal_multiplier`). Components consume; they don't infer from medications list.
- **HRmax = Tanaka** (208 − 0.7 × age), not 220 − age. Applied in `cardio-panel.tsx`.
- **Migrations**: numeric prefix `NNNN_<name>.sql`. Two files with the same prefix → silently skipped. Always check the highest applied version before adding.
- **Apple Health XML**: `<Workout>` elements → `cardio_sessions`; `<Record>` elements → metrics. Strength/flexibility workout types skipped (handled by Hevy).
- **Load semantics are per-hand**: Hevy logs dumbbell/cable lifts as the per-hand (single-implement) weight — the logged number IS the per-hand load, NOT a combined total. `training/load_mechanics.py` labels the unit; `per_hand_kg` is the IDENTITY (no halving — halving on the false "combined" premise corrupted every dumbbell ceiling, e.g. a real 20 lb lateral raise prescribed as 7.5). `e1rm_by_exercise` is Hevy-only. A physically-impossible per-hand dumbbell value (e.g. 150 lb) is a contaminated row to fix at the source, never a combined total to halve.
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
