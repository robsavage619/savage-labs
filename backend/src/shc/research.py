from __future__ import annotations

"""The research team's shared machinery: a feature store, declarative
hypotheses that run without new code, a belief ledger, and a notebook.

A hypothesis is data. Its spec names an exposure feature and the two ranges
that define arms A and B, an outcome feature, a lag, a unit (day or week) and
covariates to adjust for. The runner estimates B − A by least squares, widens
the interval for day-to-day carryover, sizes the question by power, and folds
the result into the belief it was registered against. Every step is appended
to the notebook; nothing in it is edited or deleted.
"""

import hashlib
import json
import logging
import math
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import NormalDist, mean, pstdev

import duckdb
import numpy as np

from shc import places
from shc.selflab import _ADHERENCE, _ALPHA, _design_effect, _needed_per_arm
from shc.training.mesocycle import _CAPPED_E1RM, _MAX_E1RM_MEDIAN_DEVIATION
from shc.training.volume import _RPE_GATE, _STIMULATING

log = logging.getLogger(__name__)

_NORMAL = NormalDist()
# A question that can't answer within this many days at the current pace is
# underpowered: the value score discounts it and the methodologist should send
# it back for a stronger design.
MAX_DAYS_TO_ANSWER = 120
_MIN_PER_ARM = 10
# The lab audit used 10 sessions; n ** (1/3) is only 5 at a hundred rows.
_HAC_MIN_LAGS = 10
_PACE_WINDOW_DAYS = 90


# ── Feature store ───────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Feature:
    name: str
    label: str
    unit: str
    # 'morning': read on waking, keyed to the wake date (recovery, the night's
    # sleep). 'day': accumulated over the calendar day (strain, steps, lifting).
    timing: str
    source: str
    sql: str | None = None


def _q(sql: str) -> str:
    return sql.strip()


def _daily_total(metric: str) -> str:
    """Day total of a cumulative metric, summed from the highest-priority source.

    `v_daily_metrics.value_avg` averages a day's samples, which is right for a
    rate and wrong for a count. Several sources can write the same metric for the
    same day, so keep the one source per day that /body/steps trusts first:
    Apple intervals, then the HAE daily total, then anything else.
    """
    return (
        "WITH r AS (SELECT ts::DATE AS day, value_num, CASE WHEN external_id LIKE 'apple:%' THEN 1 "
        "WHEN external_id LIKE 'hae:%' THEN 2 ELSE 3 END AS prio FROM measurements "
        f"WHERE metric = '{metric}' AND value_num IS NOT NULL), "
        "b AS (SELECT day, MIN(prio) AS prio FROM r GROUP BY day) "
        "SELECT r.day, SUM(r.value_num) FROM r JOIN b ON r.day = b.day AND r.prio = b.prio GROUP BY r.day"
    )


FEATURES: dict[str, Feature] = {
    f.name: f
    for f in [
        Feature(
            "hrv_ms",
            "HRV",
            "ms",
            "morning",
            "WHOOP",
            _q("SELECT date, AVG(hrv) FROM recovery WHERE hrv > 0 GROUP BY date"),
        ),
        Feature("weekend", "Weekend day", "yes=1", "day", "calendar"),
        Feature("time_years", "Years since 2024 (linear trend)", "years", "day", "calendar"),
        Feature("stress_high_min", "High-stress minutes outside workouts", "min", "day", "WHOOP"),
        Feature("presleep_stress", "Stress in the 2 h before bed", "0-3", "morning", "WHOOP"),
        Feature("away_night", "Slept away from home", "yes=1", "morning", "location"),
        Feature("lnhrv_dev_pct", "HRV vs 28-day baseline (log)", "%", "morning", "WHOOP"),
        Feature("lnhrv_7d_pct", "7-day mean HRV vs baseline (log)", "%", "morning", "WHOOP"),
        Feature(
            "recovery_score",
            "Recovery score",
            "pts",
            "morning",
            "WHOOP",
            _q("SELECT date, AVG(score) FROM recovery WHERE score IS NOT NULL GROUP BY date"),
        ),
        Feature(
            "rhr_bpm",
            "Resting heart rate",
            "bpm",
            "morning",
            "WHOOP",
            _q("SELECT date, AVG(rhr) FROM recovery WHERE rhr > 0 GROUP BY date"),
        ),
        Feature(
            "skin_temp",
            "Skin temperature",
            "°C",
            "morning",
            "WHOOP",
            _q(
                "SELECT date, AVG(skin_temp) FROM recovery WHERE skin_temp IS NOT NULL GROUP BY date"
            ),
        ),
        Feature(
            "spo2_pct",
            "Overnight SpO₂",
            "%",
            "morning",
            "WHOOP",
            _q("SELECT date, AVG(spo2) FROM recovery WHERE spo2 > 0 GROUP BY date"),
        ),
        Feature(
            "sleep_hours",
            "Time in bed, main sleep",
            "h",
            "morning",
            "WHOOP",
            _q(
                "SELECT night_date, MAX(epoch(ts_out - ts_in)) / 3600.0 FROM sleep "
                "WHERE NOT COALESCE(is_nap, FALSE) GROUP BY night_date"
            ),
        ),
        Feature(
            "sleep_consistency_pct",
            "Sleep consistency",
            "%",
            "morning",
            "WHOOP",
            _q(
                "SELECT night_date, MAX(sleep_consistency_pct) FROM sleep WHERE NOT COALESCE(is_nap, FALSE) GROUP BY night_date"
            ),
        ),
        Feature(
            "deep_sleep_min",
            "Deep sleep",
            "min",
            "morning",
            "WHOOP",
            _q(
                "SELECT night_date, MAX(sws_min) FROM sleep WHERE NOT COALESCE(is_nap, FALSE) GROUP BY night_date"
            ),
        ),
        Feature(
            "rem_sleep_min",
            "REM sleep",
            "min",
            "morning",
            "WHOOP",
            _q(
                "SELECT night_date, MAX(rem_min) FROM sleep WHERE NOT COALESCE(is_nap, FALSE) GROUP BY night_date"
            ),
        ),
        Feature(
            "sleep_disturbances",
            "Sleep disturbances",
            "count",
            "morning",
            "WHOOP",
            _q(
                "SELECT night_date, MAX(disturbance_count) FROM sleep WHERE NOT COALESCE(is_nap, FALSE) GROUP BY night_date"
            ),
        ),
        Feature(
            "resp_rate",
            "Breathing rate asleep",
            "breaths/min",
            "morning",
            "WHOOP",
            _q(
                "SELECT night_date, MAX(respiratory_rate) FROM sleep WHERE NOT COALESCE(is_nap, FALSE) GROUP BY night_date"
            ),
        ),
        Feature(
            "strain",
            "Day strain",
            "0-21",
            "day",
            "WHOOP",
            _q("SELECT date, MAX(strain) FROM daily_cycle GROUP BY date"),
        ),
        Feature(
            "lift_tonnes",
            "Lifting tonnage",
            "t",
            "day",
            "Hevy",
            _q("SELECT date, hevy_tonnes FROM v_daily_load WHERE hevy_tonnes > 0"),
        ),
        Feature(
            "working_sets",
            "Working sets",
            "sets",
            "day",
            "Hevy",
            _q(
                "SELECT day_d, COUNT(*) FROM workout_sets_dedup WHERE NOT COALESCE(is_warmup, FALSE) GROUP BY day_d"
            ),
        ),
        Feature(
            "pickleball_min",
            "Pickleball",
            "min",
            "day",
            "WHOOP",
            _q(
                "SELECT date, SUM(duration_min) FROM cardio_sessions WHERE lower(modality) LIKE '%pickle%' GROUP BY date"
            ),
        ),
        Feature(
            "steps",
            "Steps",
            "steps",
            "day",
            "Apple Health",
            _daily_total("step_count"),
        ),
        Feature(
            "daylight_min",
            "Time in daylight",
            "min",
            "day",
            "Apple Health",
            _daily_total("time_in_daylight_min"),
        ),
        Feature(
            "walking_speed",
            "Walking speed",
            "m/s",
            "day",
            "Apple Health",
            _q(
                "SELECT date, MAX(value_avg) FROM v_daily_metrics WHERE metric = 'walking_speed_m_s' GROUP BY date"
            ),
        ),
        # Goal outcomes: what the training is for, not just how recovered it left you.
        Feature(
            "strength_emphasis_pct14",
            "Emphasis-muscle strength, 14 days vs prior 14",
            "%",
            "day",
            "Hevy",
        ),
        Feature(
            "session_quality",
            "Plan completion",
            "%",
            "day",
            "plan adherence",
            # A session that diverged from its plan can read past 100% (the
            # comparison picks the wrong day); doing more than planned is full
            # completion, not extra quality.
            _q(
                "SELECT date, LEAST(MAX(completion_pct), 100) FROM plan_adherence "
                "WHERE completion_pct IS NOT NULL GROUP BY date"
            ),
        ),
        # Pounds, the unit the subject reads weight in; the store keeps kilograms.
        Feature(
            "body_mass_lb",
            "Body weight",
            "lb",
            "day",
            "Check-in + Apple Health",
            # Manual weigh-ins land in daily_checkin, not measurements; read both,
            # as /body does, or a logged weight never reaches the lab.
            _q(
                "SELECT day, AVG(kg) * 2.20462 FROM ("
                "SELECT date AS day, body_weight_kg AS kg FROM daily_checkin "
                "WHERE body_weight_kg IS NOT NULL UNION ALL "
                "SELECT date AS day, value_avg AS kg FROM v_daily_metrics "
                "WHERE metric = 'body_mass_kg') GROUP BY day"
            ),
        ),
        Feature(
            "body_mass_7d",
            "Body weight, 7-day mean of weigh-ins",
            "lb",
            "day",
            "Check-in + Apple Health",
        ),
        Feature(
            "vo2_max",
            "VO₂ max estimate",
            "mL/kg/min",
            "day",
            "WHOOP, else Apple Health",
            # One estimator at a time: WHOOP's weekly series once it has any rows,
            # Apple Watch's before that. Blending them would put a step in the
            # series where the source changed.
            _q(
                "SELECT date, AVG(value_avg) FROM v_daily_metrics WHERE metric = "
                "CASE WHEN EXISTS (SELECT 1 FROM measurements WHERE metric = 'vo2_max_whoop') "
                "THEN 'vo2_max_whoop' ELSE 'vo2_max' END GROUP BY date"
            ),
        ),
        Feature(
            "sleep_efficiency_pct",
            "Sleep efficiency",
            "%",
            "morning",
            "WHOOP",
            _q(
                "SELECT night_date, MAX(sleep_efficiency_pct) FROM sleep WHERE NOT COALESCE(is_nap, FALSE) GROUP BY night_date"
            ),
        ),
    ]
}

