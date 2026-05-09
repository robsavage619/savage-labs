<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=6,11,20,25,30&height=220&section=header&text=SAVAGE+LABS&fontSize=72&fontColor=ffffff&animation=fadeIn&fontAlignY=40&desc=A+personal+health+OS+%E2%80%94+not+a+wellness+app&descAlignY=63&descSize=19" width="100%" />

<br />

```
███████╗ █████╗ ██╗   ██╗ █████╗  ██████╗ ███████╗
██╔════╝██╔══██╗██║   ██║██╔══██╗██╔════╝ ██╔════╝
███████╗███████║██║   ██║███████║██║  ███╗█████╗
╚════██║██╔══██║╚██╗ ██╔╝██╔══██║██║   ██║██╔══╝
███████║██║  ██║ ╚████╔╝ ██║  ██║╚██████╔╝███████╗
╚══════╝╚═╝  ╚═╝  ╚═══╝  ╚═╝  ╚═╝ ╚═════╝ ╚══════╝

██╗      █████╗ ██████╗ ███████╗
██║     ██╔══██╗██╔══██╗██╔════╝
██║     ███████║██████╔╝███████╗
██║     ██╔══██║██╔══██╗╚════██║
███████╗██║  ██║██████╔╝███████║
╚══════╝╚═╝  ╚═╝╚═════╝ ╚══════╝
```

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

## The Problem

Consumer health tools are siloed by design.

WHOOP scores your recovery but knows nothing about your medications. Apple Health collects thousands of data points that never inform your training. Workout trackers schedule sessions without knowing you slept five hours. No tool fuses all three signals into a single coherent decision.

Savage Labs is the system built to fix that.

It ingests every available data stream — biometric wearables, workout logs, clinical labs, self-reported check-ins — fuses them server-side into a typed, versioned health contract, and runs that contract through a Claude Opus 4.7 reasoning layer that understands medication history, adjusts intensity recommendations accordingly, and delivers a single daily readiness decision.

> [!IMPORTANT]
> Everything is local. Everything is encrypted. Nothing leaves the machine.

---

## What Makes This Non-Trivial

This isn't a CRUD app wrapping a few API calls. Four engineering decisions separate it from the category:

> **Signal fusion over raw display.**
> Most dashboards surface raw numbers. Savage Labs computes *derived* signals: HRV σ-deviation relative to a 28-day medication-adjusted baseline, true Gabbett ACWR from composite load (wearable strain + strength tonnage), a weighted readiness composite that *shifts its own weights* based on whether a beta-blocker was taken. Raw numbers require interpretation. Derived signals make the decision.

> **Clinical context in every LLM call.**
> The briefing and workout planner don't call Claude with a health snapshot. They call Claude with a health snapshot *plus* active medications with dosing schedules, current diagnoses, recent lab results with reference ranges, and computed gates encoding hard constraints the model must respect. This separates a wellness chatbot from a medically-aware advisor.

> **Deterministic gates below the LLM.**
> Claude generates the plan. `validate_plan()` enforces it. If the model produces a high-intensity leg session when the gates say legs are under 48h of rest, the plan is rejected and the model is called again — not patched, not warned, rejected. The LLM layer is for reasoning; the gate layer is for correctness.

> **One source of truth, computed once.**
> `DailyState` is computed server-side at request time via `compute_daily_state()` and consumed by every downstream consumer — the dashboard, the briefing system, the workout planner. No component recomputes what another already owns.

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
│  conditions    │  labs      │  working_weights│  workout_plans  │
│                                                                 │
│  Views: v_hrv_baseline_28d, v_session_load, v_daily_load       │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      METRICS ENGINE                             │
│                  compute_daily_state()                          │
│                                                                 │
│  HRV σ-deviation  │  True ACWR  │  Sleep composite             │
│  Readiness score  │  Gates      │  Epley e1RM                  │
│  Push:pull ratio  │  Zone calc  │  Regression detection        │
└──────────┬────────────────────────────────┬─────────────────────┘
           │                                │
           ▼                                ▼
