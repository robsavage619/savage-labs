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

The system's third AI input — alongside live biometrics and clinical context — is a personal knowledge base of **405 research notes** built in Obsidian at `~/Vault/savage_vault/wiki/`. Every workout plan and daily briefing is grounded in this vault, not in the model's general training knowledge.

> [!NOTE]
> **Why a personal vault over general LLM knowledge?** LLMs know exercise science in aggregate. The vault encodes *specific protocol decisions* — which exercise selection framework this athlete follows, what rest intervals are calibrated for this training phase, which meta-analyses are trusted over which guidelines. The model is told which evidence base to apply, not left to synthesize one from training data.

### What's In It

**405 notes across 10 domains.** Every note is ingested from primary sources — textbooks, meta-analyses, RCTs — then structured with YAML frontmatter tags and actionable prescription sections. The vault is a personal distillation of the research, not summaries of summaries.

<details>
<summary><strong>Strength & Hypertrophy — 147 notes</strong></summary>

The largest domain. Built primarily from Schoenfeld's *Science and Development of Muscle Hypertrophy* (2021), Israetel's *Scientific Principles of Hypertrophy Training* (2020), Helms' *Muscle & Strength Pyramid* (Training vol., 2018), and Bompa/Zatsiorsky's periodization texts.

**Key prescriptions encoded:**

- **Volume landmark (Schoenfeld 2016 meta-analysis, 15 studies):** ≥10 working sets per muscle group per week to maximize hypertrophy. +0.37% hypertrophy per additional weekly set across 2–30 set range.
- **Hypertrophy mechanisms (Schoenfeld 2010):** Mechanical tension is primary driver; metabolic stress and muscle damage are secondary. Notes encode this hierarchy into exercise selection rules — ROM, load at stretch, time under tension weighting.
- **Rest intervals:** 90–120s minimum between compound sets for hypertrophy; 180–300s for strength. Schoenfeld (2016): longer rest superior for both strength and hypertrophy vs the "metabolic stress" shorter-rest hypothesis.
- **Exercise order:** Compound movements before isolation within a session; highest-priority muscle groups first within a training block.
- **Range of motion:** Full ROM superior to partial ROM for hypertrophy; lengthened-position loading (e.g. deficit RDLs, stretched-position flies) produces greater hypertrophic stimulus per the Pedrosa (2022) and Maeo (2021) findings.
- **DUP periodization structure:** Daily undulating periodization — distinct rep ranges across sessions within a week (strength day 3–5 reps, hypertrophy day 8–12, endurance day 15–20) — produces superior gains vs linear periodization for trained athletes.
- **SRA curves by muscle group:** Stimulus-recovery-adaptation timelines encoded per muscle (quads 72h compound, biceps 48h, delts 36–48h) — these directly feed the `forbid_muscle_groups` gate logic.
- **Supercompensation theory:** Volume landmarks → MEV (minimum effective volume) → MAV (maximum adaptive volume) → MRV (maximum recoverable volume). Training above MRV triggers deload signal.
- **Concurrent training interference:** Cardio modality and timing relative to strength sessions. Low-interference: cycling Z2 post-strength. High-interference: running before strength, same-day HIIT.

**Specific notes feeding the planner:**
`exercise-selection-strength.md`, `exercise-selection-hypertrophy.md`, `exercise-order-strength.md`, `rest-interval-strength.md`, `rest-interval-hypertrophy.md`, `range-of-motion-hypertrophy.md`, `training-volume-hypertrophy.md`, `training-frequency-hypertrophy.md`, `schoenfeld-2016-rt-volume-hypertrophy.md`, `schoenfeld-2021-science-development-muscle-hypertrophy.md` (9 chapters), `sra-training-frequency.md`, `supercompensation-theory.md`, `fitness-fatigue-theory.md`, `overreaching-detection.md`, `concurrent-training-interference.md`

</details>

<details>
<summary><strong>Sleep Science — 76 notes</strong></summary>

Built from Walker's *Why We Sleep* (2017, 16 chapters) and Winter's *The Sleep Solution* (2017, 16 chapters), with primary research on HRV monitoring during sleep, OSA, and sleep × performance.

**Key findings encoded:**

- **6–7h sleep demolishes immune function** (Walker Ch1); 2× cancer risk vs 8h; ghrelin ↑ drives ~300 kcal/day excess intake on sleep-deprived days. This underpins the sleep debt accumulator in the dashboard.
- **Sleep architecture targets:** N3 (slow-wave / deep) consolidates physical recovery and growth hormone release; REM consolidates motor learning and emotional regulation. Both tracked separately in the sleep pillar.
- **SpO2 threshold:** <95% SpO2 average flags sleep-disordered breathing — weighted higher than duration in the composite sleep score for this specific use case.
- **Sleep state misperception:** Subjective sleep quality often diverges from objective stage data. The morning check-in captures subjective quality (1–10) as a separate signal from WHOOP's objective staging.
- **Circadian anchoring:** Consistent wake time > consistent bed time for circadian stability (Winter Ch7, Ch12).
- **Stimulus control protocol:** Encoded from Winter Ch9 — bed is only for sleep; remove stimulus association. Feeds the sleep hygiene advisory in the AI advisor.
- **Fatal Familial Insomnia (Walker Ch12):** Genetic progressive insomnia → death in 12–18 months. Encoded as context for why sleep monitoring is non-negotiable, not optional.

