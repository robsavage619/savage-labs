# Changelog

All notable changes to this project. Dates are commit dates (Pacific time).

---

## 2026-05-23

### Added

- **Loaded-lift RPE floor at 6** — `save_plan()` now normalizes plans on persist: any loaded exercise (and the session-level target) prescribed below RPE 6 is raised to 6. Hevy's RPE picker only goes 6–10, so a sub-6 target (e.g. a deload set at RPE 5) is unloggable and can't be autoregulated against. Cardio/bodyweight work is left untouched — it isn't RPE-logged in Hevy.

- **Research lab study swap: yoga → heavy lift volume** — Retired the `yoga_hrv_lift` hypothesis (fired ~twice a year, so it never gathered enough exposure days to produce a verdict) and activated `lift_volume_hrv_drop`: a Pearson correlation between a day's strength tonnage and next-morning HRV deviation from the trailing 28-day mean. Runs well-powered on existing Hevy + WHOOP data (n≈180). Migration `0028`, runner `_run_lift_volume_hrv_drop`.

### Fixed

- **After-action RPE comparison ignored Hevy's loggable floor** — The autoregulation read compared logged RPE directly against the plan target with no floor. Since Hevy can't record below RPE 6, every deload set prescribed at RPE 5 was guaranteed to read "harder than planned" and drop the load — a pure artifact. The comparison now clamps the target to a floor of 6; genuine overshoots (RPE 8+) still trigger a drop.

- **HRV baseline dict keyed by string, looked up by date** — `_hrv_baseline_28d()` built its output keyed by `str(date)`, but every consumer looked it up with a `datetime.date` (`d not in baselines`). The check never matched, so every day was skipped and the yoga, two-pickleball, rest-day, rhr-trend, and sleep-quality runners all returned `n=0` ("insufficient"). Keyed by the raw date object — `two_pb_3d_hrv_drop` and the others now produce real verdicts (e.g. two-pickleball-in-3-days → REFUTED, n=145). The earlier index fix had unmasked this; the runners crashed before reaching it.

---

## 2026-05-22

### Added