┌──────────────────────┐      ┌─────────────────────────────────┐
│    FastAPI REST       │      │         AI LAYER                │
│    50+ endpoints      │      │                                 │
│                       │      │  build_daily_context()          │
│  /api/state/today     │      │  build_training_context()       │
│  /api/workout/generate│      │  build_clinical_context()       │
│  /api/chat            │      │  load_vault_research()          │
│  /api/briefing        │      │                                 │
│  /api/insights        │      │  Claude Opus 4.7                │
│  /api/hevy/push       │      │  → validate_plan()              │
│  /api/vault/search    │      │  → Ollama fallback (air-gapped) │
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
└─────────────────────────────────────────────────────────────────┘
```

---

## Engineering Highlights

### `DailyState` — The Health Contract

Every metric the system produces flows through a single typed dataclass computed once per day:

```python
@dataclass
class DailyState:
    as_of: str
    recovery: RecoveryMetrics      # WHOOP score, HRV ms, RHR, skin temp
    sleep: SleepMetrics            # duration, deep%, REM%, SpO2, debt
    training_load: TrainingLoadMetrics  # ACWR, acute/chronic, muscle group rest
    checkin: CheckinMetrics        # energy, stress, soreness, medication flag
    readiness: ReadinessSnapshot   # composite score, tier, component weights
    gates: AutoRegGates            # deterministic intensity constraints
    freshness: DataFreshness       # staleness flags per source
```

The frontend reads `/api/state/today`. The LLM briefing injects it as context. The workout planner extracts gates from it. One computation, N consumers, zero drift.

---

### HRV σ-Deviation

Raw HRV in milliseconds is nearly useless for day-to-day decisions — population baselines don't account for medications, training phase, or individual physiology. The system computes a 28-day rolling mean and standard deviation via a materialized view, then expresses today's value as a σ-deviation:

```
hrv_sigma = (today_hrv_ms − 28d_mean) / 28d_stdev
subscore  = clamp(50 + sigma × 25, 0, 100)
```

| σ value | Interpretation | Score |
|---|---|---|
| `+2.0` | Peak recovery | 100 |
| `0.0` | Baseline | 50 |
| `−2.0` | Suppressed | 0 |

This makes the signal medication-invariant: SSRIs and beta-blockers shift the baseline, not the deviation. Two athletes with different HRV baselines get meaningful, comparable readiness signals.

---

### True Gabbett ACWR

Most training load models count session count or subjective RPE. This system computes the true Gabbett acute:chronic workload ratio from a composite load that fuses WHOOP strain (cardiovascular load) with Hevy training tonnage (mechanical load):

```
composite_load_day = whoop_strain + (hevy_tonnes × 5000)

