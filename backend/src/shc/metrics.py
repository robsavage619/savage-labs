from __future__ import annotations

"""Single source of truth for "where Rob is today".

`compute_daily_state(conn)` returns a typed `DailyState` dict consumed by:
  - `/api/state/today`            (frontend dashboard, readiness UI)
  - `briefing.build_daily_context` (chat advisor system prompt)
  - `workout_planner.build_training_context` (LLM workout generation)
  - `workout_planner.validate_plan` (deterministic auto-regulation gate)

Everything that previously recomputed HRV-σ, ACWR, readiness, or β-blocker
adjustment in three different places now reads from this module instead.

Design notes
------------
* All math is centralized — there is exactly one σ formula and one ACWR
  formula in this codebase.
* ACWR is the *true* Gabbett model (acute training load ÷ chronic training load),
  computed from WHOOP `strain` + Hevy volume via `v_daily_load`. Not a
  recovery-score ratio.
* Readiness composite is computed here with the β-blocker reweighting so the
  LLM sees the same number the frontend shows.
* `gates` is a deterministic auto-regulation rule engine. It encodes hard
  safety/progression rules (red HRV → cap intensity, resistance ACWR on the
  uncoupled scale → rest/low/moderate per RES_ACWR_* thresholds, legs in last
  48h → reject leg day, propranolol day → shift HR zones, etc.).
"""

import json
import logging
import statistics as _st
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

# Propranolol: HR suppressed ~15-25 bpm, kcal under-counted ~20-30%.
# Conservative: shift HR zones -20 bpm and multiply HR-derived kcal by 1.25
# only when Rob marks `propranolol_taken=True` for the day.
PROPRANOLOL_HR_SHIFT_BPM = 20
PROPRANOLOL_KCAL_MULT = 1.25

# Single-user platform — Rob's birth-date constant matches the frontend.
_ROB_AGE = 40

# Readiness weights — collapsed from frontend lib/readiness.ts so they live in
# exactly one place. On propranolol days BOTH autonomic channels are corrupted —
# the β-blocker blunts HRV AND lowers RHR by 10–25 bpm — so both are down-weighted
# and trust shifts to sleep + subjective (panel review M8; personal_context says
# "use RPE not HR" on dosing days). These magnitudes are heuristic priors.
DEFAULT_WEIGHTS = {"hrv": 0.40, "sleep": 0.30, "rhr": 0.20, "subj": 0.10}
BETA_BLOCKER_WEIGHTS = {"hrv": 0.15, "sleep": 0.50, "rhr": 0.10, "subj": 0.25}

# Minimum valid nights before a 28-day autonomic baseline (HRV, skin temp) is
# trusted — a thin baseline gives an unstable mean/SD that can fire gates at
# random (panel review M7/M13).
BASELINE_MIN_N = 14

# ACWR gate thresholds on the UNCOUPLED scale (see _arm_acwr). Uncoupled ratios
# run systematically higher than the coupled form these bands were first set
# against, so they're shifted up (panel review M2). These are HEURISTIC priors
# for an N=1 athlete whose chronic baseline is noise-dominated — the resistance
# arm is a FATIGUE/overreaching signal, not a validated injury-risk gate;
# personal calibration from Rob's own load history is Phase 3. Conditioning keeps
# stronger (field-sport) evidence behind the leg-load language.
RES_ACWR_REST, RES_ACWR_LOW, RES_ACWR_MOD = 2.0, 1.8, 1.5
COND_ACWR_FORBID_LEGS = 1.8

# Minimum fitted weeks before a personal ACWR band is allowed to TIGHTEN below
# the population floor. The fitter itself accepts a band at 12 weeks
# (self_learning._ACWR_MIN_WEEKS); tightening is the riskier direction, so the
# bar is set strictly higher — a thin fit may loosen but not gate accumulation
# weeks as spikes until the sample describes a stable era.
_ACWR_TIGHTEN_MIN_WEEKS = 24

# Sleep-architecture gate population defaults (protective ceilings, not
# homeostats — Rob has diagnosed, off-CPAP sleep apnea, so these fire almost
# every night on the population default alone; a personal fit may only LOOSEN
# them, same treatment as the ACWR LOW/MOD bands, never tighten below).
_SLEEP_DISTURBANCE_POPULATION = 12.0
_SLEEP_CYCLE_POPULATION = 4.0

Tier = Literal["green", "yellow", "red"]
Intensity = Literal["high", "moderate", "low", "rest"]


# ── DTOs (plain dicts via asdict — DuckDB / FastAPI friendly) ────────────────


@dataclass
class RecoveryMetrics:
    score: float | None = None  # WHOOP recovery 0-100
    score_date: str | None = None
    hrv_ms: float | None = None
    hrv_baseline_28d: float | None = None
    hrv_sd_28d: float | None = None
    hrv_sigma: float | None = None  # σ deviation from 28d baseline
    rhr: int | None = None
    rhr_7d_avg: float | None = None
    rhr_baseline_28d: float | None = None
    rhr_elevated_pct: float | None = None
    skin_temp: float | None = None
    skin_temp_baseline_28d: float | None = None
    skin_temp_delta: float | None = None
    spo2_pct: float | None = (
        None  # WHOOP recovery-night SpO2 (clinical: <95% sleep-disordered breathing)
    )
    user_calibrating: bool | None = None  # WHOOP still calibrating — score is unreliable
    respiratory_rate_baseline_28d: float | None = None
    respiratory_rate_delta: float | None = (
        None  # bpm above 28d baseline (Bourdillon: +1 bpm = illness sentinel)
    )


@dataclass
class SleepMetrics:
    last_date: str | None = None
    last_hours: float | None = None
    avg_7d: float | None = None
    consistency_stdev_7d: float | None = None
    debt_7d_h: float | None = None
    deep_pct_last: float | None = None  # OSA-aware: deep sleep matters more than duration
    deep_min_last: float | None = None
    rem_min_last: float | None = None
    light_min_last: float | None = None
    awake_min_last: float | None = None
    rem_pct_last: float | None = None
    efficiency_pct_last: float | None = None
    consistency_pct_last: float | None = None
    performance_pct_last: float | None = None
    disturbance_count_last: int | None = None
    sleep_cycle_count_last: int | None = None
    in_bed_min_last: float | None = None
    no_data_min_last: float | None = None
    sleep_needed_min_last: float | None = None
    sleep_need_baseline_min_last: float | None = None  # base sleep need for body
    sleep_need_debt_min_last: float | None = None  # added need from accumulated debt
    sleep_need_strain_min_last: float | None = None  # added need from yesterday's strain
    sleep_need_nap_min_last: float | None = None  # credit from naps
    respiratory_rate_last: float | None = None  # breaths/min during sleep
    midpoint_local_h_last: float | None = None  # decimal local hours, 0-24
    midpoint_stdev_h_7d: float | None = None  # social jet-lag proxy
    spo2_avg_last: float | None = None  # < 95% is a clinical flag for sleep-disordered breathing
    score: float | None = None  # 0-100 composite (duration + deep% + spo2)


@dataclass
class TrainingLoadMetrics:
    acute_load_7d: float | None = None  # composite_load mean over 7d
    chronic_load_28d: float | None = None  # composite_load mean over 28d
    acwr: float | None = None  # acute / chronic, true Gabbett (pooled, display)
    # Modality-split ACWR. Pooled composite ACWR is blind to *which* system is
    # overloaded — a pickleball spike inflates it and rest-gates lifting that
    # isn't overloaded. Resistance ACWR (Hevy tonnes) governs lifting intensity;
    # conditioning ACWR (WHOOP strain: pickleball/cardio) governs court/cardio.
    resistance_acwr: float | None = None
    resistance_acute_7d: float | None = None
    resistance_chronic_28d: float | None = None
    conditioning_acwr: float | None = None
    conditioning_acute_7d: float | None = None
    conditioning_chronic_28d: float | None = None
    last_session_date: str | None = None
    days_since_last: int | None = None
    days_since_legs: int = 99
    days_since_push: int = 99
    days_since_pull: int = 99
    # Pickleball gets its own rest clock — it is conditioning stimulus, not a
    # leg-lift substitute, so it must not reset days_since_legs (which would
    # permanently rest-gate leg lifting for a weekend court player).
    days_since_pickleball: int = 99
    # Avg RPE of each group's most recent session — scales the rest gate:
    # a submaximal session needs less recovery than a near-failure one.
    last_rpe_legs: float | None = None
    last_rpe_push: float | None = None
    last_rpe_pull: float | None = None
    push_pull_ratio_28d: float | None = None
    push_sets_28d: int = 0
    pull_sets_28d: int = 0
    legs_sets_28d: int = 0
    cardio_min_28d: int = 0
    cardio_z2_min_7d: int = 0
    cardio_zone_min_7d: dict[str, float] = field(
        default_factory=dict
    )  # {z0:.., z1:.., ..., z5:..} from WHOOP
    # High-intensity (Z3-Z5) conditioning minutes in the last 7d. The full zone
    # breakdown is computed but only Z2 was consumed downstream; the planner
    # needs the high-intensity pole to shape POLARIZED conditioning (most volume
    # easy Z2, a small dose hard Z4/Z5, little in the Z3 "grey zone").
    cardio_high_intensity_min_7d: int = 0  # Z3+Z4+Z5
    cardio_zone3_min_7d: float = 0.0
    cardio_zone4_min_7d: float = 0.0
    cardio_zone5_min_7d: float = 0.0
    max_hr_measured: int | None = None  # WHOOP-measured max HR (preferred over Tanaka formula)
    max_hr_tanaka: int | None = None  # 208 - 0.7 × age (population formula, fallback)
    pickleball_min_7d: int = 0  # logged conditioning load only (not a programmed goal)
    pickleball_min_28d: int = 0
    cardio_modality_min_7d: dict[str, int] = field(default_factory=dict)  # per-sport minutes
    # WHOOP day_strain (0-21 logarithmic) surfaced into DailyState so the planner
    # can gate today's session on whole-day cardiovascular load, not just the
    # 7/28d ACWR. yesterday = the most recent completed cycle (drives "ease off
    # today" after a hard day); today = the in-progress cycle if WHOOP has a
    # partial reading.
    day_strain_yesterday: float | None = None
    day_strain_today: float | None = None
    day_strain_7d_avg: float | None = None


@dataclass
class CheckinMetrics:
    date: str | None = None
    propranolol_taken: bool | None = None
    body_weight_kg: float | None = None
    body_weight_trend_4wk: float | None = None  # % change vs 28d ago
    soreness_overall: int | None = None
    sleep_quality: int | None = None  # 1-10
    energy: int | None = None  # 1-10
    stress: int | None = None  # 1-10
    motivation: int | None = None  # 1-10
    illness_flag: bool = False
    travel_flag: bool = False
    muscle_soreness: dict[str, int] = field(default_factory=dict)


@dataclass
class ReadinessSnapshot:
    score: float | None = None  # 0-100 composite
    tier: Tier | None = None
    weights: dict[str, float] = field(default_factory=dict)
    components: dict[str, float | None] = field(default_factory=dict)
    beta_blocker_adjusted: bool = False