- **Post-workout retrospective surface** — A dedicated **Post-workout** dashboard section that captures execution feedback after a session instead of regenerating the (unchanged) morning recovery story. New endpoints: `GET /api/workout/retrospective/latest` (latest logged session + stored retrospective + `needs_retrospective` flag) and `POST /api/workout/retrospective` (stores the Claude-written narrative, flags, and vault citations, which feed the next morning's PRESCRIPTION → EXECUTION line). `PostWorkoutPanel` mirrors the health-story copy-prompt flow (Copy CC prompt → paste into Claude Code → POST back → Sync) and renders the narrative above the existing after-action adherence table.

- **Research-grounded retrospectives** — `GET /api/training/after-action` now returns a `## VAULT RESEARCH` block: notes selected server-side from the session's *execution* signals (rep misses → effective-reps/load-selection, RPE overshoot → fatigue-management/SFR, progression → progressive-overload, missing RPE → autoregulation), routed through the same retrieval engine the planner uses. Every adjustment the retrospective recommends is grounded in cited research.

### Fixed

- **HRV column index in lab baseline helper** — `_hrv_baseline_28d()` read the HRV value at tuple index 2, but every caller selects HRV as the second column (index 1). The yoga, two-pickleball, and rest-day runners passed `(date, hrv)` rows and crashed with "tuple index out of range" (surfaced as `n=0` inconclusive); `rhr_trend` passed `(date, hrv, rhr)` and silently averaged RHR as the HRV baseline. Now reads index 1, with all callers consistent on `(date, hrv, …)`.

---

## 2026-05-20

### Added

- **DUPR unofficial API integration** — `sync_rating()` authenticates against `api.dupr.gg` (unofficial mobile/web backend) using email + password stored in macOS Keychain. Fetches `result.stats.doubles` and upserts one snapshot per calendar day into `dupr_snapshots`. Token cached in Keychain; 401/403 triggers automatic re-login. Migration `0026` adds `dupr_snapshots` and `oauth_state` tables.

- **DUPR match history pipeline** — `sync_matches()` paginates `POST /match/v1.0/history/` (limit=25, offset=0 required — API quirk). Extracts pre/post/delta ratings from the team's `preMatchRatingAndImpact` object, per-game scores (G1/G2/G3), partner name, and opponents. Upserted into `dupr_matches` (migration `0027`). New endpoints: `POST /api/pickleball/dupr/sync-matches`, `GET /api/pickleball/matches` (joins `dupr_matches` with `recovery` for WHOOP context on tournament days).

- **2026 Goal Scorecard section** — New `GoalScorecard` component tracking three north-star metrics: DUPR doubles trajectory toward 5.0 (with glowing number, gradient progress bar, embedded latest-tournament context card), key compound e1RM hold-or-climb (per-lift trend with color-coded left borders), and bodyweight concurrent-training target with 4-week trend.

- **Pickleball panel tournament section** — Match history grouped by event date. Per-tournament header shows event name, venue, W/L record, DUPR arc (pre→post), and WHOOP recovery % + HRV for the tournament day. Per-game rows: G-label, WIN/LOSS badge, score, opponents, partner first name, DUPR delta (falls back to `→ post_rating` when delta is null).

- **DUPR wordmark** — Official navy PNG fetched from DUPR's CDN, inverted white via CSS filter, placed in the goal scorecard DUPR block header and inline in the pickleball panel tournament section eyebrow.

- **Test suite** — 117 backend tests added across four new files: `compute_daily_state` end-to-end integration, readiness composite + subscores + e1RM helper, deload / e1RM auto-regulation logic, training-load (ACWR), muscle-group recency, sleep builder, and `workout_sets_dedup` source priority.

- **CI: local pre-push gate** — GitHub Actions CI dropped in favour of a local `pre-push` hook (ruff + pyright + pytest). Keeps the feedback loop fast without needing remote CI on a personal tool.

### Fixed

- **Self-perpetuating deload loop** — Deload flag was derived from the current deload week itself, causing it to always be set once triggered. Fixed by only evaluating the e1RM regression window, not the in-flight deload state.

- **`workout_sets_dedup` column name** — Column is `exercise`, not `exercise_name`; `/training/progression/all` endpoint was referencing the wrong column name.

- **`/training/progression` route shadowing** — `dashboard.py` registered a `GET /training/progression` requiring an `exercise` query param, shadowing `training.py`'s all-exercises version. Resolved by adding `/training/progression/all` as a distinct path.

- **`recovery` table `strain` column** — `GET /pickleball/matches` JOIN referenced a `strain` column that was never in the `recovery` schema; removed.

---

## 2026-05-19

### Added

- **Plain-language clinical signal meanings** — Clinical Research Signals tiles now include an English-phrase interpretation below each computed value (e.g. "SRI 87 — tight circadian rhythm"). Range scales visualise where today's value sits within the clinical spectrum.

- **Section nav + progressive disclosure** — Fixed top nav strip with section anchors (Today, Plan, Signals, Goals, Training, Cardio, Research, Trends). Collapsible sections default to the appropriate open/closed state on first load. Gate-reconciled readiness verdict consolidates all active gate reasons into one plain-English summary card.

---

## 2026-05-18

### Added

- **PMC (Performance Management Chart)** — CTL, ATL, and TSB plotted on a shared axis over a 180-day window. TSB zone bands drawn directly on the chart (Race-Ready, Productive, Fatigued, Overreaching). Replaces the sparkline-only Banister strip.

- **HRV 7-day rolling band** — 7-day EWMA overlaid on the 90-day HRV chart with ±0.5σ guidance band. Visually separates short-term trend from long-term baseline noise.

- **Propranolol β-ADJ badge** — When the morning check-in flags propranolol taken, a `β-ADJ` chip appears on the HRV tile. Signals that the σ-deviation is calculated on the drug-adjusted baseline.

- **Muscle volume panel** — Per-muscle-group set counts for the current mesocycle week vs MEV/MAV/MRV targets. Bars colour-code to target zone (under/in/over). Reads live from `muscle_volume_targets`.

- **Pickleball panel (initial)** — Sport tab in Trend Intelligence: session-count, court-time, and play-freshness KPIs; Play Freshness bar chart (recovery score on court days); Post-play HRV Delta chart (next-morning vs day-of).

### Fixed

- **`workout_sets_dedup` column reference** — Muscle-volume SQL used `ws.exercise_name`; the view's column is `ws.exercise`. Fixed.

- **Pickleball sessions counted as legs stimulus** — Rest-day tracker was not counting pickleball workouts when checking 48h/72h muscle group rest; now treated as lower-body stimulus.

---

## 2026-05-16

### Added

- **WHOOP re-auth button** — When `oauth_state.needs_reauth` is true for WHOOP, the Biometric HUD strip shows a one-click re-authorization button instead of a stale sync warning.

- **Exercise notes + time-based durations** — Hevy workout display now surfaces per-exercise notes (coaching cues synced from the app). Time-based exercises show duration instead of reps×weight.

### Fixed

- **SVG modality icons** — All emoji-based sport/modality icons replaced with inline SVG. No more font-glyph fallbacks on systems without the full emoji set.

- **Planner session-logged-today check** — Was counting any Hevy workout type as "already trained today"; now only counts strength sessions, so a standalone pickleball day doesn't block plan generation.

---

## 2026-05-15

### Added

- **Exercise notes from Hevy** — `GET /api/hevy/workouts` now surfaces per-exercise notes alongside sets. Notes appear as coaching-cue callouts in the After-Action panel.

---

## 2026-05-12

### Added

- **Lab hypothesis rotation** — When a question accumulates 3 consecutive identical confirmed/refuted verdicts with n ≥ 1.5 × min_n, it is automatically retired (`retired_at` set, `enabled` → FALSE) and the next queued hypothesis (lowest `queued_order`) is promoted. The system never runs out of questions to test. Migration `0023` adds `retired_at` and `queued_order` columns to `lab_questions`.

- **Queued hypothesis bank (8 questions)** — Seeded alongside the rotation system; each has a wired runner function in `lab.py`. Questions promote in order: yoga → HRV lift, consecutive training → recovery drop, two pickleball sessions in 3 days → HRV depression, weekly volume spike → recovery correlation, full rest day → HRV rebound, self-reported energy ↔ same-day HRV, 7-day rising RHR → HRV below baseline, low sleep quality → reduced HRV.

- **Lab findings injected into LLM context** — `build_daily_context()` and `build_training_context()` now include a `## YOUR PERSONAL LAB FINDINGS` block with the latest CONFIRMED / REFUTED / INCONCLUSIVE verdict per enabled question, sorted by verdict strength. Every briefing and workout plan is now grounded in Rob's own statistical findings, not just population-level assumptions.

- **Health story format upgrade** — Daily briefings now open with a 3-line metrics header (HRV · WHOOP recovery · RHR · skin temp · ACWR) and a cycle-position line before the prose. Tone tuned for 5am reading: short declarative sentences, conclusions front-loaded, clinical register stripped. Anti-repetition rule added: the header owns the numbers; prose paragraphs own the meaning.

- **`/api/lab/run` response** — Now returns `retired` list of question IDs that were rotated out during the run.

### Fixed

- **`rest_seconds` silently dropped on Hevy push** — `_plan_to_hevy_exercises()` validated `rest_seconds` in the plan schema but never forwarded it to the Hevy routine exercise payload. Fixed.

---

## 2026-05-10

### Added

- **Apple Health Shortcuts ingestion** — `POST /api/apple/shortcut` accepts a native iOS Shortcuts payload (JSON body with typed metric keys). Covers body weight, gait speed, cardio fitness, VO₂max, steps, resting energy, active energy, sleep analysis, stand hours, sound exposure, and respiratory rate. Imperial→SI conversion applied server-side.

- **Apple Health webhook (HAE)** — `POST /api/apple/webhook` endpoint for HealthAutoExport push notifications with Tailscale host allowlist. Registered in the APScheduler job loop alongside the existing WHOOP/Hevy jobs.

- **Tailscale network support** — API now binds to `0.0.0.0` (configurable) so the Tailscale interface can reach it from other devices. Host allowlist in the middleware validates `Host` against a separate allow-list, decoupled from the bind address.

- **WHOOP full V2 API coverage** — Ingests `body_measurement` (height, weight, measured max HR), `whoop_user_profile`, and the full `daily_cycle` (strain, kcal, avg/max HR, score state). HR zone durations (`zone_two_min`–`zone_five_min`) and SpO2 now pulled from the dedicated columns rather than inferred.

- **Slim daily-brief endpoint** — `GET /api/daily/brief` returns a single ~24KB payload replacing the prior multi-endpoint pattern (~293KB across 6+ calls). Combines DailyState, top-5 signal-ranked vault notes, last 7 training sessions, top 20 working weights, full Hevy exercise catalog, and mesocycle state. The `shc-workout` skill fetches context in ~500ms via this endpoint.

- **Concurrent training pickleball signal** — `build_training_context()` now emits `pickleball_focus` (≥60 min/7d) and `concurrent_training` (≥150 min/7d) signals that gate finisher selection and lower-body volume targets per Wilson 2012 / Coffey & Hawley 2017.

### Fixed

- **Respiratory rate backfill** — Implausible RR values (outside 8–30 bpm) from earlier schema iterations cleaned via a targeted WHOOP resync. Migration `0022` applies the clamp to stored rows.

- **`/api/sleep/recent` column reference** — Referenced the dropped `sleep.rhr` column after the schema was normalized; updated to use `recovery.rhr`.

---

## 2026-05-09

### Added

- **Clinical Research Signals panel** — Six peer-reviewed tiles layered above the standard Insights pane, each with a primary citation tooltip: Sleep Regularity Index (Phillips 2017), lnRMSSD rolling mean with 4-week delta (Buchheit 2014), consecutive-red-recovery streak (WHOOP 2022), Allostatic Load composite (Seeman 2001), drug-adjusted HRV (Kemp 2010 / Mølgaard 1991), Z2 HR drift coefficient of variation (Maffetone).

- **Research Lab (initial)** — Pre-registered N-of-1 hypothesis catalogue: 6 standing questions with fixed test types and thresholds to prevent p-hacking. Wired through `GET /api/lab/questions`, `GET /api/lab/findings`, `POST /api/lab/run`. Frontend `LabPanel` renders one verdict-coded card per question.

- **Fueling panel** — `/api/fueling/today` endpoint computes kcal balance (dietary in − active + basal out), protein g/kg vs 1.6–2.2 g/kg hypertrophy band, hydration in oz + sodium, and body composition (weight / BF% / lean mass). Empty-state shows weight-adjusted targets from day one.

- **Periodization strip + Banister CTL/ATL/TSB** — Mesocycle phase strip (current week glows, deload week amber) backed by `ensure_active_mesocycle()`. Banister fitness-fatigue model layered on top: CTL (42d EWMA), ATL (7d EWMA), TSB (form = CTL − ATL) with color-coded zone labels.

- **After-Action autoregulation panel** — Per-exercise actuals vs plan target computed from post-Hevy-sync data. Next-session weight suggestion via Helms 2018 + RP RPE rules: −10% if RPE ≥ target+2, +2.5% if under. Rounded to nearest 2.5 lbs. Read-only — no double-logging.

- **Sleep architecture depth** — 7-night stacked bar now surfaces sleep efficiency %, wakes (disturbance count), and midpoint consistency (σ). Null deep/REM guards added; prior schema stored nulls for some WHOOP sync windows.

- **Vault index system + mesocycle tracking** — `mesocycles` and `muscle_volume_targets` tables added (migration `0017`/`0018`). Vault signals for concurrent training interference, power development, and maximal strength wired into the retrieval scorer.

- **Science-first exercise selection** — Planner enforces Hevy catalog membership before naming any exercise. Habit-bias broken by rotating selection within movement pattern categories.

- **Body diagram per-muscle soreness** — Anatomical body model on the check-in form; clickable regions set per-muscle soreness directly instead of a single global value.

### Fixed

- **Lab runner column names** — `cardio_sessions.modality` (not `sport`), `cardio_sessions.date` (not `started_at`), `daily_cycle.strain` (not `workouts.strain`), `medications.valid_to` (not `expired_at`). Runners rewritten as CTE + LEFT JOIN; `log(0)` guard added.

- **Clinical Research panel** — `kaiser_summary` table never existed; vitals now pulled from `measurements` + `labs` tables.

- **Hevy catalog enforcement** — Exercise selection was referencing non-Hevy names in some edge paths; strict catalog check now gated at validation.

- **Imperial units for skin temp** — `DailyState` now returns skin temp Δ in °F; prior ingest stored Celsius delta.

- **`rest_seconds` in workout prompt** — Vault-aware prompt now includes coaching-cue rest times sourced from the plan schema.

---

## 2026-05-08

### Added

- **Rebrand: Savage Health Center → Savage Labs** — App name, wordmark, and all internal references updated. WHOOP Obsidian wordmarks applied to vault-sourced UI surfaces.

- **Ambient state-reactive background** — Page hue shifts with readiness tier (greenish at GREEN, reddish at RED, neutral at YELLOW). `oklch` color space ensures perceptual uniformity across hues.

- **Mission-control clock** — Orbitron live clock with seconds tick and date eyebrow in the command bar dead space.

- **Anatomical check-in body model** — `react-body-highlighter` integration replaces the global soreness slider. Clickable anterior/posterior muscle map writes per-muscle soreness to `daily_checkin`.

- **Biometric HUD strip** — Always-on header bar showing live WHOOP/Hevy sync status, today's key vitals, and data freshness per source.

- **Security hardening** — CORS locked to `localhost:3000`; personal clinical context moved from source into a gitignored runtime file loaded at startup; DuckDB key validated at boot; Anthropic SDK + chat advisor removed (all AI is now clipboard-driven via the skill workflow).

- **WHOOP SPO2, full sleep stages, daily cycle** — Extended WHOOP ingest to capture SpO2, SWS/REM/light/awake minutes, efficiency, disturbances, respiratory rate, sleep cycles, and daily cycle strain.

### Fixed

- **WHOOP OAuth error handling** — `needs_reauth` flag now only set on auth-class failures (401/403), not transient network errors. Prevents spurious reauth banners.

- **Body weight trend** — Daily check-in weights now included alongside Apple Health smart-scale readings in the weight chart.

- **Skin-temp illness gate direction** — Gate previously fired when skin temp was *below* baseline; corrected to fire when Δ is positive (elevated = illness sentinel).

---

## 2026-05-04 — 2026-05-05

### Added

- **Check-in notes field + date override** — Allows back-filling illness or travel days with context from the past; surfaced on the morning check-in form.

- **Health story personal trainer tone** — `STORY_PROMPT` rewritten: direct address, conclusions first, no hedging. Full workout plan schema injected into the prompt to let Claude reference it when explaining the brief.

- **Futuristic gradient pass** — Page bloom, card sheen, and hero glow applied via Tailwind `oklch` gradient utilities. Scatter/bar tooltips made legible on dark surfaces.

---

## 2026-05-01 — 2026-05-02

### Added

- **Cardio weekly zone-stacked volume + pickleball HR efficiency** — Zone-stacked bar chart (Z0–Z5) per week over 28 days. Separate pickleball HR efficiency tile (avg HR in session vs 28d cardio baseline).

- **launchd sync agent** — `com.savage-labs.sync.plist` runs WHOOP + Hevy + adherence jobs 4× per day without the API server running. Registered at `/Library/LaunchAgents/`.

- **e1RM trajectory sparklines** — Per-exercise Epley 1RM sparklines rendered in the dead space below the weekly volume chart in the Strength panel.

- **Qualitative + paneled lab results** — Clinical panel now renders lab values with reference ranges, abnormal flags, and trend arrows. Qualitative results (e.g. "Reactive" / "Non-reactive") supported alongside numeric.

- **WHOOP as authoritative cardio source** — Apple Health workout import removed; WHOOP `workout_activities` mirrored into `cardio_sessions` as the single source of truth.

- **Workout planning when today already logged** — Planner now targets the *next* session when a workout has already been recorded today.

---

## 2026-04-29

### Added

- **WhoopVitals card** — Premium dark-gradient card (linear-gradient with subtle oklch blue shift) anchored to the official WHOOP wordmark SVG. Four-up KPI strip in Orbitron: Recovery score/100 with σ-colored glow, Strain as cardio min/wk, Sleep hours color-coded (≥7.5h green, ≥6.5h yellow, <6.5h red), and HRV σ deviation from 28d baseline. Live sync-status chip flags last sync time or OAuth reauth. Beta-blocker days annotated `β-adj` on HRV tile. "How to read this" footer covers all four metrics.

- **Orbitron typography system** — Consistent application of Orbitron across the entire UI: all section eyebrows (`.eyebrow`), section titles (`.shc-section-title`), metric numerals (`.metric-xl/lg/md`), tab switchers, and KPI labels. Adds `SectionTitle` and `HowToRead` components to `ui/metric.tsx`.

- **Clinical timeline** — Replaced the three-card clinical overview (conditions list, medications list, labs list) with a unified descending-date event lane. Color-coded dots by event type (medication = chart-line blue, condition = neutral, lab = positive green). Merges all event types into a single scannable clinical narrative.

- **Cardio trend KPIs** — `TrendKpi` sub-component: Orbitron number + directional delta badge comparing last 14 days vs prior 14 days. Four KPIs above the session log: cardio min/wk, avg HR, avg RPE, kcal/wk. Directional arrows and colors (positive/neutral/negative) match the same threshold system as recovery metrics.

- **Cardio table truncation** — Session log defaults to 8 most-recent rows; "Show all" toggle reveals the full history. Keeps the log form accessible without infinite scroll.

- **PulseCard in right rail** — Replaces the empty space at the top of the 320px right column with a readiness orb (Orbitron score, radial oklch glow, tier-colored), plain-language tier interpretation, and a 2-col sync-age footer for WHOOP and Hevy. Fills dead space with signal-rich content.

- **Sleep panel improvements** — Per-night rows now show `wk md` date format (e.g. "Fri 4/25"). Footer row adds 7d sleep debt in hours alongside best-night date and deep%. Interpretation copy covers target bands (7.5h, 15–20% deep, 20–25% REM, consistency < 1.0σ, debt > 5h flag).

- **Patterns pane helptext** — Added interpretation paragraph before scatter charts explaining how to read sleep-vs-recovery and HRV-vs-recovery correlations.

- **Correlation cards empty state** — Richer empty state: shows days collected, days remaining to unlock, and three actionable tips (check-in regularly, maintain consistent sleep, log cardio). When data is present, adds helptext on how to interpret Pearson-r and confidence ranges.

- **Trend Intelligence tab redesign** — Section header upgraded from `Eyebrow` to `shc-section-title`. Tab switcher replaced with a pill-style framed container (`oklch(1 0 0 / 0.025)` background, hairline border); each tab uses Orbitron uppercase with `tracking-[0.16em]`.

- **Analysis persistence and WHOOP sync counts** — Vault analysis results persist across app restarts; WHOOP background sync now logs ingested record counts per run.

- **Vault signal coverage** — New vault signals for body recomposition (strength gain vs weight delta), push/pull imbalance, and 4-week volume spikes.

### Fixed

- **Cooldown object array crash** — Workout renderer no longer crashes when the cooldown field is an object instead of an array.

- **Block label undefined crash** — Guard for undefined block labels in workout plan renderer; validates block/exercise field names before rendering.

- **DuckDB WAL path mismatch** — Prevents startup crash when WAL file path doesn't match the DB path after a directory move.

---

## 2026-04-24

### Added

- **Hevy integration — full push/pull** — Sync workouts from Hevy into DuckDB (`GET /api/hevy/sync`), refresh exercise template cache (`GET /api/hevy/sync-templates`), push AI plan as a Hevy routine (`POST /api/hevy/push-routine`). Hevy API key stored in macOS Keychain with env fallback.

- **Cardio & Sports panel** — 28-day summary card: session count, total minutes, top sport, zone-mix bar. Manual log form (sport, duration, avg HR, RPE) with hover-to-delete. Supports pickleball, cycling, rowing, ski-erg, walking, elliptical, and swimming.

- **Workout plan redesign** — Replaced flat table with `ExerciseBlock` card grid. Cards show sets×reps + weight, RPE badge, last-session history stamp with delta. Block section headers with colored accent bars. Auto-detected superset pills. Source badge (Claude Code / Claude / fallback). "Generate via Claude" and "Copy CC prompt" buttons.

- **Progression drawer** — Slide-in panel per exercise: Epley 1RM chart (est vs max lbs) over 30 sessions, full session table (date, top set, volume, RPE, est 1RM). Opens from PR rows, top-exercise rows, and plan exercise cards.

- **Beta-blocker-aware readiness** (`lib/readiness.ts`) — Single source of truth for composite readiness. Detects propranolol/metoprolol/etc. from medications list and shifts weights: HRV 20% / Sleep 40% / RHR 25% / Subj 15% vs default 40/30/20/10. Sigma-based HRV scoring replaces old saturation hack.

- **Workout AI endpoints** — `POST /api/workout/generate` (Claude Opus 4.7 with full clinical context), `DELETE /api/workout/plan`, `GET /api/training/muscle-balance`, `GET /api/training/exercise-last`, `GET /api/cardio/recent`, `POST /api/cardio/log`, `DELETE /api/cardio/log/{id}`.

- **`shc-workout` Claude Code skill** — Mode A (generate): pulls context, applies GREEN/YELLOW/RED intensity matrix, picks real exercises, POSTs validated JSON plan. Mode B (analyze): read-only prose with cited numbers. Includes skin-temp veto, sleep veto, push:pull bias, no-plyometrics rule.

- **Training context enrichment** — `build_training_context()` now includes 28d cardio mix, push:pull balance, skin temp delta, and goals block.

### Fixed

- **Hevy weight round-trip** — `lbs → kg` conversion now uses 4 decimal places instead of 2. Prevents `85 lbs → 38.56 kg → 85.01 lbs` display artifact in the Hevy mobile app.

- **Hevy `rpe` rejection** — Hevy's `POST /routines` schema rejects `rpe` on set objects. RPE is now folded into exercise notes (`"RPE 7 · Superset with previous"`).

- **Hevy `folder_id` on PUT** — `PUT /routines/{id}` rejects `folder_id`; it is now only sent on the initial `POST`.

- **Hevy list-wrapped response** — `_extract_routine_id()` now handles `{"routine": [{"id": "..."}]}` list-wrapped shape in addition to flat dict and top-level list.

- **Hevy API key from Keychain** — Key is loaded via `keyring` with `HEVY_API_KEY` env var as fallback.

- **Migration version conflict** — Renamed `0002_hevy.sql` → `0006_hevy.sql` to avoid collision with existing WHOOP migration.

---

## 2026-04-22

### Fixed

- **StrengthPanel null guards** (`41b91da`) — Guard `volume_kg` and `total_sets` fields against null before rendering; prevents chart crash when no training data is present for the selected window.

### Added

- **V2 dashboard + AI next-workout coach** (`01ad062`) — Full V2 dashboard layout with all five zones wired: Command Briefing strip, four Pillars (Recovery, Sleep, Training Load, Readiness), Trend Intelligence tabs, Right Rail, and AI Advisor chat sheet (Cmd+K). Next-workout endpoint calls Claude Sonnet 4.6 with clinical context and caches the response.

- **AI-powered next workout tab** (`94cce6b`) — Initial `next-workout.tsx` component with readiness-tier display (green/yellow/red), exercise blocks, RPE targets, warmup/cooldown sections, and clinical disclaimer notes.

---

## 2026-04-21

### Added

- **Real training, insights, and clinical data** (`9f23a8e`) — Wired production data into the dashboard: training heatmap, weekly volume, PRs, overload signal, correlation insights, clinical overview (meds, conditions, labs), and body-weight trend. All backed by live DuckDB queries.

- **Session-token auth layer** (`010bc73`) — Local PHI protection: dashboard requires a session token issued at startup. Prevents casual access to health data on shared machines.

- **P1 baseline snapshot** (`b858655`) — Committed working P1 state as the v2 baseline. Three-card layout: recovery ring, HRV trend, sleep stacked bars.

- **P1 skeleton** (`13d31b9`) — Initial project scaffold: FastAPI backend, DuckDB schema (migrations 0001–0005), WHOOP OAuth client, Apple Health CCDA XML ingest, Next.js 15 frontend with shadcn/ui, TanStack Query, Recharts, and synthetic data seeder (90 days).

---

## 2026-04-21 (project start)

- **Initial commit** (`a2f1eed`) — Repository initialised.

---

_Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Versions are date-based (no semver) since this is a single-user tool with no public API contract._