acute_7d    = mean(composite_load, last 7 days)
chronic_28d = mean(composite_load, last 28 days)
acwr        = acute_7d / chronic_28d
```

| ACWR | Zone | Action |
|---|---|---|
| `< 0.8` | Under-loaded | Insufficient stimulus |
| `0.8 – 1.3` | ✅ Safe zone | Adaptive overload |
| `1.3 – 1.5` | ⚠️ Elevated risk | Volume reduction gate |
| `> 1.5` | 🚨 Critical overload | Rest mandated |

---

### Weighted Readiness with Beta-Blocker Adaptation

The readiness composite isn't static. It shifts its own weight vector based on whether a beta-blocker was detected:

| Signal | Default | Beta-Blocker Day | Reason |
|---|---|---|---|
| HRV σ | **40%** | 20% | Suppressed by medication, less reliable |
| Sleep | 30% | **40%** | Becomes primary recovery indicator |
| RHR | 20% | **25%** | Relative elevation still meaningful |
| Subjective | 10% | 15% | |

Detection is dual-gated: the medications table must have an active entry *and* the morning check-in must have `propranolol_taken = true`. Both required — prevents phantom adjustments from stale records.

**Tier thresholds:** ≥67 → 🟢 GREEN · 34–66 → 🟡 YELLOW · <34 → 🔴 RED

---

### Auto-Regulation Gate Engine

`AutoRegGates` encodes 13 hard constraints derived from physiology literature. These are not LLM suggestions — they're deterministic rules enforced *after* generation:

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
<summary>Selected gate logic (13 rules)</summary>

| Condition | Gate Fired |
|---|---|
| ACWR > 1.5 | `max_intensity = "rest"` |
| Skin temp Δ ≥ 0.5°C | Z2 only — possible illness |
| Muscle group < 48h (72h compound legs) | Group forbidden |
| Compound soreness ≥ 2 muscles at severity 2 | Cap to moderate |
| e1RM regression > 3% over 4 weeks | `deload_required = True` |
| Beta-blocker dosed | HR zones −20 bpm, kcal ×1.25 |
| ACWR > 1.3 | Cap to moderate |
| Readiness RED | Cap to low |
| Illness flag | Rest day — no training |
| Travel flag | Cap to moderate |
| Sleep < 5h | No PR attempts |
| Acute soreness ≥ 3 on muscle | Group forbidden |
| HRV σ < −1.5 | Cap intensity to low |

</details>

If the LLM-generated plan violates any gate, `validate_plan()` rejects it and triggers a re-call with the violations appended to the prompt. The LLM never has unchecked authority over the training prescription.

---

### Clinical Context Injection

Every Claude invocation (chat, briefing, workout planning) includes a structured clinical context block built from live database state:

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

The `HEALTH_SYSTEM` prompt encodes drug-class interpretation rules that persist across all calls — beta-blockers require zone-shift, SSRIs shift the HRV baseline, inhaled corticosteroids flag for metabolic context. The model doesn't need to synthesize general pharmacology from training data; the system tells it what's relevant for this athlete today.

---

### Epley e1RM Tracking & Regression Detection

Every strength set is stored with weight and rep count. The system computes an estimated 1RM via the Epley formula:

```
e1RM = weight_kg × (1 + reps / 30)
```

A 4-week regression detector compares the top 50th percentile of e1RM over the most recent 56 days against the prior 56 days:

```
regression_pct = (mean(e1RM, days 0–27) − mean(e1RM, days 28–55))
               / mean(e1RM, days 28–55)
```

If regression exceeds 3%, `deload_required = True` is injected into gates. The system detects accumulating fatigue before injury does.

---

### Multi-Source Ingestion with Content-Hash Deduplication

Four independent data pipelines converge into the same DuckDB tables:

| Source | Method | Parser |
|---|---|---|
| **WHOOP** | OAuth 2.0 + APScheduler (60 min) | Async HTTP, token refresh on 401 |
| **Apple Health** | iCloud HealthAutoExport → CCDA XML | lxml + type-router to correct table |
| **Hevy** | REST API + push routine export | Async client, set-level granularity |
| **Manual** | FastAPI POST endpoints | Pydantic v2 validation |

Every ingested record is fingerprinted:

```python
content_hash = hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest()
```

Upserts key on `(source, external_id, content_hash)`. Retries are idempotent. Sync is additive, never destructive.

> [!NOTE]
> OAuth tokens (WHOOP, Hevy) never touch disk — stored in and retrieved from macOS Keychain via `keyring`. The DuckDB file itself is encrypted at rest with a key fetched from Keychain at startup.

---

### HR Zone Calculation with Medication Adjustment

HRmax uses the Tanaka formula (lower error than Fox 220−age for trained adults 30–60):

```
HRmax          = 208 − (0.7 × age)
adjusted_HRmax = HRmax − hr_zone_shift_bpm    # -20 on beta-blocker days
```

On beta-blocker days, the gate engine injects a −20 bpm shift before zone calculation. Without this, every cardio session would appear to be in a higher zone than it actually is — caloric and physiological interpretation would both be wrong.

---

## Obsidian Vault — Retrieval-Augmented Training Intelligence

The system's third AI input (alongside live biometrics and clinical context) is a personal exercise science knowledge base built in Obsidian and stored at `~/Vault/savage_vault/wiki/`. Every workout plan and daily briefing is grounded in this vault — not in the model's general training knowledge.

> [!NOTE]
> **Why a personal vault over general LLM knowledge?** LLMs know exercise science in aggregate. The vault encodes *specific protocol decisions* — which exercise selection framework this athlete follows, what rest intervals are calibrated for this training phase, which meta-analyses are trusted. The model is told which evidence base to apply, not left to synthesize one from training data.

### Signal-Ranked Note Retrieval

`load_vault_research()` selects the top 4 most-relevant notes based on today's health signals:

```python
signals = {
    "hrv_anomaly",         # HRV σ-deviation < -1.0
    "high_acwr",           # ACWR > 1.3
    "deload",              # gates.deload_required = True
    "illness",             # checkin.illness_flag = True
    "poor_sleep",          # last night < 6h
    "push_pull_imbalance", # 28d ratio > 1.2 or < 0.8
    "volume_spike",        # 4-week volume Δ > 40%
    "recomposition",       # always active (primary goal)
    "exercise_selection",  # always active
}
```

Each vault note carries YAML frontmatter tags. The retriever scores every note by matching tags against active signals — `+2` per specific signal match, `+1` for default. A deload note scores +6 on a high-ACWR/low-HRV day and surfaces automatically.

```yaml
---
tags: [overtraining, deload, hrv, recovery, acwr]
---
```

### Pinned Exercise Science Foundation

Six notes load unconditionally on every workout generation call, never competing with situational notes:

```
exercise-selection-strength.md        — movement pattern selection rules
exercise-selection-hypertrophy.md     — muscle group prioritization
exercise-order-strength.md            — compound-before-isolation ordering
schoenfeld-2010-hypertrophy-mechanisms.md — mechanical tension, metabolic stress, damage
rest-interval-hypertrophy.md          — optimal inter-set rest for hypertrophy
rest-interval-strength.md             — optimal inter-set rest for strength
```

### Section Extraction

Raw vault notes contain literature review, citations, caveats. The retriever strips everything except sections the model can act on:

```
## Summary             → high-level principle
## Prescription        → actionable protocol
## Key Claims          → evidence anchors
## Practical Takeaways → direct application
## Exercise Selection Rules → selection logic
```

A 3,000-word note is condensed to the 400-word prescription block. Context window stays efficient; the model reasons from conclusions, not from re-derived literature.

### Vault Insights — Required Plan Artifact

Every generated workout plan must include a `vault_insights` array. The backend validates this:

```python
if not plan.get("vault_insights"):
    raise ValueError("vault_insights is empty — must cite research")