# Per-muscle features, named `<kind>:<muscle>` for any muscle in exercise_muscle.
_PARAMETRIC: dict[str, tuple[str, str, str, str]] = {
    "e1rm_pct14": ("Strength, 14 days vs prior 14", "%", "day", "Hevy"),
    "sets": ("Working sets", "sets", "day", "Hevy"),
}
# What each outcome is for, in the subject's goal order for the stored training
# phase. Build: muscle, then body composition, then aerobic fitness. Cut: body
# composition first, muscle (retention) second. Recovery signals are mediators.
GOAL_WEIGHTS = {"muscle": 1.0, "body": 0.85, "cardio": 0.7, "recovery": 0.6}
_CUT_GOAL_WEIGHTS = {"body": 1.0, "muscle": 0.85, "cardio": 0.75, "recovery": 0.6}
_OTHER_GOAL_WEIGHT = 0.5
_GOAL_TEXT = {
    "build": (
        "Build muscle first ({emphasis} emphasis), then body recomposition at "
        "maintenance, then aerobic fitness."
    ),
    "cut": (
        "Lose fat while keeping muscle: body composition first (bodyweight trend, "
        "0.5-1.0%/week), muscle retention second (main-lift strength holding; "
        "{emphasis} emphasis), then aerobic fitness."
    ),
}


def goal_weights(conn: duckdb.DuckDBPyConnection) -> dict[str, float]:
    """Goal weights for Rob's stored training phase."""
    from shc.training.autoregulation import load_training_phase

    return _CUT_GOAL_WEIGHTS if load_training_phase(conn) == "cut" else GOAL_WEIGHTS


def _emphasis_muscles(conn: duckdb.DuckDBPyConnection) -> list[str]:
    from shc.training.autoregulation import _resolve_emphasis, load_emphasis

    return sorted(_resolve_emphasis(load_emphasis(conn)))


_GOALS = {
    "muscle": {"strength_emphasis_pct14", "session_quality", "working_sets", "lift_tonnes"},
    "body": {"body_mass_lb", "body_mass_7d"},
    "cardio": {"vo2_max", "walking_speed"},
    "recovery": {
        "hrv_ms",
        "lnhrv_dev_pct",
        "lnhrv_7d_pct",
        "recovery_score",
        "rhr_bpm",
        "skin_temp",
        "spo2_pct",
        "sleep_hours",
        "sleep_consistency_pct",
        "sleep_efficiency_pct",
        "deep_sleep_min",
        "rem_sleep_min",
        "sleep_disturbances",
        "resp_rate",
    },
}


def goal_of(name: str, conn: duckdb.DuckDBPyConnection | None = None) -> str:
    """The goal category an outcome feature serves: muscle, body, cardio, recovery or other.

    A custom measurement declares its own goal, so it needs `conn` to look it up.
    """
    if name.partition(":")[0] in _PARAMETRIC:
        return "muscle"
    if name.startswith("custom:") and conn is not None:
        from shc import research_team

        return research_team.custom_goal(conn, name) or "other"
    return next((g for g, names in _GOALS.items() if name in names), "other")


def feature(name: str) -> Feature | None:
    """A feature's metadata, including the parametric and journal families."""
    if name in FEATURES:
        return FEATURES[name]
    kind, _, arg = name.partition(":")
    if kind in _PARAMETRIC and arg:
        label, unit, timing, source = _PARAMETRIC[kind]
        return Feature(name, f"{label}: {arg.replace('_', ' ')}", unit, timing, source)
    if kind == "journal" and arg:
        return Feature(name, arg, "yes=1", "day", "WHOOP journal")
    return None


# Days a feature counts as zero when absent rather than missing: no pickleball
# session that day means zero minutes, not an unknown.
_ZERO_FILL = {"pickleball_min", "working_sets", "lift_tonnes"}
_ZERO_FILL_KINDS = ("sets:",)


def _rows(
    conn: duckdb.DuckDBPyConnection, sql: str, params: list | None = None
) -> dict[date, float]:
    out: dict[date, float] = {}
    for d, v in conn.execute(sql, params or []).fetchall():
        if d is not None and v is not None:
            out[d if isinstance(d, date) else date.fromisoformat(str(d)[:10])] = float(v)
    return out


def _lnhrv_dev(conn: duckdb.DuckDBPyConnection) -> dict[date, float]:
    """100 × (ln HRV − mean ln HRV over the previous 28 days): roughly % change."""
    hrv = series(conn, "hrv_ms")
    days = sorted(hrv)
    out: dict[date, float] = {}
    for d in days:
        prior = [math.log(hrv[x]) for x in days if d - timedelta(days=28) <= x < d]
        if len(prior) >= 14:
            out[d] = 100 * (math.log(hrv[d]) - mean(prior))
    return out


def _rolling7(base: dict[date, float], min_n: int = 4) -> dict[date, float]:
    out: dict[date, float] = {}
    for d in base:
        w = [base[d - timedelta(days=k)] for k in range(7) if d - timedelta(days=k) in base]
        if len(w) >= min_n:
            out[d] = mean(w)
    return out


def _muscle_sets(conn: duckdb.DuckDBPyConnection, muscle: str) -> dict[date, float]:
    """Working sets a day that credit `muscle`, primary or secondary, at 1.0 each.

    Same set filter as training/volume.py: warm-ups out, loaded, inside the
    stimulating rep window, and past the RPE gate.
    """
    return _rows(
        conn,
        "SELECT ws.day_d, COUNT(*) FROM workout_sets_dedup ws "
        "JOIN exercise_muscle m ON m.exercise_name = ws.exercise "
        f"WHERE m.muscle = ? AND NOT COALESCE(ws.is_warmup, FALSE) AND ws.weight_kg > 0 "
        f"AND {_STIMULATING} AND {_RPE_GATE} GROUP BY ws.day_d",
        [muscle],
    )


def _e1rm_pct14(conn: duckdb.DuckDBPyConnection, muscle: str) -> dict[date, float]:
    """Per day: mean over the lifts crediting `muscle` of 100 × (mean session-best
    e1RM in the trailing 14 days / the same in the 14 before − 1).

    Uses the engine's e1RM (Epley over RIR-adjusted, capped reps on per-hand
    load, Hevy working sets only). A lift counts only when trained in both
    windows, and a change past ±35% is a logging artifact, not physiology.
    Lifts are compared to themselves, so a heavy lift skipped for a fortnight
    can't read as lost strength.
    """
    return _rows(
        conn,
        f"""
        WITH d AS (
            SELECT ws.exercise AS ex, ws.day_d AS day, MAX({_CAPPED_E1RM}) AS e
            FROM workout_sets_dedup ws JOIN exercise_muscle m ON m.exercise_name = ws.exercise
            WHERE m.muscle = ? AND ws.weight_kg > 0 AND ws.reps > 0 AND ws.source = 'hevy'
              AND NOT COALESCE(ws.is_warmup, FALSE)
            GROUP BY 1, 2
        ),
        spine AS (
            SELECT ex, UNNEST(generate_series(lo, LEAST(hi + 13, current_date), INTERVAL 1 DAY))::DATE AS day
            FROM (SELECT ex, MIN(day) AS lo, MAX(day) AS hi FROM d GROUP BY ex)
        ),
        w AS (
            SELECT s.day,
                   -- Mean of session bests, not the window's best: a busier
                   -- fortnight has more chances at a high max and read as
                   -- stronger from opportunity alone (found by the hypertrophy
                   -- specialist: r = +0.20 to +0.29 with the session-count ratio).
                   AVG(d.e) OVER (PARTITION BY s.ex ORDER BY s.day
                                  ROWS BETWEEN 13 PRECEDING AND CURRENT ROW) AS cur,
                   AVG(d.e) OVER (PARTITION BY s.ex ORDER BY s.day
                                  ROWS BETWEEN 27 PRECEDING AND 14 PRECEDING) AS prev
            FROM spine s LEFT JOIN d ON d.ex = s.ex AND d.day = s.day
        )
        SELECT day, AVG(100 * (cur / prev - 1)) FROM w
        WHERE cur IS NOT NULL AND prev IS NOT NULL AND abs(cur / prev - 1) <= ?
        GROUP BY day
        """,
        [muscle, _MAX_E1RM_MEDIAN_DEVIATION],
    )


def _emphasis(conn: duckdb.DuckDBPyConnection) -> dict[date, float]:
    """Mean 14-day strength change across the emphasis muscles, on days all of them have one."""
    parts = [_e1rm_pct14(conn, m) for m in _emphasis_muscles(conn)]
    days = set.intersection(*(set(p) for p in parts))
    return {d: mean(p[d] for p in parts) for d in days}


def _weekend(_conn: duckdb.DuckDBPyConnection) -> dict[date, float]:
    """1 on Saturday and Sunday: the confounder for anything that happens on weekends."""
    d, end, out = date(2014, 1, 1), date.today() + timedelta(days=1), {}
    while d <= end:
        out[d] = 1.0 if d.weekday() >= 5 else 0.0
        d += timedelta(days=1)
    return out


_CALENDAR = {"weekend", "time_years"}


def _time_years(_conn: duckdb.DuckDBPyConnection) -> dict[date, float]:
    """Years since 2024-01-01: adjusting for it removes a steady drift across
    eras (a season of regular play, a training block) from an arm contrast."""
    d, end, out = date(2014, 1, 1), date.today() + timedelta(days=1), {}
    while d <= end:
        out[d] = (d - date(2024, 1, 1)).days / 365.25
        d += timedelta(days=1)
    return out


_FULL_STRESS_DAY = 900  # samples: a day with under 15 h of readings is a gap, not a calm day


def _stress_high_min(conn: duckdb.DuckDBPyConnection) -> dict[date, float]:
    """Minutes of HIGH stress per day, leaving out workouts and the half hour after."""
    return _rows(
        conn,
        "WITH s AS (SELECT t.date, upper(t.level) = 'HIGH' AS hi, EXISTS ("
        "SELECT 1 FROM workouts w WHERE t.sampled_at >= w.started_at "
        "AND t.sampled_at < COALESCE(w.ended_at, w.started_at) + INTERVAL 30 MINUTE) AS ex "
        "FROM whoop_stress_timeline t) "
        "SELECT date, count(*) FILTER (WHERE hi AND NOT ex) FROM s GROUP BY date "
        f"HAVING count(*) >= {_FULL_STRESS_DAY}",
    )


def _presleep_stress(conn: duckdb.DuckDBPyConnection) -> dict[date, float]:
    """Mean stress in the two hours before the night's main sleep began, keyed to the wake date."""
    return _rows(
        conn,
        "WITH n AS (SELECT night_date, arg_max(ts_in, epoch(ts_out - ts_in)) AS ts_in FROM sleep "
        "WHERE NOT COALESCE(is_nap, FALSE) AND ts_in IS NOT NULL AND ts_out IS NOT NULL "
        "GROUP BY night_date) "
        "SELECT n.night_date, avg(t.value) FROM n JOIN whoop_stress_timeline t "
        "ON t.sampled_at >= n.ts_in - INTERVAL 2 HOUR AND t.sampled_at < n.ts_in "
        "WHERE t.value IS NOT NULL GROUP BY n.night_date HAVING count(*) >= 60",
    )


_DERIVED: dict[str, Callable[[duckdb.DuckDBPyConnection], dict[date, float]]] = {
    "weekend": _weekend,
    "time_years": _time_years,
    "lnhrv_dev_pct": _lnhrv_dev,
    "lnhrv_7d_pct": lambda c: _rolling7(series(c, "lnhrv_dev_pct")),
    "body_mass_7d": lambda c: _rolling7(series(c, "body_mass_lb"), min_n=1),
    "strength_emphasis_pct14": _emphasis,
    "stress_high_min": _stress_high_min,
    "presleep_stress": _presleep_stress,
    "away_night": places.away_nights,
}
_DERIVED_KINDS: dict[str, Callable[[duckdb.DuckDBPyConnection, str], dict[date, float]]] = {
    "sets": _muscle_sets,
    "e1rm_pct14": _e1rm_pct14,
    "place": lambda c, arg: places.daily_hours(c, int(arg)),
}