**Notes in vault:** `walker-2017-why-we-sleep.md` (Ch1–16 individually), `winter-2017-sleep-solution.md` (Ch1–16), `sleep-spindles.md`, `sleep-learning-consolidation.md`, `obstructive-sleep-apnea.md`, `biphasic-sleep.md`, `napping-protocol.md`, `stimulus-control-protocol.md`, `rem-dreaming-mechanisms.md`, `dolezal-2017-sleep-exercise-review.md`

</details>

<details>
<summary><strong>Nutrition — 55 notes</strong></summary>

Built primarily from Israetel's *Renaissance Diet 2.0* (2020, 17 chapters) and Helms' *Muscle & Strength Pyramid: Nutrition* (2016), with Attia's *Outlive* (2023) for metabolic health context.

**Key prescriptions encoded:**

- **Diet priority pyramid (Israetel Ch1):** Adherence > calorie balance > macronutrients > nutrient timing > food choice > supplements. This ordering determines what the AI advisor emphasizes first.
- **Body recomposition conditions:** Possible in three cases — new to resistance training, returning after layoff, or using PEDs. For a trained athlete in neither state, simultaneous gain and loss requires precise calorie cycling. Encoded as a constraint on what Claude will recommend.
- **Protein targets:** 0.7–1.0g/lb body weight for muscle retention in a deficit; 1.0–1.2g/lb during a surplus. Minimum floor: 0.7g/lb at any calorie level.
- **Calorie deficit rate:** 0.5–1.0% body weight per week for fat loss while preserving muscle. Faster than 1% → elevated lean mass loss risk.
- **NEAT as primary TDEE lever:** Non-exercise activity thermogenesis accounts for the largest variable in TDEE. Encoded as the primary lever before adjusting food intake.
- **Peri-workout nutrition:** 20–40g protein within 2h post-training; intra-workout carbs for sessions > 75 min. Pre-workout: protein 1–2h pre.
- **Diet break / refeed protocol:** Planned maintenance phases every 4–12 weeks during deficit to restore leptin, reduce adaptive thermogenesis.
- **Supplementation tier list:** Tier 1: creatine monohydrate (3–5g/day), caffeine (3–6mg/kg pre-workout). Tier 2: vitamin D3+K2, omega-3. Tier 3: everything else. Tier list encoded to gate AI supplement recommendations.
- **Alcohol (Israetel Ch16):** Directly inhibits protein synthesis, reduces fat oxidation, disrupts sleep architecture. Flagged in the clinical notes when the check-in notes alcohol.

**Notes in vault:** `israetel-2020-renaissance-diet.md` (Ch1–17), `helms-2016-muscle-strength-pyramid-nutrition.md` (Ch1–7), `protein-target.md`, `calorie-deficit-fat-loss-rate.md`, `calorie-surplus-muscle-gain-rate.md`, `diet-break-refeed-protocol.md`, `diet-priority-pyramid.md`, `peri-workout-nutrition.md`, `nutritional-periodization.md`, `supplements-tier-list.md`, `supplement-creatine.md`, `supplement-caffeine.md`, `hunger-management.md`, `alcohol-and-performance.md`

</details>

<details>
<summary><strong>Longevity & Healthspan — 35 notes</strong></summary>

Built from Attia's *Outlive* (2023, 17 chapters). Frames every health metric in terms of the four horsemen of chronic disease: cardiovascular disease, cancer, neurodegeneration, metabolic dysfunction.

**Key prescriptions encoded:**

- **VO₂max as mortality predictor (Attia Ch11):** Bottom quartile → 4× all-cause mortality vs top quartile. No upper limit to benefit. The system tracks cardio zone distribution specifically to drive VO₂max improvement (Zone 2 base + Zone 5 intervals).
- **Centenarian Decathlon:** VO₂max, grip strength, leg press, single-leg balance, stair climb, carry test, floor-rise test, overhead press, gait speed. Encoded as the long-term performance targets that inform training prioritization.
- **Zone 2 training:** ~80% of aerobic volume at lactate threshold 1 (conversational pace). Mitochondrial density, fat oxidation capacity, metabolic flexibility. Encoded in cardio prescription logic.
- **ApoB as primary lipid target:** ApoB > LDL-C as the causal CV risk marker (Attia Ch7). Encoded to ensure the AI advisor references ApoB when lab context is injected, not just LDL.
- **APOE genotype:** APOE ε4 carriers have higher Alzheimer's risk, higher LDL absorption. Encoded as a condition interpretation rule — relevant if genetic testing is present in labs.
- **Compression of morbidity:** Goal is extending the health span — years of full function — not just lifespan. Frames training not as aesthetics but as investment in the last decade of life.
- **Grip strength (Attia Ch11):** Independent predictor of all-cause mortality; declines faster than VO₂max with age. Encoded as a non-negotiable training variable.

