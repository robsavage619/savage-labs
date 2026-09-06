from __future__ import annotations

import json
import logging
import math
import statistics
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from shc.ai.briefing import build_daily_context, store_briefing
from shc.ai.workout_planner import (
    GateViolation,
    _workout_logged_today,
    build_training_context,
    load_latest_plan,
    load_plan,
    plan_execution,
    save_plan,
    validate_plan,
)
from shc.api.deps import require_admin_key
from shc.db.schema import get_read_conn, get_write_conn, write_ctx
from shc.ingest.clinical_profile import subject_dob
from shc.lab import _welch_t as _lab_welch
from shc.metrics import MUSCLE_TO_GROUP, compute_daily_state
from shc.metrics import muscle_group as _mg
from shc.training.loadable import snap_plan_weights

router = APIRouter(tags=["dashboard"])
log = logging.getLogger(__name__)


class WorkoutPlanSubmission(BaseModel):
    plan: dict[str, Any]
    source: str = "claude"
    push_to_hevy: bool = False
    plan_date: str | None = None  # ISO date override; auto-detected from workout history if omitted
    override_reason: str | None = (
        None  # non-empty → train through max_intensity by one tier, logged
    )
    override_muscle_groups: list[str] | None = (
        None  # explicit groups (e.g. ["push","pull"]) to train through their
        # recovery gate; REQUIRES override_reason; hinge/deload/clinical guards stay
    )


class EmphasisSubmission(BaseModel):
    muscle: str
    weight: float = 1.0
    note: str | None = None


class TierSubmission(BaseModel):
    """Set which muscles are growth targets this mesocycle (migration 0078).

    ``grow`` muscles run MEV→MAV progression; ``maintain`` muscles hold at MV
    (~1-2 sets/wk), which the vault records as sufficient to retain hypertrophy
    for ~3 months in trained lifters. The list is exhaustive for the muscles it
    names — anything omitted keeps its current tier.
    """

    grow: list[str] = []
    maintain: list[str] = []


class BriefingSubmission(BaseModel):
    training_call: str  # Push | Train | Maintain | Easy | Rest
    training_rationale: str
    readiness_headline: str
    coaching_note: str
    flags: list[str] = []
    priority_metric: str = "none"


class RetrospectiveSubmission(BaseModel):
    workout_id: str
    summary: str
    progressive_overload_achieved: bool | None = None
    rpe_vs_target: str | None = None
    flags: list[str] = []
    vault_insights: list[str] = []


@router.get("/recovery/today")
async def recovery_today() -> dict:
    conn = get_read_conn()
    try:
        row = conn.execute(
            "SELECT date, score, hrv, rhr, skin_temp FROM recovery ORDER BY date DESC LIMIT 1"
        ).fetchone()
        baseline = conn.execute(
            "SELECT AVG(skin_temp) FROM recovery WHERE skin_temp IS NOT NULL AND date >= (current_date - INTERVAL '28 days')"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {}
    base = float(baseline[0]) if baseline and baseline[0] is not None else None
    return {
        "date": str(row[0]),
        "score": row[1],
        "hrv": row[2],
        "rhr": row[3],
        "skin_temp": round(float(row[4]) * 9 / 5 + 32, 2) if row[4] is not None else None,
        "skin_temp_baseline_28d": round(float(base) * 9 / 5 + 32, 2) if base else None,
        # °F delta (×9/5, no offset for a difference) — matches DailyState and
        # the project's imperial-units invariant.
        "skin_temp_delta": round((float(row[4]) - base) * 9 / 5, 2)
        if (row[4] is not None and base)
        else None,
    }


@router.get("/recovery/trend")
async def recovery_trend(days: int = Query(14, gt=0, le=365)) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_read_conn()
    try:
        # One row per date. `recovery` can hold more than one — WHOOP revisions,
        # and 2024-06-22 / 2024-09-17 still do — and every consumer of this
        # endpoint aggregates client-side, so a duplicate date silently
        # double-weights that day in the monthly means, the heatmap and both
        # scatters. Prefer the row with the most complete data, newest id last.
        rows = conn.execute(
            """
            SELECT date, score, hrv, rhr FROM recovery
            WHERE date >= $since
            QUALIFY ROW_NUMBER() OVER (
                PARTITION BY date
                ORDER BY (score IS NULL)::INT + (hrv IS NULL)::INT + (rhr IS NULL)::INT, id DESC
            ) = 1
            ORDER BY date
            """,
            {"since": since},
        ).fetchall()
    finally:
        conn.close()
    return [{"date": str(r[0]), "score": r[1], "hrv": r[2], "rhr": r[3]} for r in rows]


@router.get("/hrv/trend")
async def hrv_trend(days: int = Query(28, gt=0, le=365)) -> list[dict]:
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            WITH base AS (
                SELECT date, hrv, hrv_28d_avg, hrv_28d_sd
                FROM v_hrv_baseline_28d
                ORDER BY date
            )
            SELECT
                date, hrv, hrv_28d_avg, hrv_28d_sd,
                AVG(hrv) OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS hrv_7d_avg,
                STDDEV(hrv) OVER (ORDER BY date ROWS BETWEEN 6 PRECEDING AND CURRENT ROW) AS hrv_7d_sd
            FROM base
            ORDER BY date DESC
            LIMIT $days
            """,
            {"days": days},
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "date": str(r[0]),
            "hrv": r[1],
            "avg": r[2],
            "sd": r[3],
            "hrv_7d_avg": round(r[4], 2) if r[4] is not None else None,
            "hrv_7d_sd": round(r[5], 2) if r[5] is not None else None,
        }
        for r in reversed(rows)
    ]


@router.get("/sleep/recent")
async def sleep_recent(days: int = Query(7, gt=0, le=365)) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_read_conn()
    try:
        rows = conn.execute(
            # spo2 lives on `recovery` — Whoop's sleep endpoint omits it, so
            # sleep.spo2_avg is always NULL. See metrics._sleep for the same join.
            "SELECT s.night_date, s.stages_json, r.spo2, s.respiratory_rate, "
            "epoch(s.ts_out - s.ts_in) / 3600.0 AS hours "
            "FROM sleep s LEFT JOIN recovery r ON r.date = s.night_date "
            "WHERE s.night_date >= $since "
            "  AND COALESCE(s.is_nap, FALSE) = FALSE "
            "  AND s.ts_in IS NOT NULL AND s.ts_out IS NOT NULL "
            "ORDER BY s.night_date",
            {"since": since},
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "date": str(r[0]),
            "stages": r[1],
            "spo2": r[2],
            "respiratory_rate": r[3],
            "hours": r[4],
        }
        for r in rows
    ]


@router.get("/sleep/trend")
async def sleep_trend(days: int = Query(30, gt=0, le=365)) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_read_conn()
    try:
        rows = conn.execute(
            "SELECT night_date, stages_json, "
            "epoch(ts_out - ts_in) / 3600.0 AS hours "
            "FROM sleep WHERE night_date >= $since ORDER BY night_date",
            {"since": since},
        ).fetchall()
    finally:
        conn.close()
    return [{"date": str(r[0]), "stages": r[1], "hours": r[2]} for r in rows]


# One row per night, naps excluded.
#
# `sleep` holds every session WHOOP records, and `is_nap` does not reliably mark
# the short ones: 2026-08-25 carries a 1.1h afternoon session flagged as a
# night, and the fourteen days to 2026-09-05 held 17 rows across 14 dates. Any
# average taken over raw rows therefore counts naps as nights — which is how
# `/api/stats/summary` came to report 6.07h and 15.96h of sleep debt against
# DailyState's 8.1h and 3.8h. Longest session per date is the night.
_NIGHTS_SQL = """
    SELECT night_date, epoch(ts_out - ts_in) / 3600.0 AS hours
    FROM sleep
    WHERE night_date >= $since
      AND COALESCE(is_nap, FALSE) = FALSE
      AND ts_in IS NOT NULL AND ts_out IS NOT NULL
    QUALIFY ROW_NUMBER() OVER (
        PARTITION BY night_date ORDER BY epoch(ts_out - ts_in) DESC
    ) = 1
    ORDER BY night_date
"""


# ── Airway: nocturnal SpO2 and respiratory rate ─────────────────────────────
#
# Both numbers already exist per night and neither is trended anywhere. Rob has
# diagnosed OSA and is off CPAP, and the vault is explicit about what that means
# for this screen:
#
#   "WHOOP SpO2 floor is the primary OSA screening signal in SHC. A consistently
#    low floor (< 94%) displayed in the sleep panel warrants clinical
#    discussion."  — [[obstructive-sleep-apnea]]
#
#   "Build a 'nocturnal RR' panel showing 28d baseline, current 7d mean, and any
#    sustained excursion > +1 bpm with a colour-coded gate state."
#    — [[nicolo-2020-respiratory-rate-monitoring]]
#
# The RR baseline and delta are already computed in `metrics` and already gate
# the day (+1.0 corroborated caps intensity, +0.5 is a watch note); this endpoint
# does not re-derive them differently, it reports the same window and the same
# median so the chart and the gate can never disagree.

_SPO2_SCREEN_PCT = 94.0  # vault OSA screening floor
_SPO2_NORMAL_PCT = 95.0
_SPO2_GATE_PCT = 92.0  # where the engine actually gates
_RR_WATCH_DELTA = 0.5
_RR_GATE_DELTA = 1.0
_RR_CLINICAL_BPM = 18.0  # Nicolo: multiple nights above this is a "see a doctor" trigger
_RR_PLAUSIBLE = (8.0, 30.0)  # same bounds metrics uses for the baseline


def _rolling_mean(values: list[float | None], window: int) -> list[float | None]:
    out: list[float | None] = []
    for i in range(len(values)):
        seen = [v for v in values[max(0, i - window + 1) : i + 1] if v is not None]
        out.append(round(sum(seen) / len(seen), 2) if seen else None)
    return out


@router.get("/sleep/airway")
async def sleep_airway(days: int = Query(180, gt=0, le=1000)) -> dict:
    """Nightly SpO2 and respiratory rate against their screening thresholds.

    SpO2 is read from `recovery`, not `sleep` — WHOOP's sleep endpoint omits it,
    so `sleep.spo2_avg` is always NULL (same join as `/sleep/recent`).
    """
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            WITH one_sleep AS (
                -- `is_nap` is not reliable: 2026-08-25 carries a 1.09h afternoon
                -- session flagged as a night. The longest session per date is the
                -- actual night, and picking one also stops the join to `recovery`
                -- from multiplying nights that have more than one row.
                SELECT night_date, respiratory_rate
                FROM sleep
                WHERE night_date >= $since AND COALESCE(is_nap, FALSE) = FALSE
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY night_date
                    ORDER BY COALESCE(epoch(ts_out - ts_in), 0) DESC
                ) = 1
            ),
            one_recovery AS (
                SELECT date, spo2
                FROM recovery
                WHERE date >= $since
                QUALIFY ROW_NUMBER() OVER (
                    PARTITION BY date ORDER BY spo2 IS NULL, id
                ) = 1
            )
            SELECT s.night_date,
                   r.spo2,
                   CASE WHEN s.respiratory_rate BETWEEN $lo AND $hi
                        THEN s.respiratory_rate END AS rr
            FROM one_sleep s
            LEFT JOIN one_recovery r ON r.date = s.night_date
            ORDER BY s.night_date
            """,
            {"since": since, "lo": _RR_PLAUSIBLE[0], "hi": _RR_PLAUSIBLE[1]},
        ).fetchall()
    finally:
        conn.close()

    spo2_vals = [float(r[1]) if r[1] is not None else None for r in rows]
    rr_vals = [float(r[2]) if r[2] is not None else None for r in rows]
    spo2_roll = _rolling_mean(spo2_vals, 7)
    rr_roll = _rolling_mean(rr_vals, 7)

    nights = [
        {
            "date": str(r[0]),
            "spo2": spo2_vals[i],
            "spo2_7d": spo2_roll[i],
            "resp": rr_vals[i],
            "resp_7d": rr_roll[i],
        }
        for i, r in enumerate(rows)
    ]

    seen_spo2 = [v for v in spo2_vals if v is not None]
    seen_rr = [v for v in rr_vals if v is not None]
    # Median over the trailing 28 nights, matching metrics._recovery exactly —
    # a mean here would put the chart's baseline slightly off the gate's.
    rr_recent = [v for v in seen_rr[-28:]]
    rr_baseline = round(statistics.median(rr_recent), 2) if rr_recent else None
    rr_last7 = [v for v in seen_rr[-7:]]

    return {
        "window_days": days,
        "nights": nights,
        "spo2": {
            "n": len(seen_spo2),
            "mean": round(sum(seen_spo2) / len(seen_spo2), 2) if seen_spo2 else None,
            "min": round(min(seen_spo2), 1) if seen_spo2 else None,
            "last": round(seen_spo2[-1], 1) if seen_spo2 else None,
            "below_95": sum(1 for v in seen_spo2 if v < _SPO2_NORMAL_PCT),
            "below_94": sum(1 for v in seen_spo2 if v < _SPO2_SCREEN_PCT),
            "below_92": sum(1 for v in seen_spo2 if v < _SPO2_GATE_PCT),
            "normal_pct": _SPO2_NORMAL_PCT,
            "screen_pct": _SPO2_SCREEN_PCT,
            "gate_pct": _SPO2_GATE_PCT,
        },
        "resp": {
            "n": len(seen_rr),
            "baseline_28d": rr_baseline,
            "last": round(seen_rr[-1], 2) if seen_rr else None,
            "last_7d_mean": round(sum(rr_last7) / len(rr_last7), 2) if rr_last7 else None,
            "delta": (
                round(seen_rr[-1] - rr_baseline, 2) if seen_rr and rr_baseline is not None else None
            ),
            "nights_above_clinical": sum(1 for v in seen_rr[-30:] if v > _RR_CLINICAL_BPM),
            "watch_delta": _RR_WATCH_DELTA,
            "gate_delta": _RR_GATE_DELTA,
            "clinical_bpm": _RR_CLINICAL_BPM,
        },
    }


@router.get("/readiness/today")
async def readiness_today() -> dict:
    """Today's readiness — thin reader of the canonical DailyState.

    Kept for backwards compat. Prefer `/api/state/today` for new clients.
    """
    conn = get_read_conn()
    try:
        state = compute_daily_state(conn)
    finally:
        conn.close()
    return {
        "date": state["as_of"],
        "recovery_score": state["recovery"]["score"],
        "hrv": state["recovery"]["hrv_ms"],
        "rhr": state["recovery"]["rhr"],
        "sleep_hours": state["sleep"]["last_hours"],
        "energy": state["checkin"]["energy"],
        "stress": state["checkin"]["stress"],
        "readiness_score": state["readiness"]["score"],
        "readiness_tier": state["readiness"]["tier"],
        "beta_blocker_adjusted": state["readiness"]["beta_blocker_adjusted"],
    }


@router.get("/state/today")
async def state_today() -> dict:
    """Single source of truth — today's complete DailyState.

    Replaces ad-hoc aggregation in dashboard / briefing / planner with one
    canonical view. Includes recovery, sleep, training-load (true Gabbett
    ACWR), check-in inputs, β-blocker-aware readiness composite, deterministic
    auto-regulation gates, and data freshness.
    """
    conn = get_read_conn()
    try:
        return compute_daily_state(conn)
    finally:
        conn.close()


# ── Daily check-in (β-blocker, soreness, body weight, illness/travel flags) ──


class CheckinSubmission(BaseModel):
    date: str | None = None  # ISO date override for backfilling past days
    propranolol_taken: bool | None = None
    body_weight_kg: float | None = None
    soreness_overall: int | None = None  # 1-10
    sleep_quality_1_10: int | None = None
    energy_1_10: int | None = None
    stress_1_10: int | None = None
    motivation_1_10: int | None = None
    illness_flag: bool | None = None
    travel_flag: bool | None = None
    notes: str | None = None
    muscle_soreness: dict[str, int] | None = None  # {muscle_key: severity 1-3}
    protein_grams: int | None = None  # total protein consumed today (grams)
    # Override the weight plausibility check. A genuine 25%+ swing is possible
    # over a long enough gap, so the gate must be answerable rather than final.
    force_weight: bool = False

    @staticmethod
    def _validate_1_10(v: int | None, name: str) -> int | None:
        if v is None:
            return None
        if not 1 <= v <= 10:
            raise ValueError(f"{name} must be 1-10")
        return v


# ── Check-in weight plausibility ────────────────────────────────────────────
#
# Every 1-10 field on the check-in is bounds-checked; body weight was not, and
# on 2026-05-19 and 2026-05-21 a leading-digit slip put 138 lb into a run of
# 233-239 lb. The frontend commits this field on blur, so a typo is written the
# moment focus leaves the box — there is no confirm step to catch it. Two bad
# rows then dragged the all-time weight chart's axis down by a hundred pounds
# and gouged the rolling mean.
#
# An absolute band alone would not have caught it: 62.6 kg is a perfectly valid
# human weight. What makes it impossible is the *neighbours*, so the real test
# is deviation from the most recent prior weighing.

_WEIGHT_ABS_MIN_KG = 30.0
_WEIGHT_ABS_MAX_KG = 300.0
_WEIGHT_MAX_DEVIATION = 0.25
_WEIGHT_PRIOR_WINDOW_DAYS = 365


def check_weight_plausible(kg: float, prior_kg: float | None) -> str | None:
    """Return a rejection message for an implausible weight, or None to accept.

    `prior_kg` is the most recent weighing before this one, from any source. It
    is None when there is no usable history, in which case only the absolute
    band applies — a first entry has nothing to be inconsistent with.
    """
    if not _WEIGHT_ABS_MIN_KG <= kg <= _WEIGHT_ABS_MAX_KG:
        return (
            f"body_weight_kg {kg:.1f} kg ({kg * 2.20462:.1f} lb) is outside "
            f"{_WEIGHT_ABS_MIN_KG:.0f}-{_WEIGHT_ABS_MAX_KG:.0f} kg"
        )
    if prior_kg is None or prior_kg <= 0:
        return None
    deviation = abs(kg - prior_kg) / prior_kg
    if deviation > _WEIGHT_MAX_DEVIATION:
        return (
            f"body_weight_kg {kg * 2.20462:.1f} lb is {deviation * 100:.0f}% off your last "
            f"weighing of {prior_kg * 2.20462:.1f} lb — check for a typo. Re-send with "
            f"force_weight=true if it is real."
        )
    return None


