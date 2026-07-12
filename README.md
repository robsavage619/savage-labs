<div align="center">

<img src="images/banner.png" width="100%" />

<br />

<table>
<tr>
<td>

[![Python](https://img.shields.io/badge/Python-3.12-1e1e2e?style=for-the-badge&logo=python&logoColor=cba6f7&labelColor=1e1e2e&color=cba6f7)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-1e1e2e?style=for-the-badge&logo=fastapi&logoColor=a6e3a1&labelColor=1e1e2e&color=a6e3a1)](https://fastapi.tiangolo.com/)
[![DuckDB](https://img.shields.io/badge/DuckDB-1.1-1e1e2e?style=for-the-badge&logo=duckdb&logoColor=fab387&labelColor=1e1e2e&color=fab387)](https://duckdb.org/)

</td>
<td>

[![Next.js](https://img.shields.io/badge/Next.js-15-1e1e2e?style=for-the-badge&logo=next.js&logoColor=89b4fa&labelColor=1e1e2e&color=89b4fa)](https://nextjs.org/)
[![React](https://img.shields.io/badge/React-19-1e1e2e?style=for-the-badge&logo=react&logoColor=74c7ec&labelColor=1e1e2e&color=74c7ec)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5-1e1e2e?style=for-the-badge&logo=typescript&logoColor=89dceb&labelColor=1e1e2e&color=89dceb)](https://www.typescriptlang.org/)

</td>
<td>

[![Claude](https://img.shields.io/badge/Claude-Opus_4.8-1e1e2e?style=for-the-badge&logo=anthropic&logoColor=f5c2e7&labelColor=1e1e2e&color=f5c2e7)](https://anthropic.com/)
[![Obsidian](https://img.shields.io/badge/Obsidian-RAG-1e1e2e?style=for-the-badge&logo=obsidian&logoColor=cba6f7&labelColor=1e1e2e&color=cba6f7)](https://obsidian.md/)
[![License](https://img.shields.io/badge/License-MIT-1e1e2e?style=for-the-badge&labelColor=1e1e2e&color=a6e3a1)](LICENSE)

</td>
</tr>
</table>

<br />

</div>

---

## Why I Built This

I wear a WHOOP. I track every lift in Hevy. I get labs done regularly and export everything from Apple Health. I have a lot of data about myself — and for a long time, none of it talked to any of the rest of it.

WHOOP would tell me my recovery score without knowing I'd taken a beta-blocker that morning, which suppresses heart rate and makes the score meaningless. My workout app had no idea how I slept. Apple Health was a black hole of numbers I never looked at. And when I asked any AI assistant about my training, I had to re-explain my full situation from scratch every single time.

I got frustrated enough to build something. Savage Labs pulls every data stream I have into one place, fuses them into a single daily readiness signal, and gives me an AI that already knows my full picture before I say a word. I open it in the morning, see a green/yellow/red, read a one-paragraph brief, and know exactly what to do that day.

It runs entirely on my machine. Nothing goes to a cloud. It was never meant to be a product — it's just a tool I use every day.

---

## The Interesting Engineering Bits

It'd be easy to build a dashboard that shows you your WHOOP score and calls it done. The parts I'm actually proud of are the ones that required real thought:

> **Computing derived signals instead of displaying raw ones.**
> Raw HRV in milliseconds is nearly meaningless day-to-day — my baseline is mine, not the population's, and it shifts when I'm on medication. So instead of showing a number, I compute a σ-deviation from a rolling 28-day mean. Same idea with training load: instead of counting sessions, I compute a true Gabbett ACWR from fused wearable strain and lifting tonnage. These derived signals actually make decisions. The raw ones just inform anxiety.

> **Giving Claude my full clinical context on every call.**
> I don't just send today's metrics to the model. I send the metrics *plus* my active medications with dosing schedules, current diagnoses, recent labs with reference ranges, and a set of hard constraints it has to respect. That's what makes the difference between a generic wellness bot and something that actually understands my situation.

> **Keeping the AI honest with deterministic gates.**
> Claude generates the workout plan. A separate validation layer enforces it. If the model writes a heavy leg day but my logs show I trained legs 30 hours ago, the plan gets rejected and regenerated — not adjusted, not warned, *rejected*. The LLM is for reasoning. The gate engine is for correctness. I don't want the model to be able to talk itself into ignoring recovery rules.

> **One computation feeding everything.**
> All metrics flow through a single `DailyState` dataclass computed once per request. The dashboard reads it, the AI briefing gets injected with it, the workout planner extracts gates from it. Nothing recomputes what something else already owns.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         DATA SOURCES                            │
│  WHOOP OAuth  │  Apple Health XML  │  Hevy API  │  Check-in    │
│                      DUPR api.dupr.gg                           │
└───────┬───────┴────────┬───────────┴──────┬─────┴──────┬───────┘
        │                │                  │            │
        ▼                ▼                  ▼            ▼
┌─────────────────────────────────────────────────────────────────┐
│                    INGESTION LAYER                              │
│   OAuth token refresh  │  CCDA/lxml XML parse  │  REST client  │
│   APScheduler jobs     │  Content-hash dedup   │  Pydantic DTOs│
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       DuckDB (encrypted)                        │
│  measurements  │  workouts  │  workout_sets  │  sleep           │
│  recovery      │  cardio    │  daily_checkin │  medications     │
│  conditions    │  labs      │  daily_cycle    │  workout_plans  │
│  mesocycles    │  muscle_volume_targets       │  lab_questions  │
│  lab_findings  │  workout_retrospectives      │  working_weights│
│  dupr_snapshots│  dupr_matches                │  oauth_state    │
│                                                                 │
│  Views: v_hrv_baseline_28d, v_session_load, v_daily_load        │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      METRICS ENGINE                             │
│                  compute_daily_state()                          │
│                                                                 │
│  HRV σ-deviation  │  True ACWR  │  Sleep composite              │
│  Readiness score  │  Gates      │  Epley e1RM                   │
│  Push:pull ratio  │  Zone calc  │  Regression detection         │
│  Sleep arch.      │  Banister CTL/ATL/TSB │ Mesocycle phase     │
│  After-action     │  Fueling balance      │ Allostatic load     │
│  SRI · lnRMSSD    │  Drug-adjusted HRV    │ N-of-1 lab runners  │
│  RR sentinel      │  WHOOP-measured HRmax │ Pickleball volume   │
│  Concurrent-load signal       │  Percent-recorded filter        │
└──────────┬────────────────────────────────┬─────────────────────┘
           │                                │
           ▼                                ▼
┌──────────────────────┐      ┌─────────────────────────────────┐
│    FastAPI REST       │      │         AI LAYER                │
│    60+ endpoints      │      │                                 │
│                       │      │  build_daily_context()          │
│  /api/state/today     │      │  build_training_context()       │
│  /api/daily/brief     │      │  build_clinical_context()       │
│  /api/workout/*       │      │  load_vault_research()          │
│  /api/training/*      ├──────┤                                 │
│  /api/training/load-curve    │  Claude Opus 4.7                │
│  /api/training/after-action  │  → validate_plan()              │
│  /api/training/mesocycle     │  → Ollama fallback (air-gapped) │
│  /api/clinical-research/*                                      │
│  /api/lab/{questions,findings,run}                             │
│  /api/fueling/{today,trend}                                    │
│  /api/chat · /api/briefing · /api/insights                     │
│  /api/hevy/push · /api/vault/search                            │
└──────────┬────────────┘      └─────────────────────────────────┘
           │
           ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Next.js 15 + React 19                        │
│                                                                 │
│  TanStack Query v5  │  Recharts  │  Tailwind v4 (OKLCH)        │
│  shadcn/ui          │  Motion    │  Orbitron + Geist fonts      │
│                                                                 │
│  Command Briefing  │  Four Pillars  │  Trend Intelligence       │
│  Workout Planner   │  AI Advisor    │  Clinical Overview        │
│  Periodization Strip · After-Action · Fueling Panel             │
│  Clinical Research Signals · Research Lab (N-of-1)              │
└─────────────────────────────────────────────────────────────────┘
```

---

## How It Works — The Technical Detail

### `DailyState` — One Contract for Everything

Everything flows through a single typed dataclass computed once per request. The dashboard reads it, the AI gets it injected, the workout planner pulls gates from it. I added this after realizing I had the same metric being computed three different ways in three different places and getting three slightly different answers.

```python
@dataclass
class DailyState:
    as_of: str
    recovery: RecoveryMetrics      # WHOOP score, HRV ms, RHR, skin temp, SpO2, RR delta
    sleep: SleepMetrics            # duration, deep%, REM%, SpO2, debt, cycles, efficiency,
                                   # disturbances, respiratory_rate, sleep_need attribution
    training_load: TrainingLoadMetrics  # ACWR, acute/chronic, muscle group rest,
                                        # max_hr_measured, zone_min_7d, pickleball_min_7d/28d
    checkin: CheckinMetrics        # energy, stress, soreness, medication flag
    readiness: ReadinessSnapshot   # composite score, tier, component weights
    gates: AutoRegGates            # deterministic intensity constraints (20 rules)
    freshness: DataFreshness       # staleness flags per source
```

---

### HRV σ-Deviation

I'm on an SSRI and occasionally take a beta-blocker, both of which suppress HRV. Comparing my absolute HRV to a population norm or even my own old baseline would tell me nothing useful. What actually matters is how today compares to my recent self, medication-adjusted.

So I compute a 28-day rolling mean and standard deviation and express today as a σ-deviation:

```
hrv_sigma = (today_hrv_ms − 28d_mean) / 28d_stdev
subscore  = clamp(50 + sigma × 25, 0, 100)
```

| σ value | Interpretation | Score |
|---|---|---|
| `+2.0` | Peak recovery | 100 |
| `0.0` | Baseline | 50 |
| `−2.0` | Suppressed | 0 |

The baseline shifts when my medications shift. The deviation still means something.

---

### True Gabbett ACWR

Most training apps track session count. I wanted to know whether my actual workload — cardiovascular *and* mechanical — was in the danger zone for injury or overtraining.

WHOOP gives me strain (cardiovascular load). Hevy gives me tonnage (mechanical load). I fuse them into a composite and compute the true Gabbett acute:chronic workload ratio:

```
composite_load_day = whoop_strain + (hevy_tonnes × 5000)

acute_7d    = mean(composite_load, last 7 days)
chronic_28d = mean(composite_load, last 28 days)
acwr        = acute_7d / chronic_28d
```

| ACWR | Zone | What happens |
|---|---|---|
| `< 0.8` | Under-loaded | Not enough stimulus |
| `0.8 – 1.3` | ✅ Safe zone | Adapt and grow |
| `1.3 – 1.5` | ⚠️ Elevated risk | Volume gate fires |
| `> 1.5` | 🚨 Overload | Rest mandated |

---

### Readiness Score That Knows About My Medications

The readiness composite weight vector isn't fixed. On days when I've taken a beta-blocker, HRV becomes a less reliable signal (the drug suppresses it pharmacologically), so the weights shift:

| Signal | Normal day | Beta-blocker day | Why |
|---|---|---|---|
| HRV σ | **40%** | 20% | Pharmacologically suppressed |
| Sleep | 30% | **40%** | Better recovery indicator that day |
| RHR | 20% | **25%** | Relative changes still meaningful |
| Subjective | 10% | 15% | |

Detection is dual-gated — the medications table needs an active entry *and* the morning check-in must flag it taken. Belt and suspenders, because I didn't want a stale medication record silently shifting my readiness score.

**Tiers:** ≥67 → 🟢 GREEN · 34–66 → 🟡 YELLOW · <34 → 🔴 RED

---

### The Gate Engine

This was probably the most important design decision. Claude generates a workout plan. Before it gets shown to me, a separate deterministic layer validates it against 20 hard rules derived from physiology research. If anything fails, the plan gets rejected and Claude is called again — with the violations explained.

```python
@dataclass
class AutoRegGates:
    max_intensity: Literal["high", "moderate", "low", "rest"]
    forbid_muscle_groups: list[str]       # e.g. ["legs"] if <48h rest
    deload_required: bool
    deload_reason: str | None
    hr_zone_shift_bpm: int               # beta-blocker: -20
    kcal_multiplier: float               # beta-blocker: 1.25
    e1rm_regression_4wk_pct: float | None
    reasons: list[str]                   # human-readable rule trace
```

<details>
<summary>All 20 gate rules</summary>

| Condition | Gate |
|---|---|
| ACWR > 1.5 | `max_intensity = "rest"` |
| Skin temp Δ ≥ 0.5°C | Z2 only — possible illness |
| Muscle group < 48h (72h compound legs) | Group forbidden |
| Compound soreness ≥ 2 muscles at severity 2 | Cap to moderate |
| e1RM regression > 3% over 4 weeks | `deload_required = True` |
| Beta-blocker dosed | HR zones −20 bpm, kcal ×1.25 |
| ACWR > 1.3 | Cap to moderate |
| Readiness RED | Cap to low |
| Illness flag | Rest day |
| Travel flag | Cap to moderate |
| Sleep < 5h | No PR attempts |
| Acute soreness ≥ 3 on muscle | Group forbidden |
| HRV σ < −1.5 | Cap to low |
| SpO₂ < 94% overnight | Cap to low — hypoxia recovery flag |
| User-calibrating flag | Gates suppressed — not enough baseline |
| Respiratory rate Δ ≥ +1 bpm above 28d median | Illness sentinel (Bourdillon/Nicolò) |
| Sleep cycles < 3 | No compound primary at GREEN intensity |
| Sleep efficiency < 70% | Cap to moderate |
| Sleep disturbances ≥ 8 | Cap to moderate |
| WHOOP performance score < 33 | Cap to low |

</details>

The AI gives me good plans. The gates make sure they're safe.

---

### Injecting Clinical Context Into Every AI Call

Every time I call Claude — for a workout plan, a daily briefing, or a chat — it gets my full clinical picture assembled from the live database:

```
MEDICATIONS (active)
• [Medication] [dose] [frequency] — since [date]
...

CONDITIONS
• [Condition] (active, onset [date])
...

RECENT LABS (last 20, with ref ranges)
• [Analyte]: [value] [unit] [ref range] — [date]
...
```

On top of that, the system prompt encodes drug-class interpretation rules — what SSRIs do to HRV, what beta-blockers do to heart rate zones, what inhaled corticosteroids flag for. Claude doesn't have to figure out my situation from general pharmacology knowledge; I tell it exactly what's relevant.

---

### Self-Learning Hypertrophy Engine

The training controller doesn't use population defaults for long. Every nightly job builds a personal model of how Rob's body responds to volume — fitting parameters directly from his logged history, replacing generic RP landmarks with empirical ones.

**What it fits:**

| Parameter | Population default | Personal (fitted) | How |
|---|---|---|---|
| Biceps MEV | 8 sets | 11 sets | P20 of productive weeks |
| Biceps MRV | 20 sets | 20 sets | P80 of productive weeks |
| ACWR rest threshold | 2.0 | 2.02 | P90 of historical resistance ratios |
| ACWR low threshold | 1.8 | 1.48 | P80 of historical resistance ratios |
| ACWR mod threshold | 1.5 | 1.22 | P65 of historical resistance ratios |

**The scoring pipeline** (runs nightly + on-demand):

```
backfill_exercise_map()        → classify unmapped exercises → muscle
backfill_weekly_e1rm()         → e1RM + tonnage for every (exercise, week)
backfill_perf_scores()         → OLS trend → Israetel 1–5 score per week
regrade_stalled_with_tonnage() → upgrade flat e1RM + rising tonnage → 4
fit_volume_landmarks()         → P20/P80 of productive weeks → MEV/MRV
fit_acwr_bands()               → P65/P80/P90 of 369 historical weeks
materialize_signal_quality()   → scored_weeks × stability → confidence
record_prescription()          → log this week's calls
score_prescription_outcomes()  → grade logged calls 3 weeks later
```

**Confidence quantification.** Each muscle prescription carries a `confidence` score (0–1) derived from two signals: scored-week count (sample size) and signal stability (fraction of consecutive weeks where trend doesn't flip dramatically). Biceps at 315 scored weeks scores 0.68; lower back at 10 weeks scores 0.28. The planner context block surfaces these so Claude knows when to trust the data versus hedge.

**Retroactive validation.** The engine backtests itself: for 1,844 consecutive (week_W, week_W+1) perf-score pairs across 16 muscles, it evaluates whether the implied prediction held. Overall accuracy: 86%. Per-muscle scores are surfaced at `GET /api/training/self-learning/status`.

**Session split.** The weekly set prescription is distributed across four sessions (Upper-A Tue / Lower-A Wed / Upper-B Thu / Lower-B Fri) with ≤10 sets per muscle per session — the RP hypertrophy threshold for a single training stimulus.

**Protein gate.** When `protein_grams` is logged in the daily check-in and has been consistently below 80% of the 239g target for ≥4 of the last 7 days, volume-increase prescriptions for non-emphasis muscles are held. Adding sets when substrate is inadequate produces fatigue, not growth.

**What it's honest about.** Muscles that have never been pushed above 50% of their population MRV are flagged `undertrained` — the system is measuring training habit, not physiology. Their fitted MRV is floored at 50% of population so the prescription pushes exploration rather than locking in a low ceiling. The API surfaces which muscles have robust personal fits vs which are still on population defaults.

---

### Exercise Intelligence — Per-Hand Loads, Muscle Heads, One Canonical Model

A prescription once told me to hammer-curl 95 lbs *in each hand* — a weight I've never touched. It was a units bug, and chasing it exposed a whole layer worth getting right.

**Per-hand load semantics.** I log a dumbbell lift as the combined weight of both bells, but I *pick up* — and should be prescribed — one bell. The engine was reading the combined number as the per-hand load, so a per-hand target got validated against a total-load estimated-1RM. A small load-mechanics classifier now tags every movement (dumbbell pair, cable crossover, single-arm, barbell, machine) and normalizes the e1RM, the load ceiling, and the prescription to per-hand — with a median/MAD guard so one fat-fingered set can't inflate the ceiling. That one fix dropped the hammer-curl ceiling from a level that permitted 95 lb/hand to ~47.

**Muscle heads, not just muscle groups.** "Biceps" isn't specific enough to program well — the long head, short head, and brachialis grow from different exercises and joint positions. The engine credits each working set to the specific head an exercise trains (a hammer curl hits `biceps/brachialis` *and* `forearms/brachioradialis`, not just "biceps"), tracks per-head volume across the week, and leads exercise selection with the least-trained head — then rotates among equal-quality options instead of prescribing the same movement every week. Each pick is grounded in a cited study.

**One canonical model instead of two.** The crediting data and the head/length/science data lived in two separate tables, keyed the same way but free to disagree about which muscles a movement trains — which is exactly how a wrist curl ended up crediting biceps. I merged them into a single `exercise_muscle` row per (exercise, muscle) that carries both the volume credit *and* the anatomy, so the two can never drift apart. The migration used expand-contract: the old table names became views over the new table, so every reader kept working untouched — verified byte-identical on real data before cutting over.

---

### e1RM Tracking & Fatigue Detection

Every set goes in with weight and reps. I compute estimated 1RM via the Epley formula:

```
e1RM = weight_kg × (1 + reps / 30)
```

Then I run a 4-week regression detector — if my top-percentile e1RM has dropped more than 3% over the last 56 days, I'm accumulating fatigue and a deload gets flagged before I actually get hurt:

```
regression_pct = (mean(e1RM, days 0–27) − mean(e1RM, days 28–55))
               / mean(e1RM, days 28–55)
```

---

### Data Ingestion

Four sources, one database. Every record gets a content hash so syncs are always idempotent — I can re-run them without fear of double-counting.

| Source | How it gets in | What I get |
|---|---|---|
| **WHOOP** | OAuth 2.0, syncs every 60 min | Recovery, HRV, RHR, sleep stages (cycles, efficiency, disturbances, respiratory rate), strain, SpO2, skin temp, HR zone durations, body measurements (measured max HR), user profile |
| **Apple Health** | iCloud HealthAutoExport → CCDA XML parse | Everything — steps, HR, weight, glucose, blood pressure, sleep |
| **Hevy** | REST API | Every lift, every set, every rep, back to 2015 |
| **DUPR** | Unofficial `api.dupr.gg` backend (email/password, Keychain-stored) | Doubles + singles rating snapshots daily; full match history (scores, partners, opponents, pre/post/delta per match) |
| **Morning check-in** | Dashboard form I fill out daily | Energy, stress, soreness, body weight, medication flags |

```python
content_hash = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
```

OAuth tokens live in macOS Keychain. The database is encrypted at rest. Nothing touches disk unencrypted.

---

### HR Zones That Account for Medication and Measured Physiology

HR zone boundaries now use **WHOOP-measured max HR** when available, falling back to the Tanaka formula:

```
HRmax (measured)  = body_measurement.max_heart_rate   # e.g. 183 bpm (WHOOP)
HRmax (Tanaka)    = 208 − (0.7 × age)                 # e.g. 180 bpm — fallback only
adjusted_HRmax    = HRmax − hr_zone_shift_bpm          # −20 on beta-blocker days
```

On days I take a beta-blocker, my HR peaks lower. Without this adjustment, every cardio session would look like it was in a higher zone than it actually was. The gate engine injects the shift automatically.

**Zone durations** also use WHOOP's authoritative `zone_two_min` through `zone_five_min` columns (synced per workout) instead of inferring zones from average HR. The cardio panel shows the actual distribution pulled from WHOOP's zone breakdown.

---

## Sports-Science Layer

Once the daily-readiness loop was solid, the next push was treating Savage Labs as an actual sports-science platform — not just a wearable dashboard. Seven additions, each anchored to peer-reviewed methodology.

### Sleep Architecture — Beyond Total Hours

Total sleep duration is the noisiest possible single metric. The dashboard surfaces six dimensions every morning, each pulled from the dedicated columns the WHOOP V2 ingest writes (no JSON parsing in the hot path):

| Field | What it tells me | Reference |
|---|---|---|
| **Deep %** | N3 / slow-wave — physical recovery + GH release. Target 15-25%. | Walker 2017 |
| **REM %** | Motor learning + emotional regulation. Target 20-28%. | Walker 2017 |
| **Efficiency %** | Time asleep / time in bed. >85% = good. | Watson AASM 2015 |
| **Wakes** | Whoop disturbance count — fragmented sleep marker. | — |
| **Midpoint σ** | 7-day standard deviation of sleep midpoint hour — circadian / social-jet-lag proxy. <0.75h is tight. | Lunsford-Avery 2018 |
| **Sleep Regularity Index** | % probability the asleep/awake state matches at the same clock minute on consecutive nights. ≥80 = tight. | Phillips 2017 *Scientific Reports* |

---

### Periodization Strip + Banister Fitness-Fatigue Model

Most "training load" tools stop at ACWR. I added the full Banister model on top — separating **fitness** (slow-decay 42d EWMA), **fatigue** (fast-decay 7d EWMA), and **form** (their difference):

```python
ctl_decay = exp(-1/42)        # CTL — fitness
atl_decay = exp(-1/7)         #  ATL — fatigue
ctl = ctl * ctl_decay + load * (1 - ctl_decay)
atl = atl * atl_decay + load * (1 - atl_decay)
tsb = ctl - atl               # TSB — form
```

**Form interpretation:**

| TSB | Meaning |
|---|---|
| `> +15` | Detraining risk |
| `+5 to +15` | Race-ready |
| `−10 to +5` | Productive training zone |
| `−20 to −10` | Fatigued |
| `< −20` | Overreaching |

The mesocycle phase strip sits beside it — one cell per planned week, the current week glows, the deload week is amber. Reads the live `mesocycles` table; phase + weeks-to-deload are pulled from `ensure_active_mesocycle()`.

---

### After-Action Autoregulation — Reading the Hevy Sync

I log every set in Hevy. Once it syncs, the **After-Action panel** computes per-exercise actuals vs. plan target and emits a next-session weight suggestion. Read-only — no double-logging.

The autoregulation rules (Helms 2018 + RP autoreg, RPE-based since Hevy doesn't capture mean concentric velocity):

| Condition | Suggestion |
|---|---|
| Avg actual RPE ≥ target + 2 | **−10%** next time |
| Avg actual RPE ≥ target + 1 | **−5%** |
| Min reps short of target by ≥2 | **−5%** |
| Avg actual RPE ≤ target − 2 | **+2.5%** |
| Reps hit + RPE under target | **+2.5%** progression |
| All on target | repeat |

Every suggestion is rounded to the nearest 2.5 lbs. A `verdict` column tints the row green (progress), red (drop), or neutral (repeat).

**Hevy RPE floor.** Hevy's RPE picker only goes 6–10, so a prescribed target below 6 (e.g. a deload set at RPE 5) is unloggable — comparing a logged 6 against a target of 5 would falsely read "harder than planned" and drop the load every time. The comparison clamps the target to a floor of 6, and `save_plan()` raises any loaded-lift `rpe_target` (and the session target) to 6 on persist so plans never prescribe an RPE you can't record. Cardio/bodyweight work is left alone — Hevy doesn't RPE-log it.

---

### Post-Workout Retrospective — Execution Feedback, Not a Stale Rerun

The morning story is recovery-driven; those metrics don't change after you train. So the post-workout pass is a *separate* artifact: a vault-grounded **retrospective** of how the session went versus plan. The **Post-workout** dashboard section pairs the after-action adherence table with a copy-prompt flow (Copy CC prompt → paste into Claude Code → POST back → Sync), mirroring the morning health-story pattern.

`GET /training/after-action` now also returns a `## VAULT RESEARCH` block — notes selected server-side from the session's *execution* signals (rep misses → effective-reps/load-selection, RPE overshoot → fatigue-management/SFR, progression → progressive-overload, missing RPE → autoregulation) — so every adjustment the retrospective recommends is grounded in the same retrieval engine the planner uses. `GET /workout/retrospective/latest` returns the latest session + stored retrospective + a `needs_retrospective` flag; `POST /workout/retrospective` stores the narrative, flags, and vault citations, which then feed the next morning's "PRESCRIPTION → EXECUTION" line.

---

### Fueling Layer — Body Comp + Macros + Hydration

Apple Health was already syncing weight and active/basal energy. The ingest map now also pulls every dietary metric (energy, protein, carbs, fat, fiber, sugar, water, sodium, caffeine) and **lean body mass** from a smart scale.

The `/api/fueling/today` endpoint computes:
- **kcal balance** — dietary in − (active + basal) out
- **Protein g/kg** vs the 1.6–2.2 g/kg hypertrophy band (Morton 2018 meta)
- **Hydration** in oz + sodium in mg
- **Body composition** — weight, BF%, lean mass, falling back to BF×weight when LBM is missing

Empty-state UX: when no diet data is logged yet, the card shows targets sized to current body weight ("~194g protein, ~3779ml water, TDEE balance ±250 kcal") so the prescription is visible from day one.

---

### Clinical Research Signals — Six Peer-Reviewed Tiles

A new panel layered on top of the standard Insights pane. Each tile is anchored to a primary citation surfaced via tooltip hover:

| Tile | What it computes | Threshold | Reference |
|---|---|---|---|
| **SRI** | Overlap-based sleep regularity index | ≥80 tight, ≥60 moderate | Phillips 2017 |
| **lnRMSSD** | log-transformed HRV mean rolling 7d, with 4w-avg delta + CV% | + delta = autonomic adaptation | Buchheit 2014 |
| **Red-streak** | Consecutive recovery <34 days | 3+ doubles soft-tissue injury risk | WHOOP 2022 internal cohort |
| **Allostatic Load** | Composite of BP, BMI, LDL, HDL, trig, A1c each scored 0/1/2 | <3 low, <6 moderate, ≥6 elevated | Seeman 2001 *JAMA* |
| **Adj. HRV** | Raw HRV uplifted ~15% on propranolol days, ~7% on SSRI | strips medication shadow | Kemp 2010 meta + Mølgaard 1991 |
| **Z2 HR drift** | Coefficient-of-variation across recent Z2 cardio sessions | <5% stable, ≥7% drifting | Maffetone |

This was the layer that took the platform from "consumer wearable dashboard" to "research-grade single-subject panel."

---

### Research Lab — Pre-Registered N-of-1 Hypotheses

The piece I'm most proud of. A **pre-registered hypothesis catalog** runs against my live time-series and emits CONFIRMED / REFUTED / INCONCLUSIVE / INSUFFICIENT verdicts per question — with effect size, n, p-value, and the primary citation. The test type and threshold are fixed in advance, so I can't p-hack.

Six standing hypotheses seeded from the vault:

1. **Short sleep depresses next-day HRV** — Welch's t between <6.5h and ≥7.5h nights
2. **Long sleep lifts next-day HRV** — Welch's t between ≥8h and 6.5-7.5h nights
3. **Pickleball depresses next-morning HRV** — paired t for session vs no-session days
4. **Skin-temp +1°F precedes red recovery within 48h** — change-point rate
5. **High strain elevates next-morning RHR** — Welch's t vs trailing 28d baseline
6. **Push:pull imbalance correlates with weekly recovery** — Pearson r on |log push:pull|

Wired through:

```
GET  /api/lab/questions    → catalogue
GET  /api/lab/findings     → latest verdict per question
POST /api/lab/run          → re-run all enabled hypotheses + rotate stable questions
```

The frontend `LabPanel` renders one verdict-coded card per question with the hypothesis text, summary, effect size, n, p-value, test type, and vault citation. Hit "RUN ALL" or wire it to a weekly cron. New hypotheses go into `lab_questions` as a one-row INSERT plus a runner function in `shc/lab.py` — that's the entire surface area for adding new questions.

**Automatic rotation.** After each run, `rotate_if_stable()` checks every active question. If a question has produced 3 consecutive identical confirmed/refuted verdicts with n ≥ 1.5 × min_n, it's retired and the next queued question (lowest `queued_order`) is promoted automatically. A bank of additional hypotheses covers consecutive training → recovery drop, 3-day pickleball volume → HRV, heavy lift tonnage → next-day HRV, weekly load spike → recovery, full rest days → HRV rebound, self-reported energy ↔ HRV, 7-day rising RHR → HRV drop, and sleep quality ↔ HRV. The system never runs out of questions to test.

> **Match the study to the behaviour.** The yoga → HRV hypothesis was retired in favour of *heavy lift tonnage → next-day HRV*: yoga fired roughly twice a year, so it never gathered enough exposure days to produce a verdict, whereas lifting happens 3–4×/week and the correlation runs well-powered (n≈180). A standing hypothesis is only worth a slot if the exposure actually occurs.

**Verdicts feed the AI.** Every call to `build_daily_context()` or `build_training_context()` injects the current `## YOUR PERSONAL LAB FINDINGS` block. Claude sees which effects have been statistically confirmed or refuted on my data before writing a word — REFUTED findings override population-level assumptions.

The philosophical backbone is in the vault — Schork 2015/2022 and Daza 2018 on N-of-1 trials as rigorous science.

---

### Concurrent Training Awareness — Pickleball as Primary Sport

The original platform was framed around generic recomposition. That's changed. The primary goal is now **4.5 → 5.0 pickleball while preserving strength and size** — breaking the racquet-sport norm of trading muscle for endurance.

This required wiring concurrent training interference theory directly into the planner. The vault now contains Wilson 2012, Schumann 2022, Coffey & Hawley 2017, and Suchomel 2016. The core findings that drive planning decisions:

| Finding | Source | How it's applied |
|---|---|---|
| Lower-body explosive power is the first adaptation lost under high sport volume | Wilson 2012 | When `pickleball_min_7d ≥ 150`, drop leg hypertrophy to MEV; bias toward power block |
| AMPK activation from aerobic work suppresses mTOR-driven hypertrophy for ~6h | Coffey & Hawley 2017 | Finisher rule: ≥150 min/wk → Z2-only, no HIIT — sport already supplied the stimulus |
| Sport-specific aerobic (court movement) interferes less than running-based aerobic | Schumann 2022 | Upper-body hypertrophy volume stays at MAV — the interference is lower-body |
| Strength is the floor on which power is built — never sacrifice the floor | Suchomel 2016 | Primary compounds always present; sport volume reduces accessories, not compounds |

Two new vault signals gate the planner automatically:

```python
"pickleball_focus":     pickleball_min_7d ≥ 60     # sport present → stay out of HIIT
"concurrent_training":  pickleball_min_7d ≥ 150    # high volume → lower-body MEV + Z2 finisher only
```

These signals surface relevant vault notes (concurrent-training-interference, power-development, maximal-strength) to Claude's context, so the rationale is evidence-based and traceable, not just a hard-coded heuristic.

---

### Respiratory Rate Sentinel Gate

WHOOP logs respiratory rate per night as a dedicated sleep column. A new gate fires when tonight's value is ≥ +1 bpm above the 28-day median baseline:

```python
baseline = median(respiratory_rate values where 8 ≤ rr ≤ 30, last 28 nights)
delta    = tonight_rr − baseline
gate     = "illness sentinel" if delta ≥ 1.0 else None
```

The median (not mean) protects against outlier contamination. The 8–30 bpm clamp excludes implausible values from earlier schema iterations. Bourdillon (2018) and Nicolò (2020) both show respiratory rate rises 3–4 days before subjective illness symptoms — this gate catches it early.

---

## The Obsidian Vault

The third input into every AI call — alongside live biometrics and clinical context — is a personal knowledge base of **405 research notes** I've built in Obsidian. Every workout plan Claude generates is grounded in this vault, not in whatever the model learned during pretraining.

The difference matters. Claude knows exercise science in aggregate from its training data. My vault encodes *my* specific protocol decisions — which periodization model I follow, which meta-analyses I trust on rest intervals, what the research actually says about training frequency for hypertrophy vs what gets repeated on the internet. When Claude writes me a plan, it's applying my evidence base, not a generic one.

### What's In It

~416 notes across 8 domains, all ingested from primary sources (textbooks, meta-analyses, RCTs), structured with YAML frontmatter tags, and condensed to actionable prescription sections.

| Domain | Notes | Primary sources |
|---|---|---|
| Strength & Hypertrophy | 147 | Schoenfeld, Israetel, Helms, Bompa/Zatsiorsky — volume landmarks, SRA curves, periodization, DUP |
| Sleep Science | 76 | Walker, Winter — stage targets, SpO2 thresholds, circadian anchoring, sleep × athletic performance |
| LLM Engineering & RAG | 67 | Self-RAG, ReAct, Reflexion, Constitutional AI — informs how the retrieval system is designed |
| Nutrition | 55 | Israetel, Helms, Attia — priority hierarchy, protein targets, recomposition conditions, supplement tiers |
| Longevity & Healthspan | 35 | Attia — VO₂max, centenarian decathlon, Zone 2, ApoB vs LDL-C, compression of morbidity |
| HRV & Biometric Research | 15 | Task Force 1996, Kiviniemi, Plews, Tanaka, Dial — the papers behind every HRV and zone design decision |
| Concurrent Training & Sports Science | 11 | Wilson, Coffey & Hawley, Schumann, Suchomel, Seiler — interference theory, AMPK/mTOR, sport compatibility |
| N-of-1 Methodology | 5 | Schork, Daza, Piccininni — single-subject experimental design as rigorous science, not just self-tracking |

---

### How the Vault Gets Used

On every workout generation or briefing call, `load_vault_research()` selects the 4 most relevant notes based on what's going on with me today:

```python
signals = {
    "hrv_anomaly",         # HRV σ-deviation < -1.0
    "high_acwr",           # ACWR > 1.3
    "deload",              # gates.deload_required = True
    "illness",             # checkin.illness_flag = True OR rr_delta ≥ 1.0
    "poor_sleep",          # last night < 6h
    "push_pull_imbalance", # 28d ratio > 1.2 or < 0.8
    "volume_spike",        # 4-week volume Δ > 40%
    "recomposition",       # always active
    "exercise_selection",  # always active
    "pickleball_focus",    # pickleball_min_7d ≥ 60
    "concurrent_training", # pickleball_min_7d ≥ 150 — triggers concurrent-training vault notes
}
```

Each note has YAML frontmatter tags. The retriever scores tags against active signals (`+2` per match, `+1` for default) and returns the top 4. On a high-ACWR/low-HRV day, overtraining and deload notes automatically beat out rest-interval notes.

**Example: ACWR = 1.42, HRV σ = −1.8**

| Note | Score |
|---|---|
| `overtraining-and-deload.md` | **+6** (deload+2, hrv_anomaly+2, high_acwr+2) |
| `fitness-fatigue-theory.md` | **+4** (deload+2, hrv_anomaly+2) |
| `supercompensation-theory.md` | **+3** (volume_spike+2, default+1) |
| `rest-interval-hypertrophy.md` | **+1** (default+1) |

Six notes also load unconditionally on every plan call — exercise selection, exercise order, Schoenfeld's hypertrophy mechanisms, rest intervals for strength and hypertrophy. These are the foundation that every plan builds on regardless of the day's signals.

Raw notes get stripped down to just the actionable sections before being sent to Claude:

```
## Summary          → the principle
## Prescription     → the actual numbers
## Key Claims       → what the research says
## Practical Takeaways → how to apply it
```

A 3,000-word hypertrophy paper becomes a 400-word prescription. Every plan Claude generates has to cite which vault notes it applied — there's a `vault_insights` field that's validated server-side, so the model can't silently ignore the research I handed it.

---

## The Dashboard

What I actually look at every day. Built with Next.js 15 + React 19.

<table>
<tr>
<td width="50%">

**⚡ Athlete OS Panel**
The top card. Fuses today's readiness verdict (engine-gate-aware, not client-side), goal pressure (push:pull ratio, court load), active experiment status, and personal lab findings into four decision cells. One read, one decision.

**🧠 Command Briefing**
Claude's written assessment of the day — recovery, training intent, and what to watch. Sits below the OS Panel.

**📡 Biometric HUD**
Always-on header with live WHOOP and Hevy sync status, today's vitals, and data freshness. I want to know if something hasn't synced.

**🫀 Recovery Intelligence**
WHOOP recovery ring plus a 7-night HRV sparkline with ±1σ bands. Points outside the band are colored — it's easy to spot anomalous nights at a glance.

**😴 Sleep Architecture**
7-night stacked bar (total / deep / REM), sleep debt accumulator, SpO2 per night. The debt tracker is something I actually use.

</td>
<td width="50%">

**🏋️ Training Load**
ACWR trend with the safe-zone band drawn in, weekly volume by muscle group, push:pull ratio. I built this after noticing I was chronically over-pushing and under-pulling.

**🎯 Readiness Composite**
The score broken down into components, with a visual showing which weight vector is active. Gate reasons in plain English.

**💬 AI Advisor** `⌘K`
Claude chat, but it already knows everything before I type anything. Every message includes today's full DailyState, medications, labs, training history, and gate state.

**🌊 Ambient Layer**
The page background hue shifts with readiness — greenish when I'm good, reddish when I'm not. It's subtle but I notice it before I read anything.

</td>
</tr>
</table>

### 2026 Goal Scorecard

Three north-star metrics tracked on a dedicated section between Signals and Training:

| Track | What it shows |
|---|---|
| **DUPR doubles** | Current rating (glowing 32px Orbitron), gap to 5.0 target, gradient progress bar, DUPR sparkline with target reference line, latest tournament context card (W/L · DUPR arc · WHOOP recovery) |
| **Key compound e1RM** | Top-5 key lifts (squat, bench, deadlift, press, row, pull) with latest e1RM in lbs and 8-week trend (↑ climbing / → holding / ↓ declining), color-coded left border per trend |
| **Body weight** | Current weight in lbs, 4-week trend in lbs/wk, plain-language concurrent-training interpretation (stable / gaining / losing) |

### The Sports-Science Strip

Six newer panels stack between the daily-readiness row and the legacy Strength / Cardio panels:

| Panel | What it shows |
|---|---|
| **Periodization** | Mesocycle phase strip (W-of-N, deload-week amber) + PMC chart (CTL/ATL/TSB over 180d with zone bands) |
| **After-Action** | Per-exercise Hevy-driven autoreg: actuals vs plan, next-session weight suggestion, verdict tint |
| **Clinical Research Signals** | Six peer-reviewed tiles — SRI, lnRMSSD, red-streak, allostatic load, drug-adjusted HRV, Z2 drift — with plain-language meaning and range scale |
| **Fueling** | Body comp strip (weight / BF% / lean mass) + macros (kcal in/out/balance, protein g/kg, hydration) + 14d energy-balance bar chart |
| **Research Lab** | Six active pre-registered hypothesis cards (CONFIRMED / REFUTED / INCONCLUSIVE / INSUFFICIENT) + automatic rotation from an 8-question queued bank; verdicts injected into every AI call |

### Trend Intelligence

Six tabs I open when I want to dig into something:

| Tab | What's in it |
|---|---|
| **Recovery** | 90-day HRV with 7d EWMA + ±0.5σ guidance band, recovery score, RHR with 28d moving average, pre-illness alarm strip |
| **Body** | Weight trend, 4-week regression line, Apple Health sync |
| **Patterns** | Sleep vs recovery and HRV vs readiness scatter plots — Pearson-r per plot |
| **Insights** | Computed correlation cards, unlocks after 7 days of data |
| **Sport** | Pickleball KPIs (sessions, court time, play freshness); Play Freshness bar chart (WHOOP recovery on court days); Post-play HRV delta chart; Tournament results — match history grouped by event with per-game WIN/LOSS rows, scores, DUPR arc, and WHOOP recovery/HRV for tournament days |
| **Clinical** | Timeline of medications, diagnoses, and labs — abnormal values flagged |

### Today's Workout

Generated by Claude with full context injected. Comes back as structured blocks — warm-up, main, accessory — with exercises, sets × reps, weight, RPE, and coaching notes, each citing which vault note justified the choice. I can push it directly to Hevy as a routine with one button.

---

## AI Integration

### Slim Daily Brief Endpoint

`GET /api/daily/brief` returns a single 24KB payload that replaces the previous multi-endpoint context-building pattern (which required fetching ~293KB across 6+ endpoints). The brief combines:

- Full `DailyState` DTO (all computed metrics)
- 5 signal-ranked vault notes × 800 chars each
- Last 7 days of training sessions
- Top 20 working weights
- Complete Hevy exercise catalog
- Mesocycle + ACWR + muscle-group rest status

This endpoint is what the `shc-workout` Claude Code skill uses. Context is fetched once, in one shot, in ~500ms rather than 6+ minutes.

---

### How Context Gets Built

Every time Claude gets called, `build_daily_context()` assembles:

- Today's full DailyState (all computed metrics)
- 28-day cardio composition (Zone 2 vs threshold vs VO₂max minutes)
- Push:pull imbalance direction and magnitude
- Skin-temp delta from my 28-day baseline
- Active medications with dosing and onset dates
- Active diagnoses
- 20 most recent lab values with reference ranges
- Recent PRs, volume trend, last session per muscle group
- Active gate reasons
- Signal-ranked vault research

`build_clinical_context()` structures the clinical data into a dedicated block that appears early in the system prompt. The HEALTH_SYSTEM prompt encodes drug-class interpretation rules so Claude doesn't have to infer pharmacology from first principles.

### Workout Generation Flow

```
SYSTEM: HEALTH_SYSTEM + gate enforcement rules + personal context
USER:   build_training_context()
        → readiness tier + score
        → HRV σ, sleep quality, ACWR
        → volume push/pull/legs 28d
        → last session per muscle group (hours ago)
        → gates (max_intensity, forbid_muscle_groups, zone shifts)
        → signal-ranked vault research (top 4 notes)
        → pinned exercise science foundation (6 notes always)
        → session goals
```

Plan comes back as JSON, gets validated against gates, cached for 24h. `?regen=true` forces a fresh call.

### Running Locally Without Claude

`SHC_LLM_MODE=local_only` routes everything to a local Ollama instance (`llama3.3:70b`). Same context injection, lower reasoning quality, works fully offline. I use this when I'm traveling.

---

## Data Sources

| Source | Protocol | What I get |
|---|---|---|
| **WHOOP 4.0** | OAuth 2.0, syncs every 60 min | Recovery, HRV, RHR, sleep stages (with cycles, efficiency, disturbances, respiratory rate), strain, SpO2, skin temp, HR zone durations, body measurements (max HR), user profile |
| **Apple Health** | HealthAutoExport → CCDA XML | Steps, HR, weight, glucose, blood pressure, sleep |
| **Hevy** | REST API + routine export | Every lift back to 2015 |
| **DUPR** | Unofficial `api.dupr.gg` (Keychain credentials, daily cron) | Doubles + singles rating snapshots; full match history with per-game scores, partners, opponents, and pre/post/delta ratings |
| **Morning check-in** | Dashboard form | Energy, stress, soreness, weight, medication flags |
| **Cardio log** | Dashboard form | Manual sessions — sport, duration, HR, RPE |
| **Clinical data** | Dashboard forms | Medications, diagnoses, labs |

---

## Stack

<table>
<tr>
<th>Backend</th>
<th>Frontend</th>
</tr>
<tr>
<td>

| | |
|---|---|
| Language | Python 3.12 |
| Framework | FastAPI 0.115 |
| Database | DuckDB 1.1 (encrypted, 66 migrations) |
| Background | APScheduler 3.10 |
| HTTP | httpx 0.28 (async) |
| XML | lxml 5 (Apple Health CCDA) |
| Credentials | macOS Keychain via `keyring` |
| AI | Claude Opus 4.8 (chat-driven, no SDK calls in backend) |
| Fallback | OpenAI client → Ollama |
| Validation | Pydantic v2 |
| Packaging | uv + pyproject.toml |
| Lint / types | ruff + pyright |

</td>
<td>

| | |
|---|---|
| Framework | Next.js 15 + React 19 |
| Language | TypeScript 5 (strict) |
| Styling | Tailwind CSS v4 — OKLCH |
| Data fetching | TanStack Query v5 |
| Charts | Recharts 2.15 |
| UI primitives | shadcn/ui (Radix UI) |
| Icons | Lucide React |
| Animations | Motion 12.38 |
| Display font | Orbitron 900 |
| Body font | Geist Sans + Mono |

</td>
</tr>
</table>

**Infrastructure:** `dev-restart.sh` — API `:8000`, frontend `:3000`, WAL checkpoint on start · pre-push hook: ruff + pyright + pytest (428 tests) · APScheduler nightly jobs: WHOOP/Hevy/DUPR sync + `compute_all_scores` (full self-learning pipeline)

---

## Design

I spent more time on the UI than I probably should have. The whole thing uses OKLCH (Oklab Lightness-Chroma-Hue) — a perceptually uniform color space where the same lightness value actually looks equally bright across all hues. In standard sRGB, green looks brighter than red at the same hex value, which makes status colors feel inconsistent. OKLCH fixes that.

<table>
<tr>
<th>Status</th>
<th>Value</th>
<th>Meaning</th>
</tr>
<tr>
<td>🟢 Ready</td>
<td><code>oklch(0.72 0.18 145)</code></td>
<td>Push hard</td>
</tr>
<tr>
<td>🟡 Moderate</td>
<td><code>oklch(0.78 0.15 85)</code></td>
<td>Back off a bit</td>
</tr>
<tr>
<td>🔴 Rest</td>
<td><code>oklch(0.65 0.22 20)</code></td>
<td>Recovery only</td>
</tr>
<tr>
<td>⬛ Background</td>
<td><code>oklch(0.13 0 0)</code></td>
<td>Near-black base</td>
</tr>
<tr>
<td>◻️ Card border</td>
<td><code>oklch(1 0 0 / 0.10)</code></td>
<td>Hairline white</td>
</tr>
</table>

**Typography:** `Orbitron 900` for KPI numbers and tier labels, `Geist Sans` for everything else, `Geist Mono` for data tables.

---

## Data Model

32 tables, 6 views, 68 migrations applied.

| Group | What it stores |
|---|---|
| **Biometrics** | WHOOP recovery scores, HRV, RHR, skin temp, SpO2; sleep stage breakdown (SWS, REM, efficiency, disturbances, respiratory rate, cycles); Apple Health time-series; body measurements |
| **Training** | Hevy sessions and sets (every lift back to 2015); cardio sessions with HR zone durations; AI-generated workout plans; post-workout retrospectives; prescription vs execution adherence |
| **Self-learning engine** | Per-exercise weekly e1RM + tonnage + performance scores; fitted ACWR gate thresholds; materialized signal quality (scored weeks, stability, confidence per muscle); prescription feedback log |
| **Periodization** | Active mesocycle (phase, planned weeks, deload trigger); per-muscle MEV/MAV/MRV targets (population defaults + personal fitted variants); one canonical `exercise → muscle` table carrying both volume crediting and per-head anatomy (region, length-bias, SFR, cited rep ranges) |
| **Clinical** | Active medications with audit trail; diagnoses; lab results with reference ranges; pre-registered N-of-1 hypothesis catalogue; per-run statistical findings (verdict, n, effect size, p-value) |
| **Sport** | DUPR rating snapshots (daily); full match history with per-game scores, partners, opponents, pre/post/delta ratings |
| **Daily input** | Morning check-in (energy, stress, soreness, body weight, protein, medication flags); exercise training preferences; OAuth + sync state per data source |
| **Views** | Rolling 28d HRV baseline; per-day composite load (deduped); WHOOP session strain (quality-filtered) |

---

## Privacy

Everything runs on my MacBook. Nothing goes to a cloud. The database is encrypted at rest (DuckDB + Keychain key). OAuth tokens live in Keychain, not on disk. The API is localhost-only behind a session token. Clinical details are loaded at runtime from a gitignored file — they're not in version control.

---

## Running It

This is a personal tool built for a specific setup — it's not packaged for general use and there's no onboarding path for different hardware or environments.

It assumes:
- **WHOOP 4.0** for recovery, HRV, sleep staging, strain, and HR zones
- **Hevy** for lift logging (with history back to 2015)
- **HealthAutoExport** for Apple Health → CCDA XML sync
- **macOS Keychain** for secrets (OAuth tokens, DB encryption key, Hevy API key)
- **DUPR account** for pickleball rating history
- **Obsidian vault** on disk for RAG (405 notes, personal to me)

The architecture section covers how it's built. The stack section covers what it's built with. The most transferable design patterns — `DailyState` as a single computation contract, the deterministic gate engine layered under the LLM, signal-ranked vault retrieval — are all described in detail above and don't require this exact hardware setup to understand or adapt.

---

<div align="center">

*Built by Rob Savage — because no existing tool understood my whole picture.*

</div>