**Notes in vault:** `attia-2023-outlive.md` (Ch1–17), `four-horsemen-chronic-disease.md`, `centenarian-decathlon.md`, `vo2max-longevity.md`, `zone-2-training.md`, `compression-of-morbidity.md`, `grip-strength.md`, `apob.md`, `apoe.md`, `lp-a.md`, `medicine-3-0.md`, `cgm.md`

</details>

<details>
<summary><strong>HRV & Biometric Research — 15 notes</strong></summary>

Primary research on HRV monitoring, wearable validation, and heart rate modelling.

**Key papers encoded:**

- **Task Force (1996):** The foundational HRV standards paper. Time-domain (RMSSD, SDNN) and frequency-domain (LF/HF) metrics defined. Encoded to establish why RMSSD is the relevant metric for short-term vagal monitoring.
- **Shaffer & Ginsberg (2017):** Normative HRV ranges by age and sex. Encoded so the AI advisor contextualizes absolute HRV values against population norms when they appear in labs.
- **Kiviniemi et al. (2007):** HRV-guided training outperforms fixed-intensity programs in endurance athletes. The theoretical basis for why this system gates training intensity off HRV σ-deviation rather than a fixed schedule.
- **Plews et al. (2013, 2014):** Practical HRV monitoring for compliance; HRV + training intensity distribution in elite rowers. 7-day rolling average superior to single-day readings for training decisions. Encoded in the 28-day baseline design decision.
- **Tanaka et al. (2001):** 220−age HRmax formula underestimates HRmax in older trained adults. Tanaka formula (208 − 0.7 × age) is lower-error. Directly encoded in `cardio-panel.tsx` and the HR zone calculation.
- **Buchheit (2014):** HR recovery as a training status indicator. Post-exercise HR drop at 60s correlates with parasympathetic reactivation speed. Encoded as interpretive context for WHOOP strain data.
- **Dial et al. (2025):** WHOOP and Garmin validation study for RHR and HRV accuracy. Provides the confidence interval for treating WHOOP readings as ground truth.

**Notes in vault:** `task-force-1996-hrv-standards.md`, `shaffer-2017-hrv-metrics-norms.md`, `kiviniemi-2007-hrv-guided-endurance-training.md`, `plews-2013-hrv-monitoring-compliance.md`, `plews-2014-hrv-training-intensity-rowers.md`, `tanaka-2001-hrmax-revisited.md`, `buchheit-2014-training-status-hr-monitoring.md`, `dial-2025-wearable-rhr-hrv-validation.md`

</details>

<details>
<summary><strong>N-of-1 Methodology — 5 notes</strong></summary>

The meta-framework that justifies the entire architecture: single-subject experimental design as rigorous science.

**Key papers encoded:**

- **Schork (2015, 2022):** N-of-1 trials as the gold standard for personalized medicine. Population RCTs establish what works *on average*; N-of-1 trials establish what works *for this person*. The philosophical foundation for treating a single athlete's data as the experimental unit.
- **Daza (2018):** Counterfactual inference in single-subject designs. Causal identification in the absence of a control group. Encoded to frame how the system interprets "did this protocol work?" — comparing the same individual across time windows, not against a population baseline.
- **Piccininni et al. (2025):** Causal inference methods for N-of-1 designs. The most recent methodological development in the domain. Encoded to ground the correlation card logic (sleep→recovery, HRV→readiness) in causal rather than purely associational framing.
- **Konigorski et al.:** Digital N-of-1 trials in experimental physiology. Connects wearable sensor data to the N-of-1 experimental framework — the direct theoretical basis for WHOOP + Apple Health as measurement instruments.

**Notes in vault:** `schork-2015-personalized-medicine-one-person-trials.md`, `schork-2022-exploring-human-biology-nof1.md`, `daza-2018-counterfactual-nof1.md`, `piccininni-2025-causal-inference-nof1.md`, `konigorski-digital-nof1-experimental-physiology.md`

</details>

<details>
<summary><strong>LLM Engineering & RAG — 67 notes</strong></summary>

Comprehensive coverage of LLM application architecture — the meta-domain that informs *how the vault itself is built and queried*.