def _latest_prior_weight_kg(conn, before: str) -> float | None:
    """Most recent weighing strictly before `before`, from check-ins or Apple Health."""
    row = conn.execute(
        """
        SELECT kg FROM (
            SELECT date AS day, body_weight_kg AS kg
            FROM daily_checkin
            WHERE body_weight_kg IS NOT NULL
            UNION ALL
            SELECT ts::DATE AS day, value_num AS kg
            FROM measurements
            WHERE metric = 'body_mass_kg' AND value_num IS NOT NULL
        )
        WHERE day < $before AND day >= $before::DATE - INTERVAL ($window) DAY
        ORDER BY day DESC
        LIMIT 1
        """,
        {"before": before, "window": _WEIGHT_PRIOR_WINDOW_DAYS},
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else None


@router.get("/checkin/today")
async def get_checkin_today() -> dict:
    conn = get_read_conn()
    try:
        row = conn.execute(
            """
            SELECT date, propranolol_taken, body_weight_kg, soreness_overall,
                   sleep_quality_1_10, energy_1_10, stress_1_10, motivation_1_10,
                   illness_flag, travel_flag, notes, muscle_soreness
            FROM daily_checkin WHERE date = current_date
            """
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {"date": date.today().isoformat()}
    ms_raw = row[11]
    if isinstance(ms_raw, str):
        try:
            ms_raw = json.loads(ms_raw)
        except json.JSONDecodeError:
            ms_raw = None
    return {
        "date": str(row[0]),
        "propranolol_taken": row[1],
        "body_weight_kg": row[2],
        "soreness_overall": row[3],
        "sleep_quality_1_10": row[4],
        "energy_1_10": row[5],
        "stress_1_10": row[6],
        "motivation_1_10": row[7],
        "illness_flag": row[8],
        "travel_flag": row[9],
        "notes": row[10],
        "muscle_soreness": ms_raw if isinstance(ms_raw, dict) else {},
    }


@router.post("/checkin", dependencies=[Depends(require_admin_key)])
async def post_checkin(body: CheckinSubmission) -> dict:
    """Upsert today's daily check-in. Drives the auto-regulation gates."""
    for k, v in (
        ("soreness_overall", body.soreness_overall),
        ("sleep_quality_1_10", body.sleep_quality_1_10),
        ("energy_1_10", body.energy_1_10),
        ("stress_1_10", body.stress_1_10),
        ("motivation_1_10", body.motivation_1_10),
    ):
        if v is not None and not 1 <= v <= 10:
            raise HTTPException(status_code=422, detail=f"{k} must be 1-10")

    target_date = body.date if body.date else date.today().isoformat()
    ms_json = json.dumps(body.muscle_soreness) if body.muscle_soreness is not None else None
    async with write_ctx() as conn:
        if body.body_weight_kg is not None and not body.force_weight:
            problem = check_weight_plausible(
                body.body_weight_kg, _latest_prior_weight_kg(conn, target_date)
            )
            if problem:
                raise HTTPException(status_code=422, detail=problem)
        conn.execute(
            """
            INSERT INTO daily_checkin
                (date, propranolol_taken, body_weight_kg, soreness_overall,
                 sleep_quality_1_10, energy_1_10, stress_1_10, motivation_1_10,
                 illness_flag, travel_flag, notes, muscle_soreness, protein_grams)
            VALUES ($dt, $prop, $wt, $sor, $sq, $en, $st, $mo, $ill, $tr, $no, $ms, $prot)
            ON CONFLICT (date) DO UPDATE SET
                propranolol_taken = COALESCE(EXCLUDED.propranolol_taken, daily_checkin.propranolol_taken),
                body_weight_kg    = COALESCE(EXCLUDED.body_weight_kg, daily_checkin.body_weight_kg),
                soreness_overall  = COALESCE(EXCLUDED.soreness_overall, daily_checkin.soreness_overall),
                sleep_quality_1_10 = COALESCE(EXCLUDED.sleep_quality_1_10, daily_checkin.sleep_quality_1_10),
                energy_1_10       = COALESCE(EXCLUDED.energy_1_10, daily_checkin.energy_1_10),
                stress_1_10       = COALESCE(EXCLUDED.stress_1_10, daily_checkin.stress_1_10),
                motivation_1_10   = COALESCE(EXCLUDED.motivation_1_10, daily_checkin.motivation_1_10),
                illness_flag      = COALESCE(EXCLUDED.illness_flag, daily_checkin.illness_flag),
                travel_flag       = COALESCE(EXCLUDED.travel_flag, daily_checkin.travel_flag),
                notes             = COALESCE(EXCLUDED.notes, daily_checkin.notes),
                muscle_soreness   = COALESCE(EXCLUDED.muscle_soreness, daily_checkin.muscle_soreness),
                protein_grams     = COALESCE(EXCLUDED.protein_grams, daily_checkin.protein_grams)
            """,
            {
                "dt": target_date,
                "prop": body.propranolol_taken,
                "wt": body.body_weight_kg,
                "sor": body.soreness_overall,
                "sq": body.sleep_quality_1_10,
                "en": body.energy_1_10,
                "st": body.stress_1_10,
                "mo": body.motivation_1_10,
                "ill": body.illness_flag,
                "tr": body.travel_flag,
                "no": body.notes,
                "ms": ms_json,
                "prot": body.protein_grams,
            },
        )
    return {"status": "ok", "date": target_date}


# ── Plan adherence (closed-loop tracking) ────────────────────────────────────


@router.post("/training/adherence/recompute", dependencies=[Depends(require_admin_key)])
async def recompute_adherence() -> dict:
    """Recompute yesterday's plan-vs-execution adherence row.

    Compares the plan stored for yesterday against the actual workout (Hevy
    or WHOOP) that landed on the same date — sets prescribed vs sets
    completed, target vs actual RPE. Closes the prescription→execution loop
    so today's planner sees what really happened.
    """
    async with write_ctx() as conn:
        prior = conn.execute(
            "SELECT date, plan_json FROM workout_plans "
            "WHERE date < current_date ORDER BY date DESC LIMIT 1"
        ).fetchone()
        if not prior:
            return {"status": "no_prior_plan"}
        plan_date = prior[0]
        try:
            plan = json.loads(prior[1])
        except (json.JSONDecodeError, TypeError):
            return {"status": "plan_json_invalid"}
        prescribed_sets = sum(
            int(ex.get("sets", 0) or 0)
            for block in plan.get("blocks", [])
            for ex in block.get("exercises", [])
        )
        rec = plan.get("recommendation", {})
        target_rpe = float(rec.get("target_rpe", 0) or 0) or None

        # Order by sets_done, NOT started_at: WHOOP mirrors every Hevy lift as its own
        # workout row a second or two later, with zero sets. Picking the latest workout
        # therefore selected the WHOOP shadow and scored every session 0% complete.
        actual = conn.execute(
            """
            SELECT
                w.id,
                COUNT(*) FILTER (WHERE NOT ws.is_warmup) AS sets_done,
                AVG(ws.rpe) FILTER (WHERE ws.rpe IS NOT NULL) AS avg_rpe
            FROM workouts w
            LEFT JOIN workout_sets ws ON ws.workout_id = w.id
            WHERE w.started_at::DATE = $d
            GROUP BY w.id
            ORDER BY sets_done DESC, MAX(w.started_at) DESC LIMIT 1
            """,
            {"d": plan_date.isoformat() if hasattr(plan_date, "isoformat") else str(plan_date)},
        ).fetchone()

        wid = actual[0] if actual else None
        sets_done = int(actual[1]) if actual and actual[1] else 0
        actual_rpe = float(actual[2]) if actual and actual[2] else None
        completion_pct = (
            round(sets_done / prescribed_sets * 100, 1) if prescribed_sets > 0 else None
        )

        conn.execute(
            """
            INSERT INTO plan_adherence
                (date, plan_date, workout_id, completion_pct,
                 avg_rpe_actual, avg_rpe_target, notes)
            VALUES ($d, $pd, $wid, $cp, $rpe, $tgt, NULL)
            ON CONFLICT (date) DO UPDATE SET
                plan_date = EXCLUDED.plan_date,
                workout_id = EXCLUDED.workout_id,
                completion_pct = EXCLUDED.completion_pct,
                avg_rpe_actual = EXCLUDED.avg_rpe_actual,
                avg_rpe_target = EXCLUDED.avg_rpe_target
            """,
            {
                "d": str(plan_date),
                "pd": str(plan_date),
                "wid": wid,
                "cp": completion_pct,
                "rpe": actual_rpe,
                "tgt": target_rpe,
            },
        )
    return {
        "status": "ok",
        "plan_date": str(plan_date),
        "prescribed_sets": prescribed_sets,
        "sets_done": sets_done,
        "completion_pct": completion_pct,
        "avg_rpe_actual": actual_rpe,
        "avg_rpe_target": target_rpe,
    }


def _linreg_slope(ys: list[float]) -> float:
    n = len(ys)
    if n < 2:
        return 0.0
    xs = list(range(n))
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    num = sum((xs[i] - mean_x) * (ys[i] - mean_y) for i in range(n))
    den = sum((x - mean_x) ** 2 for x in xs) or 1.0
    return num / den


def _streak(values: list[tuple[date, bool]]) -> int:
    """Count trailing consecutive True days from most recent backward."""
    run = 0
    for _, ok in reversed(values):
        if ok:
            run += 1
        else:
            break
    return run


@router.get("/stats/summary")
async def stats_summary() -> dict:
    """Composite stats: ACWR proxy, HRV deviation, sleep consistency, streaks, trend."""
    today = date.today()
    conn = get_read_conn()
    try:
        rec_rows = conn.execute(
            "SELECT date, score, hrv, rhr FROM recovery WHERE date >= $since ORDER BY date",
            {"since": (today - timedelta(days=90)).isoformat()},
        ).fetchall()
        hrv_rows = conn.execute(
            "SELECT date, hrv, hrv_28d_avg, hrv_28d_sd FROM v_hrv_baseline_28d ORDER BY date DESC LIMIT 1"
        ).fetchone()
        sleep_rows = conn.execute(
            _NIGHTS_SQL, {"since": (today - timedelta(days=14)).isoformat()}
        ).fetchall()
        # Canonical workload ACWR — same v_daily_load source and window math as
        # metrics._training_load, so this endpoint agrees with /daily/brief.
        # (Previously this computed a recovery-SCORE ratio mislabeled as ACWR,
        # which disagreed with the canonical training-load ACWR.)
        load_rows = conn.execute(
            "SELECT date, composite_load FROM v_daily_load WHERE date >= $s ORDER BY date",
            {"s": (today - timedelta(days=28)).isoformat()},
        ).fetchall()
        _sleep_state = compute_daily_state(conn)["sleep"]
    finally:
        conn.close()

    # Uncoupled ACWR: acute=[today-6, today]/7, chronic=[today-27, today-7)/21.
    # Mirrors metrics._arm_acwr exactly so this endpoint agrees with DailyState.
    _acute_start = today - timedelta(days=6)
    _chronic_start = today - timedelta(days=27)
    recent_load = [float(r[1] or 0) for r in load_rows if r[0] >= _acute_start]
    prior_load = [float(r[1] or 0) for r in load_rows if _chronic_start <= r[0] < _acute_start]
    acute = round(sum(recent_load) / 7.0, 2) if load_rows else None
    chronic = round(sum(prior_load) / 21.0, 2) if load_rows else None
    acwr = round(acute / chronic, 2) if (acute is not None and chronic) else None

    # Recovery scores still feed the 7-day recovery trend slope below.
    scores_7 = [r[1] for r in rec_rows[-7:] if r[1] is not None]

    rhrs_7 = [r[3] for r in rec_rows[-7:] if r[3] is not None]
    rhrs_28 = [r[3] for r in rec_rows[-28:] if r[3] is not None]
    rhr_baseline = sum(rhrs_28) / len(rhrs_28) if rhrs_28 else None
    rhr_7avg = sum(rhrs_7) / len(rhrs_7) if rhrs_7 else None
    rhr_elevated_pct = (
        ((rhr_7avg - rhr_baseline) / rhr_baseline * 100.0) if (rhr_baseline and rhr_7avg) else None
    )

    hrv_sigma = None
    hrv_today = None
    hrv_baseline = None
    if hrv_rows:
        hrv_today, hrv_baseline, hrv_sd = hrv_rows[1], hrv_rows[2], hrv_rows[3]
        if hrv_today and hrv_baseline and hrv_sd:
            hrv_sigma = (hrv_today - hrv_baseline) / hrv_sd

    # Sleep comes from DailyState, not from this endpoint's own arithmetic.
    #
    # It used to take `sleep_rows[-7:]` — the last seven ROWS, not the last
    # seven nights. `sleep` carries naps, and `is_nap` does not reliably mark
    # them: over the 14 days to 2026-09-05 there were 17 rows for 14 dates,
    # three of them ~1.1-1.5h afternoon sessions. Averaging those alongside real
    # nights reported 6.07h and 15.96h of debt against DailyState's 8.1h and
    # 3.8h — a phantom twelve hours of debt, in a quantity that is 30% of the
    # readiness composite and is read by five components.
    #
    # Patching the divisor would only have made two sources disagree less. The
    # invariant is that there is one source (CLAUDE.md: "DailyState is the
    # single source of truth for readiness, HRV, sleep, training-load"), so
    # this reads it.
    sleep_consistency = _sleep_state.get("consistency_stdev_7d")
    sleep_avg_7 = _sleep_state.get("avg_7d")
    sleep_debt_7 = _sleep_state.get("debt_7d_h")

    rec_trend_slope = _linreg_slope(scores_7) if len(scores_7) >= 3 else 0.0

    recovery_streak = _streak([(r[0], (r[1] or 0) > 60) for r in rec_rows[-30:]])
    sleep_streak_rows = [(r[0], (float(r[1]) if r[1] else 0) >= 7.0) for r in sleep_rows[-30:]]
    sleep_streak = _streak(sleep_streak_rows)

    best_hrv = max((r for r in rec_rows if r[2] is not None), key=lambda r: r[2], default=None)
    lowest_rhr = min((r for r in rec_rows if r[3] is not None), key=lambda r: r[3], default=None)

    return {
        "acwr": {"acute": acute, "chronic": chronic, "ratio": acwr},
        "hrv": {
            "today": hrv_today,
            "baseline_28d": hrv_baseline,
            "deviation_sigma": hrv_sigma,
        },
        "rhr": {
            "baseline_28d": rhr_baseline,
            "last_7_avg": rhr_7avg,
            "elevated_pct": rhr_elevated_pct,
        },
        "sleep": {
            "consistency_stdev": sleep_consistency,
            "avg_7d": sleep_avg_7,
            "debt_7d_hours": sleep_debt_7,
        },
        "recovery_trend_slope_7d": rec_trend_slope,
        "streaks": {
            "recovery_above_60": recovery_streak,
            "sleep_above_7h": sleep_streak,
        },
        "personal_bests": {
            "best_hrv": ({"date": str(best_hrv[0]), "hrv": best_hrv[2]} if best_hrv else None),
            "lowest_rhr": (
                {"date": str(lowest_rhr[0]), "rhr": lowest_rhr[3]} if lowest_rhr else None
            ),
        },
    }


@router.get("/momentum")
async def momentum() -> dict:
    """This-week vs last-week comparison: avg recovery, avg sleep, training sessions."""
    today = date.today()
    this_start = today - timedelta(days=6)
    last_start = today - timedelta(days=13)
    last_end = today - timedelta(days=7)
    conn = get_read_conn()
    try:
        rec_rows = conn.execute(
            "SELECT date, score FROM recovery WHERE date >= $since ORDER BY date",
            {"since": last_start.isoformat()},
        ).fetchall()
        sleep_rows = conn.execute(_NIGHTS_SQL, {"since": last_start.isoformat()}).fetchall()
        session_rows = conn.execute(
            "SELECT started_at::DATE AS d FROM workouts "
            "WHERE started_at::DATE >= $since "
            "GROUP BY d ORDER BY d",
            {"since": last_start.isoformat()},
        ).fetchall()
    finally:
        conn.close()

    def _avg(vals: list[float]) -> float | None:
        return sum(vals) / len(vals) if vals else None

    rec_this = [r[1] for r in rec_rows if r[0] >= this_start and r[1] is not None]
    rec_last = [r[1] for r in rec_rows if last_start <= r[0] <= last_end and r[1] is not None]
    slp_this = [float(r[1]) for r in sleep_rows if r[0] >= this_start and r[1] is not None]
    slp_last = [
        float(r[1]) for r in sleep_rows if last_start <= r[0] <= last_end and r[1] is not None
    ]
    ses_this = len([r for r in session_rows if r[0] >= this_start])
    ses_last = len([r for r in session_rows if last_start <= r[0] <= last_end])

    return {
        "this_week": {
            "recovery_avg": round(_avg(rec_this), 1) if _avg(rec_this) is not None else None,
            "sleep_avg_h": round(_avg(slp_this), 1) if _avg(slp_this) is not None else None,
            "sessions": ses_this,
        },
        "last_week": {
            "recovery_avg": round(_avg(rec_last), 1) if _avg(rec_last) is not None else None,
            "sleep_avg_h": round(_avg(slp_last), 1) if _avg(slp_last) is not None else None,
            "sessions": ses_last,
        },
    }


@router.get("/insights")
async def insights() -> list[dict]:
    """Auto-derived coach-style observations from the last 90 days."""
    today = date.today()
    conn = get_read_conn()
    try:
        rows = conn.execute(
            "SELECT r.date, r.score, r.hrv, r.rhr, "
            "epoch(s.ts_out - s.ts_in) / 3600.0 AS hours "
            "FROM recovery r "
            "LEFT JOIN sleep s ON s.night_date = r.date AND s.source = r.source "
            "WHERE r.date >= $since ORDER BY r.date",
            {"since": (today - timedelta(days=90)).isoformat()},
        ).fetchall()
    finally:
        conn.close()

    items: list[dict] = []
    by_date = {r[0]: r for r in rows}
    dates = sorted(by_date.keys())

    long_sleep_next_hrv = []
    short_sleep_next_hrv = []
    for i, d in enumerate(dates[:-1]):
        today_row = by_date[d]
        next_row = by_date[dates[i + 1]]
        if today_row[4] and next_row[2]:
            if float(today_row[4]) >= 7.5:
                long_sleep_next_hrv.append(next_row[2])
            elif float(today_row[4]) < 6.5:
                short_sleep_next_hrv.append(next_row[2])

    # Only surface this association if the two buckets differ significantly
    # (Welch's t, p < 0.10). Framed as a correlation, not causation: long-sleep
    # nights tend to FOLLOW hard-training days, so depressed next-day HRV is
    # likely driven by the prior load, not the extra sleep. The rigorous,
    # pre-registered version of this test lives in the lab engine (lab.py).
    _ls = (
        _lab_welch(long_sleep_next_hrv, short_sleep_next_hrv)
        if (len(long_sleep_next_hrv) >= 5 and len(short_sleep_next_hrv) >= 5)
        else None
    )
    if _ls is not None and _ls[1] < 0.10:
        delta = sum(long_sleep_next_hrv) / len(long_sleep_next_hrv) - sum(
            short_sleep_next_hrv
        ) / len(short_sleep_next_hrv)
        verb = "higher" if delta > 0 else "lower"
        items.append(
            {
                "headline": f"Long sleep is associated with {verb} next-day HRV (~{abs(delta):.1f}ms)",
                "body": (
                    f"After ≥7.5h nights, next-day HRV averages "
                    f"{sum(long_sleep_next_hrv) / len(long_sleep_next_hrv):.1f}ms vs "
                    f"{sum(short_sleep_next_hrv) / len(short_sleep_next_hrv):.1f}ms after <6.5h "
                    f"(p={_ls[1]:.2f}). Likely reverse-causal: long nights tend to follow hard "
                    f"days, so prior load — not the sleep itself — probably drives the difference."
                ),
                "polarity": "neutral",
            }
        )

    dow_scores: dict[int, list[float]] = {}
    for r in rows:
        if r[1] is None:
            continue
        dow = datetime.fromisoformat(str(r[0])).weekday()
        dow_scores.setdefault(dow, []).append(r[1])
    if dow_scores:
        means = {d: sum(v) / len(v) for d, v in dow_scores.items() if v}
        best = max(means, key=means.get)
        worst = min(means, key=means.get)
        labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
        delta = means[best] - means[worst]
        if delta >= 4:
            items.append(
                {
                    "headline": f"{labels[best]} is your strongest recovery day",
                    "body": (
                        f"{labels[best]} averages {means[best]:.0f} vs {labels[worst]} at "
                        f"{means[worst]:.0f}  ({delta:+.0f} pt gap)."
                    ),
                    "polarity": "neutral",
                }
            )

    below_baseline = []
    scores = [r[1] for r in rows if r[1] is not None]
    if len(scores) >= 14:
        baseline = sum(scores[-28:]) / min(28, len(scores))
        low_days = [r for r in rows[-14:] if r[1] and r[1] < baseline - 10]
        for lr in low_days:
            idx = dates.index(lr[0])
            window = rows[max(0, idx - 2) : idx]
            window_hrvs = [w[2] for w in window if w[2]]
            if window_hrvs and lr[2]:
                below_baseline.append(lr[2] - sum(window_hrvs) / len(window_hrvs))
        if below_baseline:
            avg_drop = sum(below_baseline) / len(below_baseline)
            if avg_drop < -3:
                items.append(
                    {
                        "headline": f"HRV drops ~{abs(avg_drop):.0f}ms ahead of low-recovery days",
                        "body": (
                            "Days flagged low recovery are preceded by HRV "
                            f"{avg_drop:+.1f}ms vs the prior 48h  — watch load when HRV dips."
                        ),
                        "polarity": "negative",
                    }
                )

    # ── VO₂ max trend insight ──────────────────────────────────────────────
    conn2 = get_read_conn()
    try:
        vo2_rows = conn2.execute(
            "SELECT ts::DATE AS day, AVG(value_num) AS v FROM measurements "
            "WHERE metric = 'vo2_max' GROUP BY day ORDER BY day"
        ).fetchall()
        wt_rows = conn2.execute(
            "SELECT ts::DATE AS day, AVG(value_num) AS kg FROM measurements "
            "WHERE metric = 'body_mass_kg' GROUP BY day ORDER BY day"
        ).fetchall()
    finally:
        conn2.close()

    if vo2_rows and len(vo2_rows) >= 10:
        peak_row = max(vo2_rows, key=lambda r: r[1])
        current = vo2_rows[-1][1]
        peak = peak_row[1]
        peak_date = str(peak_row[0])[:7]
        delta = current - peak

        if delta < -5:
            # weight-adjusted attribution — nearest date to peak
            peak_date_str = str(peak_row[0])[:10]
            wt_at_peak = None
            if wt_rows:
                nearest = min(
                    wt_rows,
                    key=lambda r: abs(
                        (
                            date.fromisoformat(str(r[0])[:10]) - date.fromisoformat(peak_date_str)
                        ).days
                    ),
                )
                if (
                    abs(
                        (
                            date.fromisoformat(str(nearest[0])[:10])
                            - date.fromisoformat(peak_date_str)
                        ).days
                    )
                    <= 365
                ):
                    wt_at_peak = nearest[1]
            wt_current = wt_rows[-1][1] if wt_rows else None
            wt_note = ""
            if wt_at_peak and wt_current and wt_current > wt_at_peak:
                wt_delta_kg = wt_current - wt_at_peak
                # if absolute VO2 unchanged, VO2max change = v_peak * (wt_peak/wt_current - 1)
                wt_effect = round(peak * (wt_at_peak / wt_current - 1), 1)
                true_fitness_delta = round(delta - wt_effect, 1)
                wt_note = (
                    f" Weight gain (+{wt_delta_kg:.0f}kg) accounts for ~{abs(wt_effect):.1f} mL/kg/min; "
                    f"true aerobic fitness decline is ~{abs(true_fitness_delta):.1f} mL/kg/min."
                )
            items.insert(
                0,
                {
                    "headline": f"VO₂ max down {abs(delta):.1f} mL/kg/min from {peak:.1f} peak ({peak_date})",
                    "body": (
                        f"Current {current:.1f} vs peak {peak:.1f} mL/kg/min — "
                        f"~4× the expected age-related rate of decline (0.4/yr).{wt_note} "
                        f"Priority: zone 2 cardio 3×/wk and progressive weight reduction."
                    ),
                    "polarity": "negative",
                },
            )

    if not items:
        items.append(
            {
                "headline": "Still learning your patterns",
                "body": "Keep syncing — correlations surface after ~14 days of data.",
                "polarity": "neutral",
            }
        )
    return items


@router.get("/personal-bests")
async def personal_bests() -> dict:
    conn = get_read_conn()
    try:
        top_hrv = conn.execute(
            "SELECT date, hrv FROM recovery WHERE hrv IS NOT NULL ORDER BY hrv DESC LIMIT 5"
        ).fetchall()
        low_rhr = conn.execute(
            "SELECT date, rhr FROM recovery WHERE rhr IS NOT NULL ORDER BY rhr ASC LIMIT 5"
        ).fetchall()
        top_sleep = conn.execute(
            "SELECT night_date, epoch(ts_out - ts_in) / 3600.0 AS h "
            "FROM sleep WHERE ts_out IS NOT NULL AND ts_in IS NOT NULL "
            "ORDER BY h DESC LIMIT 5"
        ).fetchall()
    finally:
        conn.close()
    return {
        "top_hrv": [{"date": str(r[0]), "value": r[1]} for r in top_hrv],
        "lowest_rhr": [{"date": str(r[0]), "value": r[1]} for r in low_rhr],
        "longest_sleep": [{"date": str(r[0]), "value": r[1]} for r in top_sleep],
    }


@router.get("/week/summary")
async def week_summary() -> list[dict]:
    """Mon–Sun blocks for the current week with recovery + sleep."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    conn = get_read_conn()
    try:
        rec = conn.execute(
            "SELECT date, score FROM recovery WHERE date >= $m AND date <= $s",
            {"m": monday.isoformat(), "s": (monday + timedelta(days=6)).isoformat()},
        ).fetchall()
        sleep = conn.execute(
            "SELECT night_date, epoch(ts_out - ts_in) / 3600.0 AS h "
            "FROM sleep WHERE night_date >= $m AND night_date <= $s",
            {"m": monday.isoformat(), "s": (monday + timedelta(days=6)).isoformat()},
        ).fetchall()
    finally:
        conn.close()
    rec_map = {str(r[0]): r[1] for r in rec}
    sleep_map = {str(r[0]): r[1] for r in sleep}
    labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    out = []
    for i in range(7):
        d = monday + timedelta(days=i)
        iso = d.isoformat()
        out.append(
            {
                "label": labels[i],
                "date": iso,
                "is_today": d == today,
                "is_future": d > today,
                "recovery": rec_map.get(iso),
                "sleep_hours": sleep_map.get(iso),
            }
        )
    return out


@router.get("/training/last-session")
async def training_last_session() -> dict:
    conn = get_read_conn()
    try:
        row = conn.execute(
            """
            SELECT
                day_d AS day,
                COUNT(*) AS set_count,
                COUNT(DISTINCT canon_exercise) AS exercise_count,
                SUM(weight_kg * reps) AS volume_kg,
                ARRAY_AGG(DISTINCT exercise ORDER BY exercise) AS exercises
            FROM workout_sets_dedup ws
            WHERE ws.is_warmup = FALSE
            GROUP BY day_d
            ORDER BY day_d DESC
            LIMIT 1
            """
        ).fetchone()
        week_row = conn.execute(
            """
            SELECT COUNT(*), SUM(weight_kg * reps)
            FROM workout_sets_dedup ws
            WHERE ws.is_warmup = FALSE
              AND day_d >= date_trunc('week', current_date)::DATE
            """
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {}
    today = date.today()
    days_ago = (today - row[0]).days
    return {
        "date": str(row[0]),
        "days_ago": days_ago,
        "sets": row[1],
        "exercises": row[2],
        "volume_kg": round(row[3] or 0, 1),
        "exercise_list": list(row[4] or [])[:6],
        "week_sets": week_row[0] if week_row else 0,
        "week_volume_kg": round(week_row[1] or 0, 1) if week_row else 0,
    }


@router.get("/training/heatmap")
async def training_heatmap(weeks: int = Query(104, gt=0, le=260)) -> list[dict]:
    since = (date.today() - timedelta(weeks=weeks)).isoformat()
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                day_d AS day,
                COUNT(*) AS set_count,
                SUM(weight_kg * reps) AS volume_kg
            FROM workout_sets_dedup ws
            WHERE ws.is_warmup = FALSE AND day_d >= $since
            GROUP BY day_d
            ORDER BY day_d
            """,
            {"since": since},
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return []
    max_vol = max(r[2] or 0 for r in rows) or 1
    result = []
    for r in rows:
        vol = r[2] or 0
        intensity = min(4, int((vol / max_vol) * 4) + 1) if vol > 0 else 0
        result.append(
            {"date": str(r[0]), "intensity": intensity, "sets": r[1], "volume_kg": round(vol, 1)}
        )
    return result


@router.get("/training/weekly")
async def training_weekly(weeks: int = Query(52, gt=0, le=260)) -> list[dict]:
    since = (date.today() - timedelta(weeks=weeks)).isoformat()
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                date_trunc('week', started_at)::DATE AS week,
                COUNT(*) AS sets,
                SUM(weight_kg * reps) AS volume_kg,
                COUNT(DISTINCT day_d) AS sessions
            FROM workout_sets_dedup ws
            WHERE ws.is_warmup = FALSE
              AND weight_kg IS NOT NULL
              AND reps IS NOT NULL
              AND day_d >= $since
            GROUP BY week
            ORDER BY week
            """,
            {"since": since},
        ).fetchall()
    finally:
        conn.close()
    return [
        {"week": str(r[0]), "sets": r[1], "volume_kg": round(r[2] or 0, 1), "sessions": r[3]}
        for r in rows
    ]


@router.get("/training/prs")
async def training_prs(n: int = Query(15, gt=0, le=1000)) -> list[dict]:
    """PRs ranked by max weight, with reps-at-PR + Epley estimated 1RM.

    Epley: 1RM = weight * (1 + reps/30). For a true 1-rep set this collapses
    to the lifted weight.
    """
    conn = get_read_conn()
    try:
        # Canonical name: strip trailing "(Machine)", "(Barbell)", "(Cable)" etc.
        # Hevy emits "Leg Press (Machine)"; Fitbod emits "Leg Press" — same lift.
        # We aggregate on the canonical key but display the longest variant seen.
        rows = conn.execute(
            """
            WITH normalized AS (
                SELECT
                    ws.exercise AS raw_exercise,
                    ws.canon_exercise AS canon,
                    ws.weight_kg,
                    ws.reps,
                    ws.started_at
                FROM workout_sets_dedup ws
                WHERE ws.is_warmup = FALSE
                  AND ws.weight_kg IS NOT NULL
                  AND ws.weight_kg > 20
                  AND ws.weight_kg < 300
                  AND ws.reps IS NOT NULL AND ws.reps > 0
                  AND NOT regexp_matches(lower(ws.exercise),
                    'plank|push.?up|pull.?up|chin.?up|dip|crunch|sit.?up|burpee|'
                    'box.jump|jump|lunge|squat air|air squat|scissor|superman|'
                    'mountain.climb|bicycle|flutter|leg raise|hollow|bear crawl|'
                    'russian twist|oblique|twist|v.?up|tuck|hyperextension')
            ),
            pr AS (
                SELECT canon, MAX(weight_kg) AS pr_kg
                FROM normalized
                GROUP BY canon
                HAVING COUNT(*) >= 5 AND STDDEV(weight_kg) > 2
            ),
            display_name AS (
                -- Pick the most descriptive label per canonical group:
                -- prefer the longest variant (usually the "(Machine)" form).
                SELECT canon, ARG_MAX(raw_exercise, LENGTH(raw_exercise)) AS exercise
                FROM normalized
                GROUP BY canon
            ),
            pr_set AS (
                SELECT
                    pr.canon,
                    pr.pr_kg,
                    MAX(n.reps) AS pr_reps,
                    MAX(n.started_at::DATE) AS pr_date,
                    MAX(last.last_d) AS last_performed
                FROM pr
                JOIN normalized n ON n.canon = pr.canon AND n.weight_kg = pr.pr_kg
                JOIN (
                    SELECT canon, MAX(started_at::DATE) AS last_d
                    FROM normalized
                    GROUP BY canon
                ) last ON last.canon = pr.canon
                GROUP BY pr.canon, pr.pr_kg
            )
            SELECT d.exercise, ps.pr_kg, ps.pr_reps, ps.pr_date, ps.last_performed
            FROM pr_set ps
            JOIN display_name d ON d.canon = ps.canon
            ORDER BY ps.pr_kg DESC
            LIMIT $n
            """,
            {"n": n},
        ).fetchall()
    finally:
        conn.close()

    out = []
    for ex, pr_kg, pr_reps, pr_date, last in rows:
        reps = int(pr_reps or 1)
        est_1rm_kg = float(pr_kg) * (1 + reps / 30.0)
        out.append(
            {
                "exercise": ex,
                "pr_lbs": round(pr_kg * 2.20462, 1),
                "pr_kg": round(pr_kg, 1),
                "pr_reps": reps,
                "pr_date": str(pr_date),
                "est_1rm_lbs": round(est_1rm_kg * 2.20462, 1),
                "est_1rm_kg": round(est_1rm_kg, 1),
                "last_performed": str(last),
            }
        )
    return out


@router.get("/training/exercise-last")
async def training_exercise_last(
    exercise: str = Query(..., description="Exercise name (substring, case-insensitive)"),
) -> dict:
    """Return the most recent working set for an exercise — used as the
    plan-vs-history anchor on the Next Workout view (`last: 185×5 @ RPE 8`).
    """
    conn = get_read_conn()
    try:
        row = conn.execute(
            """
            SELECT
                ws.exercise,
                ws.day_d AS day,
                ws.weight_kg,
                ws.reps,
                ws.rpe
            FROM workout_sets_dedup ws
            WHERE ws.is_warmup = FALSE
              AND LOWER(ws.exercise) LIKE $pat
              AND ws.weight_kg IS NOT NULL
              AND ws.reps IS NOT NULL AND ws.reps > 0
            ORDER BY ws.started_at DESC, ws.weight_kg DESC
            LIMIT 1
            """,
            {"pat": f"%{exercise.lower()}%"},
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {"found": False, "exercise": exercise}
    ex, day, wkg, reps, rpe = row
    return {
        "found": True,
        "exercise": ex,
        "date": str(day),
        "weight_kg": round(wkg, 1),
        "weight_lbs": round(wkg * 2.20462, 1),
        "reps": int(reps),
        "rpe": float(rpe) if rpe is not None else None,
    }


@router.get("/training/top-exercises")
async def training_top_exercises(n: int = Query(10, gt=0, le=100)) -> list[dict]:
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                ARG_MAX(exercise, LENGTH(exercise)) AS exercise,
                COUNT(*) AS total_sets,
                SUM(weight_kg * reps) AS total_volume_kg,
                MAX(weight_kg) AS pr_kg,
                COUNT(DISTINCT day_d) AS training_days,
                MAX(day_d) AS last_performed
            FROM workout_sets_dedup ws
            WHERE ws.is_warmup = FALSE AND weight_kg IS NOT NULL AND weight_kg > 20
            GROUP BY canon_exercise
            HAVING STDDEV(weight_kg) > 1
            ORDER BY total_sets DESC
            LIMIT $n
            """,
            {"n": n},
        ).fetchall()
        slope_rows = conn.execute(
            """
            SELECT
                date_trunc('week', started_at)::DATE AS week,
                SUM(weight_kg * reps) AS volume_kg
            FROM workout_sets_dedup ws
            WHERE ws.is_warmup = FALSE
              AND day_d >= (current_date - INTERVAL '16 weeks')
            GROUP BY week
            ORDER BY week
            """
        ).fetchall()
    finally:
        conn.close()

    weeks_vol = [r[1] for r in slope_rows]
    half = len(weeks_vol) // 2
    prior = sum(weeks_vol[:half]) / max(half, 1) if half else 0
    recent = sum(weeks_vol[half:]) / max(len(weeks_vol) - half, 1) if weeks_vol else 0
    overload_pct = ((recent - prior) / prior * 100) if prior > 0 else None

    exercises = [
        {
            "exercise": r[0],
            "total_sets": r[1],
            "total_volume_kg": round(r[2] or 0, 1),
            "pr_lbs": round(r[3] * 2.20462, 1),
            "training_days": r[4],
            "last_performed": str(r[5]),
        }
        for r in rows
    ]
    return exercises


@router.get("/training/overload-signal")
async def training_overload_signal() -> dict:
    conn = get_read_conn()
    try:
        # Dense week spine, LEFT JOINed.
        #
        # A bare GROUP BY emits no row for a week with no training, so a rested
        # week simply vanished: `recent_sessions_per_week` was the mean over
        # the weeks he DID train (never pulled down by a blank one), and the
        # prior/recent split was by row count rather than by time, so "8 weeks
        # vs the prior 8" could span very different amounts of calendar.
        #
        # The current week is excluded from both halves — it is still in
        # progress, and counting a partial week as a whole one understates the
        # recent side of every comparison on this card.
        rows = conn.execute(
            """
            WITH spine AS (
                SELECT DISTINCT date_trunc('week', d)::DATE AS week
                FROM generate_series(
                    current_date - INTERVAL '16 weeks', current_date, INTERVAL '1 day'
                ) t(d)
                WHERE date_trunc('week', d) < date_trunc('week', current_date)
            ),
            agg AS (
                SELECT
                    date_trunc('week', started_at)::DATE AS week,
                    SUM(weight_kg * reps) AS volume_kg,
                    COUNT(*) AS sets,
                    COUNT(DISTINCT day_d) AS days
                FROM workout_sets_dedup ws
                WHERE ws.is_warmup = FALSE
                  AND day_d >= (current_date - INTERVAL '16 weeks')
                GROUP BY week
            )
            SELECT s.week,
                   COALESCE(a.volume_kg, 0) AS volume_kg,
                   COALESCE(a.sets, 0) AS sets,
                   COALESCE(a.days, 0) AS days
            FROM spine s
            LEFT JOIN agg a ON a.week = s.week
            ORDER BY s.week
            """
        ).fetchall()
    finally:
        conn.close()

    if not rows:
        return {
            "overload_pct": None,
            "trend": "insufficient_data",
            "recent_sessions_per_week": None,
        }

    weeks_vol = [float(r[1] or 0) for r in rows]
    half = len(weeks_vol) // 2
    prior_avg = sum(weeks_vol[:half]) / max(half, 1) if half else 0
    recent_avg = sum(weeks_vol[half:]) / max(len(weeks_vol) - half, 1) if weeks_vol else 0
    overload_pct = ((recent_avg - prior_avg) / prior_avg * 100) if prior_avg > 0 else None

    days_recent = [r[3] for r in rows[half:]]
    sessions_per_week = sum(days_recent) / max(len(days_recent), 1) if days_recent else None
    blank_weeks_recent = sum(1 for d in days_recent if not d)
    blank_weeks_prior = sum(1 for r in rows[:half] if not r[3])

    trend = (
        "progressing"
        if overload_pct and overload_pct > 5
        else "maintaining"
        if overload_pct and overload_pct > -5
        else "deloading"
        if overload_pct is not None
        else "insufficient_data"
    )

    return {
        "overload_pct": round(overload_pct, 1) if overload_pct is not None else None,
        "prior_avg_kg": round(prior_avg, 1),
        "recent_avg_kg": round(recent_avg, 1),
        "trend": trend,
        "recent_sessions_per_week": round(sessions_per_week, 1) if sessions_per_week else None,
        "weeks_compared": len(rows) - half,
        "blank_weeks_recent": blank_weeks_recent,
        "blank_weeks_prior": blank_weeks_prior,
    }


class CardioLog(BaseModel):
    date: str | None = None
    modality: str
    duration_min: int
    avg_hr: int | None = None
    rpe: float | None = None
    notes: str | None = None


@router.post("/cardio/log", dependencies=[Depends(require_admin_key)])
async def cardio_log(body: CardioLog) -> dict:
    """Log a cardio session (pickleball, walking, biking, etc.)."""
    import hashlib

    d = body.date or date.today().isoformat()
    cid = str(uuid.uuid4())
    payload = f"{d}|{body.modality}|{body.duration_min}|{body.avg_hr}|{body.rpe}|{body.notes or ''}"
    chash = hashlib.sha256(payload.encode()).hexdigest()[:16]
    async with write_ctx() as conn:
        conn.execute(
            """
            INSERT INTO cardio_sessions
              (id, date, modality, duration_min, avg_hr, rpe, zone_distribution_json, content_hash)
            VALUES ($id, $d, $m, $dur, $hr, $rpe, NULL, $h)
            """,
            {
                "id": cid,
                "d": d,
                "m": body.modality,
                "dur": body.duration_min,
                "hr": body.avg_hr,
                "rpe": body.rpe,
                "h": chash,
            },
        )
    return {"status": "ok", "id": cid, "date": d}


@router.delete("/cardio/log/{cid}", dependencies=[Depends(require_admin_key)])
async def cardio_delete(cid: str) -> dict:
    async with write_ctx() as conn:
        conn.execute("DELETE FROM cardio_sessions WHERE id = $id", {"id": cid})
    return {"status": "ok", "id": cid}


@router.get("/cardio/recent")
async def cardio_recent(days: int = Query(60, gt=0, le=365)) -> dict:
    """Recent non-strength activity: WHOOP/Apple workouts + cardio_sessions.

    Surfaces pickleball, walking, biking, etc. — anything tracked outside
    the Hevy lifting log. Used to power the Cardio & Sports panel.
    """
    conn = get_read_conn()
    try:
        # Strength sessions live in workout_sets — we want everything that
        # ISN'T already represented as a lifting session today.
        sessions = conn.execute(
            """
            SELECT
                w.id,
                w.started_at::DATE AS day,
                w.started_at,
                w.ended_at,
                COALESCE(w.kind, 'workout') AS kind,
                w.strain,
                w.avg_hr,
                w.max_hr,
                w.kcal,
                w.source,
                EXTRACT(epoch FROM (w.ended_at - w.started_at)) / 60 AS duration_min
            FROM workouts w
            WHERE w.started_at::DATE >= (current_date - $d * INTERVAL '1 day')
              AND NOT EXISTS (
                  SELECT 1 FROM workout_sets ws WHERE ws.workout_id = w.id
              )
              AND EXTRACT(epoch FROM (w.ended_at - w.started_at)) / 60 >= 5
              AND NOT (w.source = 'whoop' AND w.kind IN ('yoga', 'cross country skiing', 'meditation'))
            ORDER BY w.started_at DESC
            LIMIT 200
            """,
            {"d": days},
        ).fetchall()

        cardio = conn.execute(
            """
            SELECT id, date, modality, duration_min, avg_hr, rpe, zone_distribution_json
            FROM cardio_sessions
            WHERE date >= (current_date - $d * INTERVAL '1 day')
              AND id NOT LIKE 'whoop_w_%'
            ORDER BY date DESC
            LIMIT 200
            """,
            {"d": days},
        ).fetchall()
    finally:
        conn.close()

    items = []
    for sid, day, start, end, kind, strain, avg_hr, max_hr, kcal, source, dur in sessions:
        items.append(
            {
                "id": sid,
                "date": str(day),
                "started_at": str(start) if start else None,
                "kind": (kind or "workout").lower(),
                "strain": round(float(strain), 1) if strain is not None else None,
                "avg_hr": int(avg_hr) if avg_hr is not None else None,
                "max_hr": int(max_hr) if max_hr is not None else None,
                "kcal": round(float(kcal)) if kcal is not None else None,
                "duration_min": round(float(dur)) if dur is not None else None,
                "source": source,
            }
        )
    for cid, day, mod, dur, avg_hr, rpe, zones_json in cardio:
        items.append(
            {
                "id": cid,
                "date": str(day),
                "started_at": None,
                "kind": (mod or "cardio").lower(),
                "strain": None,
                "avg_hr": int(avg_hr) if avg_hr is not None else None,
                "max_hr": None,
                "kcal": None,
                "duration_min": int(dur) if dur is not None else None,
                "source": "manual",
                "rpe": float(rpe) if rpe is not None else None,
            }
        )

    items.sort(key=lambda r: r["date"], reverse=True)

    # Aggregate weekly cardio minutes & top modalities for the panel header.
    by_kind: dict[str, dict] = {}
    cutoff = (date.today() - timedelta(days=28)).isoformat()
    for s in items:
        if s["date"] < cutoff:
            continue
        k = s["kind"]
        b = by_kind.setdefault(k, {"sessions": 0, "minutes": 0, "kcal": 0, "strain": 0.0})
        b["sessions"] += 1
        b["minutes"] += s.get("duration_min") or 0
        b["kcal"] += s.get("kcal") or 0
        if s.get("strain"):
            b["strain"] += s["strain"]

    summary = sorted(
        [{"kind": k, **v} for k, v in by_kind.items()],
        key=lambda r: r["minutes"],
        reverse=True,
    )

    return {
        "days": days,
        "sessions": items[:60],
        "summary_28d": summary,
    }


@router.get("/training/muscle-balance")
async def training_muscle_balance(weeks: int = Query(4, gt=0, le=52)) -> dict:
    """Per-muscle-group set + volume breakdown over the last N weeks.

    Used for spotting imbalances (push/pull, lower neglect) and weekly volume targets.
    """
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT ws.exercise,
                   COUNT(*) AS sets,
                   SUM(weight_kg * reps) AS volume_kg
            FROM workout_sets_dedup ws
            WHERE ws.is_warmup = FALSE
              AND day_d >= (current_date - ($w * INTERVAL '7 days'))
            GROUP BY ws.exercise
            """,
            {"w": weeks},
        ).fetchall()
    finally:
        conn.close()

    buckets: dict[str, dict] = {
        g: {"sets": 0, "volume_kg": 0.0} for g in ("push", "pull", "legs", "core", "other")
    }
    for ex, sets_, vol in rows:
        g = _muscle_group(ex)
        buckets[g]["sets"] += int(sets_ or 0)
        buckets[g]["volume_kg"] += float(vol or 0)

    total_sets = sum(b["sets"] for b in buckets.values()) or 1
    out = [
        {
            "group": g,
            "sets": b["sets"],
            "volume_kg": round(b["volume_kg"], 1),
            "share_pct": round(b["sets"] * 100 / total_sets, 1),
            "weekly_sets": round(b["sets"] / weeks, 1),
        }
        for g, b in buckets.items()
    ]
    out.sort(key=lambda r: r["sets"], reverse=True)
    return {"weeks": weeks, "groups": out, "total_sets": total_sets}


@router.get("/insights/correlations")
async def insights_correlations() -> list[dict]:
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                j.question,
                COUNT(*) AS sample_days,
                AVG(CASE WHEN j.answered_yes THEN r.score END) AS avg_recovery_yes,
                AVG(CASE WHEN NOT j.answered_yes THEN r.score END) AS avg_recovery_no,
                AVG(CASE WHEN j.answered_yes THEN r.hrv END) AS avg_hrv_yes,
                AVG(CASE WHEN NOT j.answered_yes THEN r.hrv END) AS avg_hrv_no
            FROM whoop_journal j
            JOIN recovery r ON r.date = j.date::DATE
            GROUP BY j.question
            HAVING COUNT(*) >= 10
            ORDER BY ABS(
                AVG(CASE WHEN j.answered_yes THEN r.hrv END) -
                AVG(CASE WHEN NOT j.answered_yes THEN r.hrv END)
            ) DESC NULLS LAST
            """
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "question": r[0],
            "sample_days": r[1],
            "avg_recovery_yes": round(r[2], 1) if r[2] else None,
            "avg_recovery_no": round(r[3], 1) if r[3] else None,
            "avg_hrv_yes": round(r[4], 2) if r[4] else None,
            "avg_hrv_no": round(r[5], 2) if r[5] else None,
            "hrv_delta": round(r[4] - r[5], 2) if (r[4] and r[5]) else None,
        }
        for r in rows
    ]


