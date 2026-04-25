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
  safety/progression rules (red HRV → cap intensity, ACWR > 1.5 → rest, legs
  in last 48h → reject leg day, propranolol day → shift HR zones, etc.).
"""

import json
import logging
import statistics as _st
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────

BETA_BLOCKER_NAMES = (
    "propranolol", "metoprolol", "atenolol", "bisoprolol", "carvedilol", "nebivolol",
)

# Propranolol: HR suppressed ~15-25 bpm, kcal under-counted ~20-30%.
# Conservative: shift HR zones -20 bpm and multiply HR-derived kcal by 1.25
# only when Rob marks `propranolol_taken=True` for the day.
PROPRANOLOL_HR_SHIFT_BPM = 20
PROPRANOLOL_KCAL_MULT = 1.25

# Readiness weights — collapsed from frontend lib/readiness.ts so they live in
# exactly one place.
DEFAULT_WEIGHTS = {"hrv": 0.40, "sleep": 0.30, "rhr": 0.20, "subj": 0.10}
BETA_BLOCKER_WEIGHTS = {"hrv": 0.20, "sleep": 0.40, "rhr": 0.25, "subj": 0.15}

Tier = Literal["green", "yellow", "red"]
Intensity = Literal["high", "moderate", "low", "rest"]


# ── DTOs (plain dicts via asdict — DuckDB / FastAPI friendly) ────────────────

@dataclass
class RecoveryMetrics:
    score: float | None = None              # WHOOP recovery 0-100
    score_date: str | None = None
    hrv_ms: float | None = None
    hrv_baseline_28d: float | None = None
    hrv_sd_28d: float | None = None
    hrv_sigma: float | None = None          # σ deviation from 28d baseline
    rhr: int | None = None
    rhr_7d_avg: float | None = None
    rhr_baseline_28d: float | None = None
    rhr_elevated_pct: float | None = None
    skin_temp: float | None = None
    skin_temp_baseline_28d: float | None = None
    skin_temp_delta: float | None = None


@dataclass
class SleepMetrics:
    last_hours: float | None = None
    avg_7d: float | None = None
    consistency_stdev_7d: float | None = None
    debt_7d_h: float | None = None
    deep_pct_last: float | None = None       # OSA-aware: deep sleep matters more than duration
    deep_min_last: float | None = None
    rem_min_last: float | None = None
    spo2_avg_last: float | None = None       # < 95% is a clinical flag for sleep-disordered breathing
    score: float | None = None               # 0-100 composite (duration + deep% + spo2)


@dataclass
class TrainingLoadMetrics:
    acute_load_7d: float | None = None       # composite_load mean over 7d
    chronic_load_28d: float | None = None    # composite_load mean over 28d
    acwr: float | None = None                # acute / chronic, true Gabbett
    last_session_date: str | None = None
    days_since_last: int | None = None
    days_since_legs: int = 99
    days_since_push: int = 99
    days_since_pull: int = 99
    push_pull_ratio_28d: float | None = None
    push_sets_28d: int = 0
    pull_sets_28d: int = 0
    legs_sets_28d: int = 0
    cardio_min_28d: int = 0
    cardio_z2_min_7d: int = 0


@dataclass
class CheckinMetrics:
    date: str | None = None
    propranolol_taken: bool | None = None
    body_weight_kg: float | None = None
    body_weight_trend_4wk: float | None = None  # % change vs 28d ago
    soreness_overall: int | None = None
    sleep_quality: int | None = None             # 1-10
    energy: int | None = None                    # 1-10
    stress: int | None = None                    # 1-10
    motivation: int | None = None                # 1-10
    illness_flag: bool = False
    travel_flag: bool = False


@dataclass
class ReadinessSnapshot:
    score: float | None = None              # 0-100 composite
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
    hr_zone_shift_bpm: int = 0               # subtract from prescribed HR zones (propranolol days)
    kcal_multiplier: float = 1.0             # multiply HR-derived kcal estimates
    e1rm_regression_4wk_pct: float | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class DataFreshness:
    whoop_age_days: int | None = None
    sleep_age_days: int | None = None
    hevy_age_days: int | None = None
    cardio_age_days: int | None = None
    gaps: list[str] = field(default_factory=list)


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


# ── Helpers ──────────────────────────────────────────────────────────────────

_PUSH = ("press", "fly", "dip", "pushup", "push-up", "tricep", "shoulder", "overhead", "chest")
_PULL = ("row", "pull", "curl", "lat", "deadlift", "shrug", "face pull", "rear delt")
_LEGS = ("squat", "leg", "lunge", "hip", "glute", "hamstring", "quad", "calf", "rdl", "step-up")
_CORE = ("plank", "crunch", "ab ", "core", "oblique", "sit-up", "rotation")


def muscle_group(exercise: str) -> str:
    """Classify an exercise into push/pull/legs/core/other.

    Single source of truth — previously duplicated in workout_planner and
    dashboard.
    """
    e = exercise.lower()
    if any(k in e for k in _PUSH):
        return "push"
    if any(k in e for k in _PULL):
        return "pull"
    if any(k in e for k in _LEGS):
        return "legs"
    if any(k in e for k in _CORE):
        return "core"
    return "other"


def _is_beta_blocker(med_names: list[str]) -> bool:
    return any(any(bb in m.lower() for bb in BETA_BLOCKER_NAMES) for m in med_names)


def _hrv_subscore(sigma: float | None) -> float | None:
    if sigma is None:
        return None
    return max(0.0, min(100.0, 50.0 + sigma * 25.0))


def _sleep_subscore(hours: float | None, deep_pct: float | None, spo2: float | None) -> float | None:
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


def _rhr_subscore(today: float | None, baseline: float | None) -> float | None:
    if today is None or not baseline:
        return None
    pct = (today - baseline) / baseline
    return max(0.0, min(100.0, 50.0 - pct * 500.0))


def _subj_subscore(energy: int | None, stress: int | None, soreness: int | None) -> float | None:
    parts: list[float] = []
    if energy is not None:
        parts.append(energy * 10.0)
    if stress is not None:
        parts.append((10 - stress) * 10.0)
    if soreness is not None:
        parts.append((10 - soreness) * 10.0)
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
        "SELECT date, score, hrv, rhr, skin_temp FROM recovery ORDER BY date DESC LIMIT 1"
    ).fetchone()
    hrv_base = conn.execute(
        "SELECT hrv, hrv_28d_avg, hrv_28d_sd FROM v_hrv_baseline_28d ORDER BY date DESC LIMIT 1"
    ).fetchone()
    rhr_rows = conn.execute(
        "SELECT date, rhr FROM recovery WHERE date >= $s AND rhr IS NOT NULL ORDER BY date",
        {"s": (today - timedelta(days=28)).isoformat()},
    ).fetchall()
    skin_baseline = conn.execute(
        "SELECT AVG(skin_temp) FROM recovery WHERE skin_temp IS NOT NULL "
        "AND date >= (current_date - INTERVAL '28 days')"
    ).fetchone()

    m = RecoveryMetrics()
    if rec:
        m.score_date = str(rec[0])
        m.score = float(rec[1]) if rec[1] is not None else None
        m.hrv_ms = float(rec[2]) if rec[2] is not None else None
        m.rhr = int(rec[3]) if rec[3] is not None else None
        m.skin_temp = float(rec[4]) if rec[4] is not None else None
    if hrv_base:
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
    if skin_baseline and skin_baseline[0] is not None:
        m.skin_temp_baseline_28d = round(float(skin_baseline[0]), 2)
        if m.skin_temp is not None:
            m.skin_temp_delta = round(m.skin_temp - m.skin_temp_baseline_28d, 2)
    return m


def _sleep(conn, today: date) -> SleepMetrics:
    rows = conn.execute(
        "SELECT night_date, epoch(ts_out-ts_in)/3600.0 AS hrs, stages_json, spo2_avg "
        "FROM sleep WHERE night_date >= $s AND ts_in IS NOT NULL AND ts_out IS NOT NULL "
        "ORDER BY night_date",
        {"s": (today - timedelta(days=14)).isoformat()},
    ).fetchall()
    m = SleepMetrics()
    if not rows:
        return m
    last = rows[-1]
    m.last_hours = round(float(last[1]), 2) if last[1] is not None else None
    if last[2]:
        try:
            stages = json.loads(last[2]) if isinstance(last[2], str) else last[2]
            deep = float(stages.get("deep_min", 0) or 0)
            rem = float(stages.get("rem_min", 0) or 0)
            light = float(stages.get("light_min", 0) or 0)
            asleep = deep + rem + light
            if asleep > 0:
                m.deep_min_last = round(deep, 1)
                m.rem_min_last = round(rem, 1)
                m.deep_pct_last = round(deep / asleep, 3)
        except (ValueError, AttributeError):
            pass
    m.spo2_avg_last = round(float(last[3]), 1) if last[3] is not None else None
    hours_vals = [float(r[1]) for r in rows if r[1] is not None and 2 < float(r[1]) < 14]
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
        "SELECT date, composite_load FROM v_daily_load WHERE date >= $s ORDER BY date",
        {"s": (today - timedelta(days=28)).isoformat()},
    ).fetchall()
    if load_rows:
        recent = [float(r[1] or 0) for r in load_rows if r[0] >= today - timedelta(days=7)]
        chronic = [float(r[1] or 0) for r in load_rows]
        # Mean over the *window length*, not just non-zero days, so ACWR
        # correctly drops on rest weeks.
        if chronic:
            m.acute_load_7d = round(sum(recent) / 7.0, 2)
            m.chronic_load_28d = round(sum(chronic) / 28.0, 2)
            if m.chronic_load_28d > 0:
                m.acwr = round(m.acute_load_7d / m.chronic_load_28d, 2)

    last_session = conn.execute(
        "SELECT MAX(started_at::DATE) FROM workouts"
    ).fetchone()
    if last_session and last_session[0]:
        m.last_session_date = str(last_session[0])
        m.days_since_last = (today - last_session[0]).days

    # Days since each muscle group (uses workout_sets — strength only).
    set_rows = conn.execute(
        """
        SELECT w.started_at::DATE AS day, ws.exercise
        FROM workout_sets ws
        JOIN workouts w ON w.id = ws.workout_id
        WHERE ws.is_warmup = FALSE AND w.started_at::DATE >= $since
        """,
        {"since": (today - timedelta(days=28)).isoformat()},
    ).fetchall()
    last_by_group: dict[str, date] = {}
    bal: dict[str, int] = {"push": 0, "pull": 0, "legs": 0, "core": 0, "other": 0}
    for day, exercise in set_rows:
        g = muscle_group(exercise or "")
        bal[g] = bal[g] + 1
        if g not in last_by_group or day > last_by_group[g]:
            last_by_group[g] = day
    for g in ("push", "pull", "legs"):
        if g in last_by_group:
            setattr(m, f"days_since_{g}", (today - last_by_group[g]).days)
    m.push_sets_28d = bal["push"]
    m.pull_sets_28d = bal["pull"]
    m.legs_sets_28d = bal["legs"]
    if m.push_sets_28d and m.pull_sets_28d:
        m.push_pull_ratio_28d = round(m.push_sets_28d / m.pull_sets_28d, 2)

    cardio = conn.execute(
        """
        SELECT COALESCE(SUM(duration_min), 0) FROM cardio_sessions
        WHERE date >= (current_date - INTERVAL '28 days')
        """
    ).fetchone()
    if cardio and cardio[0] is not None:
        m.cardio_min_28d = int(cardio[0])

    z2 = conn.execute(
        """
        SELECT COALESCE(SUM(duration_min), 0)
        FROM cardio_sessions
        WHERE date >= (current_date - INTERVAL '7 days')
          AND avg_hr IS NOT NULL
          AND avg_hr BETWEEN 110 AND 145
        """
    ).fetchone()
    if z2 and z2[0] is not None:
        m.cardio_z2_min_7d = int(z2[0])
    return m


def _checkin(conn, today: date) -> CheckinMetrics:
    row = conn.execute(
        """
        SELECT date, propranolol_taken, body_weight_kg, soreness_overall,
               sleep_quality_1_10, energy_1_10, stress_1_10, motivation_1_10,
               illness_flag, travel_flag
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

    # Body-weight trend (4-week %): prefer manual checkin, fall back to
    # measurements table.
    today_kg = m.body_weight_kg
    if today_kg is None:
        latest = conn.execute(
            "SELECT value_num FROM measurements WHERE metric IN ('body_mass', 'weight') "
            "AND value_num IS NOT NULL ORDER BY ts DESC LIMIT 1"
        ).fetchone()
        today_kg = float(latest[0]) if latest and latest[0] else None
    past = conn.execute(
        """
        SELECT value_num FROM measurements
        WHERE metric IN ('body_mass', 'weight') AND value_num IS NOT NULL
          AND ts <= (current_date - INTERVAL '28 days')
        ORDER BY ts DESC LIMIT 1
        """
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
        "rhr": _rhr_subscore(rec.rhr, rec.rhr_baseline_28d),
        "subj": _subj_subscore(chk.energy, chk.stress, chk.soreness_overall),
    }
    present = [(k, v) for k, v in components.items() if v is not None]
    if not present:
        return ReadinessSnapshot(
            score=None, tier=None, weights=weights,
            components=components, beta_blocker_adjusted=beta_blocker,
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


def _gates(
    rec: RecoveryMetrics,
    sleep: SleepMetrics,
    load: TrainingLoadMetrics,
    chk: CheckinMetrics,
    readiness: ReadinessSnapshot,
    e1rm_regression_pct: float | None,
) -> AutoRegGates:
    g = AutoRegGates()
    reasons: list[str] = []

    # Hard rest gates.
    if rec.hrv_sigma is not None and rec.hrv_sigma < -1.5:
        g.max_intensity = "low"
        reasons.append(f"HRV {rec.hrv_sigma:+.2f}σ → red — cap intensity LOW")
    if rec.skin_temp_delta is not None and abs(rec.skin_temp_delta) >= 0.5:
        g.max_intensity = "low"
        reasons.append(f"Skin-temp Δ{rec.skin_temp_delta:+.2f}°C — possible illness, Z2 only")
    if chk.illness_flag:
        g.max_intensity = "rest"
        reasons.append("Illness flag set — rest day")
    if load.acwr is not None and load.acwr > 1.5:
        g.max_intensity = "rest"
        reasons.append(f"ACWR {load.acwr} > 1.5 — overload risk, rest required")
    elif load.acwr is not None and load.acwr > 1.3:
        if g.max_intensity == "high":
            g.max_intensity = "moderate"
        reasons.append(f"ACWR {load.acwr} > 1.3 — reduce volume")

    # Yellow tier softens the cap.
    if readiness.tier == "yellow" and g.max_intensity == "high":
        g.max_intensity = "moderate"
        reasons.append("Readiness yellow — cap intensity MODERATE")
    if readiness.tier == "red" and g.max_intensity in ("high", "moderate"):
        g.max_intensity = "low"
        reasons.append("Readiness red — cap intensity LOW")

    # Muscle-group recovery.
    for grp in ("legs", "push", "pull"):
        rest = getattr(load, f"days_since_{grp}")
        # Compound legs need 72h, others 48h.
        threshold = 2 if grp == "legs" else 1
        if rest is not None and rest < threshold:
            g.forbid_muscle_groups.append(grp)
            reasons.append(f"{grp.title()} {rest}d ago — needs ≥{threshold + 1}d rest")

    # Deload trigger: persistent regression on a primary lift.
    if e1rm_regression_pct is not None and e1rm_regression_pct < -3.0:
        g.deload_required = True
        g.deload_reason = f"e1RM regression {e1rm_regression_pct:.1f}% on primary lift"
        reasons.append(g.deload_reason)
        g.e1rm_regression_4wk_pct = e1rm_regression_pct

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


def _e1rm_regression(conn, today: date) -> float | None:
    """Detect 4-week regression on Rob's most-frequently-trained primary lift.

    Returns negative pct if e1RM is trending down; None if insufficient data.
    e1RM uses Epley formula: weight × (1 + reps/30).
    """
    primary = conn.execute(
        """
        SELECT ws.exercise, COUNT(*) AS n
        FROM workout_sets ws
        JOIN workouts w ON w.id = ws.workout_id
        WHERE ws.is_warmup = FALSE AND ws.weight_kg IS NOT NULL
          AND w.started_at::DATE >= $s
        GROUP BY ws.exercise
        ORDER BY n DESC LIMIT 1
        """,
        {"s": (today - timedelta(days=56)).isoformat()},
    ).fetchone()
    if not primary:
        return None
    rows = conn.execute(
        """
        SELECT w.started_at::DATE AS day, MAX(ws.weight_kg * (1 + ws.reps / 30.0)) AS e1rm
        FROM workout_sets ws
        JOIN workouts w ON w.id = ws.workout_id
        WHERE ws.is_warmup = FALSE AND ws.weight_kg IS NOT NULL
          AND ws.exercise = $ex AND w.started_at::DATE >= $s
        GROUP BY day ORDER BY day
        """,
        {"ex": primary[0], "s": (today - timedelta(days=56)).isoformat()},
    ).fetchall()
    if len(rows) < 4:
        return None
    half = len(rows) // 2
    prior = [float(r[1]) for r in rows[:half] if r[1]]
    recent = [float(r[1]) for r in rows[half:] if r[1]]
    if not prior or not recent:
        return None
    p_avg = sum(prior) / len(prior)
    r_avg = sum(recent) / len(recent)
    if p_avg <= 0:
        return None
    return round((r_avg - p_avg) / p_avg * 100.0, 2)


def _freshness(conn, today: date, rec: RecoveryMetrics, sleep: SleepMetrics, load: TrainingLoadMetrics) -> DataFreshness:
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

    if f.whoop_age_days is not None and f.whoop_age_days > 2:
        f.gaps.append(f"WHOOP {f.whoop_age_days}d stale — reduce reliance on recovery score")
    if f.sleep_age_days is not None and f.sleep_age_days > 2:
        f.gaps.append(f"Sleep {f.sleep_age_days}d stale")
    return f


# ── Public entry point ───────────────────────────────────────────────────────

def get_active_medications(conn) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM medications WHERE valid_to IS NULL"
    ).fetchall()
    return [r[0] for r in rows if r[0]]


def compute_daily_state(conn) -> dict[str, Any]:
    """Return the canonical `DailyState` for today as a JSON-serializable dict.

    This is the SINGLE source of truth consumed by the frontend, the chat
    advisor's system prompt, the workout planner's context, and the
    auto-regulation gate.
    """
    today = date.today()

    rec = _recovery(conn, today)
    sleep = _sleep(conn, today)
    load = _training_load(conn, today)
    chk = _checkin(conn, today)

    meds = get_active_medications(conn)
    beta_blocker = _is_beta_blocker(meds)

    readiness = _readiness_snapshot(rec, sleep, chk, beta_blocker=beta_blocker)
    e1rm_pct = _e1rm_regression(conn, today)
    gates = _gates(rec, sleep, load, chk, readiness, e1rm_pct)
    freshness = _freshness(conn, today, rec, sleep, load)

    state = DailyState(
        as_of=today.isoformat(),
        recovery=rec,
        sleep=sleep,
        training_load=load,
        checkin=chk,
        readiness=readiness,
        gates=gates,
        freshness=freshness,
    )
    return asdict(state)