def series(conn: duckdb.DuckDBPyConnection, name: str) -> dict[date, float]:
    """One feature as {date: value}. `journal:<question>` gives 1/0 per answered day."""
    if name.startswith("journal:"):
        return _rows(
            conn,
            "SELECT date, MAX(CASE WHEN answered_yes THEN 1 ELSE 0 END) FROM whoop_journal "
            "WHERE question = ? GROUP BY date",
            [name.partition(":")[2]],
        )
    if name.startswith("custom:"):
        # Imported here: research_team imports this module for note() and goal_of().
        from shc import research_team

        return research_team.custom_series(conn, name)
    if name in _DERIVED:
        return _DERIVED[name](conn)
    kind, _, arg = name.partition(":")
    if kind in _DERIVED_KINDS and arg:
        return _DERIVED_KINDS[kind](conn, arg)
    f = FEATURES.get(name)
    if f is None or f.sql is None:
        raise ValueError(f"unknown feature {name!r}")
    return _rows(conn, f.sql)


def known_feature(conn: duckdb.DuckDBPyConnection, name: str) -> bool:
    if name.startswith("journal:"):
        q = name.partition(":")[2]
        return (
            conn.execute("SELECT 1 FROM whoop_journal WHERE question = ? LIMIT 1", [q]).fetchone()
            is not None
        )
    kind, _, arg = name.partition(":")
    if kind in _PARAMETRIC:
        return bool(arg) and arg in _muscles(conn)
    if kind == "custom":
        from shc import research_team

        return research_team.known_custom(conn, name)
    return name in FEATURES


def _muscles(conn: duckdb.DuckDBPyConnection) -> list[str]:
    return [
        m
        for (m,) in conn.execute(
            "SELECT DISTINCT muscle FROM exercise_muscle ORDER BY 1"
        ).fetchall()
    ]


def _entry(f: Feature, s: dict[date, float], today: date) -> dict:
    recent = sum(1 for d in s if d >= today - timedelta(days=90))
    last = max(s) if s else None
    return {
        "name": f.name,
        "label": f.label,
        "unit": f.unit,
        "timing": f.timing,
        "source": f.source,
        "goal": goal_of(f.name),
        "first": str(min(s)) if s else None,
        "last": str(last) if last else None,
        "days": len(s),
        "coverage_90d_pct": round(100 * recent / 90),
        "stale": last is None or (today - last).days > 7,
    }


def dictionary(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """The data dictionary agents read before proposing: what exists, how much, how fresh.

    Per-muscle features are listed only for muscles that have data.
    """
    today = date.today()
    out = [_entry(f, series(conn, f.name), today) for f in FEATURES.values()]
    for m in _muscles(conn):
        for kind in _PARAMETRIC:
            name = f"{kind}:{m}"
            s = series(conn, name)
            f = feature(name)
            if s and f is not None:
                out.append(_entry(f, s, today))
    for q, n, first, last in conn.execute(
        "SELECT question, COUNT(DISTINCT date), MIN(date), MAX(date) FROM whoop_journal GROUP BY question ORDER BY 2 DESC"
    ).fetchall():
        out.append(
            {
                "name": f"journal:{q}",
                "label": q,
                "unit": "yes=1",
                "timing": "day",
                "source": "WHOOP journal",
                "goal": "other",
                "first": str(first),
                "last": str(last),
                "days": n,
                "coverage_90d_pct": 0 if (today - last).days > 90 else None,
                "stale": (today - last).days > 7,
            }
        )
    from shc import research_team

    out.extend(research_team.custom_dictionary(conn))
    return out


# ── Hypothesis specs ────────────────────────────────────────────────────────


class SpecError(ValueError):
    """A hypothesis spec the runner cannot execute."""


def _in(v: float, rng: dict) -> bool:
    lo, hi = rng.get("min"), rng.get("max")
    return (lo is None or v >= lo) and (hi is None or v < hi)


def validate_spec(conn: duckdb.DuckDBPyConnection, spec: dict) -> None:
    exp = spec.get("exposure") or {}
    for key in ("feature",):
        if not exp.get(key):
            raise SpecError("exposure.feature is required")
    for arm in ("a", "b"):
        rng = exp.get(arm)
        if not isinstance(rng, dict) or (rng.get("min") is None and rng.get("max") is None):
            raise SpecError(f"exposure.{arm} needs a min and/or max")
    a, b = exp["a"], exp["b"]
    # Arms must not overlap, or a day could sit in both.
    a_hi = a.get("max") if a.get("max") is not None else math.inf
    b_lo = b.get("min") if b.get("min") is not None else -math.inf
    b_hi = b.get("max") if b.get("max") is not None else math.inf
    a_lo = a.get("min") if a.get("min") is not None else -math.inf
    if not (a_hi <= b_lo or b_hi <= a_lo):
        raise SpecError("exposure.a and exposure.b overlap")
    adjust = spec.get("adjust", [])
    if not isinstance(adjust, list) or not all(isinstance(a, str) for a in adjust):
        raise SpecError("adjust must be a list of feature names, read on the exposure date")
    names = [exp["feature"], spec.get("outcome", ""), *adjust]
    for n in names:
        if not n or not known_feature(conn, n):
            raise SpecError(f"unknown feature {n!r}; see /api/research/features")
    if spec.get("unit", "day") not in ("day", "week"):
        raise SpecError("unit must be 'day' or 'week'")
    if spec.get("expected_sign") not in ("+", "-"):
        raise SpecError("expected_sign must be '+' or '-' (the predicted sign of B − A)")
    if not isinstance(spec.get("min_effect"), int | float) or spec["min_effect"] <= 0:
        raise SpecError("min_effect must be a positive number in the outcome's units")
    if not isinstance(spec.get("lag", 1), int) or not 0 <= spec.get("lag", 1) <= 14:
        raise SpecError("lag must be an integer from 0 to 14")
    if "start_date" in spec:
        try:
            date.fromisoformat(str(spec["start_date"]))
        except ValueError as exc:
            raise SpecError("start_date must be an ISO date (YYYY-MM-DD)") from exc


def _weekly(s: dict[date, float]) -> dict[date, float]:
    by: dict[date, list[float]] = {}
    for d, v in s.items():
        by.setdefault(d - timedelta(days=d.weekday()), []).append(v)
    return {wk: mean(vs) for wk, vs in by.items() if len(vs) >= 4}


def _fill_zero(name: str, s: dict[date, float], span: tuple[date, date]) -> dict[date, float]:
    if name not in _ZERO_FILL and not name.startswith(_ZERO_FILL_KINDS):
        return s
    d, out = span[0], dict(s)
    while d <= span[1]:
        out.setdefault(d, 0.0)
        d += timedelta(days=1)
    return out


def estimate(
    conn: duckdb.DuckDBPyConnection,
    spec: dict,
    today: date | None = None,
    registered: date | None = None,
    z: float = 1.96,
    cap_per_arm: int | None = None,
) -> dict:
    """Run a spec on current data: B − A adjusted for covariates, with a
    carryover-widened range (95% unless `z` says otherwise), a verdict, and a
    power estimate.

    Args:
        conn: Database connection.
        spec: The hypothesis spec.
        today: The last date the estimate may see; defaults to the real date.
        registered: When the question was registered. Only later days count
            toward ``power.days_to_confirm``; a draft has none, so it defaults
            to ``today``.
        z: Half-width of the range in standard errors; a sequential look
            passes a stricter bound.
        cap_per_arm: Keep only the first this-many days of each arm, so a look
            at a planned size reads the same days however late it is run.

    Returns:
        Arm sizes and means, effect, range, verdict, power and a summary line.
    """
    today = today or date.today()
    unit = spec.get("unit", "day")
    lag = int(spec.get("lag", 1))
    window = int(spec.get("window_days", 730))
    start = today - timedelta(days=window)
    # A fixed start keeps one era in scope as the days pass; window_days slides.
    if "start_date" in spec:
        start = max(start, date.fromisoformat(str(spec["start_date"])))
    span = (start, today)
    exp_name, out_name = spec["exposure"]["feature"], spec["outcome"]
    adj = list(spec.get("adjust", []))
    raw = {n: _fill_zero(n, series(conn, n), span) for n in {exp_name, out_name, *adj}}
    step = timedelta(days=7 if unit == "week" else 1)
    if unit == "week":
        raw = {n: _weekly(s) for n, s in raw.items()}

    rows: list[tuple[date, int, float, list[float]]] = []
    last_day = step - timedelta(days=1)  # a week-unit outcome spans seven mornings
    for d, x in raw[exp_name].items():
        # Nothing after `today` may enter: a backtest dated in the past must not
        # see the mornings it is about to be scored on.
        if d < start or d + lag * step + last_day > today:
            continue
        arm = 0 if _in(x, spec["exposure"]["a"]) else 1 if _in(x, spec["exposure"]["b"]) else None
        y = raw[out_name].get(d + lag * step)
        covs = [raw[c].get(d) for c in adj]
        if arm is None or y is None or any(c is None for c in covs):
            continue
        rows.append((d, arm, y, [float(c) for c in covs if c is not None]))
    rows.sort()
    if cap_per_arm is not None:
        taken = [0, 0]
        kept = []
        for r in rows:
            if taken[r[1]] < cap_per_arm:
                kept.append(r)
                taken[r[1]] += 1
        rows = kept
    n_a = sum(1 for r in rows if r[1] == 0)
    n_b = len(rows) - n_a
    ya = [r[2] for r in rows if r[1] == 0]
    yb = [r[2] for r in rows if r[1] == 1]
    base = {
        "n_a": n_a,
        "n_b": n_b,
        "unit": unit,
        # Raw (unadjusted) outcome means per arm: what a plain reading of the data says.
        "mean_a": round(mean(ya), 3) if ya else None,
        "mean_b": round(mean(yb), 3) if yb else None,
    }
    if n_a < _MIN_PER_ARM or n_b < _MIN_PER_ARM:
        return base | {
            "verdict": "insufficient",
            "effect": None,
            "se": None,
            "ci_low": None,
            "ci_high": None,
            "p": None,
            "design_effect": None,
            "power": None,
            "summary": f"{n_a} A and {n_b} B {unit}s with an outcome; need {_MIN_PER_ARM} of each.",
        }

    X = np.array([[1.0, float(r[1]), *r[3]] for r in rows])
    y = np.array([r[2] for r in rows])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    dof = max(len(y) - X.shape[1], 1)
    sigma2 = float(resid @ resid) / dof
    cov = sigma2 * np.linalg.pinv(X.T @ X)
    de = _hac_design_effect(X, resid, float(cov[1, 1]), dof)
    effect = float(beta[1])
    se = math.sqrt(float(cov[1, 1]) * de)
    ci = (effect - z * se, effect + z * se)
    p = 2 * (1 - _NORMAL.cdf(abs(effect) / se)) if se > 0 else 1.0
    m = float(spec["min_effect"])
    # Read the range in the predicted direction, so one rule serves both signs.
    lo, hi = ci if spec["expected_sign"] == "+" else (-ci[1], -ci[0])
    if hi < 0:
        verdict = "against"
    elif hi < m:
        verdict = "ruled_out"
    elif lo >= m:
        verdict = "supported"
    elif lo > 0:
        # Real and the right way round, but the question asked for at least m.
        verdict = "direction"
    else:
        verdict = "inconclusive"
    power = _power(rows, math.sqrt(sigma2), m, de, today, unit, registered or today)
    out_f = feature(out_name)
    unit_label = out_f.unit if out_f else ""
    return base | {
        "verdict": verdict,
        "effect": round(effect, 3),
        "se": round(se, 3),
        "ci_low": round(ci[0], 3),
        "ci_high": round(ci[1], 3),
        "p": round(p, 4),
        "design_effect": round(de, 2),
        "power": power,
        "summary": (
            f"B − A = {effect:+.2f} {unit_label} ({'95%' if z == 1.96 else f'±{z:g} se'} {ci[0]:+.2f} to {ci[1]:+.2f}), "
            f"{n_a} A / {n_b} B {unit}s, adjusted for {', '.join(adj) or 'nothing'}. → {verdict}"
        ),
    }


def _hac_design_effect(X: np.ndarray, resid: np.ndarray, ols_var: float, dof: int) -> float:
    """Variance inflation of the arm coefficient under Newey-West errors.

    Rows are taken in observation order, so a regime that lasts weeks (or an
    arm that runs in blocks) shows up as residual autocorrelation the classical
    variance ignores. Uses a Bartlett kernel with a lag of
    ``max(_HAC_MIN_LAGS, round(n ** (1/3)))``, capped at a quarter of the rows.

    Args:
        X: Design matrix; column 1 is the arm indicator.
        resid: OLS residuals, one per row of ``X``.
        ols_var: Classical OLS variance of the arm coefficient.
        dof: Residual degrees of freedom the classical variance used.

    Returns:
        Robust variance over classical variance, never below 1.0.
    """
    n = len(resid)
    if ols_var <= 0 or n < 12:
        return 1.0
    lags = min(max(_HAC_MIN_LAGS, round(n ** (1 / 3))), n // 4)
    u = X * resid[:, None]
    S = u.T @ u
    for k in range(1, lags + 1):
        g = u[k:].T @ u[:-k]
        S += (1 - k / (lags + 1)) * (g + g.T)
    bread = np.linalg.pinv(X.T @ X)
    robust = float((bread @ S @ bread)[1, 1]) * n / dof
    return max(robust / ols_var, 1.0)


# Two planned looks at the days since registration, each arm at half and at the
# full planned size, with O'Brien-Fleming bounds so the pair keeps a two-sided
# 5% error however many nights the question is re-run.
_LOOK_Z = (2.797, 1.977)
_NEEDED_FOR = (
    "n per arm to detect an effect of min_effect against zero at the lab's alpha and 80% power, "
    "enough for a 'direction' call; a 'supported' call needs the whole 95% range above "
    "min_effect, which takes an effect larger than min_effect"
)


def _looks(needed: int) -> list[tuple[int, float]]:
    """The planned (days per arm, bound in standard errors) looks for a question."""
    full = max(needed, _MIN_PER_ARM)
    half = max(math.ceil(needed / 2), _MIN_PER_ARM)
    if half >= full:
        return [(full, 1.96)]
    return [(half, _LOOK_Z[0]), (full, _LOOK_Z[1])]


def _power(
    rows: list, sd: float, min_effect: float, de: float, today: date, unit: str, since: date
) -> dict:
    """Days per arm needed to see ``min_effect``, and the wait at the current pace.

    ``days_to_answer`` counts every day in the arms: when they are big enough
    to rule the effect out. ``days_to_confirm`` counts only days after
    ``since`` (the registration date), the only ones a favourable verdict may
    rest on, and ``days_to_next_look`` is the wait to the next planned look.
    """
    needed = _needed_per_arm(sd, min_effect, de)
    recent = today - timedelta(days=_PACE_WINDOW_DAYS)
    per_day = 7 if unit == "week" else 1

    def have(arm: int, after: date | None) -> int:
        return sum(1 for r in rows if r[1] == arm and (after is None or r[0] > after))

    def wait(after: date | None, need: int) -> int | None:
        waits = []
        for arm in (0, 1):
            pace = sum(1 for r in rows if r[1] == arm and r[0] >= recent) / (
                _PACE_WINDOW_DAYS / per_day
            )
            if need <= have(arm, after):
                waits.append(0)
            elif pace > 0:
                waits.append(math.ceil((need - have(arm, after)) / pace) * per_day)
            else:
                return None
        return max(waits)

    looks = _looks(needed)
    seen = min(have(0, since), have(1, since))
    nxt = next((n for n, _ in looks if n > seen), None)
    return {
        "needed_per_arm": needed,
        "needed_for": _NEEDED_FOR,
        "looks": [{"per_arm": n, "z": z} for n, z in looks],
        "next_look_per_arm": nxt,
        "days_to_next_look": None if nxt is None else wait(since, nxt),
        "days_to_answer": wait(None, needed),
        "days_to_confirm": wait(since, needed),
        "outcome_sd": round(sd, 3),
    }


# ── Persistence: hypotheses, results, beliefs, notebook ─────────────────────


def note(
    conn: duckdb.DuckDBPyConnection,
    author: str,
    kind: str,
    title: str,
    body: str = "",
    ref: str | None = None,
    data: dict | None = None,
) -> str:
    """Append to the lab notebook. Entries are never updated or deleted."""
    nid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO research_notebook (id, author, kind, ref, title, body, data) VALUES (?, ?, ?, ?, ?, ?, ?)",
        [nid, author, kind, ref, title, body, json.dumps(data) if data is not None else None],
    )
    return nid


def add_belief(
    conn: duckdb.DuckDBPyConnection,
    claim: str,
    outcome: str,
    prior_mean: float,
    prior_sd: float,
    prior_source: str,
    decision: str | None,
    author: str,
    unit: str | None = None,
) -> str:
    """Record a belief about an outcome, its literature prior and the unit it is in.

    Args:
        conn: Open DuckDB connection.
        claim: The belief in plain words.
        outcome: Outcome feature the belief is about.
        prior_mean: Prior mean effect, in the outcome's unit.
        prior_sd: Prior standard deviation; must be positive.
        prior_source: Citation for the prior.
        decision: What the engine would change on an answer, if anything.
        author: Who wrote it.
        unit: The effect's unit; taken from the outcome feature when omitted.

    Returns:
        The new belief's id.

    Raises:
        SpecError: If prior_sd is not positive.
    """
    if prior_sd <= 0:
        raise SpecError("prior_sd must be positive")
    unit = unit or _unit_of(outcome)
    bid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO research_beliefs (id, claim, outcome, prior_mean, prior_sd, prior_source, "
        "post_mean, post_sd, decision, unit) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            bid,
            claim,
            outcome,
            prior_mean,
            prior_sd,
            prior_source,
            prior_mean,
            prior_sd,
            decision,
            unit,
        ],
    )
    note(
        conn,
        author,
        "belief",
        f"New belief: {claim}",
        f"Prior {prior_mean:+g} ± {prior_sd:g}{f' {unit}' if unit else ''} from {prior_source}.",
        ref=bid,
    )
    return bid