class MedicationIn(BaseModel):
    name: str
    dose: str | None = None
    frequency: str | None = None


@router.post("/clinical/medication", dependencies=[Depends(require_admin_key)])
async def add_medication(body: MedicationIn) -> dict:
    """Add an active medication. Used to bootstrap the medications table so
    the dashboard's beta-blocker awareness works."""

    async with write_ctx() as conn:
        conn.execute(
            "INSERT INTO medications (id, name, dose, frequency, started) VALUES ($id, $n, $d, $f, current_date)",
            {"id": str(uuid.uuid4()), "n": body.name, "d": body.dose, "f": body.frequency},
        )
    return {"status": "ok", "name": body.name}


def _group_panels(rows: list) -> list[dict]:
    """Group flat panel-result rows into [{panel, collected_at, results: [...]}]."""
    grouped: dict[tuple[str, str], dict] = {}
    for r in rows:
        panel, ts, name, value, value_text, unit, rl, rh, ref_text, abn, loinc = r
        key = (panel, str(ts) if ts else "")
        if key not in grouped:
            grouped[key] = {
                "panel": panel,
                "collected_at": str(ts) if ts else None,
                "results": [],
            }
        display: str
        if value_text is not None:
            display = value_text
        elif value is not None:
            display = f"{round(float(value), 3)}"
        else:
            display = "—"
        grouped[key]["results"].append(
            {
                "name": name,
                "value": round(float(value), 3) if value is not None else None,
                "value_text": value_text,
                "display": display,
                "unit": unit,
                "ref_low": rl,
                "ref_high": rh,
                "ref_text": ref_text,
                "is_abnormal": bool(abn) if abn is not None else False,
                "loinc": loinc,
            }
        )
    return list(grouped.values())