@dataclass
class AutoRegGates:
    """Deterministic safety + progression rails consumed by `validate_plan`.

    These are HARD constraints — the LLM may produce creative content WITHIN
    these gates but plans that violate them are auto-regenerated or rejected.
    """

    max_intensity: Intensity = "high"
    forbid_muscle_groups: list[str] = field(default_factory=list)  # e.g. ["legs"] if rested < 48h
    deload_required: bool = False
    deload_reason: str | None = None
    hr_zone_shift_bpm: int = 0  # subtract from prescribed HR zones (propranolol days)
    kcal_multiplier: float = 1.0  # multiply HR-derived kcal estimates
    e1rm_regression_4wk_pct: float | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class DataFreshness:
    whoop_age_days: int | None = None
    sleep_age_days: int | None = None
    hevy_age_days: int | None = None
    cardio_age_days: int | None = None
    whoop_stale: bool = False
    gaps: list[str] = field(default_factory=list)


@dataclass
class BodyComposition:
    """Leanness signal from progress photos — a trackable proxy, not a body-fat %.

    Derived from the front-view waist-to-shoulder / waist-to-hip ratios (see
    shc/vision/METHODOLOGY.md). The 28-day trend is gated by the ISAK 2% noise
    floor so a change is only called real when it clears measurement error.
    Surfaced as *context* for recommendations (interpreted against Rob's recomp
    goal), never as a hard gate.
    """

    as_of: str | None = None  # latest passing front-photo date
    n_photos: int = 0
    waist_to_shoulder: float | None = None  # rolling median of recent shots
    waist_to_hip: float | None = None
    trend_28d_pct: float | None = None  # signed % change in waist:shoulder
    trend_direction: str | None = None  # 'leaner' | 'softer' | 'stable' | None
    note: str | None = None  # factual cross-reference vs weight


@dataclass
class DailyState:
    as_of: str
    recovery: RecoveryMetrics
    sleep: SleepMetrics
    training_load: TrainingLoadMetrics
    checkin: CheckinMetrics
    readiness: ReadinessSnapshot
    gates: AutoRegGates
    freshness: DataFreshness
    body_composition: BodyComposition


# ── Helpers ──────────────────────────────────────────────────────────────────

# Hip-hinge patterns classify as PULL, checked BEFORE _LEGS so a hinge never
# leaks into legs. WHY: the auto-reg gate forbids whole push/pull/legs groups via
# muscle_group(), and the shipped+documented convention is that a "pull" gate
# also bars posterior-chain hinges (RDL, SL-RDL, deadlift, good morning) — they
# load the same hip-hinge/erector pattern as heavy rows/deadlifts, not the
# quad/knee-extension pattern of a squat. Previously "deadlift" → pull but "rdl"
# → legs (and "sumo deadlift"/"stiff leg deadlift" → legs via _LEGS), so the
# gate let an RDL through on a pull-rested day. Reconciled: every hinge → pull.
# Hip thrust is deliberately EXCLUDED — it's a glute-bridge (hip extension under
# a fixed back), not a standing hinge, so it stays a legs/glute movement.
_HINGE = (
    "rdl",
    "romanian deadlift",
    "deadlift",
    "good morning",
    # Partial-ROM pulls and posterior-chain/erector isolation are the same
    # hip-hinge pattern the pull gate protects — but their names lack "deadlift"
    # so they used to fall through to "other" and slip past a pull-rested day.
    "rack pull",
    "pull through",
    "back extension",
    "hyperextension",
    "reverse hyper",
    "kettlebell swing",
    "kb swing",
)

# Order matters — check HINGE first (→ pull), then LEGS and CORE before PUSH/PULL
# so "leg press" → legs, not push, and "leg curl" → legs, not pull. Compound
# terms (e.g. "calf raise") must also resolve to legs before the generic "raise"
# hits push.
_LEGS = (
    "squat",
    " leg ",
    "leg press",
    "leg curl",
    "leg extension",
    "lunge",
    "hip ",
    "glute",
    "hamstring",
    "quad",
    "calf",
    "step-up",
    "step up",
    "adduct",
    "abduct",
    "thigh",
    "sumo",
    "hack squat",
    "split squat",
    "bulgarian",
)
_CORE = (
    "plank",
    "crunch",
    "ab ",
    "core",
    "oblique",
    "sit-up",
    "rotation",
    "cable crunch",
    "ab crunch",
)
_PUSH = (
    "press",
    "fly",
    "dip",
    "pushup",
    "push-up",
    "tricep",
    "overhead",
    "chest",
    "front raise",
    "lateral raise",
    "side raise",
    "upright row",
)
_PULL = (
    "row",
    "pulldown",
    "pull-up",
    "pullup",
    "chin-up",
    "chinup",
    "curl",
    "lat ",
    "deadlift",
    "shrug",
    "face pull",
    "rear delt",
    "high pull",
    "good morning",
)

# Body-diagram muscle keys mapped to the planner's push/pull/legs taxonomy.
# Keys must match the frontend `BodyDiagram` regions verbatim.
MUSCLE_TO_GROUP: dict[str, str] = {
    # Push
    "chest": "push",
    "front_delts": "push",
    "side_delts": "push",
    "triceps": "push",
    # Pull
    "lats": "pull",
    "mid_back": "pull",
    "traps": "pull",
    "rear_delts": "pull",
    "biceps": "pull",
    # Legs
    "quads": "legs",
    "hamstrings": "legs",
    "glutes": "legs",
    "adductors": "legs",
    "calves": "legs",
    # Core (no group; informational only)
    "abs": "core",
    "lower_back": "core",
}


def muscle_group(exercise: str) -> str:
    """Classify an exercise into push/pull/legs/core/other.

    Single source of truth — previously duplicated in workout_planner and
    dashboard. Hinge checked FIRST so all hip-hinge patterns (deadlift, RDL,
    good morning) → pull consistently; then legs/core before push/pull so
    "leg press" → legs (not push) and "leg curl" → legs (not pull).
    """
    e = exercise.lower()
    if any(k in e for k in _HINGE):
        return "pull"
    if any(k in e for k in _LEGS):
        return "legs"
    if any(k in e for k in _CORE):
        return "core"
    # "rear delt fly" and "reverse fly" are PULL patterns despite "fly" in _PUSH.
    if "rear delt" in e or ("reverse" in e and "fly" in e):
        return "pull"
    # "row" is a PULL pattern — check it before _PUSH so a row whose name contains
    # a push keyword ("Chest Supported Row" → "chest") classifies as pull, not push,
    # and can't slip past a pull-rested gate. "Upright Row" is the lone exception
    # (a delt/push movement) and is left to _PUSH below.
    if "row" in e and "upright row" not in e:
        return "pull"
    if any(k in e for k in _PUSH):
        return "push"
    if any(k in e for k in _PULL):
        return "pull"
    return "other"


def pickleball_match_load(conn, lookback_days: int = 28) -> dict[str, Any] | None:
    """Differentiate competitive-match pickleball from casual court load.

    Pickleball reaches the load/ACWR model as undifferentiated cardio (WHOOP
    strain on a ``pickleball`` cardio_session). But a logged DUPR *match* — a
    rated, competitive game with win/loss and scores — carries higher
    neuromuscular and psychological load per minute than casual rallying. This
    reads ``dupr_matches`` (migration 0027) for the window and returns a load
    multiplier the conditioning arm can apply to competitive days, plus the raw
    match facts.

    FAILS VISIBLY: if ``dupr_matches`` isn't queryable here, returns None so the
    caller falls back to undifferentiated load rather than silently assuming
    "all casual". The actual blend into ``v_daily_load`` lives in the load-view
    layer — see the handoff — this helper is the readable hook it consumes.

    Args:
        conn: DuckDB connection.
        lookback_days: Window for counting competitive matches.

    Returns:
        ``{match_days, total_matches, wins, losses, competitive_load_mult,
        last_match_date}`` or None.
    """
    try:
        table_exists = conn.execute(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'dupr_matches'"
        ).fetchone()[0]
    except Exception as exc:
        log.warning("dupr_matches existence check failed: %s", exc)
        return None
    if not table_exists:
        return None
    since = (date.today() - timedelta(days=lookback_days)).isoformat()
    row = conn.execute(
        """
        SELECT
            COUNT(DISTINCT event_date)              AS match_days,
            COUNT(*)                                AS total_matches,
            COALESCE(SUM(CASE WHEN won THEN 1 ELSE 0 END), 0)        AS wins,
            COALESCE(SUM(CASE WHEN won = FALSE THEN 1 ELSE 0 END), 0) AS losses,
            MAX(event_date)                         AS last_match
        FROM dupr_matches
        WHERE event_date >= $s
        """,
        {"s": since},
    ).fetchone()
    if not row or not row[1]:
        return None
    match_days, total, wins, losses, last_match = row
    # Conservative, bounded uplift: a competitive-match day carries ~25% more
    # conditioning load per minute than casual play (rated games are played at
    # higher intensity with full effort on every point). Capped — this is a
    # heuristic prior for an N=1 athlete, not a validated coefficient.
    competitive_load_mult = 1.25
    return {
        "match_days": int(match_days or 0),
        "total_matches": int(total or 0),
        "wins": int(wins or 0),
        "losses": int(losses or 0),
        "competitive_load_mult": competitive_load_mult,
        "last_match_date": str(last_match) if last_match else None,
    }


def vo2max_series(conn, lookback_days: int = 90) -> dict[str, Any] | None:
    """Latest VO2max and a short trend for the cardio-prescription path.

    VO2max is ingested into ``measurements`` (metric ``vo2_max``, Apple Watch
    HKQuantityTypeIdentifierVO2Max) but no training reader existed — the cardio
    planner had no aerobic-fitness anchor. Reads the daily-averaged series over
    ``lookback_days`` and returns the latest value plus the signed change vs the
    earliest reading in the window. Filters obviously bad values (≤20 mL/kg/min)
    the same way the dashboard endpoint does.

    Args:
        conn: DuckDB connection.
        lookback_days: Trend window length.

    Returns:
        ``{latest, latest_date, trend_pct, change_abs, n}`` or None when there's
        no usable VO2max data.
    """
    try:
        rows = conn.execute(
            """
            SELECT ts::DATE AS day, AVG(value_num) AS vo2max
            FROM measurements
            WHERE metric = 'vo2_max' AND value_num IS NOT NULL AND value_num > 20
              AND ts >= $s
            GROUP BY day
            ORDER BY day
            """,
            {"s": (date.today() - timedelta(days=lookback_days)).isoformat()},
        ).fetchall()
    except Exception as exc:
        log.warning("vo2_max series unavailable: %s", exc)
        return None
    series = [(r[0], float(r[1])) for r in rows if r[1] is not None]
    if not series:
        return None
    latest_date, latest = series[-1]
    first = series[0][1]
    change_abs = round(latest - first, 1)
    trend_pct = round((latest - first) / first * 100.0, 2) if first else None
    return {
        "latest": round(latest, 1),
        "latest_date": str(latest_date),
        "trend_pct": trend_pct,
        "change_abs": change_abs,
        "n": len(series),
    }


