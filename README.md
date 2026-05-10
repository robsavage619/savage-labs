<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=6,11,20,25,30&height=220&section=header&text=SAVAGE+LABS&fontSize=72&fontColor=ffffff&animation=fadeIn&fontAlignY=40&desc=A+personal+health+OS+%E2%80%94+not+a+wellness+app&descAlignY=63&descSize=19" width="100%" />

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

[![Claude](https://img.shields.io/badge/Claude-Opus_4.7-1e1e2e?style=for-the-badge&logo=anthropic&logoColor=f5c2e7&labelColor=1e1e2e&color=f5c2e7)](https://anthropic.com/)
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
POST /api/lab/run          → re-run all enabled hypotheses
```

The frontend `LabPanel` renders one verdict-coded card per question with the hypothesis text, summary, effect size, n, p-value, test type, and vault citation. Hit "RUN ALL" or wire it to a weekly cron. New hypotheses go into `lab_questions` as a one-row INSERT plus a runner function in `shc/lab.py` — that's the entire surface area for adding new questions.

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

**~416 notes across 11 domains** — all ingested from primary sources (textbooks, meta-analyses, RCTs), structured with YAML frontmatter tags, and condensed to actionable prescription sections.

<details>
<summary><strong>Strength & Hypertrophy — 147 notes</strong></summary>

The biggest chunk. Primarily Schoenfeld's *Science and Development of Muscle Hypertrophy* (2021), Israetel's *Scientific Principles of Hypertrophy Training* (2020), Helms' *Muscle & Strength Pyramid* (2018), and Bompa/Zatsiorsky on periodization.

**What's encoded:**

- **Volume threshold (Schoenfeld 2016 meta, 15 studies):** ≥10 working sets per muscle group per week to maximize hypertrophy. +0.37% per additional set across a 2–30 set range.
- **Hypertrophy mechanisms (Schoenfeld 2010):** Mechanical tension is the primary driver. Metabolic stress and muscle damage are secondary. This hierarchy is encoded directly into exercise selection rules.
- **Rest intervals:** 90–120s minimum between compound sets for hypertrophy; 180–300s for strength. Longer rest is actually superior (Schoenfeld 2016) — the "metabolic stress from short rest" hypothesis didn't hold up.
- **Range of motion:** Full ROM beats partial. Lengthened-position loading (deficit RDLs, stretched-position flies) produces a greater stimulus per Pedrosa (2022) and Maeo (2021).
- **DUP periodization:** Distinct rep ranges across sessions within the week (strength 3–5, hypertrophy 8–12, endurance 15–20) outperforms linear for trained athletes.
- **SRA curves per muscle:** Stimulus-recovery-adaptation timelines per muscle group — quads 72h compound, biceps 48h, delts 36–48h — feed directly into the gate logic.
- **Volume landmarks:** MEV → MAV → MRV per Israetel. Exceeding MRV triggers a deload.
- **Cardio interference:** Low: cycling Z2 post-strength. High: running pre-strength, same-day HIIT.

**Notes:** `exercise-selection-strength.md`, `exercise-selection-hypertrophy.md`, `exercise-order-strength.md`, `rest-interval-strength.md`, `rest-interval-hypertrophy.md`, `range-of-motion-hypertrophy.md`, `training-volume-hypertrophy.md`, `schoenfeld-2016-rt-volume-hypertrophy.md`, `schoenfeld-2021-science-development-muscle-hypertrophy.md` (9 chapters), `sra-training-frequency.md`, `supercompensation-theory.md`, `fitness-fatigue-theory.md`, `overreaching-detection.md`, `concurrent-training-interference.md`

</details>

<details>
<summary><strong>Sleep Science — 76 notes</strong></summary>

Walker's *Why We Sleep* (2017) and Winter's *The Sleep Solution* (2017), both chapter by chapter, plus primary research on HRV during sleep, OSA, and sleep × athletic performance.

**What's encoded:**

- **Sleep deprivation effects (Walker Ch1):** 6–7h demolishes immune function, doubles cancer risk relative to 8h, and raises ghrelin enough to drive ~300 kcal/day of extra intake. This is why the sleep debt accumulator in the dashboard exists — I want to see when I'm accumulating a deficit.
- **Stage targets:** N3 (deep/slow-wave) drives physical recovery and GH release. REM drives motor learning and emotional regulation. Both tracked separately rather than collapsed into a single "sleep score."
- **SpO2 threshold:** <95% average flags sleep-disordered breathing — it's weighted more heavily than duration in my composite score, for obvious reasons.
- **Sleep state misperception:** Subjective quality often diverges from objective stage data. That's why I log both — WHOOP's objective staging and my own morning 1–10 rating.
- **Circadian anchoring (Winter):** Consistent wake time matters more than consistent bed time.

**Notes:** `walker-2017-why-we-sleep.md` (Ch1–16), `winter-2017-sleep-solution.md` (Ch1–16), `obstructive-sleep-apnea.md`, `sleep-spindles.md`, `sleep-learning-consolidation.md`, `napping-protocol.md`, `rem-dreaming-mechanisms.md`, `dolezal-2017-sleep-exercise-review.md`

</details>

<details>
<summary><strong>Nutrition — 55 notes</strong></summary>

Israetel's *Renaissance Diet 2.0* (2020) and Helms' *Muscle & Strength Pyramid: Nutrition* (2016), with Attia's *Outlive* (2023) for metabolic health context.

**What's encoded:**

- **Priority order (Israetel Ch1):** Adherence → calorie balance → macros → timing → food choice → supplements. This ordering determines what the AI advisor emphasizes when I ask nutrition questions.
- **Recomposition conditions:** Possible if you're new to training, returning from a layoff, or enhanced. For a trained athlete in neither state, it requires deliberate calorie cycling — encoded as a constraint on what Claude will recommend.
- **Protein floor:** 0.7g/lb minimum at any calorie level. 1.0–1.2g/lb in a surplus.
- **Deficit rate:** 0.5–1.0% body weight per week to preserve lean mass. Faster → muscle loss risk.
- **NEAT first:** Non-exercise activity thermogenesis is the biggest variable in TDEE. Increase output before cutting food.
- **Supplement tier list:** Creatine and caffeine are Tier 1. Everything else is Tier 2 or lower. Encoded to gate what Claude recommends.

**Notes:** `israetel-2020-renaissance-diet.md` (Ch1–17), `helms-2016-muscle-strength-pyramid-nutrition.md` (Ch1–7), `protein-target.md`, `calorie-deficit-fat-loss-rate.md`, `diet-break-refeed-protocol.md`, `diet-priority-pyramid.md`, `peri-workout-nutrition.md`, `supplements-tier-list.md`, `supplement-creatine.md`, `supplement-caffeine.md`

</details>

<details>
<summary><strong>Longevity & Healthspan — 35 notes</strong></summary>

Attia's *Outlive* (2023) cover to cover, framing everything through the four horsemen: cardiovascular disease, cancer, neurodegeneration, metabolic dysfunction.

**What's encoded:**

- **VO₂max as the most important fitness metric (Attia Ch11):** Bottom quartile → 4× all-cause mortality vs top. No upper limit to the benefit. I track Zone 2 and Zone 5 minutes specifically because of this.
- **Centenarian Decathlon:** VO₂max, grip strength, leg press, single-leg balance, stair climb, carry, floor-rise, overhead press, gait speed. These are my long-term training targets, not aesthetics.
- **Zone 2:** ~80% of aerobic volume at conversational pace. Mitochondrial density, fat oxidation, metabolic flexibility.
- **ApoB > LDL-C:** ApoB is the causal cardiovascular risk marker. When I ask Claude about my lipid labs, it references ApoB first.
- **Compression of morbidity:** The goal is function in the last decade, not just survival. Everything I track is downstream of this framing.

**Notes:** `attia-2023-outlive.md` (Ch1–17), `four-horsemen-chronic-disease.md`, `centenarian-decathlon.md`, `vo2max-longevity.md`, `zone-2-training.md`, `compression-of-morbidity.md`, `grip-strength.md`, `apob.md`, `apoe.md`, `medicine-3-0.md`

</details>

<details>
<summary><strong>HRV & Biometric Research — 15 notes</strong></summary>

Primary papers on HRV monitoring, wearable validation, and HR modelling — the actual research behind the design decisions in this codebase.

**Papers and what they drove:**

- **Task Force (1996):** The foundational HRV standards paper. Established why RMSSD is the right metric for short-term vagal monitoring, not LF/HF.
- **Kiviniemi et al. (2007):** HRV-guided training outperforms fixed-intensity programs. The direct basis for gating training intensity off σ-deviation rather than a fixed weekly schedule.
- **Plews et al. (2013, 2014):** 7-day rolling average is superior to single readings for training decisions. Drove the 28-day baseline window design.
- **Tanaka et al. (2001):** 220−age underestimates HRmax in trained adults. Tanaka (208 − 0.7 × age) is lower error. Encoded directly in the HR zone calculation.
- **Dial et al. (2025):** WHOOP and Garmin validation study. Establishes the confidence interval for treating WHOOP readings as ground truth.

**Notes:** `task-force-1996-hrv-standards.md`, `shaffer-2017-hrv-metrics-norms.md`, `kiviniemi-2007-hrv-guided-endurance-training.md`, `plews-2013-hrv-monitoring-compliance.md`, `tanaka-2001-hrmax-revisited.md`, `buchheit-2014-training-status-hr-monitoring.md`, `dial-2025-wearable-rhr-hrv-validation.md`

</details>

<details>
<summary><strong>Concurrent Training & Sports Science — 11 notes</strong></summary>

Added in response to pickleball becoming the primary sport goal. Covers interference effects, power development, and cardio zone methodology anchored to primary papers.

**What's encoded:**

- **Concurrent training interference (Wilson 2012):** The residual fatigue model. Lower-body explosive power is the first adaptation lost when aerobic volume is high — not upper-body strength. This asymmetry drives the planner's split: preserve compound pulling and pushing volume, drop lower-body to MEV when pickleball ≥ 150 min/7d.
- **Molecular mechanisms (Coffey & Hawley 2017):** AMPK activated by aerobic work phosphorylates TSC2 → suppresses Rheb → inhibits mTORC1 → blunts hypertrophy signaling for ~6h. Practical application: Z2-only finishers when concurrent training load is high; ≥6h separation between sport and lifting reduces interference.
- **Compatibility conditions (Schumann 2022):** Sport-specific movement patterns interfere less than generic running. Court-movement aerobic (pickleball) creates less lower-body interference than an equivalent HIIT session. Upper-body hypertrophy can remain at MAV even in high sport-volume weeks.
- **Strength as the floor (Suchomel 2016):** Maximal strength is the foundation for all power expression in racquet sports. Never sacrifice compound primaries to make room for sport volume — reduce accessories, not the strength base.
- **Polarized zone distribution (Seiler 2010, Stoggl & Sperlich 2014):** 80/20 rule — ~80% of aerobic volume at Z1/Z2 (conversational), ~20% at threshold or above. Validated across endurance sports. Applied to finisher selection: Z2-only finishers preserve this distribution when pickleball is already supplying the high-intensity stimulus.
- **Respiratory rate monitoring (Nicolò 2020, Bourdillon 2018):** RR rises 3–4 days before subjective illness. Used to implement the +1 bpm sentinel gate.
- **Athlete sleep (Vitale 2019):** Sleep extension to ≥8h improves reaction time and sprint speed. Platform now surfaces sleep cycle count, efficiency, and disturbances as first-class gate inputs.

**Notes:** `wilson-2012-concurrent-training-interference.md`, `schumann-2022-concurrent-training-compatibility.md`, `coffey-2017-concurrent-training-molecular.md`, `suchomel-2016-strength-athletic-performance.md`, `seiler-2010-polarized-training.md`, `stoggl-2014-polarized-vs-pyramidal.md`, `nicolo-2020-respiratory-rate-monitoring.md`, `vitale-2019-athlete-sleep-hygiene.md`, `robergs-2002-hrmax-formula-critique.md`, `grosicki-2025-whoop-adherence-outcomes.md`, `whoop-2025-healthspan-whitepaper.md`

</details>

<details>
<summary><strong>N-of-1 Methodology — 5 notes</strong></summary>

The meta-framework that justifies treating my own data seriously — single-subject experimental design as rigorous science, not just self-tracking.

- **Schork (2015, 2022):** Population RCTs tell you what works *on average*. N-of-1 trials tell you what works *for this person*. The philosophical backbone for why I treat my longitudinal data as an actual experiment.
- **Daza (2018):** Counterfactual inference in single-subject designs. How to ask "did this protocol work?" without a control group — comparing windows of the same individual rather than against a population baseline.
- **Piccininni et al. (2025):** Causal inference methods for N-of-1 designs. Grounds the correlation cards (sleep→recovery, HRV→readiness) in causal rather than purely associational framing.

**Notes:** `schork-2015-personalized-medicine-one-person-trials.md`, `schork-2022-exploring-human-biology-nof1.md`, `daza-2018-counterfactual-nof1.md`, `piccininni-2025-causal-inference-nof1.md`, `konigorski-digital-nof1-experimental-physiology.md`

</details>

<details>
<summary><strong>LLM Engineering & RAG — 67 notes</strong></summary>

The domain that informs how the vault retrieval itself is built — I read this research while designing the system.

- **Self-RAG (2023):** Adaptive retrieval where the model decides *when* to retrieve. Informs why I do signal-ranked retrieval rather than always dumping all notes into context.
- **ReAct (Reasoning + Acting):** Chain-of-thought combined with tool use. The mental model for how the AI advisor uses live health data alongside vault research.
- **Reflexion (Shinn et al., 2023):** Verbal RL via reflection. Why `validate_plan()` explains violations to Claude rather than just rejecting silently.
- **Constitutional AI (Bai et al., 2022):** Anthropic's safety-through-self-critique framework. Context for how Claude's safety behaviors interact with clinical coaching instructions.

**Notes:** `retrieval-augmented-generation.md`, `self-rag.md`, `react-synergizing-reasoning-and-acting.md`, `shinn-2023-reflexion-verbal-rl.md`, `hypothetical-document-embeddings.md`, `bai-2022-constitutional-ai.md`, `cognitive-architectures-for-language-agents.md`, `vector-embeddings.md`, `reranking.md`

</details>

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

**⚡ Command Briefing**
The top card. Green/yellow/red, the score, the three signals that drove it, and a paragraph from Claude explaining what it means for today. This is the whole point — one read, one decision.

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

### The Sports-Science Strip

Six newer panels stack between the daily-readiness row and the legacy Strength / Cardio panels:

| Panel | What it shows |
|---|---|
| **Periodization** | Mesocycle phase strip (W-of-N, deload-week amber) + CTL/ATL/TSB sparkline with form label |
| **After-Action** | Per-exercise Hevy-driven autoreg: actuals vs plan, next-session weight suggestion, verdict tint |
| **Clinical Research Signals** | Six peer-reviewed tiles — SRI, lnRMSSD, red-streak, allostatic load, drug-adjusted HRV, Z2 drift |
| **Fueling** | Body comp strip (weight / BF% / lean mass) + macros (kcal in/out/balance, protein g/kg, hydration) + 14d energy-balance bar chart |
| **Research Lab** | Six pre-registered hypothesis cards with CONFIRMED / REFUTED / INCONCLUSIVE / INSUFFICIENT verdicts; "Run all" button refreshes findings on demand |

### Trend Intelligence

Five tabs I open when I want to dig into something:

| Tab | What's in it |
|---|---|
| **Recovery** | 90-day HRV, recovery score, RHR with 28d moving average |
| **Body** | Weight trend, 4-week regression line, Apple Health sync |
| **Patterns** | Sleep vs recovery and HRV vs readiness scatter plots — Pearson-r per plot |
| **Insights** | Computed correlation cards, unlocks after 7 days of data |
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
| Database | DuckDB 1.1 (encrypted, 22 migrations) |
| Background | APScheduler 3.10 |
| HTTP | httpx 0.28 (async) |
| XML | lxml 5 (Apple Health CCDA) |
| Credentials | macOS Keychain via `keyring` |
| AI | Anthropic SDK 0.40 (Claude Opus 4.7) |
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

**Infrastructure:** Honcho (`Procfile`) — API `:8000`, frontend `:3000` · GitHub Actions CI (ruff, pyright, pytest on push to main)

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

<details>
<summary>Schema — 21 tables, 4 views (22 migrations applied)</summary>

```sql
measurements        -- Apple Health time-series (metric, ts, value, unit, content_hash)
                    -- captures dietary energy/protein/carbs/fat/fiber/water/sodium/caffeine + lean body mass
workouts            -- WHOOP + Hevy sessions (strain, HR, kcal, kind)
workout_sets        -- Strength sets (exercise, reps, weight_kg, rpe, is_warmup)
sleep               -- Multi-source — sws_min, rem_min, light_min, awake_min, sleep_efficiency_pct,
                    --   sleep_consistency_pct, disturbance_count, sleep_needed_min,
                    --   respiratory_rate, sleep_cycle_count, in_bed_min, no_data_min,
                    --   sleep_need_baseline_min, sleep_need_strain_min, sleep_need_nap_min, sleep_need_debt_min
recovery            -- WHOOP (date, score, hrv, rhr, skin_temp, spo2_pct, user_calibrating)
cardio_sessions     -- Manual + integrations (modality, duration, avg_hr, rpe, zones,
                    --   zone_zero_min…zone_five_min, zone_distribution_json, percent_recorded,
                    --   sport_id, sport_name, distance_meter)
daily_cycle         -- WHOOP daily cycle (date, strain, kilojoule, avg_hr, max_hr, score_state)
body_measurement    -- WHOOP body measurements (height_meter, weight_kg, max_heart_rate, synced_at)
whoop_user_profile  -- WHOOP user profile (user_id, email, first_name, last_name, synced_at)
working_weights     -- Current e1RM per exercise
workout_plans       -- AI-generated plans (plan_json, date)
workout_retrospectives  -- Post-workout summaries (completion_pct, overload_flag, vault_insights)
plan_adherence      -- Prescription vs execution
daily_checkin       -- Morning survey
medications         -- Active medications with audit trail
conditions          -- Diagnoses
labs                -- Lab results with reference ranges
mesocycles          -- Active periodization block (started_on, planned_weeks, deload_trigger)
muscle_volume_targets   -- MEV / MAV / MRV per muscle group, per mesocycle
lab_questions       -- Pre-registered hypothesis catalogue (id, hypothesis, test_type, threshold, vault_ref)
lab_findings        -- Per-run results (verdict, n, effect_size, p_value, evidence)
schema_version      -- 22 migrations applied
```

```sql
v_hrv_baseline_28d      -- Rolling 28d HRV mean and SD (for σ-deviation)
v_session_load          -- Per-day load from WHOOP strain + Hevy volume (filters percent_recorded ≥ 50%)
v_daily_load            -- Composite load — true Gabbett ACWR denominator + Banister CTL/ATL input
workout_sets_dedup      -- Deduped sets (handles Hevy sync collisions)
```

</details>

---

## Privacy

Everything runs on my MacBook. Nothing goes to a cloud. The database is encrypted at rest (DuckDB + Keychain key). OAuth tokens live in Keychain, not on disk. The API is localhost-only behind a session token. Clinical details are loaded at runtime from a gitignored file — they're not in version control.

---

## Running It

This is a personal tool built for my specific setup — WHOOP, Hevy, Apple Health export, macOS Keychain. It's not packaged for general use, but if you want to poke around:

```bash
git clone https://github.com/robsavage619/savage-labs
cd savage-labs

make install

cp env.example .env
# ANTHROPIC_API_KEY, WHOOP_CLIENT_ID, WHOOP_CLIENT_SECRET

make seed    # seeds 90 days of synthetic data
make dev     # API on :8000, frontend on :3000
```

| Command | Does |
|---|---|
| `make dev` | Start everything |
| `make seed` | 90 days synthetic data |
| `make doctor` | Check config, DB, AI spend |
| `make reset` | Nuclear option (`CONFIRM=1`) |
| `make lint` | ruff |
| `make typecheck` | pyright |
| `make test` | pytest |

---

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=6,11,20,25,30&height=120&section=footer" width="100%" />

*Built by Rob Savage — because no existing tool understood my whole picture.*

</div>