Built from Alto's *LLM-Powered Applications* (2024, 13 chapters) and primary research papers.

**Key patterns encoded:**

- **RAG architecture (retrieval-augmented generation):** Retriever + generator separation; factuality vs parametric knowledge tradeoffs; context window efficiency. Directly informs the `load_vault_research()` signal-ranked retrieval design.
- **HyDE (Hypothetical Document Embeddings):** Zero-shot dense retrieval via generating a hypothetical answer first, then retrieving against it. Potential future enhancement to vault search.
- **Self-RAG (2023):** Adaptive retrieval with critique tokens — model decides *when* to retrieve vs rely on parametric knowledge. Encoded as architectural context for why the vault is injected conditionally (signal-ranked) rather than always-on.
- **ReAct (Reasoning + Acting):** Synergizing chain-of-thought with tool use. The theoretical basis for how the AI advisor combines live health data (tool) with vault research (knowledge) in responses.
- **Reflexion (Shinn et al., 2023):** Verbal reinforcement learning via reflection. Encoded as context for why `validate_plan()` triggers re-calls with violation feedback rather than patching responses.
- **Constitutional AI (Bai et al., 2022):** Anthropic's framework for safety through self-critique. Encoded as interpretive context for how Claude's safety behaviors interact with clinical coaching guidance.
- **LLM-as-judge (MT-Bench):** Using LLMs to evaluate LLM outputs. Encoded as context for potential future automated plan quality evaluation.

**Notes in vault:** `retrieval-augmented-generation.md`, `self-rag.md`, `react-synergizing-reasoning-and-acting.md`, `shinn-2023-reflexion-verbal-rl.md`, `hyde-zero-shot-dense-retrieval.md`, `hypothetical-document-embeddings.md`, `bai-2022-constitutional-ai.md`, `llm-as-judge-mt-bench.md`, `llm-prompt-engineering-techniques.md`, `llm-chain-of-thought.md`, `cognitive-architectures-for-language-agents.md`, `vector-embeddings.md`, `dense-retrieval.md`, `reranking.md`, `raptor-recursive-abstractive-processing.md`

</details>

---

### Signal-Ranked Note Retrieval

`load_vault_research()` selects the top 4 most-relevant notes on every call based on today's health signals:

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

Each note carries YAML frontmatter tags scored against active signals (`+2` per specific signal match, `+1` for default). A high-ACWR/low-HRV day surfaces overtraining and deload notes automatically — they outcompete rest-interval notes that score well on normal days.

**Example: ACWR = 1.42, HRV σ = −1.8**

| Note | Tags matched | Score |
|---|---|---|
| `overtraining-and-deload.md` | overtraining→deload+2, hrv→hrv_anomaly+2, acwr→high_acwr+2 | **+6** |
| `fitness-fatigue-theory.md` | overreaching→deload+2, hrv→hrv_anomaly+2 | **+4** |
| `supercompensation-theory.md` | volume→volume_spike+2, default+1 | **+3** |
| `rest-interval-hypertrophy.md` | default+1 | **+1** |

### Pinned Exercise Science Foundation

Six notes load unconditionally on every workout generation call, never competing with situational notes:

```
exercise-selection-strength.md        — compound movement pattern selection
exercise-selection-hypertrophy.md     — muscle group prioritization by mechanism
exercise-order-strength.md            — compound-before-isolation ordering
schoenfeld-2010-hypertrophy-mechanisms.md — mechanical tension > metabolic stress > damage
rest-interval-hypertrophy.md          — 90–120s minimum; longer rest preserves volume
rest-interval-strength.md             — 180–300s for compound strength work
```

### Section Extraction — Only What the Model Needs

Raw vault notes contain literature review, methodology, caveats. The retriever strips everything except sections the model can act on:

```
## Summary             → high-level principle (1–3 sentences)
## Prescription        → actionable protocol (the actual numbers)
## Key Claims          → evidence anchors (what the research actually says)
## Practical Takeaways → direct application
## Exercise Selection Rules → selection logic
```

A 3,000-word hypertrophy mechanisms paper is condensed to a 400-word prescription block. The model reasons from conclusions, not re-derived literature. Context window stays efficient across 10 concurrent notes.

### Vault Insights — Required Plan Artifact

Every generated workout plan must include a `vault_insights` array. The backend validates this before accepting the plan:

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

Every plan decision is traceable: prescription → vault note → primary research.

### Architecture: Read-Only, No Sync

```
Obsidian (editor) → ~/Vault/savage_vault/wiki/*.md → load_vault_research() → Claude context
                                                   → /api/vault/search    → AI Advisor
```

The vault is strictly input. No note is ever created, modified, or deleted by the system. Obsidian remains the editor; the platform is the consumer. The researcher's curation decisions are never overridden by an automated write-back.

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
