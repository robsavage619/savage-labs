# Engine Internals

*How the metrics, gates, and autoregulation actually work. Split out of the README so the front page stays skimmable.*

[<- back to README](../README.md)

---

## How It Works: The Technical Detail

### `DailyState`: One Contract for Everything

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

Most training apps track session count. I wanted to know whether my actual workload, cardiovascular *and* mechanical, was in the danger zone for injury or overtraining.

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
| `0.8-1.3` | ✅ Safe zone | Adapt and grow |
| `1.3-1.5` | ⚠️ Elevated risk | Volume gate fires |
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

Detection is dual-gated, the medications table needs an active entry *and* the morning check-in must flag it taken. Belt and suspenders, because I didn't want a stale medication record silently shifting my readiness score.

**Tiers:** ≥67 -> 🟢 GREEN · 34-66 -> 🟡 YELLOW · <34 -> 🔴 RED

---

### The Gate Engine

This was probably the most important design decision. Claude generates a workout plan. Before it gets shown to me, a separate deterministic layer validates it against 20 hard rules derived from physiology research. If anything fails, the plan gets rejected and Claude is called again, with the violations explained.

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
| Skin temp Δ ≥ 0.5°C | Z2 only, possible illness |
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
| SpO₂ < 94% overnight | Cap to low, hypoxia recovery flag |
| User-calibrating flag | Gates suppressed, not enough baseline |
| Respiratory rate Δ ≥ +1 bpm above 28d median | Illness sentinel (Bourdillon/Nicolò) |
| Sleep cycles < 3 | No compound primary at GREEN intensity |
| Sleep efficiency < 70% | Cap to moderate |
| Sleep disturbances ≥ 8 | Cap to moderate |
| WHOOP performance score < 33 | Cap to low |

</details>

The AI gives me good plans. The gates make sure they're safe.

---

### Injecting Clinical Context Into Every AI Call

Every time I call Claude, for a workout plan, a daily briefing, or a chat, it gets my full clinical picture assembled from the live database:

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

On top of that, the system prompt encodes drug-class interpretation rules, what SSRIs do to HRV, what beta-blockers do to heart rate zones, what inhaled corticosteroids flag for. Claude doesn't have to figure out my situation from general pharmacology knowledge; I tell it exactly what's relevant.

---

### Self-Learning Hypertrophy Engine

The training controller doesn't use population defaults for long. Every nightly job builds a personal model of how Rob's body responds to volume, fitting parameters directly from his logged history, replacing generic RP landmarks with empirical ones.

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