def polarized_zone_distribution(load: TrainingLoadMetrics) -> dict[str, float] | None:
    """Easy / grey / hard split of the last 7d of HR-zone conditioning minutes.

    For the polarized-conditioning planner path: returns total minutes plus the
    fraction in each pole — ``easy`` (Z0-Z2), ``grey`` (Z3, the threshold zone a
    polarized model deliberately minimizes), and ``hard`` (Z4-Z5). Returns None
    when there's no WHOOP zone data for the window (the fallback Z2-only path
    can't populate the full breakdown).

    Args:
        load: The training-load metrics carrying ``cardio_zone_min_7d``.

    Returns:
        ``{total_min, easy_min, grey_min, hard_min, easy_pct, grey_pct,
        hard_pct}`` or None.
    """
    z = load.cardio_zone_min_7d
    if not z:
        return None
    easy = z.get("z0", 0.0) + z.get("z1", 0.0) + z.get("z2", 0.0)
    grey = z.get("z3", 0.0)
    hard = z.get("z4", 0.0) + z.get("z5", 0.0)
    total = easy + grey + hard
    if total <= 0:
        return None
    return {
        "total_min": round(total, 1),
        "easy_min": round(easy, 1),
        "grey_min": round(grey, 1),
        "hard_min": round(hard, 1),
        "easy_pct": round(easy / total, 3),
        "grey_pct": round(grey / total, 3),
        "hard_pct": round(hard / total, 3),
    }


def _hrv_subscore(sigma: float | None) -> float | None:
    if sigma is None:
        return None
    return max(0.0, min(100.0, 50.0 + sigma * 25.0))


def _sleep_subscore(
    hours: float | None, deep_pct: float | None, spo2: float | None
) -> float | None:
    if hours is None:
        return None
    # Duration component (60% weight in OSA-off-CPAP context).
    if hours >= 7.5:
        dur = 100
    elif hours >= 6.5:
        dur = 75
    elif hours >= 5.5:
        dur = 50
    elif hours >= 4:
        dur = 25
    else:
        dur = 10
    # Deep% component — Rob is off CPAP, deep matters. 13–23% is healthy.
    if deep_pct is None:
        deep_score = dur  # fall back to duration if no stage data
    elif deep_pct >= 0.18:
        deep_score = 100
    elif deep_pct >= 0.13:
        deep_score = 75
    elif deep_pct >= 0.08:
        deep_score = 50
    else:
        deep_score = 25
    # SpO2 component — < 95 average is a flag for untreated OSA.
    if spo2 is None:
        spo2_score = (dur + deep_score) / 2
    elif spo2 >= 96:
        spo2_score = 100
    elif spo2 >= 94:
        spo2_score = 70
    elif spo2 >= 92:
        spo2_score = 40
    else:
        spo2_score = 15
    return 0.5 * dur + 0.3 * deep_score + 0.2 * spo2_score


def _rhr_subscore(rhr_7d: float | None, baseline: float | None) -> float | None:
    """Readiness contribution from resting HR vs its 28d baseline.

    Fed the SMOOTHED 7-day RHR (not a single night) and a gentler slope so a
    single noisy night doesn't crater readiness — a +10% elevation now reads 25,
    not 0 (panel review M12).
    """
    if rhr_7d is None or not baseline:
        return None
    pct = (rhr_7d - baseline) / baseline
    return max(0.0, min(100.0, 50.0 - pct * 250.0))


def _subj_subscore(
    energy: int | None,
    stress: int | None,
    soreness: int | None,
    sleep_quality: int | None = None,
    motivation: int | None = None,
) -> float | None:
    """Mean of the present 1–10 subjective check-ins, each mapped to 0–100.

    Higher energy/sleep-quality/motivation and lower stress/soreness all read as
    more ready. Subjective sleep quality is the felt-rest signal — distinct from
    the objective WHOOP sleep score that drives the separate sleep component.
    """
    parts: list[float] = []
    if energy is not None:
        parts.append(energy * 10.0)
    if stress is not None:
        parts.append((10 - stress) * 10.0)
    if soreness is not None:
        parts.append((10 - soreness) * 10.0)
    if sleep_quality is not None:
        parts.append(sleep_quality * 10.0)
    if motivation is not None:
        parts.append(motivation * 10.0)
    if not parts:
        return None
    return sum(parts) / len(parts)


def _tier(score: float | None) -> Tier | None:
    if score is None:
        return None
    if score >= 67:
        return "green"
    if score >= 34:
        return "yellow"
    return "red"


# ── Section builders ─────────────────────────────────────────────────────────


def _recovery(conn, today: date) -> RecoveryMetrics:
    rec = conn.execute(
        "SELECT date, score, hrv, rhr, skin_temp, spo2, user_calibrating "
        "FROM recovery ORDER BY date DESC LIMIT 1"
    ).fetchone()
    hrv_base = conn.execute(
        "SELECT hrv, hrv_28d_avg, hrv_28d_sd, hrv_28d_n "
        "FROM v_hrv_baseline_28d ORDER BY date DESC LIMIT 1"
    ).fetchone()
    rhr_rows = conn.execute(
        "SELECT date, rhr FROM recovery WHERE date >= $s AND rhr IS NOT NULL ORDER BY date",
        {"s": (today - timedelta(days=28)).isoformat()},
    ).fetchall()
    # Skin-temp baseline + its N — a 2-night baseline must not fire the illness
    # gate, so callers require BASELINE_MIN_N valid nights (panel review M13).
    skin_baseline = conn.execute(
        "SELECT AVG(skin_temp), COUNT(skin_temp) FROM recovery WHERE skin_temp IS NOT NULL "
        "AND date >= $since",
        {"since": (today - timedelta(days=28)).isoformat()},
    ).fetchone()

    m = RecoveryMetrics()
    if rec:
        m.score_date = str(rec[0])
        m.score = float(rec[1]) if rec[1] is not None else None
        m.hrv_ms = float(rec[2]) if rec[2] is not None else None
        m.rhr = int(rec[3]) if rec[3] is not None else None
        m.skin_temp = float(rec[4]) if rec[4] is not None else None
        m.spo2_pct = float(rec[5]) if rec[5] is not None else None
        m.user_calibrating = bool(rec[6]) if rec[6] is not None else None
    if hrv_base:
        hrv_n = int(hrv_base[3]) if hrv_base[3] is not None else 0
        # Require a minimum number of valid nights — a thin baseline gives an
        # unstable mean/SD, and hrv_sigma gates intensity (panel review M7/M13).
        if hrv_n >= BASELINE_MIN_N:
            m.hrv_baseline_28d = float(hrv_base[1]) if hrv_base[1] is not None else None
            m.hrv_sd_28d = float(hrv_base[2]) if hrv_base[2] is not None else None
            if m.hrv_ms and m.hrv_baseline_28d and m.hrv_sd_28d and m.hrv_sd_28d > 0:
                m.hrv_sigma = round((m.hrv_ms - m.hrv_baseline_28d) / m.hrv_sd_28d, 2)

    rhr_vals = [float(r[1]) for r in rhr_rows]
    if rhr_vals:
        m.rhr_baseline_28d = round(sum(rhr_vals) / len(rhr_vals), 1)
        last7 = rhr_vals[-7:]
        if last7:
            m.rhr_7d_avg = round(sum(last7) / len(last7), 1)
        if m.rhr_baseline_28d and m.rhr_7d_avg:
            m.rhr_elevated_pct = round(
                (m.rhr_7d_avg - m.rhr_baseline_28d) / m.rhr_baseline_28d * 100.0, 1
            )
    skin_n = int(skin_baseline[1]) if skin_baseline and skin_baseline[1] is not None else 0
    if skin_baseline and skin_baseline[0] is not None and skin_n >= BASELINE_MIN_N:
        m.skin_temp_baseline_28d = round(float(skin_baseline[0]), 2)
        if m.skin_temp is not None:
            # WHOOP stores skin temp in Celsius. Surface the delta in Fahrenheit
            # (×9/5 — no +32 offset for a difference) so every consumer and the
            # report prompt get °F per the project's imperial-units invariant.
            m.skin_temp_delta = round((m.skin_temp - m.skin_temp_baseline_28d) * 9 / 5, 2)

    # Respiratory rate baseline (28d, naps excluded). WHOOP/Bourdillon: a +1 bpm
    # rise above baseline is an early-warning illness sentinel ~4 days out.
    # Clamp to physiologically plausible adult sleep RR (8–30 bpm) so legacy
    # data corruption doesn't poison the baseline.
    rr_rows = conn.execute(
        "SELECT respiratory_rate FROM sleep "
        "WHERE COALESCE(is_nap, FALSE) = FALSE "
        "  AND respiratory_rate IS NOT NULL "
        "  AND respiratory_rate BETWEEN 8 AND 30 "
        "  AND night_date >= $s "
        "ORDER BY night_date",
        {"s": (today - timedelta(days=28)).isoformat()},
    ).fetchall()
    rr_vals = [float(r[0]) for r in rr_rows]
    if rr_vals:
        # Use median for robustness against any remaining outliers.
        m.respiratory_rate_baseline_28d = round(_st.median(rr_vals), 2)
        last_rr = rr_vals[-1]
        m.respiratory_rate_delta = round(last_rr - m.respiratory_rate_baseline_28d, 2)
    return m


def _sleep(conn, today: date) -> SleepMetrics:
    rows = conn.execute(
        "SELECT night_date, epoch(ts_out-ts_in)/3600.0 AS hrs, "
        "       sws_min, rem_min, light_min, awake_min, "
        "       sleep_efficiency_pct, sleep_consistency_pct, sleep_performance_pct, "
        "       disturbance_count, sleep_needed_min, spo2_avg, "
        "       ts_in, ts_out, stages_json, "
        "       sleep_cycle_count, in_bed_min, no_data_min, "
        "       sleep_need_baseline_min, sleep_need_debt_min, sleep_need_strain_min, "
        "       sleep_need_nap_min, respiratory_rate "
        "FROM sleep WHERE night_date >= $s AND ts_in IS NOT NULL AND ts_out IS NOT NULL "
        "  AND COALESCE(is_nap, FALSE) = FALSE "
        "ORDER BY night_date, ts_in",
        {"s": (today - timedelta(days=14)).isoformat()},
    ).fetchall()
    m = SleepMetrics()
    if not rows:
        return m

    # Collapse multiple sleep records per night (naps already filtered) into the
    # longest one — Whoop sometimes returns split sessions for awakenings.
    by_night: dict[str, tuple] = {}
    for r in rows:
        key = str(r[0])
        prev = by_night.get(key)
        if prev is None or (r[1] or 0) > (prev[1] or 0):
            by_night[key] = r
    nights = [by_night[k] for k in sorted(by_night.keys())]
    last = nights[-1]

    m.last_date = str(last[0])
    m.last_hours = round(float(last[1]), 2) if last[1] is not None else None
    sws, rem, light, awake = last[2], last[3], last[4], last[5]
    # Fallback: parse stages_json if dedicated columns are null (older rows).
    if sws is None and last[14]:
        try:
            stages = json.loads(last[14]) if isinstance(last[14], str) else last[14]
            if isinstance(stages, str):
                stages = json.loads(stages.replace("'", '"'))
            if "total_slow_wave_sleep_time_milli" in stages:
                sws = (stages.get("total_slow_wave_sleep_time_milli") or 0) / 60000
                rem = (stages.get("total_rem_sleep_time_milli") or 0) / 60000
                light = (stages.get("total_light_sleep_time_milli") or 0) / 60000
                awake = (stages.get("total_awake_time_milli") or 0) / 60000
        except (ValueError, AttributeError, TypeError):
            pass

    if sws is not None:
        m.deep_min_last = round(float(sws), 1)
    if rem is not None:
        m.rem_min_last = round(float(rem), 1)
    if light is not None:
        m.light_min_last = round(float(light), 1)
    if awake is not None:
        m.awake_min_last = round(float(awake), 1)

    asleep = sum(float(x or 0) for x in (sws, rem, light))
    if asleep > 0:
        m.deep_pct_last = round(float(sws or 0) / asleep, 3)
        m.rem_pct_last = round(float(rem or 0) / asleep, 3)

    m.efficiency_pct_last = round(float(last[6]), 1) if last[6] is not None else None
    m.consistency_pct_last = round(float(last[7]), 1) if last[7] is not None else None
    m.performance_pct_last = round(float(last[8]), 1) if last[8] is not None else None
    m.disturbance_count_last = int(last[9]) if last[9] is not None else None
    m.sleep_needed_min_last = round(float(last[10]), 1) if last[10] is not None else None
    m.spo2_avg_last = round(float(last[11]), 1) if last[11] is not None else None
    m.sleep_cycle_count_last = int(last[15]) if last[15] is not None else None
    m.in_bed_min_last = round(float(last[16]), 1) if last[16] is not None else None
    m.no_data_min_last = round(float(last[17]), 1) if last[17] is not None else None
    m.sleep_need_baseline_min_last = round(float(last[18]), 1) if last[18] is not None else None
    m.sleep_need_debt_min_last = round(float(last[19]), 1) if last[19] is not None else None
    m.sleep_need_strain_min_last = round(float(last[20]), 1) if last[20] is not None else None
    m.sleep_need_nap_min_last = round(float(last[21]), 1) if last[21] is not None else None
    m.respiratory_rate_last = round(float(last[22]), 1) if last[22] is not None else None

    # Sleep midpoint: ts_in + (ts_out - ts_in) / 2, expressed as decimal local hours.
    def _midpoint_hours(ts_in, ts_out) -> float | None:
        if ts_in is None or ts_out is None:
            return None
        try:
            mid = ts_in + (ts_out - ts_in) / 2
            return mid.hour + mid.minute / 60 + mid.second / 3600
        except Exception:
            return None

    midpoints = [_midpoint_hours(r[12], r[13]) for r in nights]
    midpoints = [x for x in midpoints if x is not None]
    if midpoints:
        m.midpoint_local_h_last = round(midpoints[-1], 2)
        last7_mid = midpoints[-7:]
        if len(last7_mid) >= 2:
            # Treat midpoint as circular: hours near 0 and 24 are adjacent.
            shifted = [(h - last7_mid[0] + 12) % 24 - 12 + last7_mid[0] for h in last7_mid]
            m.midpoint_stdev_h_7d = round(_st.pstdev(shifted), 2)

    hours_vals = [float(r[1]) for r in nights if r[1] is not None and 2 < float(r[1]) < 14]
    last7 = hours_vals[-7:]
    if last7:
        m.avg_7d = round(sum(last7) / len(last7), 2)
        if len(last7) >= 2:
            m.consistency_stdev_7d = round(_st.pstdev(last7), 2)
        m.debt_7d_h = round(sum(max(0.0, 8.0 - h) for h in last7), 1)
    m.score = _sleep_subscore(m.last_hours, m.deep_pct_last, m.spo2_avg_last)
    return m