def _unit_of(outcome: str) -> str | None:
    f = feature(outcome)
    return f.unit if f else None


_NICE = (1, 1.5, 2, 3, 5, 7.5, 10)


def _scale(b: dict) -> float:
    """Symmetric display half-range that holds both curves to ±2 SD, on a round number."""
    need = max(
        abs(b["prior_mean"]) + 2 * b["prior_sd"], abs(b["post_mean"]) + 2 * b["post_sd"], 1e-9
    )
    mag = 10 ** math.floor(math.log10(need))
    return next(round(n * mag, 9) for n in _NICE if n * mag >= need)


def register(
    conn: duckdb.DuckDBPyConnection,
    slug: str,
    question: str,
    spec: dict,
    belief_id: str | None,
    author: str,
    rationale: str = "",
) -> dict:
    """Pre-register a hypothesis. The spec is frozen by hash; power decides its status."""
    validate_spec(conn, spec)
    if (
        belief_id
        and conn.execute("SELECT 1 FROM research_beliefs WHERE id = ?", [belief_id]).fetchone()
        is None
    ):
        raise SpecError(f"no belief {belief_id!r}")
    if conn.execute("SELECT 1 FROM research_hypotheses WHERE slug = ?", [slug]).fetchone():
        raise SpecError(
            f"hypothesis {slug!r} already registered; specs are immutable, use a new slug"
        )
    probe = estimate(conn, spec)
    pw = probe.get("power")
    value = value_score(conn, spec, belief_id, power=pw)
    if value["novelty"] == 0:
        raise SpecError("an identical spec is already registered")
    # Every new question waits for the methodologist; it runs only once approved.
    status = "proposed"
    canon = json.dumps(spec, sort_keys=True)
    hid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO research_hypotheses (id, slug, question, spec, spec_hash, belief_id, author, status, power, value_score, value_parts) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            hid,
            slug,
            question,
            canon,
            hashlib.sha256(canon.encode()).hexdigest()[:16],
            belief_id,
            author,
            status,
            json.dumps(pw) if pw else None,
            value["value"],
            json.dumps(value),
        ],
    )
    why = (
        f"Needs {pw['needed_per_arm']} {spec.get('unit', 'day')}s per arm; "
        f"confirm in {pw['days_to_confirm'] if pw['days_to_confirm'] is not None else 'no finite number of'} days."
        if pw
        else "Too little data to size yet."
    )
    note(
        conn,
        author,
        "proposal",
        f"Proposed: {question}",
        f"{rationale}\n{why} Value {value['value']:.2f}.".strip(),
        ref=hid,
        data={"spec": spec, "power": pw, "value": value},
    )
    return {"id": hid, "slug": slug, "status": status, "power": pw, "value": value}


def _combine(
    prior_mean: float, prior_sd: float, results: list[tuple[float, float]]
) -> tuple[float, float]:
    """Normal–normal update: precision-weighted average of the prior and each result."""
    prec = 1 / prior_sd**2
    acc = prior_mean * prec
    for eff, se in results:
        if se and se > 0:
            prec += 1 / se**2
            acc += eff / se**2
    return acc / prec, math.sqrt(1 / prec)


def refresh_belief(conn: duckdb.DuckDBPyConnection, belief_id: str) -> None:
    """Posterior from the prior and the latest result of every linked hypothesis.

    Rebuilt from scratch each time, so re-running a hypothesis never counts the
    same days twice. A retrospective result rests on days the author explored
    before registering, so it never moves the belief.
    """
    b = conn.execute(
        "SELECT prior_mean, prior_sd FROM research_beliefs WHERE id = ?", [belief_id]
    ).fetchone()
    if b is None:
        return
    latest = conn.execute(
        """
        SELECT r.effect, r.se FROM research_results r
        JOIN research_hypotheses h ON h.id = r.hypothesis_id
        WHERE h.belief_id = ? AND r.effect IS NOT NULL AND r.verdict <> 'retrospective'
          AND r.run_at = (
            SELECT MAX(run_at) FROM research_results WHERE hypothesis_id = h.id)
        """,
        [belief_id],
    ).fetchall()
    post_mean, post_sd = _combine(b[0], b[1], [(e, s) for e, s in latest])
    conn.execute(
        "UPDATE research_beliefs SET post_mean = ?, post_sd = ?, n_results = ?, updated_at = now() WHERE id = ?",
        [post_mean, post_sd, len(latest), belief_id],
    )