**Confidence quantification.** Each muscle prescription carries a `confidence` score (0-1) derived from two signals: scored-week count (sample size) and signal stability (fraction of consecutive weeks where trend doesn't flip dramatically). Biceps at 315 scored weeks scores 0.68; lower back at 10 weeks scores 0.28. The planner context block surfaces these so Claude knows when to trust the data versus hedge.

**Retroactive validation.** The engine backtests itself: for 1,844 consecutive (week_W, week_W+1) perf-score pairs across 16 muscles, it evaluates whether the implied prediction held. Overall accuracy: 86%. Per-muscle scores are surfaced at `GET /api/training/self-learning/status`.

**Session split.** The weekly set prescription is distributed across four sessions (Upper-A Tue / Lower-A Wed / Upper-B Thu / Lower-B Fri) with ≤10 sets per muscle per session, the RP hypertrophy threshold for a single training stimulus.

**Protein gate.** When `protein_grams` is logged in the daily check-in and has been consistently below 80% of the 239g target for ≥4 of the last 7 days, volume-increase prescriptions for non-emphasis muscles are held. Adding sets when substrate is inadequate produces fatigue, not growth.

**What it's honest about.** Muscles that have never been pushed above 50% of their population MRV are flagged `undertrained`, the system is measuring training habit, not physiology. Their fitted MRV is floored at 50% of population so the prescription pushes exploration rather than locking in a low ceiling. The API surfaces which muscles have robust personal fits vs which are still on population defaults.

---

### The Engine Grades Itself, And Publishes the Null

Every section above describes something the system *does*. This one is the only section that asks whether any of it works, and the answer is split.

**Calibration: does a prescription land where it says it will?** When the planner writes "3 x 11 @ 55 lb, RPE 8", does that set come back logged at RPE 8? Over 612 prescriptions carrying an `rpe_target`, 234 matched to a logged actual:

```
bias   +0.03 RPE   95% CI -0.04 to +0.10
SD      0.56
within 0.5 of target:  86%
```

The load model is good. Nobody had ever measured it.

**Predictive validity: does the morning readiness score relate to the session that follows?** Against volume-load r = -0.07, mean RPE +0.21, working sets +0.04. Every interval spans zero at n = 54. The gate's authority rests on readiness carrying information about capacity, and it currently **cannot be shown to**.

Splitting the composite by input says where the dead weight sits:

```
hrv     weight 0.40    no signal    (best r +0.21, CI spans zero)
sleep   weight 0.30    PREDICTS     (r +0.30 vs session RPE, CI +0.02 to +0.53)
rhr     weight 0.20    no signal    (best r +0.07, CI spans zero)
```

0.60 of the score sits on inputs with no detectable relationship to the session. HRV and RHR also correlate at about -0.75 across 913 days, largely one underlying signal wearing two hats.

**I did not re-weight anything.** Re-weighting readiness is a gate change. It needs an invariant update and a decision record, and n = 54 with one marginal correlation is not that. Measuring something is not the same as having earned the right to act on it.

I report both numbers together on purpose. The planner prescribes accurately and predicts nothing, and either one alone tells the wrong story about this engine. A dashboard that only shows the flattering half of its own evaluation is a marketing asset, not an instrument.

The same discipline produced `shc.stats.noise_floor`, one definition of the smallest worthwhile change for the whole app. This system has one subject, so a population threshold answers "where does he sit among people?" when the question is "did this move?" Half his own baseline SD can separate a real shift from ordinary day-to-day variation. A fixed band cannot. Two traps are encoded in the function rather than left to callers, because both were live in the first version: an SWC of exactly 0.0 is an *answer*, not an absence, and the floor has to come from the same window as the baseline it bands.

---

### Exercise Intelligence: Per-Hand Loads, Muscle Heads, One Canonical Model

A prescription once told me to hammer-curl 95 lbs *in each hand*, a weight I've never touched. It was a units bug, and chasing it exposed a whole layer worth getting right.

**Per-hand load semantics.** I log a dumbbell lift as the combined weight of both bells, but I *pick up*, and should be prescribed, one bell. The engine was reading the combined number as the per-hand load, so a per-hand target got validated against a total-load estimated-1RM. A small load-mechanics classifier now tags every movement (dumbbell pair, cable crossover, single-arm, barbell, machine) and normalizes the e1RM, the load ceiling, and the prescription to per-hand, with a median/MAD guard so one fat-fingered set can't inflate the ceiling. That one fix dropped the hammer-curl ceiling from a level that permitted 95 lb/hand to ~47.

**Muscle heads, not just muscle groups.** "Biceps" isn't specific enough to program well, the long head, short head, and brachialis grow from different exercises and joint positions. The engine credits each working set to the specific head an exercise trains (a hammer curl hits `biceps/brachialis` *and* `forearms/brachioradialis`, not just "biceps"), tracks per-head volume across the week, and leads exercise selection with the least-trained head, then rotates among equal-quality options instead of prescribing the same movement every week. Each pick is grounded in a cited study.

**The rotation has to speak a vocabulary I can actually log in.** For months I kept seeing the same lifts and assumed selection wasn't smart. It was: it ranked, it rotated, it fired its plateau and tenure triggers on schedule, and then emitted an exercise name that doesn't exist in my logging app's catalog, so the plan couldn't write it and the lift it was meant to replace stayed in. Four of seven rotations on the day I measured it named an unwritable movement, and two of those were the *same* exercise under a different spelling, because the curated science catalog and the app catalog had diverged into two namespaces nobody was reconciling. A movement's legal vocabulary is now an explicit, testable set, the app's own catalog plus what I've logged through it, deliberately excluding a decade of imported strings from a previous app that must still credit historical volume but can no longer be selected. A movement-identity key collapses spelling duplicates while keeping equipment words distinct (a machine press is not a dumbbell press), the plan validator rejects anything outside the set instead of silently skipping its load checks, and a test asserts every muscle has *more* curated movements than menu slots, because a muscle with exactly as many options as slots can never rotate at all, which is precisely what had happened to my rear and side delts.

The general lesson: the interesting failure wasn't in the algorithm, it was in the seam between two data sources that were each internally consistent. Nothing errored. The system just quietly did nothing.

**And the same seam was hiding a much larger one.** My training history from a previous app had been imported into the current one, so the same physical session existed in the database twice, same day, same reps, same weight to five decimals, under two different names. The deduplication view that was supposed to catch this elected one source per (day, canonical exercise), but its canonical key only stripped a trailing parenthetical, so it matched **1 of 17 real twin pairs**. 27% of all-time sets were duplicates.

It hid for years behind a floating-point detail. An exact-match join on `(day, reps, weight_kg)` returns *zero* duplicates, because one source stored `61.235` and the other `61.23497000135107`. Round to 0.1 kg first and twelve thousand appear.

Rolling 7/28/90-day windows were never affected, so no live decision was ever wrong. I verified that rather than assuming it: set counts and tonnage are byte-identical across all three windows before and after the fix. But the volume-landmark fit looks back 104 weeks, so every fitted MEV/MAV/MRV was built on inflated input. Chest +57%, front delts +53%, adductors +50%. Targets I could never hit, for a reason that had nothing to do with training.

The fix needed two mechanisms, because neither alone reaches far enough. A stronger canonical key (strip, lowercase, depunctuate, singularize, then *sort* the tokens) covers the punctuation and word-order family. An evidence-derived twin table covers the word-choice renames no normalizer can touch. Every row in that table was derived from **behaviour, not string similarity**: both names logged on the same day with an identical full set sequence. Residual duplication went from 29.1% to 6.2%.

Two things I got wrong on the way, both recorded in the changelog. I reported that rotation and e1RM were fragmented by the same twins, which turned out to be false, because that boundary was already handled. And I nearly promoted the exercise menu's identity function into the ledger, which token-sorts and would have merged `Cable Twist (Down to up)` with `(Up to down)`. Two real, distinct lifts.

**Two authorities for the same number, and the lower one silently won.** Weekly volume targets come from a fitted per-muscle model; the evidence-based dose comes from a curated research brief. Both were rendered into the same block of planner context, two lines apart, and where they disagreed the prescription followed the fitted one, abs asked for 12-20 sets a week and drew 6, which across four sessions is one exercise per session. The fit is a percentile of weeks I actually performed, so it measures habit and reports it as physiology: a muscle never trained hard can never be prescribed hard. There's a guard that floors an obviously habit-driven fit to population norms, but it compared with a strict `<` and my quads sat at exactly half the population ceiling, so it missed. Fitted landmarks are now floored against the curated brief as well, and the engine publishes its weekly set budget, measured capacity vs. demand, instead of leaving over-prescription to be triaged silently.

**One canonical model instead of two.** The crediting data and the head/length/science data lived in two separate tables, keyed the same way but free to disagree about which muscles a movement trains, which is exactly how a wrist curl ended up crediting biceps. I merged them into a single `exercise_muscle` row per (exercise, muscle) that carries both the volume credit *and* the anatomy, so the two can never drift apart. The migration used expand-contract: the old table names became views over the new table, so every reader kept working untouched, verified byte-identical on real data before cutting over.

---

### e1RM Tracking & Fatigue Detection

Every set goes in with weight and reps. I compute estimated 1RM via the Epley formula:

```
e1RM = weight_kg × (1 + reps / 30)
```

Then I run a 4-week regression detector, if my top-percentile e1RM has dropped more than 3% over the last 56 days, I'm accumulating fatigue and a deload gets flagged before I actually get hurt:

```
regression_pct = (mean(e1RM, days 0–27) − mean(e1RM, days 28–55))
               / mean(e1RM, days 28–55)
```

---

### Data Ingestion

Four sources, one database. Every record gets a content hash so syncs are always idempotent. I can re-run them without fear of double-counting.

| Source | How it gets in | What I get |
|---|---|---|
| **WHOOP** | OAuth 2.0, syncs every 60 min | Recovery, HRV, RHR, sleep stages (cycles, efficiency, disturbances, respiratory rate), strain, SpO2, skin temp, HR zone durations, body measurements (measured max HR), user profile |
| **Apple Health** | iCloud HealthAutoExport -> CCDA XML parse | Everything, steps, HR, weight, glucose, blood pressure, sleep |
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

