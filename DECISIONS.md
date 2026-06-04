# Savage Labs — Decisions

ADR log for architecture choices. Most recent first. One section per decision.

When adding: include **Context**, **Decision**, **Why**, **Consequences**. Skip the ceremony if it's a small choice — three sentences is fine. The point is that future-you (or Claude) can answer "why did we do it this way?" without re-deriving from code.

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
