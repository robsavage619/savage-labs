# Sports-Science Layer

*Sleep architecture, periodization, autoregulation, fueling, clinical signals, and the n-of-1 research lab.*

[<- back to README](../README.md)

---

## Sports-Science Layer

Once the daily-readiness loop was solid, the next push was treating Savage Labs as an actual sports-science platform, not just a wearable dashboard. Seven additions, each anchored to peer-reviewed methodology.

### Sleep Architecture: Beyond Total Hours

Total sleep duration is the noisiest possible single metric. The dashboard surfaces six dimensions every morning, each pulled from the dedicated columns the WHOOP V2 ingest writes (no JSON parsing in the hot path):

| Field | What it tells me | Reference |
|---|---|---|
| **Deep %** | N3 / slow-wave, physical recovery + GH release. Target 15-25%. | Walker 2017 |
| **REM %** | Motor learning + emotional regulation. Target 20-28%. | Walker 2017 |
| **Efficiency %** | Time asleep / time in bed. >85% = good. | Watson AASM 2015 |
| **Wakes** | Whoop disturbance count, fragmented sleep marker. |, |
| **Midpoint σ** | 7-day standard deviation of sleep midpoint hour, circadian / social-jet-lag proxy. <0.75h is tight. | Lunsford-Avery 2018 |
| **Sleep Regularity Index** | % probability the asleep/awake state matches at the same clock minute on consecutive nights. ≥80 = tight. | Phillips 2017 *Scientific Reports* |

---

### Periodization Strip + Banister Fitness-Fatigue Model

Most "training load" tools stop at ACWR. I added the full Banister model on top, separating **fitness** (slow-decay 42d EWMA), **fatigue** (fast-decay 7d EWMA), and **form** (their difference):

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

The mesocycle phase strip sits beside it, one cell per planned week, the current week glows, the deload week is amber. Reads the live `mesocycles` table; phase + weeks-to-deload are pulled from `ensure_active_mesocycle()`.

---

### After-Action Autoregulation: Reading the Hevy Sync

I log every set in Hevy. Once it syncs, the **After-Action panel** computes per-exercise actuals vs. plan target and emits a next-session weight suggestion. Read-only, no double-logging.

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

**Hevy RPE floor.** Hevy's RPE picker only goes 6-10, so a prescribed target below 6 (e.g. a deload set at RPE 5) is unloggable, comparing a logged 6 against a target of 5 would falsely read "harder than planned" and drop the load every time. The comparison clamps the target to a floor of 6, and `save_plan()` raises any loaded-lift `rpe_target` (and the session target) to 6 on persist so plans never prescribe an RPE you can't record. Cardio/bodyweight work is left alone. Hevy doesn't RPE-log it.

---

### Post-Workout Retrospective: Execution Feedback, Not a Stale Rerun

The morning story is recovery-driven; those metrics don't change after you train. So the post-workout pass is a *separate* artifact: a vault-grounded **retrospective** of how the session went versus plan. The **Post-workout** dashboard section pairs the after-action adherence table with a copy-prompt flow (Copy CC prompt -> paste into Claude Code -> POST back -> Sync), mirroring the morning health-story pattern.

`GET /training/after-action` now also returns a `## VAULT RESEARCH` block, notes selected server-side from the session's *execution* signals (rep misses -> effective-reps/load-selection, RPE overshoot -> fatigue-management/SFR, progression -> progressive-overload, missing RPE -> autoregulation), so every adjustment the retrospective recommends is grounded in the same retrieval engine the planner uses. `GET /workout/retrospective/latest` returns the latest session + stored retrospective + a `needs_retrospective` flag; `POST /workout/retrospective` stores the narrative, flags, and vault citations, which then feed the next morning's "PRESCRIPTION -> EXECUTION" line.

---

### Fueling Layer: Body Comp + Macros + Hydration

Apple Health was already syncing weight and active/basal energy. The ingest map now also pulls every dietary metric (energy, protein, carbs, fat, fiber, sugar, water, sodium, caffeine) and **lean body mass** from a smart scale.

The `/api/fueling/today` endpoint computes:
- **kcal balance**, dietary in − (active + basal) out
- **Protein g/kg** vs the 1.6-2.2 g/kg hypertrophy band (Morton 2018 meta)
- **Hydration** in oz + sodium in mg
- **Body composition**, weight, BF%, lean mass, falling back to BF×weight when LBM is missing

Empty-state UX: when no diet data is logged yet, the card shows targets sized to current body weight ("~194g protein, ~3779ml water, TDEE balance ±250 kcal") so the prescription is visible from day one.

---

### Clinical Research Signals: Four Tiles That Survived an Audit

A panel layered on top of the standard Insights pane. Each tile is anchored to a primary citation surfaced via tooltip hover:

| Tile | What it computes | Threshold | Reference |
|---|---|---|---|
| **SRI** | Overlap-based sleep regularity index | ≥80 tight, ≥60 moderate | Phillips 2017 |
| **lnRMSSD** | log-transformed HRV mean rolling 7d, with 4w-avg delta + CV% | + delta = autonomic adaptation | Buchheit 2014 |
| **Red-streak** | Consecutive recovery <34 days | 3+ doubles soft-tissue injury risk | WHOOP 2022 internal cohort |
| **Allostatic Load** | Composite of BP, BMI, LDL, HDL, trig, A1c each scored 0/1/2 | <3 low, <6 moderate, ≥6 elevated | Seeman 2001 *JAMA* |