def _training_load(conn, today: date) -> TrainingLoadMetrics:
    m = TrainingLoadMetrics()
    load_rows = conn.execute(
        "SELECT date, composite_load, whoop_strain, hevy_tonnes "
        "FROM v_daily_load WHERE date >= $s ORDER BY date",
        {"s": (today - timedelta(days=28)).isoformat()},
    ).fetchall()
    if load_rows:
        # UNCOUPLED ACWR (panel review M2): chronic is the 21 days BEFORE the
        # acute window (days 8–28), not the full 28 that contain it. The coupled
        # form (acute ⊂ chronic) compresses ratios toward 1.0 and dampens the
        # very spikes the gate exists to catch (Lolli 2019; Windt & Gabbett 2019).
        # Mean over the window length (not just non-zero days) so ACWR drops on
        # rest weeks. Per arm: composite (pooled, display), conditioning (WHOOP
        # strain), resistance (Hevy tonnes); scale-invariant within an arm.
        #
        # The acute window is the 7 days ENDING today — [today-6, today] — and the
        # chronic window is the 21 days immediately before it — [today-27, today-7].
        # Both edges are bounded explicitly so the arms stay exactly 7 and 21 days:
        # an earlier `>= today-7` gave the acute arm an 8th day-slot (today-7) while
        # still dividing by 7, inflating every ratio ~14% and making the Gabbett
        # thresholds (1.5/1.8/2.0 — defined on a true 7:21 ratio) fire too eagerly.
        acute_start = today - timedelta(days=6)
        chronic_start = today - timedelta(days=27)

        def _arm_acwr(idx: int) -> tuple[float, float, float | None]:
            recent = [float(r[idx] or 0) for r in load_rows if r[0] >= acute_start]
            prior = [float(r[idx] or 0) for r in load_rows if chronic_start <= r[0] < acute_start]
            acute = sum(recent) / 7.0
            chronic = sum(prior) / 21.0
            # Ratio from RAW means — rounding chronic first can zero a small arm.
            ratio = round(acute / chronic, 2) if chronic > 0 else None
            return round(acute, 2), round(chronic, 2), ratio

        m.acute_load_7d, m.chronic_load_28d, m.acwr = _arm_acwr(1)
        m.conditioning_acute_7d, m.conditioning_chronic_28d, m.conditioning_acwr = _arm_acwr(2)
        m.resistance_acute_7d, m.resistance_chronic_28d, m.resistance_acwr = _arm_acwr(3)

    last_session = conn.execute("SELECT MAX(started_at::DATE) FROM workouts").fetchone()
    if last_session and last_session[0]:
        m.last_session_date = str(last_session[0])
        m.days_since_last = (today - last_session[0]).days

    # Days since each muscle group (uses workout_sets — strength only).
    set_rows = conn.execute(
        """
        SELECT day_d AS day, ws.exercise, ws.rpe
        FROM workout_sets_dedup ws
        WHERE ws.is_warmup = FALSE AND day_d >= $since
        """,
        {"since": (today - timedelta(days=28)).isoformat()},
    ).fetchall()
    last_by_group: dict[str, date] = {}
    bal: dict[str, int] = {"push": 0, "pull": 0, "legs": 0, "core": 0, "other": 0}
    for day, exercise, _rpe in set_rows:
        g = muscle_group(exercise or "")
        bal[g] = bal[g] + 1
        if g not in last_by_group or day > last_by_group[g]:
            last_by_group[g] = day
    # Pickleball is a lower-body stimulus but a CONDITIONING one — it gets its
    # own clock (same-day legs gate in _gates) instead of resetting the 72h
    # lifting clock. Resetting days_since_legs here meant a weekend court
    # schedule permanently rest-gated leg lifting (23 leg sets vs 85 push in
    # the 28d that motivated this change).
    pb_last_row = conn.execute(
        "SELECT MAX(date) FROM cardio_sessions WHERE modality = 'pickleball'"
    ).fetchone()
    if pb_last_row and pb_last_row[0]:
        pb_date = (
            pb_last_row[0]
            if isinstance(pb_last_row[0], date)
            else date.fromisoformat(str(pb_last_row[0]))
        )
        m.days_since_pickleball = (today - pb_date).days

    for g in ("push", "pull", "legs"):
        if g in last_by_group:
            setattr(m, f"days_since_{g}", (today - last_by_group[g]).days)
            # Avg logged RPE of that group's most recent session — lets the
            # rest gate distinguish a submaximal day from a near-failure one.
            rpes = [
                float(r[2])
                for r in set_rows
                if r[0] == last_by_group[g] and r[2] is not None and muscle_group(r[1] or "") == g
            ]
            if rpes:
                setattr(m, f"last_rpe_{g}", round(sum(rpes) / len(rpes), 1))
    m.push_sets_28d = bal["push"]
    m.pull_sets_28d = bal["pull"]
    m.legs_sets_28d = bal["legs"]
    if m.push_sets_28d and m.pull_sets_28d:
        m.push_pull_ratio_28d = round(m.push_sets_28d / m.pull_sets_28d, 2)

    cardio = conn.execute(
        """
        SELECT COALESCE(SUM(duration_min), 0) FROM cardio_sessions
        WHERE date >= $since
        """,
        {"since": (today - timedelta(days=28)).isoformat()},
    ).fetchone()
    if cardio and cardio[0] is not None:
        m.cardio_min_28d = int(cardio[0])

    # Per-modality breakdown for last 7 days — drives the pickleball_focus signal.
    # Exclude WHOOP auto-detected non-sport modalities (yoga, meditation) — same
    # filter the cardio panel applies so the numbers stay consistent.
    modality_rows = conn.execute(
        """
        SELECT modality, COALESCE(SUM(duration_min), 0) AS mins
        FROM cardio_sessions
        WHERE date >= $since AND modality NOT IN ('yoga', 'meditation', 'cross country skiing')
        GROUP BY modality
        """,
        {"since": (today - timedelta(days=7)).isoformat()},
    ).fetchall()
    m.cardio_modality_min_7d = {(r[0] or "unknown"): int(r[1] or 0) for r in modality_rows}
    m.pickleball_min_7d = m.cardio_modality_min_7d.get("pickleball", 0)
    pb28_row = conn.execute(
        """
        SELECT COALESCE(SUM(duration_min), 0) FROM cardio_sessions
        WHERE date >= $since AND modality = 'pickleball'
        """,
        {"since": (today - timedelta(days=28)).isoformat()},
    ).fetchone()
    if pb28_row and pb28_row[0] is not None:
        m.pickleball_min_28d = int(pb28_row[0])

    # Z2 (and full HR-zone breakdown) — prefer WHOOP's authoritative zone
    # durations on each workout. Falls back to inferring from avg_hr when
    # zone data isn't present (older imports, manual cardio entries).
    zone_row = conn.execute(
        """
        SELECT
            COALESCE(SUM(zone_zero_min),  0) AS z0,
            COALESCE(SUM(zone_one_min),   0) AS z1,
            COALESCE(SUM(zone_two_min),   0) AS z2,
            COALESCE(SUM(zone_three_min), 0) AS z3,
            COALESCE(SUM(zone_four_min),  0) AS z4,
            COALESCE(SUM(zone_five_min),  0) AS z5
        FROM workouts
        WHERE started_at >= $since
        """,
        {"since": (today - timedelta(days=7)).isoformat()},
    ).fetchone()
    zone_total = sum(zone_row) if zone_row else 0
    if zone_total > 0:
        m.cardio_zone_min_7d = {
            "z0": round(float(zone_row[0]), 1),
            "z1": round(float(zone_row[1]), 1),
            "z2": round(float(zone_row[2]), 1),
            "z3": round(float(zone_row[3]), 1),
            "z4": round(float(zone_row[4]), 1),
            "z5": round(float(zone_row[5]), 1),
        }
        m.cardio_z2_min_7d = int(round(float(zone_row[2])))
        m.cardio_zone3_min_7d = m.cardio_zone_min_7d["z3"]
        m.cardio_zone4_min_7d = m.cardio_zone_min_7d["z4"]
        m.cardio_zone5_min_7d = m.cardio_zone_min_7d["z5"]
        m.cardio_high_intensity_min_7d = int(
            round(float(zone_row[3]) + float(zone_row[4]) + float(zone_row[5]))
        )
    else:
        # Fallback: HR-range inference using whichever max HR we have.
        # 60–70% of max = Z2 (Seiler / polarized model).
        max_hr = _latest_max_hr(conn) or 180  # 180 = Tanaka @ age 40
        z2_low = int(round(0.60 * max_hr))
        z2_high = int(round(0.70 * max_hr))
        z2 = conn.execute(
            f"""
            SELECT COALESCE(SUM(duration_min), 0)
            FROM cardio_sessions
            WHERE date >= $since
              AND avg_hr IS NOT NULL
              AND avg_hr BETWEEN {z2_low} AND {z2_high}
            """,
            {"since": (today - timedelta(days=7)).isoformat()},
        ).fetchone()
        if z2 and z2[0] is not None:
            m.cardio_z2_min_7d = int(z2[0])

    # Max HR — prefer WHOOP-measured, fall back to Tanaka formula.
    m.max_hr_measured = _latest_max_hr(conn)
    age_today = _age_today(conn)
    if age_today is not None:
        m.max_hr_tanaka = int(round(208 - 0.7 * age_today))

    _apply_day_strain(conn, today, m)
    return m