@router.get("/clinical/overview")
async def clinical_overview() -> dict:
    """Comprehensive clinical snapshot — drives the Clinical pane.

    Returns conditions (with ICD-10), medications (with start dates), latest
    labs (with ref ranges, H/L flags, days since drawn), full lab history per
    analyte, and current vitals. The frontend layers risk-stratification on top.
    """
    conn = get_read_conn()
    try:
        conditions = conn.execute(
            """
            SELECT name, onset, status, icd10
            FROM conditions
            ORDER BY (status = 'resolved'), onset DESC NULLS LAST
            """
        ).fetchall()
        medications = conn.execute(
            """
            SELECT name, dose, frequency, started, stopped
            FROM medications
            WHERE valid_to IS NULL AND stopped IS NULL
            ORDER BY started DESC NULLS LAST
            """
        ).fetchall()
        # Latest value per lab name
        latest_labs = conn.execute(
            """
            SELECT DISTINCT ON (name)
                name, value, unit, ref_low, ref_high, collected_at, loinc
            FROM labs
            WHERE value IS NOT NULL
            ORDER BY name, collected_at DESC
            """
        ).fetchall()
        # Full history per lab name (for trends)
        all_labs = conn.execute(
            """
            SELECT name, value, unit, ref_low, ref_high, collected_at
            FROM labs
            WHERE value IS NOT NULL
            ORDER BY name, collected_at
            """
        ).fetchall()
        # Panels: grouped lab results from a single order (urine dipstick,
        # renal panel, infectious screens, etc.). Includes both numeric and
        # qualitative results.
        panel_rows = conn.execute(
            """
            SELECT panel, collected_at, name, value, value_text, unit,
                   ref_low, ref_high, ref_text, is_abnormal, loinc
            FROM labs
            WHERE panel IS NOT NULL
            ORDER BY collected_at DESC, panel, name
            """
        ).fetchall()
        # Vitals: latest per metric
        vitals = conn.execute(
            """
            SELECT DISTINCT ON (metric) metric, value_num, unit, ts
            FROM measurements
            WHERE source = 'kaiser_summary'
            ORDER BY metric, ts DESC
            """
        ).fetchall()
    finally:
        conn.close()

    def _flag(value: float | None, low: float | None, high: float | None) -> str | None:
        if value is None:
            return None
        if low is not None and value < low:
            return "L"
        if high is not None and value > high:
            return "H"
        return None

    history_by_name: dict[str, list[dict]] = {}
    for r in all_labs:
        name, value, unit, rl, rh, ts = r
        history_by_name.setdefault(name, []).append(
            {
                "value": round(float(value), 2),
                "unit": unit,
                "ref_low": rl,
                "ref_high": rh,
                "collected_at": str(ts) if ts else None,
                "flag": _flag(float(value), rl, rh),
            }
        )

    return {
        "conditions": [
            {
                "name": r[0],
                "onset": str(r[1]) if r[1] else None,
                "status": r[2],
                "icd10": r[3],
            }
            for r in conditions
        ],
        "medications": [
            {
                "name": r[0],
                "dose": r[1],
                "frequency": r[2],
                "started": str(r[3]) if r[3] else None,
                "stopped": str(r[4]) if r[4] else None,
            }
            for r in medications
        ],
        "key_labs": [
            {
                "name": r[0],
                "value": round(float(r[1]), 2),
                "unit": r[2],
                "ref_low": r[3],
                "ref_high": r[4],
                "collected_at": str(r[5]) if r[5] else None,
                "loinc": r[6],
                "flag": _flag(float(r[1]), r[3], r[4]),
            }
            for r in latest_labs
        ],
        "lab_history": history_by_name,
        "panels": _group_panels(panel_rows),
        "vitals": [
            {
                "metric": r[0],
                "value": round(float(r[1]), 2),
                "unit": r[2],
                "ts": str(r[3]) if r[3] else None,
            }
            for r in vitals
        ],
    }


# Lab follow-up cadences (months). Conservative defaults aligned with USPSTF /
# ADA / AHA guidance for an adult with elevated cardiometabolic risk markers.
_LAB_FOLLOWUP_MONTHS = {
    "HbA1c": 12,
    "Total Cholesterol": 12,
    "LDL Cholesterol (calc)": 12,
    "HDL Cholesterol": 12,
    "Triglycerides": 12,
    "TTG IgA": 36,
}

# Med safety advisories — keyed by medication-name substring, lowercase.
_MED_ADVISORIES: dict[str, list[dict]] = {
    "propranolol": [
        {
            "severity": "warning",
            "text": "Non-selective β-blocker — monitor for bronchospasm in patients with asthma; albuterol response may be blunted. Confirm metoprolol/atenolol contraindicated before switching.",
            "applies_when_condition": "asthma",
        },
        {
            "severity": "info",
            "text": "Blunts RHR & HR-zone response by ~15–20 bpm on dose days. Use RPE as ground truth for cardio intensity.",
        },
    ],
    "escitalopram": [
        {
            "severity": "info",
            "text": "SSRIs can suppress HRV (~5–10%). Read HRV trend, not absolute, while on therapy.",
        },
    ],
    "ciclesonide": [
        {
            "severity": "info",
            "text": "Inhaled corticosteroid — rinse mouth post-dose to reduce thrush risk.",
        },
    ],
}


# ── FIB-4 — non-invasive advanced-liver-fibrosis index ───────────────────────
#
# FIB-4 = (age × AST) / (platelets × √ALT).  Computed on read, never stored:
# every input already lives in `labs`, so a materialised copy could only go
# stale or disagree with the row it was derived from.
#
# `metrics._ROB_AGE` is a *today* constant and cannot age a historical draw, so
# FIB-4 derives the age at the draw from a DOB — scoring a 2023 draw with a 2026
# age silently inflates it.
#
# The DOB is NOT a constant here. This repo is public, and a full date of birth
# is an identity credential in a way the age printed all over the engine is not,
# so it is read from the gitignored clinical profile (`patient.dob`). Absent
# profile → no FIB-4, reported as such: an age-dependent index must not fall
# back to today's age behind the reader's back.

# Two threshold sets exist and they are NOT interchangeable — say which one you
# mean. Sterling 2006 derived 1.45 / 3.25 in an HIV/HCV-coinfected cohort
# (`sterling-2006-fib-4-fibrosis-index.md`). The 1.30 / 2.67 pair below is from
# Shah 2009, doi:10.1016/j.cgh.2009.05.033 (`shah-2009-fib4-nafld-validation.md`),
# which revalidated the index in 541 biopsy-confirmed NAFLD adults — the right
# set here, because Rob's open question is steatosis, not viral hepatitis.
# Do NOT attribute these two numbers to Sterling; that is the specific
# mis-citation both vault notes exist to prevent.
#
# What a rule-out is worth: Shah reports 90% NPV at <=1.30, but says outright
# that it runs "much lower" with metabolic-syndrome features (83% in their
# steatohepatitis subgroup), and 33 of their 327 sub-1.30 subjects were false
# negatives. Both derivation cohorts were ~75-80% Caucasian, so performance in
# East Asian or admixed individuals is uncharacterised.
#
# Age caveat: the lower cut-off loses specificity below ~35 and above ~65 (where
# a raised rule-out near 2.0 is commonly applied). Rob is 40 — inside the
# validated band — but this constant outlives that.
_FIB4_RULE_OUT = 1.30
_FIB4_RULE_IN = 2.67

# The three analytes, by their exact `labs.name`. All three MUST come from one
# draw — an AST from one panel against a platelet count from another produces a
# plausible-looking number that means nothing.
_FIB4_INPUTS = ("AST", "ALT", "Platelet Count")

# Non-negotiable on every payload: a low FIB-4 is not a clean liver.
_FIB4_CAVEAT = (
    "FIB-4 screens for ADVANCED fibrosis (F3–F4) only. It does NOT rule out "
    "steatosis (fatty liver), steatohepatitis, or inflammation — an elevated ALT "
    "with a low FIB-4 still warrants a fatty-liver workup. A low score is not an "
    "all-clear."
)

_FIB4_BANDS = {
    "rule_out": "Advanced fibrosis effectively ruled out — does not rule out fatty liver",
    "indeterminate": "Indeterminate — further workup (elastography / imaging) indicated",
    "rule_in": "High risk of advanced fibrosis — hepatology referral indicated",
}


def _age_at(dob: date, when: date) -> int:
    """Completed years from ``dob`` to ``when``."""
    return when.year - dob.year - ((when.month, when.day) < (dob.month, dob.day))


def _fib4(age_years: int, ast: float, alt: float, platelets: float) -> float | None:
    """FIB-4 index. ``None`` when any input is non-positive (undefined domain).

    Args:
        age_years: Age at the draw, not today.
        ast: AST in unit/L.
        alt: ALT in unit/L.
        platelets: Platelet count in x10^9/L — the formula's native unit, no
            conversion.
    """
    if age_years <= 0 or ast <= 0 or alt <= 0 or platelets <= 0:
        return None
    return (age_years * ast) / (platelets * math.sqrt(alt))


def _fib4_band(score: float) -> str:
    if score < _FIB4_RULE_OUT:
        return "rule_out"
    if score > _FIB4_RULE_IN:
        return "rule_in"
    return "indeterminate"


def _fib4_by_draw(rows: list[tuple], dob: date | None) -> list[dict]:
    """One FIB-4 entry per blood draw, newest first.

    Draws are keyed on ``collected_at`` so all three analytes provably share a
    single venipuncture. A draw missing any input yields ``value: None`` and the
    missing analyte names — it never borrows a value from an adjacent draw.

    Args:
        rows: ``(name, value, collected_at)`` for the FIB-4 analytes only.
        dob: Subject DOB, for the age at each draw. Required and explicit —
            None scores nothing and says so, rather than reaching for a
            today-anchored age. Callers pass `subject_dob()`.
    """
    by_draw: dict[Any, dict[str, float]] = {}
    for name, value, collected_at in rows:
        if value is None or collected_at is None:
            continue
        by_draw.setdefault(collected_at, {})[name] = float(value)

    out: list[dict] = []
    for collected_at, vals in by_draw.items():
        drawn_on = collected_at.date() if hasattr(collected_at, "date") else collected_at
        missing = [n for n in _FIB4_INPUTS if n not in vals]
        entry: dict[str, Any] = {
            "collected_at": str(collected_at),
            "value": None,
            "band": None,
            "band_label": None,
            "missing_inputs": missing,
        }
        if dob is None:
            entry["missing_inputs"] = [*missing, "patient.dob (clinical profile)"]
            out.append(entry)
            continue
        if not missing:
            age = _age_at(dob, drawn_on)
            score = _fib4(age, vals["AST"], vals["ALT"], vals["Platelet Count"])
            if score is not None:
                entry |= {
                    "value": round(score, 2),
                    "band": _fib4_band(score),
                    "band_label": _FIB4_BANDS[_fib4_band(score)],
                    "age_at_draw": age,
                    "inputs": {
                        "ast": vals["AST"],
                        "alt": vals["ALT"],
                        "platelets": vals["Platelet Count"],
                    },
                }
        out.append(entry)

    out.sort(key=lambda e: e["collected_at"], reverse=True)
    return out


@router.get("/clinical/risk")
async def clinical_risk() -> dict:
    """Cardiometabolic risk strip + overdue lab gaps + medication advisories.

    A pragmatic informatics snapshot: BMI/BP/lipid/A1c clustered with
    risk-zone classification, follow-up gaps surfaced per standard intervals,
    and medication advisories cross-referenced with active conditions.
    """
    today = date.today()
    conn = get_read_conn()
    try:
        labs = conn.execute(
            """
            SELECT DISTINCT ON (name) name, value, unit, ref_low, ref_high, collected_at
            FROM labs WHERE value IS NOT NULL
            ORDER BY name, collected_at DESC
            """
        ).fetchall()
        vitals = conn.execute(
            """
            SELECT DISTINCT ON (metric) metric, value_num, unit, ts
            FROM measurements
            WHERE source = 'kaiser_summary'
            ORDER BY metric, ts DESC
            """
        ).fetchall()
        conditions = conn.execute(
            "SELECT lower(name) FROM conditions WHERE valid_to IS NULL"
        ).fetchall()
        meds = conn.execute(
            "SELECT name, started FROM medications WHERE valid_to IS NULL AND stopped IS NULL"
        ).fetchall()
        # FIB-4 inputs: every row of the three analytes, NOT the latest-per-name
        # `labs` pull above — that one collapses across draws, which is exactly
        # the mix that makes FIB-4 silently wrong.
        fib4_rows = conn.execute(
            """
            SELECT name, value, collected_at
            FROM labs
            WHERE name IN ('AST', 'ALT', 'Platelet Count')
              AND value IS NOT NULL AND collected_at IS NOT NULL
            """
        ).fetchall()
    finally:
        conn.close()

    lab_by_name = {
        r[0]: {"value": float(r[1]), "ref_high": r[4], "collected_at": r[5]} for r in labs
    }
    vital_by_metric = {r[0]: {"value": float(r[1]), "ts": r[3]} for r in vitals}
    active_conditions = [r[0] for r in conditions]

    def _classify_bp(sbp: float, dbp: float) -> str:
        if sbp >= 140 or dbp >= 90:
            return "stage2"
        if sbp >= 130 or dbp >= 80:
            return "stage1"
        if sbp >= 120:
            return "elevated"
        return "normal"

    def _classify_bmi(bmi: float) -> str:
        if bmi >= 30:
            return "obese"
        if bmi >= 25:
            return "overweight"
        if bmi >= 18.5:
            return "normal"
        return "underweight"

    def _classify_ldl(ldl: float) -> str:
        if ldl >= 190:
            return "very_high"
        if ldl >= 160:
            return "high"
        if ldl >= 130:
            return "borderline"
        if ldl >= 100:
            return "near_optimal"
        return "optimal"

    def _classify_a1c(a1c: float) -> str:
        if a1c >= 6.5:
            return "diabetic"
        if a1c >= 5.7:
            return "prediabetic"
        return "normal"

    cardiometabolic: list[dict] = []
    sbp = vital_by_metric.get("blood_pressure_systolic")
    dbp = vital_by_metric.get("blood_pressure_diastolic")
    if sbp and dbp:
        cardiometabolic.append(
            {
                "key": "bp",
                "label": "Blood pressure",
                "value": f"{int(sbp['value'])}/{int(dbp['value'])}",
                "unit": "mmHg",
                "ts": str(sbp["ts"]),
                "zone": _classify_bp(sbp["value"], dbp["value"]),
            }
        )

    bmi = vital_by_metric.get("bmi")
    if bmi:
        cardiometabolic.append(
            {
                "key": "bmi",
                "label": "BMI",
                "value": f"{bmi['value']:.1f}",
                "unit": "kg/m²",
                "ts": str(bmi["ts"]),
                "zone": _classify_bmi(bmi["value"]),
            }
        )

    ldl = lab_by_name.get("LDL Cholesterol (calc)")
    if ldl:
        cardiometabolic.append(
            {
                "key": "ldl",
                "label": "LDL-C",
                "value": f"{ldl['value']:.0f}",
                "unit": "mg/dL",
                "ts": str(ldl["collected_at"]),
                "zone": _classify_ldl(ldl["value"]),
            }
        )

    a1c = lab_by_name.get("HbA1c")
    if a1c:
        cardiometabolic.append(
            {
                "key": "a1c",
                "label": "HbA1c",
                "value": f"{a1c['value']:.1f}",
                "unit": "%",
                "ts": str(a1c["collected_at"]),
                "zone": _classify_a1c(a1c["value"]),
            }
        )

    # Overdue labs
    overdue: list[dict] = []
    for name, months in _LAB_FOLLOWUP_MONTHS.items():
        rec = lab_by_name.get(name)
        if not rec or not rec["collected_at"]:
            continue
        last = rec["collected_at"]
        if hasattr(last, "date"):
            last = last.date()
        days = (today - last).days
        due_at_days = months * 30
        if days > due_at_days:
            overdue.append(
                {
                    "name": name,
                    "last_value": rec["value"],
                    "last_date": str(last),
                    "days_overdue": days - due_at_days,
                    "interval_months": months,
                    "months_since": round(days / 30, 1),
                }
            )
    overdue.sort(key=lambda x: -x["days_overdue"])

    # Medication advisories — surface only when the condition trigger applies (or always for plain info).
    advisories: list[dict] = []
    for med_name, _started in meds:
        lower = med_name.lower()
        for key, items in _MED_ADVISORIES.items():
            if key in lower:
                for it in items:
                    cond_trigger = it.get("applies_when_condition")
                    if cond_trigger and not any(cond_trigger in c for c in active_conditions):
                        continue
                    advisories.append(
                        {
                            "med": med_name.split("(")[0].strip(),
                            "severity": it["severity"],
                            "text": it["text"],
                        }
                    )

    # Adherence/onset-window chips for newer meds.
    onset_windows: list[dict] = []
    onset_thresholds_days = {"escitalopram": 28, "lexapro": 28, "grastek": 365, "grass pollen": 365}
    for med_name, started in meds:
        if not started:
            continue
        days = (today - started).days
        lower = med_name.lower()
        for key, full_effect_days in onset_thresholds_days.items():
            if key in lower:
                onset_windows.append(
                    {
                        "med": med_name.split("(")[0].strip(),
                        "days_since_start": days,
                        "full_effect_days": full_effect_days,
                        "phase": (
                            "onset"
                            if days < min(28, full_effect_days // 2)
                            else "active"
                            if days < full_effect_days
                            else "established"
                        ),
                    }
                )
                break

    fib4_history = _fib4_by_draw(fib4_rows, subject_dob())
    fib4_latest = next((e for e in fib4_history if e["value"] is not None), None)

    return {
        "cardiometabolic": cardiometabolic,
        "overdue_labs": overdue,
        "med_advisories": advisories,
        "onset_windows": onset_windows,
        # Hepatic sits apart from the cardiometabolic strip on purpose — FIB-4 is
        # a fibrosis screen, not a cardiometabolic marker, and it carries a
        # caveat the chip shape has nowhere to put.
        "hepatic": {
            "fib4": {
                "latest": fib4_latest,
                "history": fib4_history,
                "caveat": _FIB4_CAVEAT,
                "cutoffs": {"rule_out": _FIB4_RULE_OUT, "rule_in": _FIB4_RULE_IN},
                "formula": "(age x AST) / (platelets x sqrt(ALT))",
            }
        },
    }


@router.get("/body/trend")
async def body_trend() -> list[dict]:
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT day, AVG(kg) AS kg
            FROM (
                SELECT ts::DATE AS day, value_num AS kg
                FROM measurements
                WHERE metric = 'body_mass_kg' AND value_num IS NOT NULL
                UNION ALL
                SELECT date AS day, body_weight_kg AS kg
                FROM daily_checkin
                WHERE body_weight_kg IS NOT NULL
            )
            GROUP BY day
            ORDER BY day
            """
        ).fetchall()
    finally:
        conn.close()
    return [
        {"date": str(r[0]), "kg": round(r[1], 2), "lbs": round(r[1] * 2.20462, 1)} for r in rows
    ]


@router.get("/body/vo2max")
async def body_vo2max() -> list[dict]:
    """VO2 max time series.

    Priority order:
    1. Direct Apple Watch readings (HKQuantityTypeIdentifierVO2Max) from measurements table.
    2. Uth-Sørensen estimate from WHOOP RHR: VO2max ≈ 15.3 × HRmax / HRrest
       HRmax = 208 − (0.7 × 39) = 180.7 bpm  (Tanaka et al., 2001 — more accurate than 220−age).

    Propranolol PRN blunts resting HR → estimated values are floor estimates on dosing days.
    """
    AGE = 39
    HR_MAX = round(208 - 0.7 * AGE, 1)  # Tanaka formula: 180.7 for age 39
    conn = get_read_conn()
    try:
        # Check for direct Apple Health VO2Max readings
        apple_rows = conn.execute(
            """
            SELECT ts::DATE AS day, AVG(value_num) AS vo2max
            FROM measurements
            WHERE metric = 'vo2_max' AND value_num IS NOT NULL AND value_num > 20
            GROUP BY day
            ORDER BY day
            """
        ).fetchall()

        if apple_rows:
            return [
                {"date": str(r[0]), "vo2max": round(float(r[1]), 1), "source": "apple_watch"}
                for r in apple_rows
                if r[1]
            ]

        # Fall back to Uth-Sørensen estimation from WHOOP RHR
        rows = conn.execute(
            """
            SELECT date, AVG(rhr) AS rhr
            FROM recovery
            WHERE rhr IS NOT NULL AND rhr > 30
            GROUP BY date
            ORDER BY date
            """
        ).fetchall()
    finally:
        conn.close()
    return [
        {"date": str(r[0]), "vo2max": round(15.3 * HR_MAX / r[1], 1), "source": "estimated"}
        for r in rows
        if r[1]
    ]


@router.get("/whoop/patterns")
async def whoop_patterns() -> dict:
    """Recovery patterns derived from WHOOP data: day-of-week, distributions, correlations."""
    conn = get_read_conn()
    try:
        # Day-of-week average recovery (0=Mon … 6=Sun)
        dow_rows = conn.execute(
            """
            SELECT dayofweek(date) AS dow, AVG(score) AS avg_score, COUNT(*) AS n
            FROM recovery
            WHERE score IS NOT NULL
            GROUP BY dow
            ORDER BY dow
            """
        ).fetchall()

        # Recovery score distribution
        dist_rows = conn.execute(
            """
            SELECT
                CASE
                    WHEN score < 34 THEN 'Red (0–33)'
                    WHEN score < 67 THEN 'Yellow (34–66)'
                    ELSE 'Green (67–100)'
                END AS bucket,
                COUNT(*) AS n
            FROM recovery
            WHERE score IS NOT NULL
            GROUP BY bucket
            """
        ).fetchall()

        # Sleep vs recovery scatter (90d)
        scatter_rows = conn.execute(
            """
            SELECT
                r.date,
                r.score AS recovery,
                r.hrv,
                r.rhr,
                (EPOCH(sl.ts_out) - EPOCH(sl.ts_in)) / 3600.0 AS sleep_h
            FROM recovery r
            JOIN sleep sl ON sl.night_date = r.date
            WHERE r.score IS NOT NULL
              AND sl.ts_in IS NOT NULL AND sl.ts_out IS NOT NULL
              AND r.date >= current_date - INTERVAL 90 DAY
            ORDER BY r.date DESC
            LIMIT 90
            """
        ).fetchall()

        # Rolling 7d average for trend
        trend_rows = conn.execute(
            """
            SELECT date, score, hrv, rhr
            FROM recovery
            WHERE score IS NOT NULL
              AND date >= current_date - INTERVAL 90 DAY
            ORDER BY date
            """
        ).fetchall()

    finally:
        conn.close()

    # DuckDB dayofweek(): 0=Sun, 1=Mon … 6=Sat. Shift by -1 to align with Mon-first labels.
    DOW_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    return {
        "by_day_of_week": [
            {"day": DOW_LABELS[(int(r[0]) - 1) % 7], "avg_recovery": round(r[1], 1), "n": r[2]}
            for r in dow_rows
        ],
        "distribution": [{"bucket": r[0], "n": r[1]} for r in dist_rows],
        "sleep_vs_recovery": [
            {
                "date": str(r[0]),
                "recovery": round(r[1], 0),
                "hrv": round(r[2], 1) if r[2] else None,
                "rhr": r[3],
                "sleep_h": round(r[4], 2) if r[4] else None,
            }
            for r in scatter_rows
        ],
        "trend_90d": [
            {
                "date": str(r[0]),
                "recovery": r[1],
                "hrv": round(r[2], 1) if r[2] else None,
                "rhr": r[3],
            }
            for r in trend_rows
        ],
    }


@router.get("/body/steps")
async def body_steps(days: int = Query(90, gt=0, le=5000)) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            -- Three sources can write step_count for the same day (apple XML intervals,
            -- HAE daily total, Shortcuts snapshot). Pick the highest-priority source per
            -- day to avoid triple-counting: apple intervals (1) > HAE total (2) > shortcut (3).
            WITH ranked AS (
                SELECT
                    ts::DATE AS day,
                    value_num,
                    CASE
                        WHEN external_id LIKE 'apple:%' THEN 1
                        WHEN external_id LIKE 'hae:%'   THEN 2
                        ELSE                                 3
                    END AS prio
                FROM measurements
                WHERE metric = 'step_count' AND ts::DATE >= $since
            ),
            best_prio AS (
                SELECT day, MIN(prio) AS prio FROM ranked GROUP BY day
            )
            SELECT r.day, SUM(r.value_num) AS steps
            FROM ranked r
            JOIN best_prio b ON r.day = b.day AND r.prio = b.prio
            GROUP BY r.day
            ORDER BY r.day
            """,
            {"since": since},
        ).fetchall()
    finally:
        conn.close()
    return [{"date": str(r[0]), "steps": int(r[1] or 0)} for r in rows]