**This panel used to have six tiles, and the other two were fiction.** An audit against the live database found that two had *never once rendered a value*, both swallowed by a bare `except Exception`. A Z2 heart-rate-drift tile queried a column name that doesn't exist, and would have been wrong anyway: it computed variance *across* sessions, which is not within-session cardiac drift, and no minute-level HR exists in this database to compute the real thing from. A drug-adjusted HRV tile queried `medications.generic_name` when the column is `name`, so its branch was permanently false and the adjustment factor was 1.000 essentially always. Raw HRV wearing a citation. A third reported a materially wrong number, and a blanket PEER-REVIEWED badge sat over two sources that are not peer-reviewed.

Both dead tiles were removed rather than repaired. A number nobody can compute honestly is worse than a blank space, because a blank space doesn't get cited back to you six months later. That audit is why this section no longer claims a count it can't defend.

---

### Research Lab: Pre-Registered N-of-1 Hypotheses

The piece I'm most proud of. A **pre-registered hypothesis catalog** runs against my live time-series and emits CONFIRMED / REFUTED / INCONCLUSIVE / INSUFFICIENT verdicts per question, with effect size, n, p-value, and the primary citation. The test type and threshold are fixed in advance, so I can't p-hack.

The catalogue seeded with six hypotheses from the vault and has grown to 15. Two have been **confirmed** on my own data:

| Finding | Effect | n | p |
|---|---|---|---|
| ≥8h sleep lifts next-morning HRV | **+14.0ms** vs 6.5-7.5h nights | 62 | 0.018 |
| A pickleball day depresses next-morning HRV | **−12.3ms** vs rest days | 152 | 0.019 |

Seven are **refuted**, which is the half nobody publishes and the half that actually changes behaviour: yoga does nothing measurable for my HRV (n=203), short sleep doesn't depress it the way the literature predicts (n=95), and stacking 2+ pickleball sessions in 3 days doesn't compound the hit (n=145).

Wired through:

```
GET  /api/lab/questions    → catalogue
GET  /api/lab/findings     → latest verdict per question, answered and open
POST /api/lab/run          → run due hypotheses, re-verify answers, rotate stable questions
```

The frontend `LabPanel` renders one verdict-coded card per question with the hypothesis text, summary, effect size, n, p-value, test type, and vault citation, grouped into **Answered** and **Under test**. New hypotheses go into `lab_questions` as a one-row INSERT plus a runner function in `shc/lab.py`, that's the entire surface area for adding new questions.

**The lifecycle.** After each run, `rotate_if_stable()` retires any question that has produced 3 consecutive identical confirmed/refuted verdicts with n ≥ 1.5 × min_n, and promotes the next queued question. Retirement means *answered*, not *deleted*: a retired question is re-run every 30 days, and if the re-check disagrees with the verdict it retired on, `reverify_retired()` puts it back under test where it must earn retirement again.

That last part earns its keep immediately. The pickleball finding was retired CONFIRMED at −12.3ms and then sat frozen while my court volume climbed to 649 min/week; re-tested on the current window it comes back at −4.5ms, p=0.31. The effect decayed and nothing would have noticed.

> **Match the study to the behaviour.** A standing hypothesis is only worth a slot if the exposure keeps occurring. Yoga -> HRV did resolve REFUTED (−0.4ms across 43 yoga days), but slowly, and on the current window it has fallen back to INSUFFICIENT because I stopped doing yoga, the question decays faster than it answers. *Heavy lift tonnage -> next-day HRV* runs well-powered on the same calendar (n≈190) because lifting happens 3-4×/week.

**Multiplicity, honestly.** Confirmations must survive a Benjamini, Hochberg correction whose family is the **whole catalogue**, not whatever happened to run that cycle, a run-scoped denominator shrinks as questions retire (mine had reached m=3), which makes the correction quietly looser over time and lets an unchanged p-value flip verdict because an unrelated question resolved. What BH here does *not* cover: the catalogue is re-run daily against accumulating data, so these p-values are uncorrected for repeated looks. A confirmation is strong evidence, not proof, and the README should say so rather than the dashboard implying otherwise.

**Verdicts feed the AI.** Every call to `build_daily_context()` or `build_training_context()` injects the current `## YOUR PERSONAL LAB FINDINGS` block. Claude sees which effects have been statistically confirmed or refuted on my data before writing a word. REFUTED findings override population-level assumptions.

The philosophical backbone is in the vault. Schork 2015/2022 and Daza 2018 on N-of-1 trials as rigorous science.

---

### Concurrent Training Awareness: Pickleball as Primary Sport

The original platform was framed around generic recomposition. That's changed. The primary goal is now **4.5 -> 5.0 pickleball while preserving strength and size**, breaking the racquet-sport norm of trading muscle for endurance.

This required wiring concurrent training interference theory directly into the planner. The vault now contains Wilson 2012, Schumann 2022, Coffey & Hawley 2017, and Suchomel 2016. The core findings that drive planning decisions:

| Finding | Source | How it's applied |
|---|---|---|
| Lower-body explosive power is the first adaptation lost under high sport volume | Wilson 2012 | When `pickleball_min_7d ≥ 150`, drop leg hypertrophy to MEV; bias toward power block |
| AMPK activation from aerobic work suppresses mTOR-driven hypertrophy for ~6h | Coffey & Hawley 2017 | Finisher rule: ≥150 min/wk -> Z2-only, no HIIT, sport already supplied the stimulus |
| Sport-specific aerobic (court movement) interferes less than running-based aerobic | Schumann 2022 | Upper-body hypertrophy volume stays at MAV, the interference is lower-body |
| Strength is the floor on which power is built, never sacrifice the floor | Suchomel 2016 | Primary compounds always present; sport volume reduces accessories, not compounds |

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

The median (not mean) protects against outlier contamination. The 8-30 bpm clamp excludes implausible values from earlier schema iterations. Bourdillon (2018) and Nicolò (2020) both show respiratory rate rises 3-4 days before subjective illness symptoms, this gate catches it early.

---