def _apply_day_strain(conn, today: date, m: TrainingLoadMetrics) -> None:
    """Surface WHOOP `daily_cycle.strain` into the training-load metrics.

    WHOOP day-strain (0-21, logarithmic) is the whole-day cardiovascular load —
    distinct from the 7/28d ACWR arms — and previously only reached lab.py. The
    planner uses ``day_strain_yesterday`` to ease today's session after a hard
    day. Fails VISIBLY: if `daily_cycle` (or its `strain` column) isn't present,
    the fields stay None and a warning is logged rather than silently zeroed.
    """
    try:
        rows = conn.execute(
            """
            SELECT date, MAX(strain) AS strain
            FROM daily_cycle
            WHERE date >= $s AND strain IS NOT NULL
            GROUP BY date
            ORDER BY date
            """,
            {"s": (today - timedelta(days=7)).isoformat()},
        ).fetchall()
    except Exception as exc:
        log.warning("daily_cycle.strain unavailable — day_strain not surfaced: %s", exc)
        return
    if not rows:
        return
    by_date = {
        (r[0] if isinstance(r[0], date) else date.fromisoformat(str(r[0]))): float(r[1])
        for r in rows
        if r[1] is not None
    }
    if today in by_date:
        m.day_strain_today = round(by_date[today], 1)
    prior = sorted(d for d in by_date if d < today)
    if prior:
        m.day_strain_yesterday = round(by_date[prior[-1]], 1)
    vals = list(by_date.values())
    if vals:
        m.day_strain_7d_avg = round(sum(vals) / len(vals), 1)


def _latest_max_hr(conn) -> int | None:
    """Most recent WHOOP-measured max HR from body_measurement."""
    try:
        row = conn.execute(
            "SELECT max_heart_rate FROM body_measurement "
            "WHERE max_heart_rate IS NOT NULL "
            "ORDER BY measured_at DESC LIMIT 1"
        ).fetchone()
        return int(row[0]) if row and row[0] is not None else None
    except Exception:
        # body_measurement may not exist on older schemas.
        return None


def _age_today(conn) -> int | None:
    """Rob's age. Single-user platform — hardcoded constant matches frontend."""
    return _ROB_AGE


