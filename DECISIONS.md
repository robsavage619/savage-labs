# SHC Decisions

ADR log for SHC architecture choices. Most recent first. One section per decision.

When adding: include **Context**, **Decision**, **Why**, **Consequences**. Skip the ceremony if it's a small choice — three sentences is fine. The point is that future-you (or Claude) can answer "why did we do it this way?" without re-deriving from code.

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