_FAVOURABLE = ("supported", "direction")


def _wait_text(res: dict) -> str:
    pw = res.get("power") or {}
    nxt, to_next, to_all = (
        pw.get("next_look_per_arm"),
        pw.get("days_to_next_look"),
        pw.get("days_to_confirm"),
    )
    if nxt is None:
        return "and the planned number of days per arm has been reached without confirming it"
    if to_next is None:
        return "and one arm is gaining none at the current pace"
    text = f"the next look is at {nxt} per arm, about {to_next} more days at the current pace"
    if to_all is not None and to_all != to_next:
        text += f" (the full planned size: about {to_all} more days)"
    return text


def _confirm_on_new_days(
    conn: duckdb.DuckDBPyConnection, spec: dict, res: dict, registered: date
) -> dict:
    """Hold a favourable verdict to the days that arrived after registration.

    A question is proposed after its author explored the data, so the days up to
    registration were open to selection: leads that looked good get registered.
    The effect and range still describe every day; the verdict may only be
    favourable when the days since registration say so on their own.

    Those days are read only at the planned looks (half and the full planned
    size per arm, the half look held to a stricter bound), each on exactly the
    first n days of each arm. The nightly re-run therefore cannot keep
    re-testing growing data until it crosses 1.96; between looks the verdict
    stays retrospective.

    Args:
        conn: Database connection.
        spec: The registered spec.
        res: The all-days estimate for that spec.
        registered: The date the question was registered.

    Returns:
        ``res``, with its verdict and summary replaced when the favourable call
        rests on days seen before registration or on no planned look.
    """
    if res["verdict"] not in _FAVOURABLE:
        return res
    first = registered + timedelta(days=1)
    if "start_date" in spec:
        first = max(first, date.fromisoformat(str(spec["start_date"])))
    since = spec | {"start_date": first.isoformat()}
    planned = (res.get("power") or {}).get("needed_per_arm") or _MIN_PER_ARM
    unit = res["unit"]
    head = res["summary"].rsplit(" → ", 1)[0]
    new = estimate(conn, since)
    have = min(new["n_a"], new["n_b"])
    for n_k, z in reversed(_looks(planned)):
        if have < n_k:
            continue
        look = estimate(conn, since, z=z, cap_per_arm=n_k)
        if look["verdict"] in _FAVOURABLE:
            return res | {
                "verdict": look["verdict"],
                "summary": f"{head} On the first {n_k} A / {n_k} B {unit}s since it was "
                f"registered (a planned look, bound ±{z:g} se): {look['effect']:+.2f} "
                f"({look['ci_low']:+.2f} to {look['ci_high']:+.2f}). → {look['verdict']}",
            }
    return res | {
        "verdict": "retrospective",
        "summary": f"{head} Those {unit}s were open to exploration before the question was "
        f"written. Only {new['n_a']} A / {new['n_b']} B {unit}s since it was registered on "
        f"{registered.isoformat()}; they have to show it on their own, {_wait_text(res)}. "
        "→ retrospective",
    }


def run(conn: duckdb.DuckDBPyConnection, slug: str, author: str = "runner") -> dict:
    h = conn.execute(
        "SELECT id, question, spec, belief_id, created_at FROM research_hypotheses WHERE slug = ?",
        [slug],
    ).fetchone()
    if h is None:
        raise SpecError(f"no hypothesis {slug!r}")
    hid, question, spec_json, belief_id, created_at = h
    spec = json.loads(spec_json)
    registered = created_at.date()
    res = _confirm_on_new_days(conn, spec, estimate(conn, spec, registered=registered), registered)
    conn.execute(
        "INSERT INTO research_results (id, hypothesis_id, n_a, n_b, effect, se, ci_low, ci_high, p, "
        "design_effect, verdict, summary, power, mean_a, mean_b) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            str(uuid.uuid4()),
            hid,
            res["n_a"],
            res["n_b"],
            res["effect"],
            res["se"],
            res["ci_low"],
            res["ci_high"],
            res["p"],
            res["design_effect"],
            res["verdict"],
            res["summary"],
            json.dumps(res["power"]) if res["power"] else None,
            res["mean_a"],
            res["mean_b"],
        ],
    )
    if belief_id:
        refresh_belief(conn, belief_id)
    note(
        conn,
        author,
        "result",
        f"{res['verdict'].replace('_', ' ').capitalize()}: {question}",
        res["summary"],
        ref=hid,
    )
    return res | {"slug": slug}


_QUIET_DAYS = 30
# ponytail: auto-retire at twice the review limit so a slow month can't retire
# a question the methodologist approved; tighten if dead questions linger.
_RETIRE_AFTER_DAYS = 2 * MAX_DAYS_TO_ANSWER


def _dead_reason(
    conn: duckdb.DuckDBPyConnection, spec: dict, res: dict, today: date | None = None
) -> str | None:
    """Why a live question can never answer, or None while it still can.

    Applies the review's own rules to a question already running: its exposure
    or outcome has gone quiet, or it has no answer yet and cannot reach one.
    """
    today = today or date.today()
    for name in (spec["exposure"]["feature"], spec["outcome"]):
        if name in _CALENDAR or name in _ZERO_FILL or name.startswith(_ZERO_FILL_KINDS):
            continue  # absence is a real zero or a calendar fact, not a dead feed
        s = series(conn, name)
        last = max(s) if s else None
        if last is None or (today - last).days > _QUIET_DAYS:
            return f"{name} has had no data since {last or 'ever'}, so no new days can arrive."
    if res.get("verdict") not in ("inconclusive", "insufficient") or not res.get("power"):
        return None
    days = res["power"]["days_to_answer"]
    if days is None:
        return f"One arm gained no {res.get('unit', 'day')}s in {_PACE_WINDOW_DAYS} days, so it cannot answer."
    if days > _RETIRE_AFTER_DAYS:
        return f"Needs {days} more days at the current pace; the limit is {MAX_DAYS_TO_ANSWER}."
    return None