@router.get("/body/rhr-trend")
async def body_rhr_trend(days: int = Query(90, gt=0, le=365)) -> list[dict]:
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_read_conn()
    try:
        apple_rows = conn.execute(
            """
            SELECT ts::DATE AS day, AVG(value_num) AS rhr
            FROM measurements
            WHERE metric = 'resting_heart_rate' AND ts::DATE >= $since
            GROUP BY day ORDER BY day
            """,
            {"since": since},
        ).fetchall()
        whoop_rows = conn.execute(
            "SELECT date, rhr FROM recovery WHERE date >= $since ORDER BY date",
            {"since": since},
        ).fetchall()
    finally:
        conn.close()
    apple_map = {str(r[0]): round(r[1], 1) for r in apple_rows}
    whoop_map = {str(r[0]): r[1] for r in whoop_rows}
    all_dates = sorted(set(apple_map) | set(whoop_map))
    return [{"date": d, "apple": apple_map.get(d), "whoop": whoop_map.get(d)} for d in all_dates]


@router.get("/fueling/today")
async def fueling_today() -> dict:
    """Today's energy balance, macros, hydration. Empty fields when no data.

    Pulls from `measurements` (Apple Health). Diet entries flow through Apple
    Health from MyFitnessPal / Cronometer / Lose-It / etc. Body composition
    flows from a smart-scale (Withings, Renpho, Eufy, Fitbit Aria).
    """
    today = date.today()
    conn = get_read_conn()
    try:
        # Today's intake totals (sum of values logged today)
        rows = conn.execute(
            """
            SELECT metric, COALESCE(SUM(value_num), 0)
            FROM measurements
            WHERE ts::DATE = $d
              AND metric IN (
                'dietary_energy_kcal','dietary_protein_g','dietary_carbs_g',
                'dietary_fat_g','dietary_fiber_g','dietary_sugar_g',
                'dietary_water_ml','dietary_sodium_mg','dietary_caffeine_mg',
                'active_energy_kcal','basal_energy_kcal'
              )
            GROUP BY metric
            """,
            {"d": today.isoformat()},
        ).fetchall()
        sums = {r[0]: float(r[1]) for r in rows}

        # Latest body weight (kg) — Apple Health (smart scale) preferred, fall back to check-in.
        bw = conn.execute(
            "SELECT value_num FROM measurements "
            "WHERE metric = 'body_mass_kg' AND ts::DATE >= $s "
            "ORDER BY ts DESC LIMIT 1",
            {"s": (today - timedelta(days=30)).isoformat()},
        ).fetchone()
        body_mass_kg = float(bw[0]) if bw else None
        if body_mass_kg is None:
            ck = conn.execute(
                "SELECT body_weight_kg FROM daily_checkin "
                "WHERE body_weight_kg IS NOT NULL ORDER BY date DESC LIMIT 1"
            ).fetchone()
            if ck:
                body_mass_kg = float(ck[0])

        # Latest body fat % and lean mass — last 30 days
        bf = conn.execute(
            "SELECT value_num, ts::DATE FROM measurements "
            "WHERE metric = 'body_fat_pct' AND ts::DATE >= $s "
            "ORDER BY ts DESC LIMIT 1",
            {"s": (today - timedelta(days=30)).isoformat()},
        ).fetchone()
        lbm = conn.execute(
            "SELECT value_num, ts::DATE FROM measurements "
            "WHERE metric = 'lean_body_mass_kg' AND ts::DATE >= $s "
            "ORDER BY ts DESC LIMIT 1",
            {"s": (today - timedelta(days=30)).isoformat()},
        ).fetchone()
    finally:
        conn.close()

    kcal_in = sums.get("dietary_energy_kcal") or None
    active_out = sums.get("active_energy_kcal") or None
    basal_out = sums.get("basal_energy_kcal") or None
    tdee_today = (active_out or 0) + (basal_out or 0) if (active_out or basal_out) else None
    balance = (kcal_in - tdee_today) if (kcal_in is not None and tdee_today is not None) else None

    protein_g = sums.get("dietary_protein_g") or None
    protein_per_kg = (
        round(protein_g / body_mass_kg, 2) if (protein_g is not None and body_mass_kg) else None
    )
    # Athletic target: 1.6-2.2 g/kg body mass
    protein_target_g = round(body_mass_kg * 1.8, 0) if body_mass_kg else None

    return {
        "as_of": today.isoformat(),
        "body_mass_kg": round(body_mass_kg, 2) if body_mass_kg else None,
        "body_mass_lbs": round(body_mass_kg * 2.20462, 1) if body_mass_kg else None,
        "body_fat_pct": round(float(bf[0]), 1) if bf else None,
        "body_fat_date": bf[1].isoformat() if bf else None,
        "lean_body_mass_kg": round(float(lbm[0]), 2) if lbm else None,
        "lean_body_mass_lbs": round(float(lbm[0]) * 2.20462, 1) if lbm else None,
        "lean_body_mass_date": lbm[1].isoformat() if lbm else None,
        "kcal_in": round(kcal_in, 0) if kcal_in else None,
        "kcal_active_out": round(active_out, 0) if active_out else None,
        "kcal_basal_out": round(basal_out, 0) if basal_out else None,
        "kcal_tdee_today": round(tdee_today, 0) if tdee_today else None,
        "kcal_balance": round(balance, 0) if balance is not None else None,
        "protein_g": round(protein_g, 1) if protein_g else None,
        "protein_per_kg": protein_per_kg,
        "protein_target_g": protein_target_g,
        "carbs_g": round(sums.get("dietary_carbs_g"), 1) if sums.get("dietary_carbs_g") else None,
        "fat_g": round(sums.get("dietary_fat_g"), 1) if sums.get("dietary_fat_g") else None,
        "fiber_g": round(sums.get("dietary_fiber_g"), 1) if sums.get("dietary_fiber_g") else None,
        "sugar_g": round(sums.get("dietary_sugar_g"), 1) if sums.get("dietary_sugar_g") else None,
        "water_ml": round(sums.get("dietary_water_ml"), 0)
        if sums.get("dietary_water_ml")
        else None,
        "water_oz": round(sums.get("dietary_water_ml") / 29.5735, 1)
        if sums.get("dietary_water_ml")
        else None,
        "sodium_mg": round(sums.get("dietary_sodium_mg"), 0)
        if sums.get("dietary_sodium_mg")
        else None,
        "caffeine_mg": round(sums.get("dietary_caffeine_mg"), 0)
        if sums.get("dietary_caffeine_mg")
        else None,
        "has_diet_data": kcal_in is not None or protein_g is not None,
        "has_body_comp_data": bf is not None or lbm is not None,
    }


@router.get("/fueling/trend")
async def fueling_trend(days: int = Query(14, gt=0, le=90)) -> list[dict]:
    """Per-day kcal balance + protein g/kg over the last N days."""
    since = (date.today() - timedelta(days=days)).isoformat()
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT ts::DATE AS day, metric, COALESCE(SUM(value_num), 0)
            FROM measurements
            WHERE ts::DATE >= $s
              AND metric IN (
                'dietary_energy_kcal','dietary_protein_g',
                'active_energy_kcal','basal_energy_kcal','body_mass_kg'
              )
            GROUP BY day, metric ORDER BY day
            """,
            {"s": since},
        ).fetchall()
    finally:
        conn.close()

    by_day: dict[str, dict[str, float]] = {}
    for d, m, v in rows:
        by_day.setdefault(str(d), {})[m] = float(v)

    # Carry-forward body mass for protein/kg
    last_bw: float | None = None
    out: list[dict] = []
    for d in sorted(by_day.keys()):
        m = by_day[d]
        bw = m.get("body_mass_kg")
        if bw and bw > 30:  # body mass averaging not summing — take last reading
            last_bw = bw
        kcal_in = m.get("dietary_energy_kcal") or None
        kcal_out = (m.get("active_energy_kcal", 0) + m.get("basal_energy_kcal", 0)) or None
        protein = m.get("dietary_protein_g") or None
        out.append(
            {
                "date": d,
                "kcal_in": round(kcal_in, 0) if kcal_in else None,
                "kcal_out": round(kcal_out, 0) if kcal_out else None,
                "balance": round(kcal_in - kcal_out, 0) if (kcal_in and kcal_out) else None,
                "protein_g": round(protein, 1) if protein else None,
                "protein_per_kg": round(protein / last_bw, 2) if (protein and last_bw) else None,
            }
        )
    return out


@router.get("/lab/questions")
async def lab_questions() -> list[dict]:
    conn = get_read_conn()
    try:
        rows = conn.execute(
            "SELECT id, title, hypothesis, test_type, window_days, vault_ref, enabled "
            "FROM lab_questions ORDER BY id"
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r[0],
            "title": r[1],
            "hypothesis": r[2],
            "test_type": r[3],
            "window_days": r[4],
            "vault_ref": r[5],
            "enabled": bool(r[6]),
        }
        for r in rows
    ]


@router.get("/lab/findings")
async def lab_findings_latest() -> list[dict]:
    """Latest finding per question — answered questions INCLUDED.

    This filtered on ``q.enabled = TRUE``, and `lab.rotate_if_stable` disables a
    question at exactly the moment it reaches a stable definitive verdict. So the
    endpoint could only ever return questions the lab had NOT answered: nine
    resolved hypotheses — including both CONFIRMED findings (≥8h sleep → +14.0ms
    next-morning HRV, n=62; pickleball → −12.3ms, n=152) — were invisible, and
    the research panel was structurally incapable of showing a conclusion.
    """
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            WITH latest AS (
                SELECT question_id, MAX(run_at) AS run_at
                FROM lab_findings GROUP BY question_id
            )
            SELECT q.id, q.title, q.hypothesis, q.vault_ref, q.test_type,
                   f.run_at, f.n, f.effect_size, f.effect_unit, f.p_value, f.verdict,
                   f.summary, q.retired_at, q.min_n
            FROM lab_questions q
            LEFT JOIN latest l ON l.question_id = q.id
            LEFT JOIN lab_findings f ON f.question_id = q.id AND f.run_at = l.run_at
            WHERE q.enabled = TRUE OR q.retired_at IS NOT NULL
            ORDER BY q.id
            """
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "id": r[0],
            "title": r[1],
            "hypothesis": r[2],
            "vault_ref": r[3],
            "test_type": r[4],
            "run_at": r[5].isoformat() if r[5] else None,
            "n": r[6],
            "effect_size": r[7],
            "effect_unit": r[8],
            "p_value": r[9],
            "verdict": r[10],
            "summary": r[11],
            # answered = retired on a stable definitive verdict; open = still under test
            "status": "answered" if r[12] is not None else "open",
            "answered_at": r[12].isoformat() if r[12] else None,
            "min_n": r[13],
        }
        for r in rows
    ]


@router.post("/lab/run", dependencies=[Depends(require_admin_key)])
async def lab_run() -> dict:
    """Execute every enabled hypothesis and persist findings."""
    from shc import lab as _lab

    async with write_ctx() as conn:
        findings = _lab.run_all(conn)
        _lab.persist(conn, findings)
        # Re-open before rotate: a re-verified question that changed its answer
        # goes back under test, and must re-earn retirement from scratch.
        reopened = _lab.reverify_retired(conn, findings)
        retired = _lab.rotate_if_stable(conn)
    return {
        "ran": len(findings),
        "verdicts": {f.question_id: f.verdict for f in findings},
        "retired": retired,
        "reopened": reopened,
        "completed_at": date.today().isoformat(),
    }


# ── Clinical research signals ───────────────────────────────────────────────


def _swc(values: list[float]) -> float | None:
    """Smallest worthwhile change: 0.5 x the SD of the subject's own baseline.

    Hopkins' 0.2 x between-subject SD does not apply to an n-of-1 series; for
    individual monitoring the reference is the person's own day-to-day
    variation. A delta smaller than this is inside the noise floor and must not
    be read as a change. See [[sesoi-typical-error-individual-change]].
    """
    if len(values) < 7:
        return None
    m = sum(values) / len(values)
    sd = (sum((x - m) ** 2 for x in values) / (len(values) - 1)) ** 0.5
    return 0.5 * sd


