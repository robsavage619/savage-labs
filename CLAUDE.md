# Savage Health Center — Project Conventions

Personal health command center. Single user (Rob). Always push to main directly — no PRs, no feature branches.

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