def run_all(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """Run every active question, then retire the ones that can never answer."""
    out = []
    for slug, spec_json in conn.execute(
        "SELECT slug, spec FROM research_hypotheses WHERE status = 'active' ORDER BY created_at"
    ).fetchall():
        try:
            res = run(conn, slug, author="nightly")
            dead = _dead_reason(conn, json.loads(spec_json), res)
            if dead:
                retire(conn, slug, dead, "nightly")
                res["retired"] = dead
            out.append(res)
        except (SpecError, ValueError, duckdb.Error) as exc:
            log.exception("research run failed: %s", slug)
            note(conn, "nightly", "error", f"Run failed: {slug}", f"{type(exc).__name__}: {exc}")
            out.append({"slug": slug, "verdict": "error", "summary": str(exc)})
    return out


def beliefs(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, claim, outcome, prior_mean, prior_sd, prior_source, post_mean, post_sd, n_results, "
        "decision, updated_at, forecast_gain, unit FROM research_beliefs ORDER BY updated_at DESC"
    ).fetchall()
    keys = [
        "id",
        "claim",
        "outcome",
        "prior_mean",
        "prior_sd",
        "prior_source",
        "post_mean",
        "post_sd",
        "n_results",
        "decision",
        "updated_at",
        "forecast_gain",
        "unit",
    ]
    out = []
    for r in rows:
        d = dict(zip(keys, r, strict=True))
        d["unit"] = d["unit"] or _unit_of(d["outcome"])
        d["goal"] = goal_of(d["outcome"], conn)
        d["scale"] = _scale(d)
        d["updated_at"] = d["updated_at"].isoformat() if d["updated_at"] else None
        out.append(d)
    return out


def _live_power(conn: duckdb.DuckDBPyConnection, spec: dict, registered: date, stored: dict | None):
    """Power on today's data, or the stored figure flagged stale when the spec can't run."""
    try:
        return estimate(conn, spec, registered=registered).get("power"), False
    except (SpecError, KeyError, ValueError):
        log.warning("power recompute failed for spec %s", spec.get("outcome"), exc_info=True)
        return stored, True


def hypotheses(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """Every question with its latest result.

    ``power`` is rescored on current data for questions still open (the numbers
    stored at proposal go stale as the series grow) and ``power_at_proposal``
    keeps the stored copy; a question that is closed keeps its stored figure.
    """
    rows = conn.execute(
        """
        SELECT h.id, h.slug, h.question, h.spec, h.belief_id, h.author, h.status, h.power, h.created_at,
               h.value_score, h.value_parts, r.mean_a, r.mean_b, r.verdict, r.effect, r.ci_low, r.ci_high, r.p, r.n_a, r.n_b, r.design_effect, r.summary, r.run_at
        FROM research_hypotheses h
        LEFT JOIN research_results r ON r.hypothesis_id = h.id
            AND r.run_at = (SELECT MAX(run_at) FROM research_results WHERE hypothesis_id = h.id)
        ORDER BY h.created_at DESC
        """
    ).fetchall()
    out = []
    for row in rows:
        hid, r = row[0], row[1:]
        res = r[12:]
        stored = json.loads(r[6]) if r[6] else None
        power, stale = (
            _live_power(conn, json.loads(r[2]), r[7].date(), stored)
            if r[5] in ("proposed", "active")
            else (stored, False)
        )
        out.append(
            {
                "id": hid,
                "slug": r[0],
                "question": r[1],
                "spec": json.loads(r[2]),
                "belief_id": r[3],
                "author": r[4],
                "status": r[5],
                "power": power,
                "power_at_proposal": stored,
                "power_stale": stale,
                "created_at": r[7].isoformat(),
                "value_score": r[8],
                "value_parts": json.loads(r[9]) if r[9] else None,
                "result": None
                if res[0] is None
                else {
                    "verdict": res[0],
                    "effect": res[1],
                    "ci_low": res[2],
                    "ci_high": res[3],
                    "p": res[4],
                    "n_a": res[5],
                    "n_b": res[6],
                    "design_effect": res[7],
                    "summary": res[8],
                    "run_at": res[9].isoformat() if res[9] else None,
                    "mean_a": r[10],
                    "mean_b": r[11],
                },
            }
        )
    return out


def notebook(conn: duckdb.DuckDBPyConnection, limit: int = 50) -> list[dict]:
    rows = conn.execute(
        "SELECT id, written_at, author, kind, ref, title, body FROM research_notebook ORDER BY written_at DESC LIMIT ?",
        [limit],
    ).fetchall()
    return [
        {
            "id": r[0],
            "written_at": r[1].isoformat(),
            "author": r[2],
            "kind": r[3],
            "ref": r[4],
            "title": r[5],
            "body": r[6],
        }
        for r in rows
    ]


# ── Forecaster ──────────────────────────────────────────────────────────────

FORECAST_METRIC = "lnhrv_dev_pct"
# Monthly cut-offs refit on data up to each one, then scored on the next 30
# days: every scored point is one the model never saw.
_BACKTEST_ORIGINS = 6
_BACKTEST_HORIZON = 30


@dataclass(frozen=True)
class ForecastTarget:
    metric: str
    label: str
    min_scored: int


FORECAST_TARGETS: dict[str, ForecastTarget] = {
    t.metric: t
    for t in [
        ForecastTarget(FORECAST_METRIC, "Next-morning HRV vs baseline", 30),
    ]
}


def forecast_target(metric: str) -> ForecastTarget:
    """The forecast target for a metric.

    Raises:
        SpecError: If the metric is not a forecast target.
    """
    t = FORECAST_TARGETS.get(metric)
    if t is None:
        raise SpecError(f"no forecast target {metric!r}; one of {sorted(FORECAST_TARGETS)}")
    return t


@dataclass(frozen=True)
class _Term:
    belief_id: str
    claim: str
    spec: dict
    effect: float  # posterior mean of B − A
    p_b: float  # share of classified days in arm B, so the term is centred on an average day


def _models(
    conn: duckdb.DuckDBPyConnection, origin: date, metric: str = FORECAST_METRIC
) -> list[_Term]:
    """Each belief's day-unit hypothesis on `metric`, refit on data up to
    `origin` and shrunk toward its literature prior."""
    rows = conn.execute(
        "SELECT b.id, b.claim, b.prior_mean, b.prior_sd, h.spec FROM research_beliefs b "
        "JOIN research_hypotheses h ON h.belief_id = b.id WHERE h.status = 'active' ORDER BY h.created_at"
    ).fetchall()
    terms: list[_Term] = []
    for bid, claim, pm, psd, spec_json in rows:
        spec = json.loads(spec_json)
        if (
            any(t.belief_id == bid for t in terms)
            or spec.get("unit", "day") != "day"
            or spec["outcome"] != metric
        ):
            continue
        res = estimate(conn, spec, today=origin)
        if res["effect"] is None:
            continue
        post, _ = _combine(pm, psd, [(res["effect"], res["se"])])
        terms.append(_Term(bid, claim, spec, post, res["n_b"] / (res["n_a"] + res["n_b"])))
    return terms


def _features_for(
    conn: duckdb.DuckDBPyConnection, terms: list[_Term], span: tuple[date, date]
) -> dict[str, dict[date, float]]:
    names = {t.spec["exposure"]["feature"] for t in terms}
    return {n: _fill_zero(n, series(conn, n), span) for n in names}


def _predict(
    terms: list[_Term], feats: dict[str, dict[date, float]], morning: date, drop: str | None = None
) -> float:
    """Deviation from baseline the lab expects this morning: each term adds its
    effect for an arm-B day and subtracts it for an arm-A day, both centred so an
    average day predicts zero. A day in neither arm contributes nothing."""
    total = 0.0
    for t in terms:
        if t.belief_id == drop:
            continue
        x = feats[t.spec["exposure"]["feature"]].get(
            morning - timedelta(days=int(t.spec.get("lag", 1)))
        )
        if x is None:
            continue
        if _in(x, t.spec["exposure"]["b"]):
            total += t.effect * (1 - t.p_b)
        elif _in(x, t.spec["exposure"]["a"]):
            total -= t.effect * t.p_b
    return total


def _skill(pairs: list[tuple[float, float]]) -> float | None:
    """1 − MSE(lab) / MSE(same-as-baseline). Above zero means the lab beats the naive guess."""
    base = sum(a * a for a, _ in pairs)
    if not pairs or base == 0:
        return None
    return 1 - sum((a - p) ** 2 for a, p in pairs) / base


# ponytail: treats scored points as independent; move to a Diebold-Mariano
# variance with lags if the forecast ever beats baseline by a hair.
def _skill_call(pairs: list[tuple[float, float]], base: list[float] | None = None) -> str | None:
    """Whether the lab beats the baseline guess beyond chance: better, worse or tie.

    Tests the mean per-point gain in squared error (baseline minus lab) against
    its own standard error, so a skill a hair above zero reads as a tie.

    Args:
        pairs: (actual, lab prediction) per scored point.
        base: The baseline guess per point; zero when omitted.
    """
    if len(pairs) < 10:
        return None
    b = base or [0.0] * len(pairs)
    gain = [(a - g) ** 2 - (a - p) ** 2 for (a, p), g in zip(pairs, b, strict=True)]
    m = mean(gain)
    se = math.sqrt(sum((g - m) ** 2 for g in gain) / (len(gain) - 1) / len(gain))
    if se == 0 or abs(m) <= 1.96 * se:
        return "tie"
    return "better" if m > 0 else "worse"


_PERSIST_FIT_DAYS = 90


def _persistence_coef(actual: dict[date, float], origin: date, lag: int) -> float:
    """Shrunk persistence: the through-origin slope of the value on its value `lag`
    days earlier, fitted only on days up to `origin` and held to [0, 1]."""
    xs, ys = [], []
    for i in range(_PERSIST_FIT_DAYS):
        d = origin - timedelta(days=i)
        if d in actual and d - timedelta(days=lag) in actual:
            xs.append(actual[d - timedelta(days=lag)])
            ys.append(actual[d])
    den = sum(x * x for x in xs)
    if len(xs) < 20 or den == 0:
        return 0.0
    return min(1.0, max(0.0, sum(x * y for x, y in zip(xs, ys, strict=True)) / den))


def _best_baseline(series_rows: list[dict]) -> dict:
    """Skill against the better of the zero baseline and shrunk persistence.

    Reads the scored series, so a stored backtest reports the same numbers the
    run did. Every field is None for a series saved before persistence was kept.
    """
    none = {"skill_best": None, "baseline": None, "rmse_persist": None, "call_best": None}
    if not series_rows or any("persist" not in x for x in series_rows):
        return none
    a = [x["actual"] for x in series_rows]
    p = [x["predicted"] for x in series_rows]
    q = [x["persist"] for x in series_rows]
    mse_zero = mean(v * v for v in a)
    mse_persist = mean((v - w) ** 2 for v, w in zip(a, q, strict=True))
    mse_lab = mean((v - w) ** 2 for v, w in zip(a, p, strict=True))
    use_persist = mse_persist < mse_zero
    base_mse = mse_persist if use_persist else mse_zero
    return {
        "skill_best": None if base_mse == 0 else 1 - mse_lab / base_mse,
        "baseline": "persistence" if use_persist else "zero",
        "rmse_persist": math.sqrt(mse_persist),
        "call_best": _skill_call(list(zip(a, p, strict=True)), q if use_persist else None),
    }


def backtest(
    conn: duckdb.DuckDBPyConnection, today: date | None = None, metric: str = FORECAST_METRIC
) -> dict:
    """Rolling-origin backtest of one forecast target, with each belief's contribution.

    The baseline guess is zero (no change from the outcome's own baseline); the
    `*_best` fields repeat the score against the better of zero and a shrunk
    persistence (a fraction of the last known value, fitted before each origin).
    The skill is withheld, with a `reason`, when no belief predicts the target or
    fewer than the target's `min_scored` points could be scored: a model with
    no terms scores exactly zero by construction, which is not a finding.

    Args:
        conn: Open DuckDB connection.
        today: Last day that may be scored; defaults to today.
        metric: A key of FORECAST_TARGETS.

    Returns:
        Skill, n, RMSEs, per-belief gains, the scored series and a reason when
        skill is withheld.
    """
    today = today or date.today()
    target = forecast_target(metric)
    actual = series(conn, metric)
    scored: list[tuple[date, float, float, dict[str, float]]] = []
    persist: list[float] = []
    claims: dict[str, str] = {}
    for k in range(_BACKTEST_ORIGINS, 0, -1):
        origin = today - timedelta(days=k * _BACKTEST_HORIZON)
        phi = _persistence_coef(actual, origin, 1)
        terms = _models(conn, origin, metric)
        claims |= {t.belief_id: t.claim for t in terms}
        feats = _features_for(conn, terms, (origin - timedelta(days=30), today))
        for i in range(1, _BACKTEST_HORIZON + 1):
            m = origin + timedelta(days=i)
            if m > today or m not in actual:
                continue
            lab = _predict(terms, feats, m)
            persist.append(phi * actual.get(m - timedelta(days=1), 0.0))
            scored.append(
                (
                    m,
                    actual[m],
                    lab,
                    {t.belief_id: _predict(terms, feats, m, drop=t.belief_id) for t in terms},
                )
            )
    reason = None
    if not claims:
        reason = "No active belief predicts this target yet, so there is nothing to score."
    elif len(scored) < target.min_scored:
        reason = (
            f"Only {len(scored)} scorable points in the backtest window; need {target.min_scored}."
        )
    skill = None if reason else _skill([(a, p) for _, a, p, _ in scored])
    gains = {}
    for bid in claims:
        without = _skill([(a, w.get(bid, p)) for _, a, p, w in scored])
        gains[bid] = None if skill is None or without is None else skill - without
    rows = [
        {"date": str(m), "actual": round(a, 2), "predicted": round(p, 2), "persist": round(q, 2)}
        for (m, a, p, _), q in zip(scored, persist, strict=True)
    ]
    return {
        "metric": metric,
        "label": target.label,
        "skill": skill,
        **(_best_baseline(rows) if skill is not None else _best_baseline([])),
        "n": len(scored),
        "reason": reason,
        "rmse_lab": math.sqrt(mean((a - p) ** 2 for _, a, p, _ in scored)) if scored else None,
        "rmse_base": math.sqrt(mean(a * a for _, a, _, _ in scored)) if scored else None,
        "gains": gains,
        "series": rows,
    }


def _bet_date(today: date, actual: dict[date, float]) -> date:
    return today + timedelta(days=1) if today in actual else today


def forecast_today(
    conn: duckdb.DuckDBPyConnection, today: date | None = None, metric: str = FORECAST_METRIC
) -> dict | None:
    """Score past live forecasts, then log today's bet before its value exists.

    The bet is for this morning, or tomorrow's once this morning's value is in.

    Returns:
        The new forecast, or None when the target's value is already in (a
        forecast made after the fact would score itself) or one is logged.
    """
    today = today or date.today()
    forecast_target(metric)
    actual = series(conn, metric)
    for (d,) in conn.execute(
        "SELECT target_date FROM research_forecasts WHERE metric = ? AND actual IS NULL",
        [metric],
    ).fetchall():
        if d in actual:
            conn.execute(
                "UPDATE research_forecasts SET actual = ? WHERE target_date = ? AND metric = ?",
                [actual[d], d, metric],
            )
    when = today
    exists = conn.execute(
        "SELECT 1 FROM research_forecasts WHERE target_date = ? AND metric = ?",
        [when, metric],
    ).fetchone()
    if today in actual or exists:
        return None
    terms = _models(conn, today, metric)
    feats = _features_for(conn, terms, (today - timedelta(days=30), when))
    pred = _predict(terms, feats, when)
    used = [
        {
            "belief_id": t.belief_id,
            "claim": t.claim,
            "contribution": round(_predict([t], feats, when), 3),
        }
        for t in terms
    ]
    conn.execute(
        "INSERT INTO research_forecasts (target_date, metric, predicted, terms) VALUES (?, ?, ?, ?)",
        [when, metric, pred, json.dumps(used)],
    )
    return {"target_date": str(when), "predicted": pred, "terms": used}


def store_backtest(conn: duckdb.DuckDBPyConnection, bt: dict, author: str = "forecaster") -> None:
    """Persist a backtest and write each belief's contribution back to the ledger."""
    conn.execute(
        "INSERT INTO research_forecast_skill (metric, skill, n, rmse_lab, rmse_base, gains, series, reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        [
            bt["metric"],
            bt["skill"],
            bt["n"],
            bt["rmse_lab"],
            bt["rmse_base"],
            json.dumps(bt["gains"]),
            json.dumps(bt["series"]),
            bt.get("reason"),
        ],
    )
    for bid, g in bt["gains"].items():
        conn.execute("UPDATE research_beliefs SET forecast_gain = ? WHERE id = ?", [g, bid])
    if bt["skill"] is not None:
        call = bt.get("call_best") or _skill_call(
            [(x["actual"], x["predicted"]) for x in bt["series"]]
        )
        head = f"Forecast skill {bt['skill']:+.3f} over {bt['n']} unseen mornings"
        if call == "tie":
            note(
                conn,
                author,
                "forecast",
                f"{head}: a tie with the baseline",
                "The forecast is not distinguishable from the baseline guess, so no belief "
                "can be said to improve it.",
            )
        else:
            helps = sum(1 for g in bt["gains"].values() if g is not None and g > 0)
            note(
                conn,
                author,
                "forecast",
                f"{head}: {call or 'too few points to call'}",
                f"{helps} of {len(bt['gains'])} beliefs improve the forecast; the rest are candidates for demotion.",
            )


def forecast_view(
    conn: duckdb.DuckDBPyConnection, live_days: int = 60, metric: str = FORECAST_METRIC
) -> dict:
    """The latest backtest and live record for one target, plus the targets on offer."""
    target = forecast_target(metric)
    row = conn.execute(
        "SELECT run_at, metric, skill, n, rmse_lab, rmse_base, gains, series, reason "
        "FROM research_forecast_skill WHERE metric = ? ORDER BY run_at DESC LIMIT 1",
        [metric],
    ).fetchone()
    live = conn.execute(
        "SELECT target_date, predicted, actual, made_at FROM research_forecasts WHERE metric = ? "
        "ORDER BY target_date DESC LIMIT ?",
        [metric, live_days],
    ).fetchall()
    scored = [(float(a), float(p)) for _, p, a, _ in live if a is not None]
    rows = [] if row is None else json.loads(row[7])
    return {
        "backtest": None
        if row is None
        else {
            "run_at": row[0].isoformat(),
            "metric": row[1],
            "skill": row[2],
            "call": None
            if row[2] is None
            else _skill_call([(x["actual"], x["predicted"]) for x in rows]),
            **_best_baseline(rows if row[2] is not None else []),
            "n": row[3],
            "rmse_lab": row[4],
            "rmse_base": row[5],
            "gains": json.loads(row[6]),
            "series": rows,
            "reason": row[8],
        },
        "live": [
            {
                "date": str(d),
                "predicted": round(p, 2),
                "actual": None if a is None else round(a, 2),
                "made_at": m.isoformat(),
            }
            for d, p, a, m in reversed(live)
        ],
        "live_skill": _skill(scored),
        "live_n": len(scored),
        "target": {
            "metric": target.metric,
            "label": target.label,
            "unit": _unit_of(target.metric),
        },
        "targets": [{"metric": t.metric, "label": t.label} for t in FORECAST_TARGETS.values()],
    }


# ── The team's workflow: value, review, brief ───────────────────────────────

# Ceiling on the uncertainty term, and its value for a belief with no result yet.
_UNCERTAINTY_CAP = 3.0


def value_score(
    conn: duckdb.DuckDBPyConnection, spec: dict, belief_id: str | None, power: dict | None = None
) -> dict:
    """Fixed value-of-information score, so no proposer can argue its way up.

    value = uncertainty × decision × feasibility × novelty × goal, where
    uncertainty is the belief's current 95% half-width in units of the smallest
    effect worth acting on (capped at 3) once it has a result, and the cap
    itself before that: an untested belief is fully open whatever prior width
    its proposer wrote, so neither a wide prior nor a small min_effect can
    raise a new question's rank. decision is 1 when an answer would
    change what the engine does and 0.5 otherwise, feasibility is 1 inside 120
    days and decays beyond, novelty drops for a question the team has already
    asked, and goal weights the outcome by what it serves (GOAL_WEIGHTS: muscle
    above body composition above cardio above recovery mediators).
    """
    uncertainty, decision = _UNCERTAINTY_CAP, 0.5
    if belief_id:
        b = conn.execute(
            "SELECT post_sd, decision, n_results FROM research_beliefs WHERE id = ?", [belief_id]
        ).fetchone()
        if b is not None:
            decision = 1.0 if b[1] else 0.5
            if b[2]:
                uncertainty = min(_UNCERTAINTY_CAP, 1.96 * float(b[0]) / float(spec["min_effect"]))
    days = (power or {}).get("days_to_confirm")
    feasibility = (
        0.05 if days is None else 1.0 if days <= MAX_DAYS_TO_ANSWER else MAX_DAYS_TO_ANSWER / days
    )
    canon = json.dumps(spec, sort_keys=True)
    novelty = 1.0
    for (other,) in conn.execute(
        "SELECT spec FROM research_hypotheses WHERE status <> 'rejected'"
    ).fetchall():
        o = json.loads(other)
        if json.dumps(o, sort_keys=True) == canon:
            novelty = 0.0
            break
        same_question = (
            o["exposure"]["feature"] == spec["exposure"]["feature"]
            and o["outcome"] == spec["outcome"]
            and o.get("unit", "day") == spec.get("unit", "day")
        )
        if same_question:
            novelty = min(novelty, 0.5)
    goal = goal_of(spec["outcome"], conn)
    goal_weight = goal_weights(conn).get(goal, _OTHER_GOAL_WEIGHT)
    return {
        "value": round(uncertainty * decision * feasibility * novelty * goal_weight, 3),
        "uncertainty": round(uncertainty, 3),
        "decision": decision,
        "feasibility": round(feasibility, 3),
        "novelty": novelty,
        "goal": goal,
        "goal_weight": goal_weight,
    }


def _revise(
    conn: duckdb.DuckDBPyConnection,
    original: tuple,
    reasons: str,
    author: str,
    spec: dict | None,
    question: str | None,
) -> dict:
    """Reject a proposal as written and register the reviewer's design as active.

    Everything that can refuse runs before the first write: the connection has
    no transaction to roll back a half-applied revision.
    """
    hid, slug, old_question, belief_id, proposer = original
    if not spec:
        raise SpecError("revise needs revised_spec: the design you would accept")
    validate_spec(conn, spec)
    days = (estimate(conn, spec).get("power") or {}).get("days_to_confirm")
    if days is None or days > MAX_DAYS_TO_ANSWER:
        raise SpecError(
            f"the revised design confirms in {days if days is not None else 'no finite number of'} "
            f"days; the limit is {MAX_DAYS_TO_ANSWER}. Reject instead, or revise further."
        )
    canon = json.dumps(spec, sort_keys=True)
    for (other,) in conn.execute(
        "SELECT spec FROM research_hypotheses WHERE status <> 'rejected'"
    ).fetchall():
        if json.dumps(json.loads(other), sort_keys=True) == canon:
            raise SpecError("the revised spec is identical to one already registered")
    n = conn.execute(
        "SELECT count(*) FROM research_hypotheses WHERE slug LIKE ?", [f"{slug}-r%"]
    ).fetchone()
    new_slug = f"{slug}-r{(n[0] if n else 0) + 1}"
    conn.execute("UPDATE research_hypotheses SET status = 'rejected' WHERE id = ?", [hid])
    note(
        conn,
        author,
        "rejection",
        f"Revised: {old_question}",
        reasons,
        ref=hid,
        data={"revised_as": new_slug},
    )
    new = register(
        conn,
        new_slug,
        (question or old_question).strip(),
        spec,
        belief_id,
        proposer,
        rationale=f"The methodologist's revision of {slug}, approved as designed.",
    )
    conn.execute("UPDATE research_hypotheses SET status = 'active' WHERE id = ?", [new["id"]])
    note(conn, author, "review", f"Approved: {question or old_question}", reasons, ref=new["id"])
    return {"slug": slug, "status": "rejected", "revised_as": new_slug}


def review(
    conn: duckdb.DuckDBPyConnection,
    slug: str,
    decision: str,
    reasons: str,
    author: str,
    revised_spec: dict | None = None,
    revised_question: str | None = None,
) -> dict:
    """The methodologist's call on a proposed question.

    Args:
        conn: Write connection.
        slug: The proposed question.
        decision: ``approve`` makes it active; ``reject`` closes it; ``revise``
            closes it and registers `revised_spec` as an active question, so a
            fixable design is not left as prose in a rejection.
        reasons: Why, in plain sentences.
        author: Who reviewed.
        revised_spec: The design the reviewer would accept (``revise`` only).
        revised_question: The question reworded for that design, if it changed.

    Returns:
        The slug and its new status, plus ``revised_as`` for a revision.

    Raises:
        SpecError: On an unknown or already-reviewed slug, a bad decision, or a
            revision that is invalid, a duplicate, or cannot answer in time.
    """
    if decision not in ("approve", "reject", "revise"):
        raise SpecError("decision must be 'approve', 'reject' or 'revise'")
    row = conn.execute(
        "SELECT id, question, status, belief_id, author FROM research_hypotheses WHERE slug = ?",
        [slug],
    ).fetchone()
    if row is None:
        raise SpecError(f"no hypothesis {slug!r}")
    hid, question, status, belief_id, proposer = row
    if status != "proposed":
        raise SpecError(f"{slug!r} is {status}, not awaiting review")
    if decision == "revise":
        return _revise(
            conn,
            (hid, slug, question, belief_id, proposer),
            reasons,
            author,
            revised_spec,
            revised_question,
        )
    new_status = "active" if decision == "approve" else "rejected"
    conn.execute("UPDATE research_hypotheses SET status = ? WHERE id = ?", [new_status, hid])
    note(
        conn,
        author,
        "review" if decision == "approve" else "rejection",
        f"{'Approved' if decision == 'approve' else 'Rejected'}: {question}",
        reasons,
        ref=hid,
    )
    return {"slug": slug, "status": new_status}


def review_queue(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """What the methodologist sees: the spec, its power and value, the data
    behind each feature. Never the analyst's rationale, so the review is blind.

    Power and value are re-scored on today's data and code. A spec is frozen
    by hash but the features it names are not, so the numbers stored when it
    was proposed go stale; `power_at_proposal` keeps them for comparison.
    """
    rows = conn.execute(
        "SELECT slug, question, spec, power, belief_id, created_at FROM research_hypotheses "
        "WHERE status = 'proposed' ORDER BY created_at"
    ).fetchall()
    feats = {f["name"]: f for f in dictionary(conn)}
    out = []
    for slug, question, spec_json, pw, belief_id, created in rows:
        spec = json.loads(spec_json)
        names = [spec["exposure"]["feature"], spec["outcome"], *spec.get("adjust", [])]
        live = estimate(conn, spec, registered=created.date()).get("power")
        out.append(
            {
                "slug": slug,
                "question": question,
                "spec": spec,
                "power": live,
                "power_at_proposal": json.loads(pw) if pw else None,
                "value_score": value_score(conn, spec, belief_id, power=live)["value"],
                "created_at": created.isoformat(),
                "features": [feats.get(n, {"name": n}) for n in names],
            }
        )
    return sorted(out, key=lambda q: -q["value_score"])


def _misses(conn: duckdb.DuckDBPyConnection, metric: str = FORECAST_METRIC) -> dict:
    """Where the latest backtest of `metric` went most wrong: the patterns a curious analyst chases."""
    row = conn.execute(
        "SELECT series FROM research_forecast_skill WHERE metric = ? ORDER BY run_at DESC LIMIT 1",
        [metric],
    ).fetchone()
    if row is None:
        return {}
    pts = [
        (date.fromisoformat(x["date"]), x["actual"] - x["predicted"]) for x in json.loads(row[0])
    ]
    if not pts:
        return {}
    names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    by_wd: dict[int, list[float]] = {}
    for d, r in pts:
        by_wd.setdefault(d.weekday(), []).append(r)
    ctx = {
        n: series(conn, n)
        for n in ("strain", "sleep_hours", "pickleball_min", "steps", "resp_rate", "skin_temp")
    }
    worst = sorted(pts, key=lambda x: abs(x[1]), reverse=True)[:12]
    recent = [r for d, r in pts if d >= max(p[0] for p in pts) - timedelta(days=30)]
    return {
        "note": "Residual = actual − forecast, in % of HRV vs 28-day baseline. Positive means HRV came in higher than the lab expected.",
        "by_weekday": [
            {"day": names[k], "mean_residual": round(mean(v), 2), "n": len(v)}
            for k, v in sorted(by_wd.items())
        ],
        "last_30_days_bias": round(mean(recent), 2) if recent else None,
        "worst_mornings": [
            {
                "date": str(d),
                "residual": round(r, 1),
                **{
                    n: (
                        round(s[d - timedelta(days=1)], 1) if (d - timedelta(days=1)) in s else None
                    )
                    for n, s in ctx.items()
                    if n not in ("sleep_hours", "resp_rate", "skin_temp")
                },
                **{
                    n: (round(s[d], 1) if d in s else None)
                    for n, s in ctx.items()
                    if n in ("sleep_hours", "resp_rate", "skin_temp")
                },
            }
            for d, r in worst
        ],
    }


_DETECT_HISTORY_DAYS = 180
_MIN_DETECT_POINTS = 30


def _smallest_effect(sd: float, de: float, n: int) -> float:
    """The smallest effect `_needed_per_arm` says n per arm can detect (bisection on its formula)."""
    lo, hi = sd * 1e-6, sd * 1e3
    for _ in range(80):
        mid = math.sqrt(lo * hi)
        if _needed_per_arm(sd, mid, de) <= n:
            hi = mid
        else:
            lo = mid
    return hi


def detectable_in_120d(conn: duckdb.DuckDBPyConnection, today: date | None = None) -> dict:
    """Per outcome, the smallest B − A effect a question could detect in 120 days.

    Uses the lab's own alpha and 80% power (`selflab._needed_per_arm`) on the
    outcome's live noise over the last 180 days and its pace over the last 90,
    with the arms filling at half the pace each. The design effect is the
    lag-1 one the trials use, so it understates carryover in a regime that
    lasts weeks. Observational questions fill the arms at the same pace, so the
    first figure also bounds them; the second assumes 80% of days adhered to.

    Args:
        conn: Open DuckDB connection.
        today: Last day that may be read; defaults to today.

    Returns:
        Outcome name to a dict with ``detectable_effect`` and
        ``detectable_at_80pct_adherence`` (outcome units), or ``None`` for
        both with a ``reason`` when the number cannot be computed.
    """
    today = today or date.today()
    names = ["lnhrv_dev_pct", "strength_emphasis_pct14"]
    names += [f"e1rm_pct14:{m}" for m in _emphasis_muscles(conn)]
    out: dict[str, dict] = {}
    for name in names:
        f = feature(name)
        base = {"unit": f.unit if f else None, "alpha": _ALPHA, "power": 0.8}
        pts = sorted(
            (d, v)
            for d, v in series(conn, name).items()
            if today - timedelta(days=_DETECT_HISTORY_DAYS) < d <= today
        )
        recent = sum(1 for d, _ in pts if d > today - timedelta(days=_PACE_WINDOW_DAYS))
        if len(pts) < _MIN_DETECT_POINTS:
            out[name] = base | {
                "detectable_effect": None,
                "detectable_at_80pct_adherence": None,
                "reason": f"only {len(pts)} readings in the last {_DETECT_HISTORY_DAYS} days; "
                f"need {_MIN_DETECT_POINTS} to measure the noise",
            }
            continue
        sd = pstdev(v for _, v in pts)
        de = _design_effect(pts)
        n = int(MAX_DAYS_TO_ANSWER * recent / _PACE_WINDOW_DAYS / 2)
        n_adh = int(n * _ADHERENCE)
        if sd == 0 or n_adh < 2:
            out[name] = base | {
                "detectable_effect": None,
                "detectable_at_80pct_adherence": None,
                "reason": f"{n} readings per arm fit in {MAX_DAYS_TO_ANSWER} days at the "
                f"last {_PACE_WINDOW_DAYS} days' pace; too few to size an effect",
            }
            continue
        out[name] = base | {
            "units_per_arm": n,
            "outcome_sd": round(sd, 3),
            "design_effect": round(de, 2),
            "detectable_effect": round(_smallest_effect(sd, de, n), 2),
            "detectable_at_80pct_adherence": round(_smallest_effect(sd, de, n_adh), 2),
            "reason": None,
        }
    out["top_set_e1rm"] = {
        "detectable_effect": None,
        "detectable_at_80pct_adherence": None,
        "reason": "a lift's top-set e1RM needs a named exercise and a randomized trial "
        "(selflab); research outcomes are per muscle (e1rm_pct14:<muscle>)",
    }
    return out


def brief(conn: duckdb.DuckDBPyConnection) -> dict:
    """Everything the analyst reads before proposing, rebuilt from the database on
    every call so no agent works from memory of a previous conversation."""
    from shc.training.autoregulation import load_training_phase

    fc = forecast_view(conn).get("backtest") or {}
    return {
        "rules": {
            "outcome_scale": "lnhrv_dev_pct is % change in HRV vs your 28-day baseline; 3% is the smallest change worth acting on.",
            "max_days_to_answer": MAX_DAYS_TO_ANSWER,
            "detectable_in_120d": detectable_in_120d(conn),
            "min_per_arm": _MIN_PER_ARM,
            "confirm_rule": "The limit is judged on power.days_to_confirm, which counts only days after registration: days you explored cannot confirm the question they suggested. A lead that matters and cannot confirm in time needs a designed experiment, not a wider window.",
            "value_formula": "uncertainty × decision × feasibility × novelty × goal_weight (see value_score); computed by the server, not the proposer.",
            "goal_weights": goal_weights(conn) | {"other": _OTHER_GOAL_WEIGHT},
            "goals": _GOAL_TEXT[load_training_phase(conn)].format(
                emphasis=" and ".join(m.replace("_", " ") for m in _emphasis_muscles(conn))
            )
            + " HRV, sleep and RHR are mediators. Outcomes: e1rm_pct14:<muscle>, sets:<muscle>, strength_emphasis_pct14, session_quality, body_mass_lb, body_mass_7d, vo2_max.",
            "spec_shape": {
                "exposure": {
                    "feature": "<feature name>",
                    "a": {"max": "<number>"},
                    "b": {"min": "<number>"},
                },
                "outcome": "<feature name>",
                "lag": "days (or weeks when unit is week) from exposure to outcome, 0-14",
                "unit": "day | week",
                "adjust": [
                    "<feature names measured on the exposure date; time_years removes a steady drift across eras>"
                ],
                "start_date": "optional YYYY-MM-DD: ignore everything before it (keeps one era in scope)",
                "window_days": "optional look-back from today, default 730",
                "expected_sign": "+ | - (predicted sign of B − A)",
                "min_effect": "<smallest effect worth acting on, in outcome units>",
            },
        },
        "forecast": {k: fc.get(k) for k in ("skill", "n", "rmse_lab", "rmse_base", "gains")},
        "forecast_targets": {
            m: {
                k: (forecast_view(conn, metric=m).get("backtest") or {}).get(k)
                for k in ("skill", "n", "reason")
            }
            | {"label": t.label}
            for m, t in FORECAST_TARGETS.items()
        },
        "misses": _misses(conn),
        "beliefs": beliefs(conn),
        "hypotheses": hypotheses(conn),
        "notebook": notebook(conn, 80),
        "features": dictionary(conn),
    }


def forecast_preview(
    conn: duckdb.DuckDBPyConnection, today: date | None = None, metric: str = FORECAST_METRIC
) -> dict:
    """The lab's next bet on a target without a value yet, and what drives it.

    Not stored: the logged forecast is still the one written at 04:50.
    """
    today = today or date.today()
    forecast_target(metric)
    target = _bet_date(today, series(conn, metric))
    terms = _models(conn, today, metric)
    feats = _features_for(conn, terms, (today - timedelta(days=30), target))
    parts = [
        {
            "claim": t.claim,
            "belief_id": t.belief_id,
            "contribution": _predict([t], feats, target),
            "feature": t.spec["exposure"]["feature"],
            "exposure": feats[t.spec["exposure"]["feature"]].get(
                target - timedelta(days=int(t.spec.get("lag", 1)))
            ),
            "arm_a": t.spec["exposure"]["a"],
            "arm_b": t.spec["exposure"]["b"],
            "effect": t.effect,
            "share_b": t.p_b,
        }
        for t in terms
    ]
    row = conn.execute(
        "SELECT rmse_lab FROM research_forecast_skill WHERE metric = ? ORDER BY run_at DESC LIMIT 1",
        [metric],
    ).fetchone()
    return {
        "metric": metric,
        "target_date": str(target),
        "predicted": sum(p["contribution"] for p in parts),
        "typical_miss": row[0] if row else None,
        "terms": sorted(parts, key=lambda p: abs(p["contribution"]), reverse=True),
    }


def misses(conn: duckdb.DuckDBPyConnection, metric: str = FORECAST_METRIC) -> dict:
    if metric not in FORECAST_TARGETS:
        raise SpecError(f"unknown forecast target {metric!r}")
    return _misses(conn, metric) | {"metric": metric}


def retire(conn: duckdb.DuckDBPyConnection, slug: str, reason: str, author: str) -> dict:
    """Stop running an active question. Its results stay; it leaves the nightly run and the forecast."""
    row = conn.execute(
        "SELECT id, question, status FROM research_hypotheses WHERE slug = ?", [slug]
    ).fetchone()
    if row is None:
        raise SpecError(f"no hypothesis {slug!r}")
    hid, question, status = row
    if status != "active":
        raise SpecError(f"{slug!r} is {status}, not active")
    # Its results stay valid evidence, so the belief they fed is left as it is.
    conn.execute("UPDATE research_hypotheses SET status = 'retired' WHERE id = ?", [hid])
    note(conn, author, "retirement", f"Retired: {question}", reason, ref=hid)
    return {"slug": slug, "status": "retired"}