def _sleep_regularity_index(conn, today: date) -> dict:
    """Phillips 2017 SRI over the full 24h day, across 14 nights.

    SRI = 100 x (2 x P(same sleep/wake state at minute m on consecutive days) - 1),
    so a perfectly regular schedule is 100 and a random one is 0.

    The full 1440-minute day is the whole point of the metric and this used to
    score only the sleep window (`min(start)-30` to `max(end)+30`), which throws
    away the long high-agreement daytime stretch and reports a systematically
    pessimistic number against Phillips' full-day thresholds: 66.3 where the
    real SRI on the same 11 nights was 75.8 — "moderate" for what is actually a
    fairly tight schedule.
    """
    rows = conn.execute(
        "SELECT night_date, "
        "       arg_max(ts_in, epoch(ts_out - ts_in)) AS ts_in, "
        "       arg_max(ts_out, epoch(ts_out - ts_in)) AS ts_out "
        "FROM sleep "
        "WHERE night_date >= $s AND ts_in IS NOT NULL AND ts_out IS NOT NULL "
        "AND COALESCE(is_nap, FALSE) = FALSE "
        "GROUP BY night_date ORDER BY night_date",
        {"s": (today - timedelta(days=14)).isoformat()},
    ).fetchall()

    nights: list[tuple[int, int]] = []
    for _nd, ts_in, ts_out in rows:
        base = ts_in.replace(hour=0, minute=0, second=0, microsecond=0)
        start = int((ts_in - base).total_seconds() // 60)
        nights.append((start, start + int((ts_out - ts_in).total_seconds() // 60)))

    sri: float | None = None
    if len(nights) >= 2:
        agree = total = 0
        for i in range(1, len(nights)):
            a_s, a_e = nights[i - 1]
            b_s, b_e = nights[i]
            for m in range(1440):
                # A session can run past midnight, so test the minute in this
                # cycle and the next before calling the subject awake.
                a = any(a_s <= m + 1440 * k < a_e for k in (0, 1))
                b = any(b_s <= m + 1440 * k < b_e for k in (0, 1))
                agree += a == b
                total += 1
        if total:
            sri = round(100.0 * (2.0 * agree / total - 1.0), 1)

    return {
        "value": sri,
        "n_nights": len(nights),
        "interpretation": (
            "tight" if sri is not None and sri >= 80
            else "moderate" if sri is not None and sri >= 60
            else "scattered" if sri is not None
            else None
        ),
        "ref": "Phillips 2017 - Scientific Reports",
        "peer_reviewed": True,
    }


def _ln_rmssd_trend(conn, today: date) -> dict:
    """Buchheit 2014: TODAY's lnRMSSD against a 7-day rolling baseline, +/- SWC.

    The comparison is daily-vs-baseline. This used to compare a 7-day mean
    ending YESTERDAY against the mean of all rolling means — smoothed against
    smoothed, which damps the delta so far that the +/-0.05 bands (written for
    daily-vs-baseline) essentially never tripped.
    """
    rows = conn.execute(
        "SELECT date, hrv FROM recovery WHERE date >= $s AND hrv IS NOT NULL "
        "ORDER BY date",
        {"s": (today - timedelta(days=28)).isoformat()},
    ).fetchall()
    vals = [math.log(float(v)) for _d, v in rows if v and float(v) > 0]
    if len(vals) < 8:
        return {
            "today": None, "baseline_7d": None, "delta": None, "swc": None,
            "within_noise": None, "cv_pct_7d": None, "n_days": len(vals),
            "ref": "Buchheit 2014 - Front Physiol", "peer_reviewed": True,
        }

    today_ln = vals[-1]
    baseline_window = vals[-8:-1]
    baseline = sum(baseline_window) / len(baseline_window)
    delta = today_ln - baseline
    # SWC comes from the SAME window as the baseline it bands. Deriving it from
    # a wider window would compare today against a 7-day mean using a 28-day
    # noise floor — two different questions in one verdict.
    swc = _swc(baseline_window)
    sd = 2.0 * swc if swc is not None else None
    return {
        "today": round(today_ln, 3),
        "baseline_7d": round(baseline, 3),
        "delta": round(delta, 3),
        # `is not None`, not a truthiness check: a perfectly flat baseline has an
        # SWC of exactly 0.0, which is a real answer ("any change is outside the
        # noise") and not a missing one. `if swc` silently discarded it.
        "swc": round(swc, 3) if swc is not None else None,
        # The verdict the tile should actually render. A delta inside the
        # subject's own noise floor is not a signal, whatever its sign.
        "within_noise": (abs(delta) < swc) if swc is not None else None,
        "cv_pct_7d": round(100.0 * sd / baseline, 2) if sd is not None and baseline > 0 else None,
        "n_days": len(vals),
        "ref": "Buchheit 2014 - Front Physiol",
        "peer_reviewed": True,
    }


def _recovery_red_streak(conn, today: date) -> dict:
    """Consecutive days in WHOOP's red recovery band (<34%).

    Vendor-defined, and labelled as such. The previous version cited "WHOOP
    2022 - internal cohort" and claimed 3+ days is "~double the soft-tissue
    injury risk" under a PEER-REVIEWED badge. That figure is from a vendor blog
    with no published cohort, methods or interval. The count is a fact; the
    risk multiplier was not, and is gone. For an injury-risk read with actual
    literature behind it, use ACWR ([[windt-2017-workload-injury-aetiology]],
    [[zouhal-2021-acwr-scientific-evidence]]), which this engine already
    computes in `metrics.py`.
    """
    rows = conn.execute(
        "SELECT date, score FROM recovery WHERE date >= $s ORDER BY date DESC",
        {"s": (today - timedelta(days=14)).isoformat()},
    ).fetchall()
    streak = 0
    for _d, score in rows:
        if score is not None and float(score) < 34:
            streak += 1
        else:
            break
    return {
        "consecutive_red_days": streak,
        "alarm": streak >= 3,
        "ref": "WHOOP recovery banding (vendor-defined, not peer-reviewed)",
        "peer_reviewed": False,
    }


# Seeman's index spans neuroendocrine, cardiovascular, metabolic and immune
# axes. This database has cardiovascular and metabolic only — no cortisol,
# catecholamines, DHEA-S or inflammatory markers — so what is computed here is
# a CARDIOMETABOLIC SUBSET and is labelled that way rather than borrowing the
# full construct's name unqualified.
_ALLOSTATIC_AXES = {
    "bp_systolic": "cardiovascular",
    "bp_diastolic": "cardiovascular",
    "bmi": "metabolic",
    "waist_cm": "metabolic",
    "ldl": "metabolic",
    "trig": "metabolic",
    "a1c": "metabolic",
    "hdl_low": "metabolic",
}


def _allostatic_load(conn) -> dict:
    """Cardiometabolic subset of Seeman 2001, each marker banded 0/1/2.

    Two things the previous version got wrong, both silent:

    1. It read `bp_systolic` / `systolic` from `measurements`. The column is
       `blood_pressure_systolic`. Blood pressure — the highest-scoring marker
       in this subject's set — dropped out of every score ever rendered.
    2. The score renormalises over whichever markers happen to be present, so
       missing data MOVES THE NUMBER rather than widening an interval. That is
       unavoidable without imputation, but it must be disclosed: `n_markers`,
       the axes covered, and the age of each input now ride on the payload.
    """
    vitals = {
        str(r[0]).lower(): (float(r[1]), r[2])
        for r in conn.execute(
            "SELECT DISTINCT ON (metric) metric, value_num, ts::DATE "
            "FROM measurements WHERE source = 'kaiser_summary' "
            "ORDER BY metric, ts DESC"
        ).fetchall()
        if r[1] is not None
    }
    labs = {
        str(r[0]).lower(): (float(r[1]), r[2])
        for r in conn.execute(
            "SELECT DISTINCT ON (name) name, value, collected_at::DATE "
            "FROM labs WHERE value IS NOT NULL ORDER BY name, collected_at DESC"
        ).fetchall()
        if r[1] is not None
    }

    def pick(store: dict, *keys: str) -> tuple[float | None, object]:
        for k in keys:
            if k in store:
                return store[k]
        return (None, None)

    bp_sys = pick(vitals, "blood_pressure_systolic", "bp_systolic", "systolic")
    bp_dia = pick(vitals, "blood_pressure_diastolic", "bp_diastolic", "diastolic")
    bmi = pick(vitals, "bmi")
    waist = pick(vitals, "waist_circumference_cm")
    ldl = pick(labs, "ldl cholesterol (calc)", "ldl-c", "ldl")
    hdl = pick(labs, "hdl cholesterol", "hdl")
    trig = pick(labs, "triglycerides")
    a1c = pick(labs, "hba1c", "a1c")

    def band(v: float | None, low: float, high: float) -> int | None:
        if v is None:
            return None
        return 2 if v >= high else 1 if v >= low else 0

    def band_low(v: float | None, bad: float, borderline: float) -> int | None:
        """Inverted marker — lower is worse (HDL)."""
        if v is None:
            return None
        return 2 if v < bad else 1 if v < borderline else 0

    scored = {
        "bp_systolic": (band(bp_sys[0], 130, 140), bp_sys),
        "bp_diastolic": (band(bp_dia[0], 80, 90), bp_dia),
        "bmi": (band(bmi[0], 25, 30), bmi),
        "waist_cm": (band(waist[0], 94, 102), waist),
        "ldl": (band(ldl[0], 100, 130), ldl),
        "trig": (band(trig[0], 150, 200), trig),
        "a1c": (band(a1c[0], 5.7, 6.5), a1c),
        "hdl_low": (band_low(hdl[0], 35, 40), hdl),
    }

    present = {k: v for k, (v, _src) in scored.items() if v is not None}
    total = sum(present.values())
    score = round(10.0 * total / (2 * len(present)), 1) if present else None

    return {
        "score_0_10": score,
        "components": present,
        "n_markers": len(present),
        "missing": sorted(k for k, (v, _s) in scored.items() if v is None),
        "axes_covered": sorted({_ALLOSTATIC_AXES[k] for k in present}),
        # Every input's draw date, because this score currently blends a
        # 2023 lipid panel with a 2026 metabolic one and the single number
        # gives no hint of that.
        "input_dates": {
            k: (str(src[1]) if src[1] is not None else None)
            for k, (v, src) in scored.items()
            if v is not None
        },
        "interpretation": (
            "low" if score is not None and score < 3
            else "moderate" if score is not None and score < 6
            else "elevated" if score is not None
            else None
        ),
        "scope": "cardiometabolic subset - no neuroendocrine or immune markers available",
        "ref": "Seeman 2001 - JAMA (subset)",
        "peer_reviewed": True,
    }


@router.get("/clinical-research/insights")
async def clinical_research_insights() -> dict:
    """Four longitudinal physiology signals with published thresholds.

    Was six. Z2 HR drift and drug-adjusted HRV were removed 2026-09-06: both
    had been dead since they were written (they queried `cardio_sessions.
    started_at` and `medications.generic_name`, neither of which exists), and
    both failures were swallowed by a bare `except Exception`, so the tiles
    rendered an em-dash and a x1.00 factor instead of an error. Z2 drift was
    also misnamed — it computed the CV of MEAN HR ACROSS sessions, which is not
    within-session cardiac drift, and no minute-level HR series exists in this
    database to compute the real thing from.

    FIB-4 deliberately does NOT appear here. It lives on `/api/clinical/risk`
    (`hepatic.fib4`) and is already rendered by `clinical-overview.tsx`. This
    panel is longitudinal wearable physiology; that one is clinical labs.
    Duplicating it across both is two sources of truth for one number.

    Every signal that can be compared to the subject's own noise floor is —
    see `_swc` and [[sesoi-typical-error-individual-change]]. A population
    threshold alone cannot say whether a change is real for one person.
    """
    today = date.today()
    conn = get_read_conn()
    try:
        sri = _sleep_regularity_index(conn, today)
        ln = _ln_rmssd_trend(conn, today)
        red_streak = _recovery_red_streak(conn, today)
        allostatic = _allostatic_load(conn)
    finally:
        conn.close()

    return {
        "as_of": today.isoformat(),
        "sleep_regularity_index": sri,
        "ln_rmssd": ln,
        "recovery_deficit_streak": red_streak,
        "allostatic_load": allostatic,
    }


@router.get("/oauth/status")
async def oauth_status() -> list[dict]:
    conn = get_read_conn()
    try:
        rows = conn.execute("SELECT source, last_sync_at, needs_reauth FROM oauth_state").fetchall()
    finally:
        conn.close()
    return [{"source": r[0], "last_sync_at": str(r[1]), "needs_reauth": r[2]} for r in rows]


@router.get("/briefing")
async def get_briefing() -> dict:
    conn = get_read_conn()
    try:
        row = conn.execute(
            """
            SELECT briefing_date, generated_at, training_call, training_rationale,
                   readiness_headline, coaching_note, flags, priority_metric,
                   input_tokens, output_tokens, cache_read_tokens, cost_usd
            FROM ai_briefing
            ORDER BY briefing_date DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {}
    return {
        "briefing_date": str(row[0]),
        "generated_at": str(row[1]),
        "training_call": row[2],
        "training_rationale": row[3],
        "readiness_headline": row[4],
        "coaching_note": row[5],
        "flags": json.loads(row[6]) if row[6] else [],
        "priority_metric": row[7],
        "tokens": {
            "input": row[8],
            "output": row[9],
            "cache_read": row[10],
        },
        "cost_usd": row[11],
    }


# ── Next Workout ─────────────────────────────────────────────────────────────

# `_muscle_group` lives in `shc.metrics` — single source of truth.
_muscle_group = _mg


_WORKOUT_CACHE: dict[str, dict] = {}


# kept for reference by the Ollama fallback path only
@router.get("/workout/context")
async def workout_context() -> dict:
    """Return the full training context string used to generate workout plans.

    Call this from the Claude chat interface before generating a plan.
    """
    conn = get_read_conn()
    try:
        context, plan_date = build_training_context(conn)
    finally:
        conn.close()
    return {"context": context, "plan_date": plan_date.isoformat()}


@router.post("/workout/plan", dependencies=[Depends(require_admin_key)])
async def submit_workout_plan(body: WorkoutPlanSubmission) -> dict:
    """Accept a Claude-generated workout plan, validate it, persist it, and
    optionally push it to Hevy as a routine.

    This endpoint is the write-path used by the Claude chat interface.
    Auto-regulation gates from today's `DailyState` are enforced — plans
    that violate them are rejected with HTTP 409.

    Pass `override_reason` to deliberately train through the max_intensity
    gate by one tier (see `validate_plan`'s docstring for what it does and
    does not loosen). Every override that's actually exercised — i.e. the
    plan genuinely exceeded the true gate, not just carried an unused reason
    string — is logged to `gate_overrides` for audit.
    """
    conn = get_read_conn()
    try:
        if body.plan_date:
            plan_date = date.fromisoformat(body.plan_date)
        else:
            from shc.ai.workout_planner import _workout_logged_today

            real_today = date.today()
            plan_date = (
                (real_today + timedelta(days=1)) if _workout_logged_today(conn) else real_today
            )
        state = compute_daily_state(
            conn, planning_date=plan_date if plan_date != date.today() else None
        )
        from shc.ai.workout_planner import INTENSITY_ORDER, e1rm_by_exercise

        e1rm_ceilings = e1rm_by_exercise(conn, plan_date)

        from shc.ai.vault import valid_citation_filenames

        # Validate with the connection still open so the conn-gated checks
        # (engine-split adherence, clinical contraindication cap, dampened-volume
        # re-check) actually run — they self-skip when conn is None.
        validate_plan(
            body.plan,
            state=state,
            e1rm_ceilings=e1rm_ceilings,
            allowed_citations=valid_citation_filenames(),
            conn=conn,
            override_reason=body.override_reason,
            override_muscle_groups=body.override_muscle_groups,
        )

        # Audit only a GENUINE override — a reason was supplied AND the plan
        # actually needed it (exceeded the true, un-loosened gate). A reason
        # carried on a plan that was already within the gate logs nothing.
        gates = state.get("gates", {})
        true_max = gates.get("max_intensity", "high")
        req_intensity = body.plan.get("recommendation", {}).get("intensity")
        override_used = bool(
            body.override_reason
            and req_intensity in INTENSITY_ORDER
            and INTENSITY_ORDER.index(req_intensity) > INTENSITY_ORDER.index(true_max)
        )
        # Muscle-group override: audit only the groups that were BOTH forbidden and
        # actually trained in the plan — a listed group that wasn't gated or wasn't
        # used bypassed nothing.
        forbid_set = set(gates.get("forbid_muscle_groups", []))
        requested_groups = set(body.override_muscle_groups or [])
        trained_groups = {
            _muscle_group(ex.get("name", ""))
            for block in body.plan.get("blocks", [])
            for ex in block.get("exercises", [])
        }
        mg_overridden = sorted(forbid_set & requested_groups & trained_groups)

        # Muscle-level override audit (2026-07-23 remediation): mirrors the
        # group audit above at fine-grained resolution — a listed muscle (or a
        # listed group expanded to its members) only counts as "overridden" if
        # it was BOTH individually rest-gated AND actually trained (primary)
        # in the plan. Requires the still-open conn to resolve exercise →
        # primary muscle; done here rather than after conn.close() below.
        forbid_muscles_set = set(gates.get("forbid_muscles", []))
        requested_muscles = set(requested_groups)
        for grp in ("push", "pull", "legs"):
            if grp in requested_groups:
                requested_muscles |= {mu for mu, gg in MUSCLE_TO_GROUP.items() if gg == grp}
        trained_muscles: set[str] = set()
        for block in body.plan.get("blocks", []):
            for ex in block.get("exercises", []):
                name = ex.get("name", "")
                if not name:
                    continue
                try:
                    trained_muscles.update(
                        r[0]
                        for r in conn.execute(
                            "SELECT muscle FROM exercise_muscle WHERE exercise_name = ? "
                            "AND role = 'primary'",
                            [name],
                        ).fetchall()
                    )
                except Exception as exc:
                    log.debug("muscle-override audit lookup failed for %r: %s", name, exc)
        muscle_overridden = sorted(forbid_muscles_set & requested_muscles & trained_muscles)

        # Snap every prescribed load onto a weight the gym can actually produce.
        # The planner is an external LLM handed non-round anchors and returns
        # `weight_lbs` as a free float, so 37% of recent prescriptions landed in a
        # physical gap between two weights Rob has used (a 235 lb Hip Thrust on a
        # 230/270 machine). Deliberately NOT a validator: this runs AFTER
        # `validate_plan` and never rejects, because a 409 on a non-round number
        # would block a plan for a cosmetic cause. It mutates `body.plan` in place,
        # so the persisted plan and the Hevy routine below both carry the loadable
        # number. Residual, accepted: a snap to the nearer notch can land up to
        # half a grid step ABOVE a load the ceiling check just approved.
        #
        # Broad except on purpose: snapping is a convenience over a validated plan,
        # so a failure here must never turn into a 422 and cost Rob his session.
        # It is logged at ERROR, not swallowed — an unloadable weight is a far
        # smaller problem than a plan that cannot be submitted.
        try:
            snapped = snap_plan_weights(conn, body.plan)
        except Exception:
            log.exception("loadable snapping failed for %s — plan saved unsnapped", plan_date)
            snapped = []
    except GateViolation as exc:
        raise HTTPException(status_code=409, detail=f"Auto-regulation gate: {exc}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        conn.close()

    if override_used or mg_overridden or muscle_overridden:
        import json
        import uuid

        bypassed = {"gate_reasons": gates.get("reasons", [])}
        if mg_overridden:
            bypassed["muscle_groups_overridden"] = mg_overridden
        if muscle_overridden:
            bypassed["muscles_overridden"] = muscle_overridden
        async with write_ctx() as wconn:
            wconn.execute(
                "INSERT INTO gate_overrides (id, plan_date, requested_intensity, "
                "gate_max_intensity, reason, gates_bypassed_json) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    str(uuid.uuid4()),
                    plan_date,
                    req_intensity or "n/a",
                    true_max,
                    body.override_reason,
                    json.dumps(bypassed),
                ],
            )
        log.warning(
            "gate override exercised on %s — intensity=%s (gate=%s) muscle_groups=%s "
            "muscles=%s — %s",
            plan_date.isoformat(),
            req_intensity if override_used else "—",
            true_max,
            mg_overridden or "—",
            muscle_overridden or "—",
            body.override_reason,
        )

    plan_date_iso = plan_date.isoformat()
    # Persist whether a deload genuinely fired today (gate, not narrative text).
    # This is the structured signal the deload-cooldown reads — anchoring the
    # cooldown window to actual fires, not stray mentions of "deload" in copy.
    deload_prescribed = bool(state.get("gates", {}).get("deload_required"))
    plan_with_meta = {
        "generated_at": plan_date_iso,
        "source": body.source,
        "deload_prescribed": deload_prescribed,
        **body.plan,
    }

    await save_plan(plan_with_meta, source=body.source, target_date=plan_date)
    _WORKOUT_CACHE[plan_date_iso] = plan_with_meta

    hevy_result = None
    if body.push_to_hevy:
        from shc.ingest.hevy import push_routine

        hevy_result = await push_routine(plan_with_meta)

    return {
        "status": "ok",
        "date": plan_date_iso,
        "hevy": hevy_result,
        # Fail visibly: every load the engine moved onto a loadable notch is
        # reported back, not just written into the stored plan.
        "snapped": [
            {
                "exercise": s.exercise,
                "from_lbs": s.original_lbs,
                "to_lbs": s.weight_lbs,
                "delta_pct": round(s.delta_pct, 1),
                "reason": s.reason,
            }
            for s in snapped
        ],
    }


@router.get("/training/science")
async def get_training_science(muscle: str | None = Query(default=None)) -> dict:
    """Evidence-grounded build-up guidance for a muscle (or all curated muscles).

    Returns, per muscle: the cited development brief, the sports-science-grounded
    exercise selection (lengthened-position + head coverage, each with rep target
    and citation), the active MEV/MAV/MRV landmarks, and an honest data-coverage
    read (personalized to Rob's history vs population default). This is the
    queryable surface behind "how do I build up X".
    """
    conn = get_read_conn()
    try:
        from shc.training.autoregulation import muscle_science_report

        report = muscle_science_report(conn, muscle.strip().lower() if muscle else None)
    finally:
        conn.close()
    return {"science": report}


@router.get("/training/emphasis")
async def get_emphasis() -> dict:
    """Return Rob's persisted muscle-emphasis priorities (the engine's live lever)."""
    conn = get_read_conn()
    try:
        rows = conn.execute(
            "SELECT muscle, weight, note, updated_at FROM muscle_emphasis ORDER BY muscle"
        ).fetchall()
    finally:
        conn.close()
    return {
        "emphasis": [
            {"muscle": m, "weight": w, "note": n, "updated_at": str(ts)} for m, w, n, ts in rows
        ]
    }


@router.post("/training/emphasis", dependencies=[Depends(require_admin_key)])
async def set_emphasis(body: EmphasisSubmission) -> dict:
    """Set (upsert) a muscle's training emphasis — the lever that lets what Rob
    asks for actually reach the autoregulation engine.

    The muscle must exist in the trained taxonomy (`exercise_muscle_map`); an
    unknown name is rejected rather than silently stored as a dead row, so a typo
    surfaces instead of quietly no-op'ing the priority Rob set.
    """
    muscle = body.muscle.strip().lower()
    if not muscle:
        raise HTTPException(status_code=422, detail="muscle is required")
    async with write_ctx() as conn:
        known = {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT primary_muscle FROM exercise_muscle_map"
            ).fetchall()
        }
        if muscle not in known:
            raise HTTPException(
                status_code=422,
                detail=f"unknown muscle {muscle!r}; not in the trained taxonomy",
            )
        conn.execute(
            """
            INSERT INTO muscle_emphasis (muscle, weight, note, updated_at)
            VALUES (?, ?, ?, now())
            ON CONFLICT (muscle) DO UPDATE
                SET weight = EXCLUDED.weight,
                    note = EXCLUDED.note,
                    updated_at = now()
            """,
            [muscle, body.weight, body.note],
        )
    return {"status": "ok", "muscle": muscle, "weight": body.weight}


@router.get("/training/tier")
async def get_volume_tier() -> dict:
    """Return each muscle's volume tier + landmarks, and this week's set budget.

    ``grow`` muscles are the mesocycle's growth targets (MEV→MAV); ``maintain``
    muscles hold at MV so the weekly set budget concentrates instead of
    spreading across all 17 (see migration 0078 / ENGINE_INVARIANTS #10).
    """
    conn = get_read_conn()
    try:
        from shc.training.autoregulation import weekly_prescription
        from shc.training.mesocycle import volume_targets

        targets = volume_targets(conn)
        capacity = weekly_prescription(conn).capacity
    finally:
        conn.close()
    muscles = [
        {
            "muscle": m,
            "tier": vt.tier,
            "mv": vt.mv,
            "mev": vt.mev,
            "mav": vt.mav,
            "mrv": vt.mrv,
            "landmark_source": vt.source,
        }
        for m, vt in sorted(targets.items(), key=lambda kv: (kv[1].tier, kv[0]))
    ]
    return {
        "muscles": muscles,
        "grow": [m["muscle"] for m in muscles if m["tier"] == "grow"],
        "maintain": [m["muscle"] for m in muscles if m["tier"] == "maintain"],
        "capacity": capacity,
    }


@router.post("/training/tier", dependencies=[Depends(require_admin_key)])
async def set_volume_tier(body: TierSubmission) -> dict:
    """Set which muscles grow this mesocycle and which hold at maintenance.

    Guards, in order:

    * unknown muscle name → 422 (a typo must surface, not silently no-op)
    * a muscle in BOTH lists → 422 (ambiguous intent is never averaged)
    * demoting an emphasis muscle → 422. `_decide` would override it anyway
      (ENGINE_INVARIANTS #7/#10: a lagging bring-up is never parked at MV), so
      accepting the write would store a lie the engine then ignores. Drop the
      emphasis first if that is really the intent.
    * an empty grow tier → 422. Zero growth targets is never a training
      decision, and it is what a buggy caller sending `{}` would produce.
    """
    grow = [m.strip().lower() for m in body.grow if m.strip()]
    maintain = [m.strip().lower() for m in body.maintain if m.strip()]
    if overlap := set(grow) & set(maintain):
        raise HTTPException(
            status_code=422, detail=f"muscle(s) in both grow and maintain: {sorted(overlap)}"
        )
    if not grow and not maintain:
        raise HTTPException(status_code=422, detail="nothing to set")

    async with write_ctx() as conn:
        known = {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT muscle_group FROM muscle_volume_targets"
            ).fetchall()
        }
        if unknown := (set(grow) | set(maintain)) - known:
            raise HTTPException(status_code=422, detail=f"unknown muscle(s): {sorted(unknown)}")

        emphasis = {r[0] for r in conn.execute("SELECT muscle FROM muscle_emphasis").fetchall()}
        if clash := set(maintain) & emphasis:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"cannot set emphasis muscle(s) to maintain: {sorted(clash)} — the engine "
                    "overrides it (invariant 7/10). DELETE /training/emphasis/<muscle> first."
                ),
            )

        # Would this leave nothing growing? Check against the resulting state,
        # not just the payload, so a partial update can't empty the tier either.
        current_grow = {
            r[0]
            for r in conn.execute(
                "SELECT muscle_group FROM muscle_volume_targets WHERE tier = 'grow'"
            ).fetchall()
        }
        resulting = (current_grow | set(grow)) - set(maintain)
        if not resulting:
            raise HTTPException(
                status_code=422,
                detail="that would leave no muscle growing — set at least one grow tier",
            )

        for muscle, tier in [(m, "grow") for m in grow] + [(m, "maintain") for m in maintain]:
            conn.execute(
                "UPDATE muscle_volume_targets SET tier = ?, updated_at = now() "
                "WHERE muscle_group = ?",
                [tier, muscle],
            )
    return {"status": "ok", "grow": grow, "maintain": maintain, "now_growing": sorted(resulting)}


@router.delete("/training/emphasis/{muscle}", dependencies=[Depends(require_admin_key)])
async def delete_emphasis(muscle: str) -> dict:
    """Remove a muscle from the emphasis set (stop prioritizing it)."""
    m = muscle.strip().lower()
    async with write_ctx() as conn:
        conn.execute("DELETE FROM muscle_emphasis WHERE muscle = ?", [m])
    return {"status": "ok", "muscle": m}


@router.delete("/workout/plan", dependencies=[Depends(require_admin_key)])
async def delete_workout_plan(target_date: str | None = Query(default=None)) -> dict:
    """Delete a stored workout plan (defaults to today). Used to discard test/bad plans."""
    d = target_date or date.today().isoformat()
    async with write_ctx() as conn:
        conn.execute("DELETE FROM workout_plans WHERE date = $d", {"d": d})
    _WORKOUT_CACHE.pop(d, None)
    return {"status": "ok", "date": d}


def _with_execution(plan: dict, plan_date: str) -> dict:
    """Stamp a served plan with whether it has already been trained.

    Without this the card presents a completed session's prescriptions as the
    day's action, and its loads — set before the session — read as a deload
    against the heavier weights the session actually logged.
    """
    status = plan_execution(plan_date)
    if status:
        plan["execution"] = status
    return plan


@router.get("/workout/next")
async def workout_next(regen: bool = Query(default=False)) -> dict:
    """Return today's workout plan.

    Priority order:
    1. In-memory cache (fast path, same process lifetime)
    2. DB-persisted plan for today (survives restarts)
    3. Most recent stored plan from any prior date (persistent across day boundaries)
    4. Fallback stub (instructs user to generate via chat)
    """
    today = date.today().isoformat()

    if not regen and today in _WORKOUT_CACHE:
        # Execution status is deliberately re-read outside the cache: the session
        # that executes the plan lands hours after the plan is cached, and a
        # frozen "not executed yet" is exactly the stale-card bug.
        return _with_execution(_WORKOUT_CACHE[today], today)

    stored = load_plan(today)
    if stored and not regen:
        _WORKOUT_CACHE[today] = stored
        return _with_execution(stored, today)

    # No plan for today — try the most recent stored plan from any prior date
    if not regen:
        latest = load_latest_plan()
        if latest:
            plan_dict, plan_date = latest
            plan_dict["_carried_from"] = plan_date
            return _with_execution(plan_dict, plan_date)

    # No stored plan at all — return a stub that prompts the user to generate via chat
    conn = get_read_conn()
    try:
        rec = conn.execute(
            "SELECT date, score, hrv, rhr FROM recovery ORDER BY date DESC LIMIT 1"
        ).fetchone()
        hrv_base = conn.execute(
            "SELECT hrv, hrv_28d_avg, hrv_28d_sd FROM v_hrv_baseline_28d ORDER BY date DESC LIMIT 1"
        ).fetchone()
        sleep_row = conn.execute(
            "SELECT epoch(ts_out - ts_in) / 3600.0 FROM sleep ORDER BY night_date DESC LIMIT 1"
        ).fetchone()
        workout_rows = conn.execute(
            """
            SELECT day_d AS day, ws.exercise, COUNT(*) AS sets
            FROM workout_sets_dedup ws
            WHERE ws.is_warmup = FALSE AND day_d >= $since
            GROUP BY day_d, ws.exercise ORDER BY day_d DESC
            """,
            {"since": (date.today() - timedelta(days=14)).isoformat()},
        ).fetchall()
        # Canonical workload ACWR from v_daily_load (matches metrics._training_load
        # and /stats/summary). Previously this used a recovery-SCORE ratio, which
        # gated the fallback plan on the wrong signal.
        load_rows = conn.execute(
            "SELECT date, composite_load FROM v_daily_load WHERE date >= $s ORDER BY date",
            {"s": (date.today() - timedelta(days=28)).isoformat()},
        ).fetchall()
    finally:
        conn.close()

    rec_score = rec[1] if rec else None
    hrv_today = hrv_base[0] if hrv_base else None
    hrv_avg = hrv_base[1] if hrv_base else None
    hrv_sd = hrv_base[2] if hrv_base else None
    hrv_sigma = (
        round((hrv_today - hrv_avg) / hrv_sd, 2) if (hrv_today and hrv_avg and hrv_sd) else None
    )
    sleep_hours = round(float(sleep_row[0]), 1) if sleep_row and sleep_row[0] else None
    _today = date.today()
    _acute_start = _today - timedelta(days=6)
    _chronic_start = _today - timedelta(days=27)
    _recent_load = [float(r[1] or 0) for r in load_rows if r[0] >= _acute_start]
    _prior_load = [float(r[1] or 0) for r in load_rows if _chronic_start <= r[0] < _acute_start]
    acwr_acute = round(sum(_recent_load) / 7.0, 2) if load_rows else None
    acwr_chronic = round(sum(_prior_load) / 21.0, 2) if load_rows else None
    acwr = (
        round(acwr_acute / acwr_chronic, 2) if (acwr_acute is not None and acwr_chronic) else None
    )

    group_last_day: dict[str, str] = {}
    for row in workout_rows:
        g = _muscle_group(row[1])
        if g not in group_last_day or row[0] > date.fromisoformat(str(group_last_day[g])):
            group_last_day[g] = str(row[0])
    days_since: dict[str, int] = {
        g: (date.today() - date.fromisoformat(last)).days for g, last in group_last_day.items()
    }

    return _fallback_plan(rec_score, days_since, hrv_sigma, acwr, sleep_hours, today)


def _select_exercises_for_focus(focus_group: str, n: int) -> list[tuple[str, float]]:
    """Pick `n` real exercises from working_weights for the given muscle group,
    prioritizing recently-performed compound movements. Returns (name, weight_kg).
    """
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT ww.exercise, ww.weight_kg, MAX(w.started_at::DATE) AS last_day, COUNT(*) AS sessions
            FROM working_weights ww
            JOIN workout_sets ws ON ws.exercise = ww.exercise
            JOIN workouts w ON w.id = ws.workout_id
            WHERE w.started_at::DATE >= (current_date - INTERVAL '120 days')
              AND ws.is_warmup = FALSE
            GROUP BY ww.exercise, ww.weight_kg
            ORDER BY last_day DESC, sessions DESC
            """
        ).fetchall()
    finally:
        conn.close()

    picked: list[tuple[str, float]] = []
    seen_keys: set[str] = set()
    for ex, wkg, _last, _n in rows:
        if _muscle_group(ex) != focus_group:
            continue
        # de-dup near-identical movement variants ("Bicep Curl (Cable)" vs "Cable Bicep Curl")
        key = "".join(c for c in ex.lower() if c.isalpha())[:14]
        if key in seen_keys:
            continue
        seen_keys.add(key)
        picked.append((ex, float(wkg)))
        if len(picked) >= n:
            break
    return picked


def _walking_asymmetry_28d() -> float | None:
    """Return the 28-day mean walking asymmetry (%) from Apple Health, or None.

    Backs the conditioning block's high-impact avoidance with a real gait signal
    rather than a hardcoded assumption. Returns None when no asymmetry has been
    ingested, so callers degrade to a neutral rationale instead of inventing data.
    """
    conn = get_read_conn()
    try:
        row = conn.execute(
            """
            SELECT AVG(value_num)
            FROM measurements
            WHERE metric = 'walking_asymmetry_pct'
              AND ts >= (current_date - INTERVAL '28 days')
            """
        ).fetchone()
    finally:
        conn.close()
    return round(float(row[0]), 1) if row and row[0] is not None else None


def _fallback_plan(rec_score, days_since, hrv_sigma, acwr, sleep_hours, today) -> dict:
    tier = "green"
    if rec_score is not None:
        if rec_score < 34:
            tier = "red"
        elif rec_score < 67:
            tier = "yellow"
    most_rested = max(days_since.items(), key=lambda x: x[1]) if days_since else ("legs", 3)
    focus_group = most_rested[0]
    focus_map = {
        "legs": "Lower Body — Strength",
        "push": "Upper Body Push",
        "pull": "Upper Body Pull",
        "other": "Full Body",
        "core": "Full Body",
    }
    focus = focus_map.get(focus_group, "Full Body")
    intensity = "high" if tier == "green" else ("moderate" if tier == "yellow" else "low")
    rpe = 8.0 if tier == "green" else (6.5 if tier == "yellow" else 5.0)

    # Per-tier prescription: red = strict deload, yellow = moderate, green = working set %.
    weight_pct = 1.00 if tier == "green" else (0.85 if tier == "yellow" else 0.65)
    sets, reps_str = (4, "5") if tier == "green" else ((3, "8") if tier == "yellow" else (2, "10"))
    accessory_sets = sets - 1 if sets > 2 else sets

    primary = _select_exercises_for_focus(focus_group, 2)
    accessories = _select_exercises_for_focus(focus_group, 5)[2:5]  # different from primary

    def to_exercise(name: str, wkg: float, ssets: int, sreps: str, srpe: float, note: str) -> dict:
        scaled_lbs = round(wkg * weight_pct * 2.20462 / 5) * 5  # round to nearest 5 lbs
        return {
            "name": name,
            "sets": ssets,
            "reps": sreps,
            "weight_lbs": scaled_lbs if scaled_lbs > 0 else None,
            "rpe_target": srpe,
            "notes": note,
        }

    blocks: list[dict] = []
    if primary:
        blocks.append(
            {
                "label": "Primary — Compound",
                "exercises": [
                    to_exercise(
                        name,
                        wkg,
                        sets,
                        reps_str,
                        rpe,
                        f"~{int(weight_pct * 100)}% of working weight ({round(wkg * 2.20462)} lbs)"
                        if tier != "green"
                        else "Working weight",
                    )
                    for name, wkg in primary
                ],
            }
        )
    if accessories:
        blocks.append(
            {
                "label": "Accessory",
                "exercises": [
                    to_exercise(
                        name,
                        wkg,
                        accessory_sets,
                        "10–12" if tier != "red" else "12–15",
                        max(5.0, rpe - 1),
                        "Slow eccentric, full ROM",
                    )
                    for name, wkg in accessories
                ],
            }
        )
    if not blocks:
        # Cold-start guard: no working weights yet for this group.
        blocks = [
            {
                "label": "Primary",
                "exercises": [
                    {
                        "name": f"{focus} compound (your choice)",
                        "sets": sets,
                        "reps": reps_str,
                        "rpe_target": rpe,
                        "notes": "No working weight on file for this group yet — pick a movement and log a set.",
                    }
                ],
            }
        ]

    # ── Conditioning / metabolic finisher (fat-loss layer) ──
    # Low-impact bias when the measured gait asymmetry is elevated (Apple Health
    # walking_asymmetry_pct, 28d mean). Falls back to low-impact by default when
    # no asymmetry signal is ingested — we never assert forefoot overload we
    # can't see in the data.
    asymmetry_pct = _walking_asymmetry_28d()
    asymmetry_note = (
        f"Low-impact bias — 28d walking asymmetry {asymmetry_pct}%."
        if asymmetry_pct is not None
        else "Low-impact bias (no gait-asymmetry signal on file)."
    )
    if tier == "green":
        blocks.append(
            {
                "label": "Metabolic Finisher",
                "rationale": asymmetry_note,
                "exercises": [
                    {
                        "name": "Kettlebell Swing",
                        "sets": 5,
                        "reps": "20",
                        "weight_lbs": 53,
                        "rpe_target": 8.0,
                        "notes": "EMOM 5 min, 60s rest. Drive with hips.",
                    },
                    {
                        "name": "Sled Push",
                        "sets": 4,
                        "reps": "20m",
                        "rpe_target": 8.0,
                        "notes": "Heavy. Walk back. ~6 min.",
                    },
                ],
            }
        )
    elif tier == "yellow":
        blocks.append(
            {
                "label": "Conditioning · Z2/Z3",
                "rationale": asymmetry_note,
                "exercises": [
                    {
                        "name": "Bike (upright or recumbent)",
                        "sets": 1,
                        "reps": "10 min",
                        "rpe_target": 6.0,
                        "notes": "Steady tempo. Use RPE 6 as intensity guide.",
                    },
                ],
            }
        )
    else:  # red
        blocks.append(
            {
                "label": "Active Recovery · Zone 2",
                "rationale": asymmetry_note,
                "exercises": [
                    {
                        "name": "Walk or easy bike",
                        "sets": 1,
                        "reps": "20 min",
                        "rpe_target": 3.0,
                        "notes": "Conversational pace. Builds aerobic base without taxing recovery.",
                    },
                ],
            }
        )

    rationale = (
        f"{focus_group.capitalize()} last trained {most_rested[1]} days ago — most recovered."
        if days_since
        else "No recent training history — full body recommended."
    )
    if tier == "red":
        rationale += (
            " Recovery low → working at 65% to preserve adaptation without taxing the system."
        )
    elif tier == "yellow":
        rationale += " Moderate effort, 85% of working weights."

    # The one plain sentence the dashboard shows. `rationale` above stays the
    # technical record; this is what a tired person reads at 6am, so it carries
    # no jargon and no numbers that need a lookup to mean anything.
    if not days_since:
        summary = "Full body today — there is no recent training history to work around."
    elif tier == "red":
        summary = (
            f"{focus_group.capitalize()} today, kept deliberately light — "
            "your recovery is low and pushing through it costs more than it buys."
        )
    elif tier == "yellow":
        summary = (
            f"{focus_group.capitalize()} today at a moderate effort — "
            f"it has had {most_rested[1]} days off and is the freshest thing you own."
        )
    else:
        summary = (
            f"{focus_group.capitalize()} today, and you can push — "
            f"it has rested {most_rested[1]} days and your recovery is green."
        )

    return {
        "generated_at": today,
        "source": "fallback",
        "readiness_tier": tier,
        "readiness_summary": (
            (f"Recovery score {rec_score:.0f}." if rec_score else "No recovery data.")
            + (f" HRV {hrv_sigma:+.1f}σ from baseline." if hrv_sigma else "")
            + (f" Sleep {sleep_hours}h." if sleep_hours else "")
        ),
        "recommendation": {
            "intensity": intensity,
            "focus": focus,
            "summary": summary,
            "rationale": rationale,
            "estimated_duration_min": 55 if tier != "red" else 35,
            "target_rpe": rpe,
        },
        "warmup": [
            {"name": "Joint circles (neck → ankles)", "duration_sec": 120},
            {"name": "Bodyweight squats", "sets": 2, "reps": 15, "notes": "Focus on depth"},
            {
                "name": f"{focus_group.capitalize()}-specific activation",
                "sets": 2,
                "reps": 12,
                "notes": "50% of working weight",
            },
        ],
        "blocks": blocks,
        "cooldown": "5 min mobility — target trained muscle groups",
        "clinical_notes": [],
        "vault_insights": [
            "ACWR 0.8–1.3 minimizes injury risk (`gabbett-2016-training-injury-prevention-paradox.md`) — current: "
            + (f"{acwr:.2f}" if acwr else "unknown"),
            "HRV-guided training outperforms fixed-load programs (`kiviniemi-2007-hrv-guided-endurance-training.md`)",
            f"{int(weight_pct * 100)}% of working weight at {sets}×{reps_str} matches DUP {tier} day prescription "
            "(`progressive-overload-strength.md`).",
        ],
    }


# ── Briefing ──────────────────────────────────────────────────────────────────


@router.get("/briefing/context")
async def briefing_context() -> dict:
    """Return today's health snapshot for use when generating the daily briefing."""
    conn = get_read_conn()
    try:
        context = build_daily_context(conn)
    finally:
        conn.close()
    return {"context": context}


@router.get("/daily/brief")
async def daily_brief_slim() -> dict:
    """Slim, LLM-optimized combined daily brief.

    Designed to be < 50KB so a Claude Code session can fit it in main context
    without delegating to a sub-agent. Returns:

    - `state`: full DailyState snapshot (DTO from `compute_daily_state`)
    - `vault`: top 5 vault notes, each trimmed to summary + first 800 chars
    - `training`: last 7 days of sessions, top 20 working weights, available
                  Hevy exercise names (compact form), volume targets, mesocycle
                  position. Same numbers as `/api/workout/context` but JSON
                  rather than rendered text.

    Use this instead of `/api/briefing/context` + `/api/workout/context`
    whenever you don't need the full vault-research excerpts.
    """
    from shc.ai.vault import _get_index, state_signals

    conn = get_read_conn()
    try:
        state_d = compute_daily_state(conn)  # already a dict
        signals = state_signals(state_d)
        index = _get_index()
        # limit > pinned count so state-ranked notes survive the central
        # _PINNED_SHARE cap (vault issue #13) instead of returning all-pinned.
        notes = index.query(signals=signals, limit=8) if index else []
        vault_payload = [
            {
                "filename": n.filename,
                "title": n.title,
                "tags": n.tags,
                "summary": n.summary,
                "excerpt": (n.excerpt or "")[:800],
            }
            for n in notes
        ]

        # Extract structured training data — no rendered text.
        training = _slim_training_context(conn, today=date.today(), state=state_d)
        # Authoritative report mode — computed the same way the workout planner
        # decides whether to auto-plan the next session, so the report and the
        # plan never disagree. The model must use this, not re-infer it.
        trained_today = _workout_logged_today(conn)
    finally:
        conn.close()

    return {
        "as_of": state_d["as_of"],
        "mode": "post_workout" if trained_today else "pre_workout",
        "planning_date": (
            (date.today() + timedelta(days=1)) if trained_today else date.today()
        ).isoformat(),
        "state": state_d,
        "vault": vault_payload,
        "training": training,
        "signals": sorted(signals),
    }


def _slim_training_context(conn, today: date, state: dict) -> dict:
    """Extract the structured training data the planner needs — no rendered text."""
    # Last 7 days of sessions (one row per workout, abbreviated).
    sessions_rows = conn.execute(
        """
        SELECT w.id, w.started_at::DATE AS d, w.kind,
               COUNT(ws.id) AS n_sets,
               ROUND(SUM(ws.weight_kg * ws.reps) / 1000.0, 1) AS tonnes,
               STRING_AGG(DISTINCT ws.exercise, ' | ') AS exercises
        FROM workouts w
        LEFT JOIN workout_sets_dedup ws ON ws.workout_id = w.id AND ws.is_warmup = FALSE
        WHERE w.started_at >= (current_date - INTERVAL '7 days')
          AND w.kind NOT IN ('yoga', 'meditation', 'mindfulness')
        GROUP BY w.id, d, w.kind
        ORDER BY d DESC
        LIMIT 20
        """
    ).fetchall()
    sessions = [
        {
            "date": str(r[1]) if r[1] else None,
            "kind": r[2],
            "n_sets": int(r[3]) if r[3] else 0,
            "tonnes": float(r[4]) if r[4] else None,
            "exercises": (r[5] or "").split(" | ")[:6],
        }
        for r in sessions_rows
    ]

    # Top 20 working weights (most recently updated).
    ww_rows = conn.execute(
        """
        SELECT exercise, weight_kg, updated_at
        FROM working_weights
        ORDER BY updated_at DESC
        LIMIT 20
        """
    ).fetchall()
    working_weights = [
        {
            "exercise": r[0],
            "weight_lbs": round(float(r[1]) * 2.20462, 1) if r[1] else None,
            "updated_at": str(r[2]) if r[2] else None,
        }
        for r in ww_rows
    ]

    # Available Hevy exercises grouped by primary muscle (compact list — name only).
    try:
        avail_rows = conn.execute(
            "SELECT primary_muscle_group, title FROM hevy_exercise_templates "
            "ORDER BY primary_muscle_group, title"
        ).fetchall()
        available_by_group: dict[str, list[str]] = {}
        for grp, name in avail_rows:
            available_by_group.setdefault(grp or "other", []).append(name)
    except Exception:
        available_by_group = {}

    # Mesocycle position (compute week index from started_on).
    mesocycle = None
    if _table_exists(conn, "mesocycles"):
        meso_row = conn.execute(
            """
            SELECT id, started_on, planned_weeks, status, deload_week
            FROM mesocycles
            WHERE started_on <= current_date
              AND (ended_on IS NULL OR ended_on >= current_date)
            ORDER BY started_on DESC LIMIT 1
            """
        ).fetchone()
        if meso_row:
            started_on = meso_row[1]
            week_index = ((today - started_on).days // 7) + 1 if started_on else None
            mesocycle = {
                "started_on": str(started_on) if started_on else None,
                "week_index": week_index,
                "planned_weeks": int(meso_row[2]) if meso_row[2] is not None else None,
                "status": meso_row[3],
                "deload_week": int(meso_row[4]) if meso_row[4] is not None else None,
            }

    return {
        "last_7d_sessions": sessions,
        "working_weights_top20": working_weights,
        "available_exercises_by_group": available_by_group,
        "mesocycle": mesocycle,
        "muscle_balance_28d": {
            "push_sets": state["training_load"]["push_sets_28d"],
            "pull_sets": state["training_load"]["pull_sets_28d"],
            "legs_sets": state["training_load"]["legs_sets_28d"],
            "push_pull_ratio": state["training_load"]["push_pull_ratio_28d"],
        },
        "acwr": {
            "value": state["training_load"]["acwr"],
            "acute_7d": state["training_load"]["acute_load_7d"],
            "chronic_21d": state["training_load"]["chronic_load_21d"],
        },
        "rest_status": {
            "days_since_legs": state["training_load"]["days_since_legs"],
            "days_since_push": state["training_load"]["days_since_push"],
            "days_since_pull": state["training_load"]["days_since_pull"],
        },
    }


def _table_exists(conn, name: str) -> bool:
    try:
        row = conn.execute(
            "SELECT 1 FROM information_schema.tables WHERE table_name = $n",
            {"n": name},
        ).fetchone()
        return row is not None
    except Exception:
        return False


@router.post("/briefing", dependencies=[Depends(require_admin_key)])
async def submit_briefing(body: BriefingSubmission) -> dict:
    """Accept a Claude-generated daily briefing and persist it."""
    valid_calls = {"Push", "Train", "Maintain", "Easy", "Rest"}
    if body.training_call not in valid_calls:
        raise HTTPException(status_code=422, detail=f"training_call must be one of {valid_calls}")
    await store_briefing(body.model_dump())
    return {"status": "ok"}


# ── Health story (chat-driven narrative briefing) ────────────────────────────


class HealthStorySubmission(BaseModel):
    narrative: str
    sources: list[str] = []
    model: str | None = None


@router.get("/health-story")
async def get_health_story() -> dict:
    """Return the latest persisted narrative health story."""
    conn = get_read_conn()
    try:
        row = conn.execute(
            "SELECT story_date, generated_at, model, narrative, sources "
            "FROM ai_health_story ORDER BY story_date DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {}
    return {
        "story_date": str(row[0]),
        "generated_at": str(row[1]),
        "model": row[2],
        "narrative": row[3],
        "sources": json.loads(row[4]) if row[4] else [],
    }


@router.post("/health-story", dependencies=[Depends(require_admin_key)])
async def post_health_story(body: HealthStorySubmission) -> dict:
    """Accept a Claude-generated narrative health story and persist it."""
    if not body.narrative.strip():
        raise HTTPException(status_code=422, detail="narrative is empty")
    today = date.today().isoformat()
    async with write_ctx() as conn:
        conn.execute(
            """
            INSERT INTO ai_health_story (story_date, generated_at, model, narrative, sources)
            VALUES ($d, now(), $m, $n, $s)
            ON CONFLICT (story_date) DO UPDATE SET
                generated_at = now(),
                model = EXCLUDED.model,
                narrative = EXCLUDED.narrative,
                sources = EXCLUDED.sources
            """,
            {"d": today, "m": body.model, "n": body.narrative, "s": json.dumps(body.sources)},
        )
    return {"status": "ok", "story_date": today}


# ── Lift progression ──────────────────────────────────────────────────────────


@router.get("/training/progression")
async def lift_progression(
    exercise: str = Query(..., description="Exercise name (partial match ok)"),
    sessions: int = Query(default=20, gt=0, le=100),
) -> dict:
    """Return per-session weight/volume history for a specific exercise.

    Reads from ``workout_sets_dedup`` so workouts logged to both Fitbod and
    Hevy aren't counted twice.
    """
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                day_d AS day,
                ws.exercise,
                COUNT(*) FILTER (WHERE NOT is_warmup) AS work_sets,
                MAX(weight_kg) FILTER (WHERE NOT is_warmup) AS max_kg,
                SUM(reps) FILTER (WHERE NOT is_warmup) AS total_reps,
                SUM(weight_kg * reps) FILTER (WHERE NOT is_warmup) AS volume_kg,
                AVG(rpe) FILTER (WHERE NOT is_warmup AND rpe IS NOT NULL) AS avg_rpe
            FROM workout_sets_dedup ws
            WHERE LOWER(ws.exercise) LIKE $pat
            GROUP BY day_d, ws.exercise
            ORDER BY day_d DESC
            LIMIT $n
            """,
            {"pat": f"%{exercise.lower()}%", "n": sessions},
        ).fetchall()
    finally:
        conn.close()

    history = [
        {
            "date": str(r[0]),
            "exercise": r[1],
            "work_sets": r[2],
            "max_lbs": round(r[3] * 2.20462, 1) if r[3] else None,
            "max_kg": round(r[3], 2) if r[3] else None,
            "total_reps": r[4],
            "volume_kg": round(r[5], 1) if r[5] else None,
            "avg_rpe": round(r[6], 1) if r[6] else None,
        }
        for r in rows
    ]

    # Progression signal: compare last 3 vs prior 3 max weights
    weights = [h["max_kg"] for h in history if h["max_kg"]]
    signal = None
    if len(weights) >= 6:
        recent = sum(weights[:3]) / 3
        prior = sum(weights[3:6]) / 3
        pct = (recent - prior) / prior * 100 if prior > 0 else 0
        signal = "progressing" if pct > 2 else ("stalled" if pct > -2 else "regressing")

    return {"exercise": exercise, "history": history, "progression_signal": signal}


@router.get("/training/stalls")
async def lift_stalls(min_sessions: int = Query(default=4, ge=2, le=20)) -> list[dict]:
    """Return exercises with no meaningful weight increase over the last N sessions."""
    conn = get_read_conn()
    try:
        # Get last N sessions per exercise with their max weight
        rows = conn.execute(
            """
            WITH ranked AS (
                SELECT
                    ws.exercise,
                    day_d AS day,
                    MAX(ws.weight_kg) AS max_kg,
                    ROW_NUMBER() OVER (PARTITION BY ws.exercise ORDER BY started_at DESC) AS rn,
                    COUNT(*) OVER (PARTITION BY ws.exercise) AS total_sessions
                FROM workout_sets_dedup ws
                WHERE ws.is_warmup = FALSE AND ws.weight_kg IS NOT NULL AND ws.weight_kg > 0
                GROUP BY ws.exercise, day_d, started_at
            )
            SELECT exercise, max_kg, rn, total_sessions
            FROM ranked
            WHERE rn <= $n AND total_sessions >= $n
            ORDER BY exercise, rn
            """,
            {"n": min_sessions},
        ).fetchall()
    finally:
        conn.close()

    # Group by exercise and check for stall
    from itertools import groupby

    stalls = []
    for exercise, group in groupby(rows, key=lambda r: r[0]):
        sessions = list(group)
        weights = [r[1] for r in sessions if r[1]]
        total = sessions[0][3] if sessions else 0
        if len(weights) < min_sessions:
            continue
        mn, mx = min(weights), max(weights)
        variation = (mx - mn) / mn if mn > 0 else 0
        if variation < 0.02:  # < 2% change = stalled
            stalls.append(
                {
                    "exercise": exercise,
                    "min_kg": round(mn, 2),
                    "max_kg": round(mx, 2),
                    "min_lbs": round(mn * 2.20462, 1),
                    "max_lbs": round(mx * 2.20462, 1),
                    "sessions_checked": min_sessions,
                    "total_sessions_on_record": total,
                }
            )

    stalls.sort(key=lambda x: -x["total_sessions_on_record"])
    return stalls


# ── Workout retrospective ─────────────────────────────────────────────────────


@router.get("/workout/recent")
async def recent_workouts(limit: int = Query(default=10, gt=0, le=50)) -> list[dict]:
    """Return recent workouts with their exercise summary — for retrospective generation."""
    conn = get_read_conn()
    try:
        rows = conn.execute(
            """
            SELECT
                w.id,
                w.started_at,
                w.ended_at,
                w.notes,
                STRING_AGG(DISTINCT ws.exercise, ', ') AS exercises,
                COUNT(*) FILTER (WHERE NOT ws.is_warmup) AS work_sets,
                MAX(ws.weight_kg) AS max_weight_kg,
                SUM(ws.weight_kg * ws.reps) FILTER (WHERE NOT ws.is_warmup) AS volume_kg,
                AVG(ws.rpe) FILTER (WHERE ws.rpe IS NOT NULL) AS avg_rpe
            FROM workouts w
            JOIN workout_sets ws ON ws.workout_id = w.id
            GROUP BY w.id, w.started_at, w.ended_at, w.notes
            ORDER BY w.started_at DESC
            LIMIT $n
            """,
            {"n": limit},
        ).fetchall()
        # Fetch which ones already have a retrospective
        retro_ids = {
            r[0] for r in conn.execute("SELECT workout_id FROM workout_retrospectives").fetchall()
        }
    finally:
        conn.close()

    return [
        {
            "id": r[0],
            "started_at": str(r[1]),
            "ended_at": str(r[2]) if r[2] else None,
            "notes": r[3],
            "exercises": r[4],
            "work_sets": r[5],
            "volume_kg": round(r[7], 1) if r[7] else None,
            "volume_lbs": round(r[7] * 2.20462, 1) if r[7] else None,
            "avg_rpe": round(r[8], 1) if r[8] else None,
            "has_retrospective": r[0] in retro_ids,
        }
        for r in rows
    ]


@router.get("/training/after-action")
async def training_after_action() -> dict:
    """Per-exercise autoregulation read-out for the last completed Hevy session.

    For each exercise in the most recent session: compares actual sets/reps/RPE
    against the saved plan target (if one exists for that date) and emits a
    next-session weight suggestion. Read-only — Rob logs in Hevy, this just
    reads what synced and tells him what to do next time.

    Rules (Helms 2018 / RP autoreg, RPE-only since Hevy doesn't capture MCV):
        avg actual RPE ≥ target + 2  → -10% next time
        avg actual RPE ≥ target + 1  → -5%
        rep miss ≥ 2 reps/set        → -5%
        avg actual RPE ≤ target - 2  → +2.5%
        else                         → repeat (progress 2.5% if all reps + RPE met)
    """
    import json as _json

    conn = get_read_conn()
    try:
        last_day = conn.execute(
            "SELECT MAX(day_d) FROM workout_sets_dedup WHERE is_warmup = FALSE"
        ).fetchone()
        if not last_day or not last_day[0]:
            return {"as_of": date.today().isoformat(), "session_date": None, "exercises": []}
        sess_date: date = last_day[0]

        actuals = conn.execute(
            """
            SELECT canon_exercise,
                   ANY_VALUE(exercise) AS exercise,
                   COUNT(*)            AS sets,
                   AVG(reps)           AS avg_reps,
                   MIN(reps)           AS min_reps,
                   AVG(weight_kg)      AS avg_weight_kg,
                   MAX(weight_kg)      AS max_weight_kg,
                   AVG(NULLIF(rpe, 0)) AS avg_rpe
            FROM workout_sets_dedup
            WHERE day_d = $d AND is_warmup = FALSE AND reps > 0 AND weight_kg > 0
            GROUP BY canon_exercise
            ORDER BY MIN(set_idx)
            """,
            {"d": sess_date.isoformat()},
        ).fetchall()

        plan_row = conn.execute(
            "SELECT plan_json FROM workout_plans WHERE date = $d",
            {"d": sess_date.isoformat()},
        ).fetchone()
        state_d = compute_daily_state(conn)
    finally:
        conn.close()

    # Build {canonical-name: target} from the plan
    plan_targets: dict[str, dict[str, Any]] = {}
    if plan_row:
        try:
            plan = _json.loads(plan_row[0]) if isinstance(plan_row[0], str) else plan_row[0]
            for block in plan.get("blocks", []):
                for ex in block.get("exercises", []):
                    name = (ex.get("name") or "").lower().strip()
                    if not name:
                        continue
                    reps_raw = ex.get("reps")
                    target_reps: int | None = None
                    if isinstance(reps_raw, int):
                        target_reps = reps_raw
                    elif isinstance(reps_raw, str):
                        import re as _re

                        m = _re.search(r"(\d+)", reps_raw)
                        target_reps = int(m.group(1)) if m else None
                    plan_targets[name] = {
                        "target_reps": target_reps,
                        "target_weight_lbs": ex.get("weight_lbs"),
                        "target_weight_kg": ex.get("weight_kg")
                        or (ex.get("weight_lbs") * 0.453592 if ex.get("weight_lbs") else None),
                        "target_rpe": ex.get("rpe_target"),
                        "target_sets": ex.get("sets"),
                        "block": block.get("label"),
                        "notes": ex.get("notes"),
                    }
        except (ValueError, AttributeError, TypeError):
            pass

    LB_PER_KG = 2.20462

    def _round_to_2_5(lbs: float) -> float:
        return round(lbs / 2.5) * 2.5

    out: list[dict] = []
    for canon, exname, sets_n, avg_reps, min_reps, avg_wt, max_wt, avg_rpe in actuals:
        plan_target = (
            plan_targets.get((exname or "").lower().strip())
            or plan_targets.get(canon.lower().strip())
            or {}
        )
        target_reps = plan_target.get("target_reps")
        target_rpe = plan_target.get("target_rpe")
        target_weight_lbs = plan_target.get("target_weight_lbs") or (
            round(plan_target.get("target_weight_kg") * LB_PER_KG)
            if plan_target.get("target_weight_kg")
            else None
        )
        actual_weight_lbs = round(float(max_wt or 0) * LB_PER_KG, 1) if max_wt else None
        avg_rpe_val = round(float(avg_rpe), 1) if avg_rpe is not None else None

        # Compute suggestion
        delta_pct = 0.0
        reason_parts: list[str] = []

        # Hevy's RPE picker floors at 6, so any prescribed target below 6 is
        # unloggable — a logged 6 against a target of 5 is "on target", not an
        # overshoot. Clamp the comparison to the floor to avoid spurious drops.
        HEVY_RPE_FLOOR = 6.0
        cmp_target = max(target_rpe, HEVY_RPE_FLOOR) if target_rpe is not None else None
        rpe_gap = (
            (avg_rpe_val - cmp_target)
            if (avg_rpe_val is not None and cmp_target is not None)
            else None
        )
        if rpe_gap is not None:
            if rpe_gap >= 2:
                delta_pct = -10
                reason_parts.append(
                    f"avg RPE {avg_rpe_val} vs target {cmp_target:g} — fatigue ahead of plan"
                )
            elif rpe_gap >= 1:
                delta_pct = -5
                reason_parts.append(
                    f"avg RPE {avg_rpe_val} vs target {cmp_target:g} — harder than planned"
                )
            elif rpe_gap <= -2:
                delta_pct = 2.5
                reason_parts.append(f"avg RPE {avg_rpe_val} vs target {cmp_target:g} — too easy")

        if target_reps is not None and min_reps is not None and (target_reps - min_reps) >= 2:
            if delta_pct >= 0:
                delta_pct = -5
                reason_parts.append(
                    f"missed reps by {target_reps - int(min_reps)} on at least one set"
                )

        # On-target & RPE met or unknown: nudge up 2.5% if reps were hit AND RPE under target
        if (
            delta_pct == 0
            and rpe_gap is not None
            and rpe_gap < 0
            and target_reps is not None
            and min_reps is not None
            and min_reps >= target_reps
        ):
            delta_pct = 2.5
            reason_parts.append("hit all reps under target RPE — small progression")

        next_lbs: float | None = None
        base_lbs = target_weight_lbs or actual_weight_lbs
        if base_lbs is not None and delta_pct != 0:
            next_lbs = _round_to_2_5(base_lbs * (1 + delta_pct / 100))

        verdict = (
            "drop"
            if delta_pct < 0
            else "progress"
            if delta_pct > 0
            else "repeat"
            if (target_reps is not None or target_rpe is not None)
            else "no_plan_target"
        )

        out.append(
            {
                "exercise": exname,
                "block": plan_target.get("block"),
                "sets": int(sets_n),
                "avg_reps": round(float(avg_reps), 1) if avg_reps is not None else None,
                "min_reps": int(min_reps) if min_reps is not None else None,
                "target_reps": target_reps,
                "actual_weight_lbs": actual_weight_lbs,
                "target_weight_lbs": target_weight_lbs,
                "avg_rpe": avg_rpe_val,
                "target_rpe": target_rpe,
                "delta_pct": delta_pct,
                "next_session_lbs": next_lbs,
                "verdict": verdict,
                "reason": "; ".join(reason_parts)
                if reason_parts
                else (
                    "On target — repeat planned weight"
                    if (target_rpe or target_reps)
                    else "No plan target on file — log RPE in Hevy for autoreg"
                ),
            }
        )

    # Ground the retrospective in vault research, selected by execution signals
    # derived from the verdicts (not just recovery state). Same retrieval engine
    # the morning planner uses — see shc.ai.vault.
    from shc.ai.vault import _get_index, state_signals

    extra_signals: set[str] = set()
    hints: list[str] = []
    verdicts = {e["verdict"] for e in out}
    reasons = " ".join(e["reason"] for e in out).lower()
    no_rpe_logged = bool(out) and all(e["avg_rpe"] is None for e in out)

    if "drop" in verdicts or "missed reps" in reasons:
        hints += [
            "effective reps",
            "proximity to failure",
            "load selection",
            "repetitions in reserve",
        ]
    if "harder than planned" in reasons or "fatigue ahead" in reasons:
        extra_signals.add("deload")
        hints += ["fatigue management", "autoregulation", "stimulus to fatigue ratio"]
    if "progress" in verdicts or "repeat" in verdicts:
        hints += ["progressive overload", "step loading"]
    if no_rpe_logged:
        hints += ["autoregulation", "proximity to failure", "repetitions in reserve"]

    signals = state_signals(state_d) | extra_signals
    idx = _get_index()
    # Rank by the execution question this retrospective raises (verdict reasons),
    # not the static pinned set — and limit > pinned count so signal notes
    # survive the central _PINNED_SHARE cap (vault issues #12, #13).
    question = reasons.strip() or None
    notes = idx.query(signals, keyword_hints=hints, limit=10, question=question) if idx else []
    vault_research = (
        "## VAULT RESEARCH (ground every adjustment in these)\n\n"
        + "\n\n---\n\n".join(
            f"### {n.title} (`{n.filename}`)\n\n{(n.excerpt or n.body_excerpt or '')[:1400]}"
            for n in notes
        )
        if notes
        else ""
    )

    return {
        "as_of": date.today().isoformat(),
        "session_date": sess_date.isoformat(),
        "days_ago": (date.today() - sess_date).days,
        "has_plan": bool(plan_targets),
        "exercises": out,
        "signals": sorted(signals),
        "vault_research": vault_research,
    }


@router.post("/workout/retrospective", dependencies=[Depends(require_admin_key)])
async def submit_retrospective(body: RetrospectiveSubmission) -> dict:
    """Store a Claude-generated workout retrospective."""
    async with write_ctx() as conn:
        conn.execute(
            """
            INSERT INTO workout_retrospectives
                (workout_id, generated_at, summary, progressive_overload_achieved,
                 rpe_vs_target, flags, vault_insights)
            VALUES ($wid, now(), $summary, $po, $rpe, $flags, $vi)
            ON CONFLICT (workout_id) DO UPDATE SET
                generated_at = excluded.generated_at,
                summary = excluded.summary,
                progressive_overload_achieved = excluded.progressive_overload_achieved,
                rpe_vs_target = excluded.rpe_vs_target,
                flags = excluded.flags,
                vault_insights = excluded.vault_insights
            """,
            {
                "wid": body.workout_id,
                "summary": body.summary,
                "po": body.progressive_overload_achieved,
                "rpe": body.rpe_vs_target,
                "flags": json.dumps(body.flags),
                "vi": json.dumps(body.vault_insights),
            },
        )
    return {"status": "ok", "workout_id": body.workout_id}


@router.get("/workout/retrospective/latest")
async def latest_retrospective() -> dict:
    """Return the most recent completed session and its stored retrospective (if any).

    Powers the post-workout surface: when ``needs_retrospective`` is true the UI
    shows the copy-prompt flow; once a retrospective is POSTed back it renders the
    narrative, flags, and vault insights here. Read-only.
    """
    conn = get_read_conn()
    try:
        row = conn.execute(
            """
            SELECT
                w.id,
                w.started_at,
                STRING_AGG(DISTINCT ws.exercise, ', ')        AS exercises,
                COUNT(*) FILTER (WHERE NOT ws.is_warmup)      AS work_sets,
                r.generated_at,
                r.summary,
                r.progressive_overload_achieved,
                r.rpe_vs_target,
                r.flags,
                r.vault_insights
            FROM workouts w
            JOIN workout_sets ws ON ws.workout_id = w.id
            LEFT JOIN workout_retrospectives r ON r.workout_id = w.id
            GROUP BY w.id, w.started_at, r.generated_at, r.summary,
                     r.progressive_overload_achieved, r.rpe_vs_target,
                     r.flags, r.vault_insights
            ORDER BY w.started_at DESC
            LIMIT 1
            """
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return {"workout_id": None, "needs_retrospective": False, "retrospective": None}

    has_retro = row[5] is not None
    started = row[1]
    days_ago = (date.today() - started.date()).days if started else None

    retrospective = None
    if has_retro:
        retrospective = {
            "generated_at": str(row[4]) if row[4] else None,
            "summary": row[5],
            "progressive_overload_achieved": row[6],
            "rpe_vs_target": row[7],
            "flags": json.loads(row[8]) if row[8] else [],
            "vault_insights": json.loads(row[9]) if row[9] else [],
        }

    return {
        "workout_id": row[0],
        "started_at": str(started) if started else None,
        "session_date": started.date().isoformat() if started else None,
        "days_ago": days_ago,
        "exercises": row[2],
        "work_sets": row[3],
        "needs_retrospective": not has_retro,
        "retrospective": retrospective,
    }


@router.post("/internal/checkpoint", dependencies=[Depends(require_admin_key)])
async def internal_checkpoint() -> dict:
    """Force a DuckDB WAL checkpoint so a clean shutdown preserves all writes.

    Called by dev-restart.sh before killing the process.
    """
    conn = get_write_conn()
    conn.execute("CHECKPOINT")
    return {"status": "ok"}


# ── Midday session endpoints ──────────────────────────────────────────────────


class MiddayActivity(BaseModel):
    """Machine-readable activity type; lifting uses the existing plan validator."""

    name: str
    kind: Literal["strength", "cardio", "mobility", "recovery"]
    duration_min: int = Field(gt=0, le=60)
    notes: str


class MiddaySessionSubmission(BaseModel):
    session_type: str  # 'workout' | 'recovery' | 'mixed'
    title: str
    duration_min: int = Field(gt=0, le=60)
    intensity: str  # 'high' | 'moderate' | 'low' | 'passive'
    activities: list[MiddayActivity]
    strength_plan: dict[str, Any] | None = None
    rationale: str
    performance_goal: str


_VALID_SESSION_TYPES = {"workout", "recovery", "mixed"}
_VALID_INTENSITIES = {"high", "moderate", "low", "passive"}


def _validate_midday(body: MiddaySessionSubmission, state: dict, conn: Any) -> None:
    """Enforce today's gates before persisting any midday recommendation."""
    from shc.ai.vault import valid_citation_filenames
    from shc.ai.workout_planner import _clinical_volume_cap, e1rm_by_exercise

    gates = state["gates"]
    order = {"passive": 0, "rest": 0, "low": 1, "moderate": 2, "high": 3}
    kinds = {a.kind for a in body.activities}
    active = bool(kinds - {"recovery"})
    if order[body.intensity] > order[gates["max_intensity"]]:
        raise GateViolation("Midday intensity exceeds today's DailyState gate")
    if active and (body.intensity == "passive" or gates["max_intensity"] == "rest"):
        raise GateViolation("Active exercise cannot be prescribed as passive recovery")
    if kinds & {"strength", "cardio"} and body.session_type == "recovery":
        raise GateViolation("Training activities require workout or mixed session_type")
    if gates["deload_required"] and ("strength" in kinds or order[body.intensity] > 1):
        raise GateViolation("Midday deload sessions must be low intensity without extra lifting")
    acwr = state["training_load"].get("acwr")
    if acwr is not None and acwr > 1.5 and (active or body.intensity != "passive"):
        raise GateViolation("ACWR > 1.5: midday must be passive recovery")
    if acwr is not None and acwr > 1.3 and ("strength" in kinds or order[body.intensity] > 1):
        raise GateViolation("ACWR > 1.3: midday must be low intensity without lifting")
    if "cardio" in kinds and (
        "legs" in gates.get("forbid_muscle_groups", [])
        or set(gates.get("forbid_muscles", [])) & {"quads", "hamstrings", "glutes", "calves"}
    ):
        raise GateViolation("Lower-body recovery gate blocks midday cardio")
    clinical_cap, clinical_reason = _clinical_volume_cap(conn)
    if (clinical_cap == 0 and active) or (clinical_cap is not None and body.intensity == "high"):
        raise GateViolation(f"Midday clinical restriction: {clinical_reason}")
    if "strength" not in kinds:
        if body.strength_plan is not None:
            raise ValueError("strength_plan requires a strength activity")
        return
    if body.strength_plan is None:
        raise ValueError("Strength activities require a structured strength_plan")
    recent = conn.execute(
        "SELECT DISTINCT ws.exercise, w.started_at > now() - INTERVAL '4 hours' "
        "FROM workouts w JOIN workout_sets ws ON ws.workout_id = w.id "
        "WHERE w.started_at::DATE = current_date AND NOT ws.is_warmup"
    ).fetchall()
    if any(row[1] for row in recent):
        raise GateViolation("Allow at least four hours between lifting sessions")
    if acwr is None or acwr > 1.3 or state["readiness"]["tier"] != "green":
        raise GateViolation("Midday lifting requires verified green readiness and ACWR ≤ 1.3")
    plan = body.strength_plan
    morning_groups = {_mg(row[0]) for row in recent}
    if any(
        _mg(ex.get("name", "")) in morning_groups
        for block in plan.get("blocks", [])
        for ex in block.get("exercises", [])
    ):
        raise GateViolation("Midday lifting must target different groups from today's earlier lift")
    if plan.get("recommendation", {}).get("intensity") != body.intensity:
        raise ValueError("strength_plan intensity must match the midday session")
    sets = sum(ex.get("sets", 0) for b in plan.get("blocks", []) for ex in b.get("exercises", []))
    if sets > 10:
        raise GateViolation("Midday lifting is capped at 10 working sets")
    validate_plan(
        plan,
        state=state,
        conn=conn,
        e1rm_ceilings=e1rm_by_exercise(conn, date.today()),
        allowed_citations=valid_citation_filenames(),
    )


@router.get("/midday/context")
async def midday_context() -> dict:
    """Return the prompt Rob pastes into Claude to generate a midday session recommendation."""
    conn = get_read_conn()
    try:
        from shc.ai.workout_planner import build_midday_context

        prompt = build_midday_context(conn)
    finally:
        conn.close()
    return {"prompt": prompt, "date": date.today().isoformat()}


@router.post("/midday/session", dependencies=[Depends(require_admin_key)])
async def submit_midday_session(body: MiddaySessionSubmission) -> dict:
    """Accept and persist a Claude-generated midday session recommendation."""
    if body.session_type not in _VALID_SESSION_TYPES:
        raise HTTPException(422, f"session_type must be one of {sorted(_VALID_SESSION_TYPES)}")
    if body.intensity not in _VALID_INTENSITIES:
        raise HTTPException(422, f"intensity must be one of {sorted(_VALID_INTENSITIES)}")
    if not body.activities:
        raise HTTPException(422, "activities list cannot be empty")
    total_min = sum(a.duration_min for a in body.activities)
    if total_min > body.duration_min:
        raise HTTPException(422, "Activity durations exceed the session duration")

    rec = {
        "title": body.title,
        "duration_min": body.duration_min,
        "intensity": body.intensity,
        "activities": [a.model_dump() for a in body.activities],
        "strength_plan": body.strength_plan,
        "rationale": body.rationale,
        "performance_goal": body.performance_goal,
    }
    async with write_ctx() as conn:
        try:
            _validate_midday(body, compute_daily_state(conn), conn)
        except GateViolation as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        conn.execute(
            """
            INSERT INTO midday_sessions (session_date, session_type, recommendation, source, generated_at)
            VALUES (current_date, $type, $rec, 'claude', now())
            ON CONFLICT (session_date) DO UPDATE SET
                session_type     = EXCLUDED.session_type,
                recommendation   = EXCLUDED.recommendation,
                source           = EXCLUDED.source,
                generated_at     = EXCLUDED.generated_at
            """,
            {"type": body.session_type, "rec": json.dumps(rec)},
        )
    return {"status": "ok", "date": date.today().isoformat()}


@router.get("/midday/session/today")
async def get_midday_session() -> dict:
    """Return today's midday session recommendation, or null if none generated yet."""
    conn = get_read_conn()
    try:
        row = conn.execute(
            "SELECT session_type, recommendation FROM midday_sessions WHERE session_date = current_date"
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return {"session": None}
    rec = json.loads(row[1]) if isinstance(row[1], str) else row[1]
    return {"session": {"session_type": row[0], **rec}}


@router.get("/whoop/stress")
def whoop_stress(days: int = Query(7, ge=1, le=30)) -> dict:
    """Stress curve + daily rollup from the private-API ingest.

    Returns the per-sample timeline for charting plus one row per day. Empty
    lists (not an error) when `shc whoop-private sync-metrics` has never run —
    the panel renders an explicit "not synced" state rather than a blank chart.
    """
    conn = get_read_conn()
    try:
        since = date.today() - timedelta(days=days)
        daily = [
            {
                "date": r[0].isoformat(),
                "score": r[1],
                "level": r[2],
                "high_pct": r[3],
            }
            for r in conn.execute(
                """
                SELECT date, stress_score, stress_level, stress_high_pct
                FROM whoop_private_daily
                WHERE date > ? AND stress_score IS NOT NULL
                ORDER BY date
                """,
                [since],
            ).fetchall()
        ]
        samples = [
            {"t": r[0].isoformat(), "value": r[1], "level": r[2]}
            for r in conn.execute(
                """
                SELECT sampled_at, value, level
                FROM whoop_stress_timeline
                WHERE date > ? AND value IS NOT NULL
                ORDER BY sampled_at
                """,
                [since],
            ).fetchall()
        ]
        return {"daily": daily, "samples": samples, "high_day_threshold": 0.15}
    finally:
        conn.close()


@router.get("/whoop/behavior-impact")
def whoop_behavior_impact() -> dict:
    """WHOOP's own server-side impact analysis (latest snapshot).

    `AUTOMATED` rows are metric-derived and populate without journal data;
    journal-derived rows need weeks of logging before WHOOP will score them.
    """
    conn = get_read_conn()
    try:
        latest = conn.execute("SELECT MAX(as_of) FROM whoop_behavior_impact").fetchone()
        if not latest or latest[0] is None:
            return {"as_of": None, "items": []}
        rows = conn.execute(
            """
            SELECT title, impact_pct, impact_style, tag_style, yes_count, no_count
            FROM whoop_behavior_impact
            WHERE as_of = ?
            ORDER BY impact_pct DESC NULLS LAST
            """,
            [latest[0]],
        ).fetchall()
        return {
            "as_of": latest[0].isoformat(),
            "items": [
                {
                    "title": r[0],
                    "impact_pct": r[1],
                    "style": r[2],
                    "tag": r[3],
                    "yes_count": r[4],
                    "no_count": r[5],
                }
                for r in rows
            ],
        }
    finally:
        conn.close()