def _checkin(conn, today: date) -> CheckinMetrics:
    row = conn.execute(
        """
        SELECT date, propranolol_taken, body_weight_kg, soreness_overall,
               sleep_quality_1_10, energy_1_10, stress_1_10, motivation_1_10,
               illness_flag, travel_flag, muscle_soreness
        FROM daily_checkin WHERE date = $d
        """,
        {"d": today.isoformat()},
    ).fetchone()
    m = CheckinMetrics()
    if row:
        m.date = str(row[0])
        m.propranolol_taken = bool(row[1]) if row[1] is not None else None
        m.body_weight_kg = float(row[2]) if row[2] is not None else None
        m.soreness_overall = int(row[3]) if row[3] is not None else None
        m.sleep_quality = int(row[4]) if row[4] is not None else None
        m.energy = int(row[5]) if row[5] is not None else None
        m.stress = int(row[6]) if row[6] is not None else None
        m.motivation = int(row[7]) if row[7] is not None else None
        m.illness_flag = bool(row[8]) if row[8] is not None else False
        m.travel_flag = bool(row[9]) if row[9] is not None else False
        if row[10] is not None:
            raw = row[10]
            if isinstance(raw, str):
                import json as _json

                try:
                    raw = _json.loads(raw)
                except _json.JSONDecodeError:
                    raw = {}
            if isinstance(raw, dict):
                m.muscle_soreness = {
                    str(k): int(v) for k, v in raw.items() if isinstance(v, (int, float))
                }

    # Body-weight trend (4-week %): prefer manual checkin, fall back to
    # measurements table.
    today_kg = m.body_weight_kg
    if today_kg is None:
        latest = conn.execute(
            "SELECT value_num FROM measurements WHERE metric IN ('body_mass_kg', 'body_mass', 'weight') "
            "AND value_num IS NOT NULL ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        today_kg = float(latest[0]) if latest and latest[0] else None
    past = conn.execute(
        """
        SELECT value_num FROM measurements
        WHERE metric IN ('body_mass_kg', 'body_mass', 'weight') AND value_num IS NOT NULL
          AND ts <= $cutoff
        ORDER BY ts DESC LIMIT 1
        """,
        {"cutoff": (today - timedelta(days=28)).isoformat()},
    ).fetchone()
    past_kg = float(past[0]) if past and past[0] else None
    if today_kg and past_kg:
        m.body_weight_trend_4wk = round((today_kg - past_kg) / past_kg * 100.0, 2)
    return m


def _readiness_snapshot(
    rec: RecoveryMetrics,
    sleep: SleepMetrics,
    chk: CheckinMetrics,
    *,
    beta_blocker: bool,
) -> ReadinessSnapshot:
    weights = BETA_BLOCKER_WEIGHTS if beta_blocker else DEFAULT_WEIGHTS
    components: dict[str, float | None] = {
        "hrv": _hrv_subscore(rec.hrv_sigma),
        "sleep": sleep.score,
        "rhr": _rhr_subscore(rec.rhr_7d_avg or rec.rhr, rec.rhr_baseline_28d),
        "subj": _subj_subscore(
            chk.energy,
            chk.stress,
            chk.soreness_overall,
            chk.sleep_quality,
            chk.motivation,
        ),
    }
    present = [(k, v) for k, v in components.items() if v is not None]
    if not present:
        return ReadinessSnapshot(
            score=None,
            tier=None,
            weights=weights,
            components=components,
            beta_blocker_adjusted=beta_blocker,
        )
    wsum = sum(weights[k] for k, _ in present) or 1.0
    score = sum(weights[k] / wsum * v for k, v in present)
    return ReadinessSnapshot(
        score=round(score, 1),
        tier=_tier(score),
        weights=weights,
        components=components,
        beta_blocker_adjusted=beta_blocker,
    )


DELOAD_COOLDOWN_DAYS = 9


def _acwr_band_sample_weeks(conn) -> tuple[int, int]:
    """Fitted sample-week count for the (resistance, conditioning) ACWR arms.

    Reads ``personal_acwr_bands.sample_weeks`` directly so the gate can decide
    whether a personal band rests on enough history to tighten the population
    floor. Returns ``(0, 0)`` when the table is absent or empty.
    """
    try:
        rows = conn.execute(
            "SELECT arm, MAX(sample_weeks) FROM personal_acwr_bands GROUP BY arm"
        ).fetchall()
    except Exception:
        return 0, 0
    by_arm = {str(arm): int(n) for arm, n in rows if n is not None}
    return by_arm.get("resistance", 0), by_arm.get("conditioning", 0)


def _apply_band(personal: float, population: float, floor_only: bool) -> float:
    """Reconcile a personal ACWR threshold against its population default.

    When ``floor_only`` (thin sample), the personal band may only LOOSEN —
    ``max`` keeps the conservative population floor. Once the sample is thick
    enough to trust, the personal band is used as-is and may tighten below the
    floor.
    """
    return max(personal, population) if floor_only else personal


def _apply_band_loosen_down(personal: float, population: float) -> float:
    """Like ``_apply_band(floor_only=True)`` but for gates where LOOSENING
    means LOWERING the trigger threshold — e.g. sleep-cycle count, where the
    population default is a protective ceiling a chronic condition may
    legitimately clear most nights without the night being unusually bad.
    """
    return min(personal, population)


# Illness-gate corroboration thresholds. A skin-temp / respiratory-rate rise is
# used as an illness sentinel, but for someone with chronic allergic rhinitis +
# asthma those signals are inflated by H1-mediated peripheral vasodilation and
# sleep-disordered breathing WITHOUT systemic infection — so a lone-signal cap
# false-positives constantly (see wiki/allergic-rhinitis-confounds-recovery-metrics.md
# and the 4-10% PPV of single-model wearable illness detection). Require an
# independent signal to agree before capping; reserve a lone cap for a fever-range
# spike no peripheral vasodilation can produce.
_ILLNESS_CORROB_HRV_SIGMA = -1.0  # HRV suppressed beyond mild day-to-day noise
_ILLNESS_CORROB_RECOVERY = 50.0  # WHOOP recovery clearly depressed (not just yellow)
_ILLNESS_CORROB_RHR_PCT = 8.0  # RHR meaningfully elevated vs 28d baseline
_GREEN_RECOVERY_MIN = 67.0  # WHOOP green floor — affirmative "recovered" evidence
_SKIN_TEMP_FEVER_DELTA = 2.0  # °F rise too large to be peripheral vasodilation alone


def _illness_gate_corroborated(rec: RecoveryMetrics) -> bool:
    """Whether a skin-temp / resp-rate rise should be treated as possible illness.

    Returns True (cap) when an independent signal corroborates infection — suppressed
    HRV, depressed recovery, or elevated RHR — OR when recovery evidence is missing
    (fail conservative). Returns False (don't cap) only when recovery is affirmatively
    green with normal HRV: on such a day an isolated temp/RR bump is far more likely
    allergy or environment than infection for a chronic-rhinitis athlete.
    """
    illness_signal = (
        (rec.hrv_sigma is not None and rec.hrv_sigma < _ILLNESS_CORROB_HRV_SIGMA)
        or (rec.score is not None and rec.score < _ILLNESS_CORROB_RECOVERY)
        or (rec.rhr_elevated_pct is not None and rec.rhr_elevated_pct >= _ILLNESS_CORROB_RHR_PCT)
    )
    if illness_signal:
        return True
    recovery_affirmatively_green = (rec.score is not None and rec.score >= _GREEN_RECOVERY_MIN) or (
        rec.score is None
        and rec.hrv_sigma is not None
        and rec.hrv_sigma >= _ILLNESS_CORROB_HRV_SIGMA
    )
    return not recovery_affirmatively_green


def _whoop_stale(rec: RecoveryMetrics, today: date) -> bool:
    """WHOOP recovery hasn't synced in >2 days — HRV/skin-temp/SpO2-derived caps go blind.

    Single source of truth so the safety gate and any downstream consumer (e.g. the
    volume controller's conditioning-interference hold) can never disagree about
    whether recovery data is stale.
    """
    return rec.score_date is not None and (today - date.fromisoformat(rec.score_date)).days > 2


def _sleep_stale(sleep: SleepMetrics, today: date) -> bool:
    """Sleep table hasn't synced in >2 days — sleep-architecture/RR-derived caps go blind."""
    return sleep.last_date is not None and (today - date.fromisoformat(sleep.last_date)).days > 2


def _gates(
    rec: RecoveryMetrics,
    sleep: SleepMetrics,
    load: TrainingLoadMetrics,
    chk: CheckinMetrics,
    readiness: ReadinessSnapshot,
    e1rm_regression_pct: float | None,
    deload_cooldown: bool = False,
    e1rm_lift: str | None = None,
    conn=None,
) -> AutoRegGates:
    g = AutoRegGates()
    reasons: list[str] = []

    # Load personal ACWR bands if available; fall back to population constants.
    res_rest = RES_ACWR_REST
    res_low = RES_ACWR_LOW
    res_mod = RES_ACWR_MOD
    cond_forbid_legs = COND_ACWR_FORBID_LEGS
    if conn is not None:
        try:
            from shc.training.self_learning import read_acwr_bands

            personal = read_acwr_bands(conn)
            if personal:
                # Personal bands LOOSEN the population defaults freely, but may
                # only TIGHTEN below them once the fit rests on enough weeks to
                # describe Rob's current training era rather than the low-volume
                # history that drags percentiles down (the ACWR trap: an
                # unfloored thin-sample band gates ordinary accumulation as a
                # "fatigue spike", suppressing volume → lowering chronic load →
                # worsening next week's ratio). _ACWR_TIGHTEN_MIN_WEEKS is set
                # above the fitter's own minimum so the bar to tighten is
                # strictly stricter than the bar to merely fit. Gating is
                # per-arm on each arm's own sample_weeks.
                _res_n, cond_n = _acwr_band_sample_weeks(conn)
                cond_floor = cond_n < _ACWR_TIGHTEN_MIN_WEEKS
                # All three resistance bands (REST/LOW/MOD) are absolute
                # injury-spike ceilings (Gabbett), not homeostats. Fitted as
                # percentiles of Rob's own load they sit BELOW the population
                # thresholds and gate ordinary progressive overload as if it were
                # a fatigue spike — the ACWR-as-anti-progression trap, which is
                # actively hostile to a hypertrophy goal. So every resistance band
                # is floor_only: it may only LOOSEN above population (earn more
                # rope), never tighten below it. Resistance ACWR on Rob's N=1
                # noise-dominated chronic baseline is not injury-validated;
                # letting his thin-data history tighten the hardest gate below 2.0
                # turned ordinary accumulation into a "fatigue spike" and grounded
                # good days. Conditioning keeps sample-gated personalization
                # (field-sport evidence is stronger) and may still tighten once
                # well-fit.
                res_rest = _apply_band(personal["RES_ACWR_REST"], RES_ACWR_REST, floor_only=True)
                res_low = _apply_band(personal["RES_ACWR_LOW"], RES_ACWR_LOW, floor_only=True)
                res_mod = _apply_band(personal["RES_ACWR_MOD"], RES_ACWR_MOD, floor_only=True)
                cond_forbid_legs = _apply_band(
                    personal["COND_ACWR_FORBID_LEGS"], COND_ACWR_FORBID_LEGS, cond_floor
                )
        except Exception as exc:
            import logging as _log

            _log.getLogger(__name__).debug("personal ACWR bands unavailable: %s", exc)

    # Load personal sleep-architecture bands if available; fall back to
    # population constants. Loosen-only (see _apply_band_loosen_down): a thin
    # or absent fit keeps the protective population default, never gets
    # stricter than it.
    disturbance_threshold = _SLEEP_DISTURBANCE_POPULATION
    cycle_threshold = _SLEEP_CYCLE_POPULATION
    if conn is not None:
        try:
            from shc.training.self_learning import read_sleep_bands

            personal_sleep = read_sleep_bands(conn)
            if personal_sleep:
                disturbance_threshold = _apply_band(
                    personal_sleep["DISTURBANCE_P80"],
                    _SLEEP_DISTURBANCE_POPULATION,
                    floor_only=True,
                )
                cycle_threshold = _apply_band_loosen_down(
                    personal_sleep["CYCLE_P20"], _SLEEP_CYCLE_POPULATION
                )
        except Exception as exc:
            import logging as _log

            _log.getLogger(__name__).debug("personal sleep bands unavailable: %s", exc)

    # Freshness guard: WHOOP recovery data older than 2 days is stale — the HRV/
    # skin-temp/SpO₂ values reflect a past night, not tonight's recovery.  Firing
    # safety caps on stale data locks Rob into "low" indefinitely after a sync outage.
    # Same 48h window the conditioning gate uses (see below). Uses the same helper
    # `_freshness()` uses for `DataFreshness.whoop_stale` — one flag, never two.
    whoop_stale = _whoop_stale(rec, date.today())
    sleep_stale = _sleep_stale(sleep, date.today())

    # Hard rest gates.
    if whoop_stale:
        reasons.append(
            "WHOOP not synced >2d — HRV/skin-temp/SpO₂ safety caps are BLIND "
            "(verify recovery manually)"
        )
    else:
        if rec.hrv_sigma is not None and rec.hrv_sigma < -1.5:
            g.max_intensity = "low"
            reasons.append(f"HRV {rec.hrv_sigma:+.2f}σ → red — cap intensity LOW")
        if rec.skin_temp_delta is not None and rec.skin_temp_delta >= 0.9:
            # skin_temp_delta is already °F. 0.9°F ≈ 0.5°C. Only elevated (positive)
            # deltas signal risk. But a lone skin-temp rise is heavily confounded by
            # allergic vasodilation/environment for a chronic-rhinitis athlete, so it
            # only caps when a fever-range spike OR an independent illness signal
            # corroborates it (see _illness_gate_corroborated).
            fever_range = rec.skin_temp_delta >= _SKIN_TEMP_FEVER_DELTA
            if fever_range or _illness_gate_corroborated(rec):
                g.max_intensity = "low"
                cause = "fever-range spike" if fever_range else "corroborated by HRV/RHR/recovery"
                reasons.append(
                    f"Skin-temp Δ+{rec.skin_temp_delta:.1f}°F above baseline "
                    f"({cause}) — possible illness, Z2 only"
                )
            else:
                reasons.append(
                    f"Skin-temp Δ+{rec.skin_temp_delta:.1f}°F above baseline but recovery green "
                    "& HRV normal — reads as allergy/environment, not illness; not capping "
                    "[allergic-rhinitis-confounds-recovery-metrics]"
                )
        if rec.spo2_pct is not None and rec.spo2_pct < 92.0:
            # Clinical threshold for sleep-disordered breathing / hypoxia overnight.
            g.max_intensity = "low" if g.max_intensity == "high" else g.max_intensity
            reasons.append(f"Overnight SpO₂ {rec.spo2_pct:.1f}% < 92% — cap intensity LOW")
    if rec.user_calibrating:
        # WHOOP recovery score is unreliable while calibrating — flag it but don't gate.
        reasons.append("WHOOP user_calibrating=true — recovery score may be unreliable")

    # Respiratory-rate sentinel — Bourdillon et al. RR baseline drift is a 4-day
    # leading indicator for viral illness. +1 bpm above 28d baseline = high
    # specificity early warning; +0.5 bpm = elevated suspicion. respiratory_rate_delta
    # is sourced from the `sleep` table (not WHOOP recovery), so it's gated on
    # sleep_stale — same guard pattern as the sleep-architecture flags below —
    # rather than firing on a night that may be days old.
    if not sleep_stale and rec.respiratory_rate_delta is not None:
        # Same allergy confound as skin temp: nasal congestion + sleep-disordered
        # breathing raise the sleeping RR without infection. Only cap when an
        # independent signal corroborates; otherwise surface it as a watch note.
        if rec.respiratory_rate_delta >= 1.0 and _illness_gate_corroborated(rec):
            if g.max_intensity == "high":
                g.max_intensity = "moderate"
            reasons.append(
                f"Resp rate +{rec.respiratory_rate_delta:.1f} bpm vs baseline — "
                "corroborated early-warning illness signal, cap MODERATE"
            )
        elif rec.respiratory_rate_delta >= 0.5:
            reasons.append(
                f"Resp rate +{rec.respiratory_rate_delta:.1f} bpm vs baseline — "
                "watch for additional illness signs (uncorroborated; may be allergy/congestion)"
            )

    # Sleep-architecture / quality caps. Every one of these markers is
    # chronically "off" on Rob's diagnosed off-CPAP OSA baseline (Vitale 2019:
    # <4 cycles is structurally inadequate; efficiency/disturbances/performance
    # are the WHOOP score breakdown), so any ONE firing is his normal, not an
    # acute red flag — capping intensity on it every night parked him at MODERATE.
    # Following the same corroboration rule the soreness gate uses (M11), a lone
    # marker is surfaced but only ≥2 concurrent markers — a genuinely fragmented
    # night relative to his baseline — cap intensity.
    sleep_flags: list[str] = []
    if (
        not sleep_stale
        and sleep.sleep_cycle_count_last is not None
        and sleep.sleep_cycle_count_last < cycle_threshold
    ):
        sleep_flags.append(
            f"only {sleep.sleep_cycle_count_last} sleep cycles (personal floor "
            f"{cycle_threshold:.1f})"
        )
    if not sleep_stale and sleep.efficiency_pct_last is not None and sleep.efficiency_pct_last < 75:
        sleep_flags.append(f"sleep efficiency {sleep.efficiency_pct_last:.0f}% < 75%")
    if (
        not sleep_stale
        and sleep.disturbance_count_last is not None
        and sleep.disturbance_count_last >= disturbance_threshold
    ):
        sleep_flags.append(
            f"disturbances {sleep.disturbance_count_last} ≥ {disturbance_threshold:.1f} "
            "(personal baseline)"
        )
    if (
        not sleep_stale
        and sleep.performance_pct_last is not None
        and sleep.performance_pct_last < 60
    ):
        sleep_flags.append(f"sleep performance {sleep.performance_pct_last:.0f}% < 60%")
    if len(sleep_flags) >= 2:
        if g.max_intensity == "high":
            g.max_intensity = "moderate"
        reasons.append(
            "Fragmented night — " + "; ".join(sleep_flags) + " (≥2 sleep markers) → cap MODERATE"
        )
    elif sleep_flags:
        reasons.append(
            f"Sleep marker: {sleep_flags[0]} — single marker (OSA-normal), noted but not capping"
        )

    if chk.illness_flag:
        g.max_intensity = "rest"
        reasons.append("Illness flag set — rest day")
    # ACWR gates — modality-split (Gabbett thresholds applied per arm).
    # Lifting intensity is governed by the RESISTANCE arm (Hevy). A CONDITIONING
    # spike (pickleball/cardio) must not rest-gate the barbell, so it holds
    # court/cardio and forbids legs (pickleball = lateral lower-body stimulus)
    # rather than capping global intensity. This prevents a heavy pickleball
    # week from grounding under-stimulated upper-body lifting.
    res = load.resistance_acwr
    if res is not None and res > res_rest:
        # An overreaching signal reduces LOAD; it does not forbid training.
        # Resistance ACWR on an N=1 noise-dominated chronic baseline is not an
        # injury-validated stop-gate, and a full rest day drops chronic load →
        # worsens tomorrow's ratio (the anti-progression trap). A reduced
        # technique/pump day keeps chronic load climbing so the ratio
        # self-corrects. Only an objective recovery gate above (illness, HRV,
        # SpO₂) may push below LOW to rest.
        if g.max_intensity in ("high", "moderate"):
            g.max_intensity = "low"
        reasons.append(
            f"Resistance ACWR {res} > {res_rest} — high lifting fatigue, cap LOW "
            "(reduced load, not rest — resting would worsen the ratio)"
        )
    elif res is not None and res > res_low:
        if g.max_intensity in ("high", "moderate"):
            g.max_intensity = "low"
        reasons.append(f"Resistance ACWR {res} > {res_low} — elevated lifting fatigue, cap LOW")
    elif res is not None and res > res_mod:
        if g.max_intensity == "high":
            g.max_intensity = "moderate"
        reasons.append(f"Resistance ACWR {res} > {res_mod} — accumulating fatigue, cap MODERATE")

    # When WHOOP hasn't synced for >2 days, conditioning_acwr trends toward zero as
    # the chronic window fills with zeros — silently low ratio means leg/conditioning
    # gates never fire. Reuse the whoop_stale flag computed above.
    cond_raw = load.conditioning_acwr
    cond = None if whoop_stale else cond_raw
    if whoop_stale:
        # Fail VISIBLY: the conditioning/leg-protection gate runs on WHOOP strain.
        # When that data is stale we can't see court/cardio load, so the gate is
        # blind — say so rather than silently letting a leg day through.
        reasons.append(
            "WHOOP not synced >48h — conditioning ACWR unavailable; leg/court-load "
            "protection gate is BLIND today (verify pickleball/cardio load manually)"
        )
    if cond is not None and cond > cond_forbid_legs:
        # Court/cardio overload. Protect the lower body that absorbs court load;
        # leave upper-body lifting available.
        if "legs" not in g.forbid_muscle_groups:
            g.forbid_muscle_groups.append("legs")
        reasons.append(
            f"Conditioning ACWR {cond} > {cond_forbid_legs} — court/cardio overload; hold "
            "pickleball + hard cardio, legs off today (upper-body lifting OK)"
        )
    elif cond is not None and cond > 1.3:
        reasons.append(f"Conditioning ACWR {cond} > 1.3 — ease off added pickleball/cardio volume")

    # Yellow tier softens the cap.
    if readiness.tier == "yellow" and g.max_intensity == "high":
        g.max_intensity = "moderate"
        reasons.append("Readiness yellow — cap intensity MODERATE")
    if readiness.tier == "red" and g.max_intensity in ("high", "moderate"):
        g.max_intensity = "low"
        reasons.append("Readiness red — cap intensity LOW")

    # Muscle-group recovery. Base: compound legs ≥3d (72h); push/pull ≥2d (48h)
    # — calibrated to a near-failure session. A submaximal session (avg RPE
    # ≤ 6.5, i.e. 3+ RIR) recovers ~24h faster, and a flat calendar gate after
    # easy sessions caps frequency below what the over-40 hypertrophy evidence
    # prescribes (maintain or increase frequency, not reduce it).
    for grp in ("legs", "push", "pull"):
        rest = getattr(load, f"days_since_{grp}")
        last_rpe = getattr(load, f"last_rpe_{grp}")
        if grp == "legs":
            # Frequency is the over-40 hypertrophy lever (vault: raise it, don't
            # cut it). Default legs to 48h; only a genuine near-failure session
            # (avg RPE ≥ 9) earns the full 72h. Per-muscle soreness (below) does
            # the fine-grained gating a flat calendar rule can't — a flat 72h gate
            # after moderate leg days was capping legs at ~2×/wk.
            threshold = 3 if (last_rpe is not None and last_rpe >= 9.0) else 2
        else:
            threshold = 2
            if last_rpe is not None and last_rpe <= 6.5:
                threshold -= 1
        if rest is not None and rest < threshold:
            if grp not in g.forbid_muscle_groups:
                g.forbid_muscle_groups.append(grp)
            rpe_note = f" (last session avg RPE {last_rpe:.1f})" if last_rpe else ""
            reasons.append(f"{grp.title()} {rest}d ago — needs ≥{threshold}d rest{rpe_note}")

    # Same-day pickleball forbids leg lifting; from the next day on it does
    # not — court time is conditioning stimulus, not heavy eccentric load, and
    # the conditioning-ACWR gate above already protects against court overload.
    if load.days_since_pickleball == 0 and "legs" not in g.forbid_muscle_groups:
        g.forbid_muscle_groups.append("legs")
        reasons.append("Pickleball today — legs off until tomorrow")

    # Per-muscle soreness from body-diagram check-in.
    # Severity 3 (acute) on any muscle in a group → forbid that group.
    # Severity 2 (moderate) on >=2 muscles in a group → cap intensity moderate.
    if chk.muscle_soreness:
        sore_by_grp: dict[str, list[tuple[str, int]]] = {"push": [], "pull": [], "legs": []}
        for muscle, sev in chk.muscle_soreness.items():
            grp = MUSCLE_TO_GROUP.get(muscle)
            if grp and grp in sore_by_grp:
                sore_by_grp[grp].append((muscle, int(sev)))
        for grp, items in sore_by_grp.items():
            if grp in g.forbid_muscle_groups:
                continue
            acute = [m for m, s in items if s >= 3]
            moderate = [m for m, s in items if s == 2]
            # Soreness/DOMS is the weakest recovery signal (Damas 2016) — it
            # dissociates from actual readiness — so it no longer hard-forbids a
            # group on its own (panel review M11). Acute soreness forbids ONLY
            # when an objective channel corroborates (readiness yellow/red or
            # HRV ≥1σ below baseline); otherwise it just caps intensity.
            objective_under_recovery = readiness.tier in ("yellow", "red") or (
                rec.hrv_sigma is not None and rec.hrv_sigma < -1.0
            )
            if acute and objective_under_recovery:
                g.forbid_muscle_groups.append(grp)
                reasons.append(
                    f"{grp.title()} acute soreness ({', '.join(acute)}) + objective "
                    "under-recovery — rest group"
                )
            elif acute and g.max_intensity == "high":
                g.max_intensity = "moderate"
                reasons.append(
                    f"{grp.title()} acute soreness ({', '.join(acute)}), subjective only — "
                    "cap MODERATE, not forbidden"
                )
            elif len(moderate) >= 2 and g.max_intensity == "high":
                g.max_intensity = "moderate"
                reasons.append(
                    f"{grp.title()} moderate soreness in {len(moderate)} muscles — cap MODERATE"
                )

    # Deload trigger: persistent regression on a primary lift.
    # Cooldown guard: the e1RM regression metric is computed from logged loads,
    # and deload sessions log lighter loads *by design*. Re-triggering a deload
    # off a metric that the previous deload depressed creates a self-perpetuating
    # loop. If a deload was already prescribed within the cooldown window, record
    # the regression but suppress the trigger so the block can re-accumulate.
    if e1rm_regression_pct is not None and e1rm_regression_pct < -3.0:
        g.e1rm_regression_4wk_pct = e1rm_regression_pct
        lift = e1rm_lift or "primary lift"
        if deload_cooldown:
            reasons.append(
                f"e1RM regression {e1rm_regression_pct:.1f}% on {lift} noted, but a "
                f"deload fired within {DELOAD_COOLDOWN_DAYS}d — trigger suppressed to "
                "allow re-accumulation"
            )
        else:
            g.deload_required = True
            g.deload_reason = f"e1RM regression {e1rm_regression_pct:.1f}% on {lift}"
            reasons.append(g.deload_reason)

    # Travel — keep it moderate at most.
    if chk.travel_flag and g.max_intensity == "high":
        g.max_intensity = "moderate"
        reasons.append("Travel day — cap intensity MODERATE")

    # β-blocker dosing — shift HR zones, scale kcal.
    if chk.propranolol_taken:
        g.hr_zone_shift_bpm = PROPRANOLOL_HR_SHIFT_BPM
        g.kcal_multiplier = PROPRANOLOL_KCAL_MULT
        reasons.append(
            f"Propranolol taken — HR zones −{PROPRANOLOL_HR_SHIFT_BPM} bpm, "
            f"kcal ×{PROPRANOLOL_KCAL_MULT}"
        )

    g.reasons = reasons
    return g


# Free-weight compound patterns that make a meaningful "primary strength lift".
# e1RM on these tracks real strength; machine/cable/isolation work does not.
_STRENGTH_PATTERNS = (
    "bench press",
    "squat",
    "deadlift",
    "overhead press",
    "military press",
    "bent over row",
    "pendlay row",
    "meadows row",
    "t bar row",
    "hip thrust",
    "good morning",
    "lunge",
    "split squat",
    "chin up",
    "pull up",
    "push press",
)
# Equipment/markers that disqualify a lift as a strength-tracking primary:
# machines and cables fix the path (load ≠ effort), "goblet" caps load by grip.
_NOT_STRENGTH = (
    "machine",
    "smith",
    "cable",
    "hammerstrength",
    "iso-lateral",
    "assisted",
    "band",
    "suspension",
    "pec deck",
    "goblet",
)


def _is_strength_lift(name: str) -> bool:
    """True for free-weight compound lifts whose e1RM tracks real strength."""
    e = name.lower()
    if any(bad in e for bad in _NOT_STRENGTH):
        return False
    return any(pat in e for pat in _STRENGTH_PATTERNS)


def _e1rm_regression(conn, today: date) -> tuple[float, str] | None:
    """Detect a regression in peak e1RM on a real primary strength lift.

    Returns (pct, lift_name) if peak strength is trending down; None if
    insufficient data. e1RM uses Epley: weight × (1 + reps/30). Effort-aware:

    - The "primary lift" must be a free-weight compound (machines/cables fix the
      path so load ≠ effort, and they're what gets deloaded — using them creates
      a self-referential loop).
    - Sets logged on deload-prescribed days are excluded (they're light by
      design and would manufacture a phantom regression).
    - Only working sets count (RPE ≥ 7, or RPE absent — never light back-offs).
    - Compares PEAK e1RM recent-half vs prior-half, not averages: a real
      regression means even your best recent effort fell below your best prior
      effort, which a few light sessions can't fake.
    """
    since = (today - timedelta(days=56)).isoformat()
    candidates = conn.execute(
        """
        SELECT ws.exercise, COUNT(*) AS n
        FROM workout_sets_dedup ws
        WHERE ws.is_warmup = FALSE AND ws.weight_kg IS NOT NULL
          AND day_d >= $s
        GROUP BY ws.exercise
        ORDER BY n DESC
        """,
        {"s": since},
    ).fetchall()
    primary_ex = next(
        (ex for ex, n in candidates if n >= 6 and _is_strength_lift(ex)),
        None,
    )
    if primary_ex is None:
        return None
    rows = conn.execute(
        """
        SELECT day_d AS day, MAX(ws.weight_kg * (1 + ws.reps / 30.0)) AS e1rm
        FROM workout_sets_dedup ws
        WHERE ws.is_warmup = FALSE AND ws.weight_kg IS NOT NULL
          AND ws.exercise = $ex AND day_d >= $s
          AND (ws.rpe IS NULL OR ws.rpe >= 7)
          AND day_d NOT IN (
              SELECT date FROM workout_plans
              WHERE json_extract_string(plan_json, '$.deload_prescribed') = 'true'
          )
        GROUP BY day_d ORDER BY day_d
        """,
        {"ex": primary_ex, "s": since},
    ).fetchall()
    if len(rows) < 4:
        return None
    half = len(rows) // 2
    prior = [float(r[1]) for r in rows[:half] if r[1]]
    recent = [float(r[1]) for r in rows[half:] if r[1]]
    if len(prior) < 2 or len(recent) < 2:
        return None
    p_peak = max(prior)
    r_peak = max(recent)
    if p_peak <= 0:
        return None
    return round((r_peak - p_peak) / p_peak * 100.0, 2), primary_ex


def _deload_in_cooldown(conn, today: date, window: int = DELOAD_COOLDOWN_DAYS) -> bool:
    """True if a deload was already prescribed within the cooldown window.

    Looks at prescribed plans (not logged sets) so the signal is the *intent* to
    deload, independent of what was actually performed. Used to suppress the
    e1RM-regression deload trigger and break the self-perpetuating deload loop.
    """
    row = conn.execute(
        """
        SELECT COUNT(*) FROM workout_plans
        WHERE date >= $s AND date < $today
          AND json_extract_string(plan_json, '$.deload_prescribed') = 'true'
        """,
        {"s": (today - timedelta(days=window)).isoformat(), "today": today.isoformat()},
    ).fetchone()
    return bool(row and row[0])


def _freshness(
    conn, today: date, rec: RecoveryMetrics, sleep: SleepMetrics, load: TrainingLoadMetrics
) -> DataFreshness:
    f = DataFreshness()
    if rec.score_date:
        f.whoop_age_days = (today - date.fromisoformat(rec.score_date)).days
    sleep_last = conn.execute("SELECT MAX(night_date) FROM sleep").fetchone()
    if sleep_last and sleep_last[0]:
        f.sleep_age_days = (today - sleep_last[0]).days
    if load.last_session_date:
        f.hevy_age_days = (today - date.fromisoformat(load.last_session_date)).days
    cardio_last = conn.execute("SELECT MAX(date) FROM cardio_sessions").fetchone()
    if cardio_last and cardio_last[0]:
        f.cardio_age_days = (today - cardio_last[0]).days

    f.whoop_stale = _whoop_stale(rec, today)

    if f.whoop_age_days is not None and f.whoop_age_days > 2:
        f.gaps.append(f"WHOOP {f.whoop_age_days}d stale — reduce reliance on recovery score")
    if f.sleep_age_days is not None and f.sleep_age_days > 2:
        f.gaps.append(f"Sleep {f.sleep_age_days}d stale")
    if f.hevy_age_days is not None and f.hevy_age_days > 2:
        f.gaps.append(
            f"Hevy {f.hevy_age_days}d stale — resistance ACWR/e1RM trends running blind"
        )
    if f.cardio_age_days is not None and f.cardio_age_days > 2:
        f.gaps.append(f"Cardio {f.cardio_age_days}d stale — conditioning load may be incomplete")
    return f


# ── Public entry point ───────────────────────────────────────────────────────


def _body_composition(conn, today: date) -> BodyComposition:
    """Leanness trend from passing front-view progress photos.

    Uses a rolling median of recent shots for the current value and the ISAK 2%
    noise floor to gate the 28-day trend (METHODOLOGY.md §2). Returns an empty
    block when there are no usable photos.
    """
    rows = conn.execute(
        """
        SELECT p.photo_date,
               max(CASE WHEN m.metric = 'waist_to_shoulder' THEN m.value_norm END),
               max(CASE WHEN m.metric = 'waist_to_hip' THEN m.value_norm END)
        FROM progress_photos p
        JOIN photo_measurements m ON m.photo_id = p.id
        WHERE p.angle = 'front' AND p.quality_pass
        GROUP BY p.photo_date
        ORDER BY p.photo_date
        """
    ).fetchall()
    series = [
        (r[0], float(r[1]), float(r[2])) for r in rows if r[1] is not None and r[2] is not None
    ]
    if not series:
        return BodyComposition()

    dates = [d for d, _, _ in series]
    w2s = [s for _, s, _ in series]
    w2h = [h for _, _, h in series]
    latest = dates[-1]

    cur_w2s = round(_st.median(w2s[-3:]), 4)
    cur_w2h = round(_st.median(w2h[-3:]), 4)

    # Trend reference: photos at least 14 days before the latest, so the
    # comparison spans real time rather than the same session.
    ref_vals = [s for d, s in zip(dates, w2s, strict=True) if (latest - d).days >= 14]
    trend_pct: float | None = None
    direction: str | None = None
    if ref_vals:
        ref = _st.median(ref_vals[-3:])
        if ref:
            trend_pct = round((cur_w2s - ref) / ref * 100, 2)
            # ISAK 2% noise floor — below it, no real change.
            direction = (
                "stable" if abs(trend_pct) < 2.0 else ("leaner" if trend_pct < 0 else "softer")
            )

    return BodyComposition(
        as_of=latest.isoformat(),
        n_photos=len(series),
        waist_to_shoulder=cur_w2s,
        waist_to_hip=cur_w2h,
        trend_28d_pct=trend_pct,
        trend_direction=direction,
    )


def _body_comp_note(bc: BodyComposition, weight_trend_4wk: float | None) -> str | None:
    """Factual cross-reference of leanness trend against weight (no advice).

    Recomp-aware so it agrees with the photo-endpoint corroboration logic
    (panel review M9): waist-leaner WHILE weight rises is a signal CONFLICT, not
    "recomp on track" — the same (Δwaist, Δweight) must not get opposite verdicts.
    """
    if not bc.trend_direction or weight_trend_4wk is None:
        return None
    wt = weight_trend_4wk
    if bc.trend_direction == "leaner":
        if wt > 1.0:
            return (
                "waist trending leaner but weight rising — signals disagree; "
                "don't read as fat loss without more data"
            )
        if wt < -1.0:
            return "waist and weight both down — leaning out; verify strength/size are holding"
        return "waist trending leaner while weight held — recomp on track (size kept, fat down)"
    if bc.trend_direction == "softer" and wt > 0:
        return "waist and weight both up — drifting toward fat gain"
    if bc.trend_direction == "stable":
        return f"waist stable (within 2% noise), weight trend {wt:+.1f}%"
    return f"waist {bc.trend_direction}, weight trend {wt:+.1f}%"


_PHYSIQUE_BIAS_MAX = 0.15  # bounded ±15% emphasis nudge — physique is slow-moving


def physique_volume_bias(conn, lookback_days: int = 120) -> dict[str, float] | None:
    """Per-muscle volume-emphasis nudges from physique geometry + critique trend.

    Produces a conservative, bounded ``{muscle: factor}`` map (factor in
    [1-_PHYSIQUE_BIAS_MAX, 1+_PHYSIQUE_BIAS_MAX], 1.0 = no change) for the
    autoregulation emphasis path. Two trended (NOT latest-only) signals combine:

    * **Waist:shoulder trend** (BodyComposition): a *softening* taper (waist
      rising relative to shoulders) nudges UP the muscles that drive the
      V-taper — side_delts, lats, glutes — and the trunk (abs). A *leaning*
      taper relaxes those nudges toward neutral.
    * **Physique-critique verdict trend**: the *majority* verdict across recent
      ``physique_critiques`` rows (leaner / stable / softer). Only the
      structured ``verdict`` column is used — the free-text bodies are NOT
      parsed, because reliable per-muscle extraction from prose would need an
      LLM and the backend never calls one (faking it is worse than skipping).

    Returns None when neither signal is available. Muscles absent from the map
    are implicitly 1.0.

    Args:
        conn: DuckDB connection.
        lookback_days: Window for the critique-verdict trend.

    Returns:
        ``{muscle: factor}`` or None.
    """
    today = date.today()
    bc = _body_composition(conn, today)

    # Critique verdict trend — majority over the window (trended, not latest).
    verdict_trend: str | None = None
    try:
        vrows = conn.execute(
            """
            SELECT verdict FROM physique_critiques
            WHERE created_at >= $s AND verdict IS NOT NULL
            ORDER BY created_at
            """,
            {"s": (today - timedelta(days=lookback_days)).isoformat()},
        ).fetchall()
        verdicts = [str(v[0]) for v in vrows if v[0]]
        if verdicts:
            counts: dict[str, int] = {}
            for v in verdicts:
                counts[v] = counts.get(v, 0) + 1
            verdict_trend = max(counts, key=lambda k: counts[k])
    except Exception as exc:
        log.warning("physique_critiques trend unavailable: %s", exc)

    if bc.trend_direction is None and verdict_trend is None:
        return None

    # Combine the two directional signals into a single softening "pressure" in
    # [-1, 1]: +1 = clearly softening (bias toward taper muscles), -1 = leaning.
    pressure = 0.0
    n = 0
    if bc.trend_direction is not None:
        pressure += {"softer": 1.0, "leaner": -1.0}.get(bc.trend_direction, 0.0)
        n += 1
    if verdict_trend is not None:
        pressure += {"softer": 1.0, "leaner": -1.0}.get(verdict_trend, 0.0)
        n += 1
    if n:
        pressure /= n
    if pressure <= 0:
        # Leaning or stable → no positive emphasis nudge; keep it neutral.
        return None

    nudge = round(1.0 + _PHYSIQUE_BIAS_MAX * pressure, 3)
    # Taper-driving muscles get the emphasis when the silhouette is softening.
    return {
        "side_delts": nudge,
        "lats": nudge,
        "glutes": nudge,
        "abs": nudge,
    }


def compute_daily_state(conn, planning_date: date | None = None) -> dict[str, Any]:
    """Return the canonical `DailyState` for today as a JSON-serializable dict.

    Pass `planning_date` to compute gates/muscle-rest relative to a future date
    (e.g. tomorrow when a workout was already completed today). Recovery, sleep,
    and check-in are always anchored to real-world today.
    """
    today = date.today()
    effective = planning_date or today

    rec = _recovery(conn, today)
    sleep = _sleep(conn, today)
    load = _training_load(conn, effective)
    chk = _checkin(conn, today)

    # Reweight readiness away from HR-based signals on propranolol-dosing days.
    # Keyed off the day's check-in flag — the same authoritative signal the gate
    # uses (see _gates). Previously this also required propranolol to appear in
    # the active-medications list, so the reweight and the gate could diverge if
    # the PRN prescription wasn't currently listed.
    beta_blocker = bool(chk.propranolol_taken)

    readiness = _readiness_snapshot(rec, sleep, chk, beta_blocker=beta_blocker)
    e1rm = _e1rm_regression(conn, today)
    e1rm_pct, e1rm_lift = e1rm if e1rm else (None, None)
    deload_cooldown = _deload_in_cooldown(conn, today)
    gates = _gates(
        rec, sleep, load, chk, readiness, e1rm_pct, deload_cooldown, e1rm_lift, conn=conn
    )
    recovery_missing = (
        rec.score_date is None and rec.score is None and rec.hrv_ms is None and rec.rhr is None
    )
    if recovery_missing and gates.max_intensity == "high":
        gates.max_intensity = "moderate"
        gates.reasons.insert(
            0,
            "Recovery data unavailable — cap intensity MODERATE until recovery is verified manually",
        )
    from shc.training.autoregulation import weekly_deload_status

    weekly_deload = weekly_deload_status(conn)
    if weekly_deload.get("recommended"):
        gates.deload_required = True
        gates.deload_reason = str(weekly_deload.get("reason") or "weekly fatigue deload")
        if gates.deload_reason not in gates.reasons:
            gates.reasons.append(gates.deload_reason)
    freshness = _freshness(conn, today, rec, sleep, load)

    body_comp = _body_composition(conn, today)
    body_comp.note = _body_comp_note(body_comp, chk.body_weight_trend_4wk)

    state = DailyState(
        as_of=today.isoformat(),
        recovery=rec,
        sleep=sleep,
        training_load=load,
        checkin=chk,
        readiness=readiness,
        gates=gates,
        freshness=freshness,
        body_composition=body_comp,
    )
    return asdict(state)