```

The frontend renders these attributed with the Obsidian logo:

```
┌─ FROM YOUR VAULT ─────────────────────────────────────────┐
│  ◈  · Rest 90–120s between compound sets per              │
│       rest-interval-strength.md                           │
│     · Upper pull emphasis applied — push:pull at 1.35     │
│       per exercise-selection-hypertrophy.md               │
│     · Volume capped — ACWR at 1.38, within 10% of         │
│       deload threshold per overtraining-and-deload.md     │
└───────────────────────────────────────────────────────────┘
```

This creates an auditable chain: plan decision → vault note → evidence.

### Architecture: Read-Only, No Sync

```
Obsidian (editor) → ~/Vault/savage_vault/wiki/*.md → load_vault_research() → Claude context
                                                   → /api/vault/search    → AI Advisor
```

The vault is strictly input. No note is ever created, modified, or deleted by the system.

---

## Dashboard

The dashboard is a single-page React application structured around eight discrete zones:

<table>
<tr>
<td width="50%">

**⚡ Command Briefing**
Today's readiness tier (GREEN / YELLOW / RED), composite score, the three signals that drove it (HRV σ, sleep, ACWR), and a Claude-generated narrative synthesizing everything into a single recommendation.

**📡 Biometric HUD**
Persistent header strip with live WHOOP + Hevy sync-status badges, real-time vitals (recovery, HRV, RHR, strain), and data-age indicators.

**🫀 Recovery Intelligence**
WHOOP recovery ring with 7-night HRV sparkline and ±1σ band. Points outside the band are colored to flag anomalous nights.

**😴 Sleep Architecture**
Stacked bar across 7 nights (total / deep / REM), sleep debt accumulator, per-night SpO2. Weighted for sleep-disordered breathing context.

</td>
<td width="50%">

**🏋️ Training Load**
ACWR trend with safe-zone band (0.8–1.3), weekly volume by muscle group, push:pull ratio, monotony index.

**🎯 Readiness Composite**
Score and component breakdown with visual indication of active weight vector. Gate reasons rendered in natural language.

**💬 AI Advisor** `⌘K`
Full Claude chat with `build_daily_context()` injected per-message — the model always has today's DailyState, medications, diagnoses, labs, training history, and gates.

**🌊 Ambient Layer**
Full-page gradient keyed to readiness score. Hue shifts green → neutral → red as readiness falls. Communicates system state before a number is read.

</td>
</tr>
</table>

### Trend Intelligence — Five-Tab Deep Dive

| Tab | Content |
|---|---|
| **Recovery** | 90-day rolling HRV, recovery score, RHR time series with 28d moving average |
| **Body** | Weight trend with 4-week regression line, target range band, Apple Health sync |
| **Patterns** | Scatter plots: sleep vs recovery, HRV vs readiness — Pearson-r with confidence range |
| **Insights** | Computed correlation cards — unlocks after 7 days of data |
| **Clinical** | Unified event timeline of medications, diagnoses, labs (abnormal flagged) |

### Today's Workout Plan

AI-generated via Claude Opus 4.7 with full `DailyState` + clinical context + ranked vault research. Structured as blocks (warm-up / main / accessory) with exercises, sets × reps, target weight, RPE, coaching notes, and vault citations. Cached per day; `?regen=true` forces a fresh call. **Push to Hevy** button exports the plan as a live routine via the Hevy REST API.

---

## AI Integration

### Briefing System

`shc/ai/briefing.py` builds two context blocks per call:

**`build_daily_context()`** injects: DailyState (all computed metrics), 28-day cardio composition (Z2 vs threshold vs VO2max minutes), push:pull imbalance direction, skin-temp delta from baseline, active medications with dosing and onset, active conditions, recent labs with reference ranges, training history (PRs, volume trend, last session per muscle group), gate reasons, and signal-ranked vault research.

**`build_clinical_context()`** structures the clinical data as a dedicated markdown block that appears early in the system prompt.

### Workout Planner

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
        → session goals (duration target, focus areas)
```

`validate_plan()` checks every field against gates — accepts or rejects + re-calls. Response cached 24h.

### Air-Gapped Fallback

`SHC_LLM_MODE=local_only` routes all calls to a local Ollama instance (`llama3.3:70b`). Full clinical context injection preserved. Functions offline with no data leaving the machine.

### Cost Management

`ANTHROPIC_DAILY_CAP_USD` (default `$2.00`) limits daily Claude API spend. All calls log token usage and cost to `data/logs/`. `make doctor` reports current-day spend and remaining budget.

---

## Data Sources

| Source | Protocol | Data |
|---|---|---|
| **WHOOP 4.0** | OAuth 2.0, background sync 60 min | Recovery 0–100, HRV (ms), RHR, strain, sleep stages, SpO2, skin temp |
| **Apple Health** | iCloud HealthAutoExport → CCDA XML | Steps, active energy, HR, HRV, sleep, blood pressure, body weight, glucose, temp |
| **Hevy** | REST API + routine push export | Exercises, sets, reps, weight (kg), RPE, timestamps |
| **Morning check-in** | Dashboard form | Energy, stress, motivation, sleep quality (1–10), medication flag, body weight, muscle soreness |
| **Cardio log** | Dashboard form | Sport, duration (min), average HR, RPE |
| **Clinical data** | Dashboard forms | Active medications (dose, frequency, onset), diagnoses, lab results with reference ranges |

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
| Database | DuckDB 1.1 (encrypted, 14 migrations) |
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

**Infrastructure:** Honcho (`Procfile`) — API `:8000`, frontend `:3000` · GitHub Actions CI (ruff, pyright, pytest) · `make install / dev / seed / reset / doctor / lint / test`

---

## Design System

The frontend uses OKLCH (Oklab Lightness-Chroma-Hue) — a perceptually uniform color space where green, yellow, and red at the same lightness value look equally bright to the human eye. In sRGB, greens appear brighter and reds appear darker at the same hex value. OKLCH eliminates that.

<table>
<tr>
<th>Status</th>
<th>Value</th>
<th>Meaning</th>
</tr>
<tr>
<td>🟢 Ready</td>
<td><code>oklch(0.72 0.18 145)</code></td>
<td>Full intensity — push hard</td>
</tr>
<tr>
<td>🟡 Moderate</td>
<td><code>oklch(0.78 0.15 85)</code></td>
<td>Proceed with caution</td>
</tr>
<tr>
<td>🔴 Rest</td>
<td><code>oklch(0.65 0.22 20)</code></td>
<td>Recovery work only</td>
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

**Typography:** `Orbitron 900` — KPI numbers, tier labels, eyebrows · `Geist Sans` — body copy · `Geist Mono` — tabular data, metrics

---

## Data Model

<details>
<summary>Core tables (14 + 4 views)</summary>

### Core Tables

```sql
measurements        -- Apple Health time-series (metric, ts, value, unit, content_hash)
workouts            -- WHOOP + Hevy sessions (strain, HR, kcal, kind)
workout_sets        -- Strength sets (exercise, reps, weight_kg, rpe, is_warmup)
sleep               -- Multi-source (stages_json, spo2_avg, hrv, rhr, night_date)
recovery            -- WHOOP (date, score, hrv, rhr, skin_temp)
cardio_sessions     -- Manual + integrations (modality, duration, avg_hr, rpe, zones)
working_weights     -- Current e1RM per exercise (updated per session)
workout_plans       -- AI-generated plans (plan_json, source, date)
workout_retrospectives  -- Post-workout summaries (completion_pct, overload_flag, vault_insights)
plan_adherence      -- Prescription vs execution (avg_rpe_actual vs target)
daily_checkin       -- Morning survey (energy, stress, soreness, medication, body_weight)
medications         -- Active medications with audit trail (valid_to for history)
conditions          -- Diagnoses (status, onset, valid_to)
labs                -- Lab results (value, ref_low/high, panel, is_abnormal, collected_at)
schema_version      -- Migration tracking (14 applied)
```

### Materialized Views

```sql
v_hrv_baseline_28d      -- Rolling 28d HRV mean and SD per date (for σ-deviation)
v_session_load          -- Per-day load from WHOOP strain + Hevy volume
v_daily_load            -- Composite load — true Gabbett ACWR denominator
workout_sets_dedup      -- Deduped sets (handles Hevy sync collisions on retry)
```

</details>

---

## Security & Privacy

> [!WARNING]
> This system handles sensitive personal health data. The following properties are non-negotiable.

- ✅ **No cloud storage** — all data stays on-device; no telemetry, no third-party analytics
- ✅ **Encrypted database** — DuckDB encrypted at rest; `PRAGMA key` set from Keychain at startup
- ✅ **Keychain-only credentials** — OAuth tokens and API keys never touch disk
- ✅ **Localhost only** — FastAPI requires a session token; not exposed to the internet
- ✅ **Idempotent ingestion** — content-hash dedup prevents double-counting on sync retry
- ✅ **Personal context gitignored** — clinical details loaded at runtime from `backend/data/` (not committed)

---

## Quickstart

**Prerequisites:** Python 3.12+, Node 20+, [uv](https://github.com/astral-sh/uv), macOS (Keychain required)

```bash
git clone https://github.com/robsavage619/savage-health-center
cd savage-health-center

make install

cp env.example .env
# Three required values:
# ANTHROPIC_API_KEY   — console.anthropic.com
# WHOOP_CLIENT_ID     — developer.whoop.com
# WHOOP_CLIENT_SECRET — developer.whoop.com

make seed    # 90 days of synthetic data + run migrations
make dev     # FastAPI :8000 + Next.js :3000
```

### Commands

| Command | What it does |
|---|---|
| `make dev` | Start API + frontend via Honcho |
| `make seed` | Seed 90 days of synthetic data |
| `make reset` | Drop and rebuild database (`CONFIRM=1` required) |
| `make doctor` | Verify config, DuckDB, Ollama status, daily AI spend |
| `make logs` | Tail all service logs |
| `make lint` | Run ruff |
| `make typecheck` | Run pyright |
| `make test` | Run pytest suite |

### LLM Modes

```bash
SHC_LLM_MODE=auto        # Claude Opus 4.7 with Ollama fallback (default)
SHC_LLM_MODE=local_only  # Ollama only — air-gapped, no Anthropic calls
```

---

<div align="center">

<img src="https://capsule-render.vercel.app/api?type=waving&color=gradient&customColorList=6,11,20,25,30&height=120&section=footer" width="100%" />

*Built by Rob Savage — senior software engineer, FinOps architect, and one person who wanted a health system that understood his whole picture.*

</div>
