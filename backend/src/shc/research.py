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
from statistics import NormalDist, mean

import duckdb
import numpy as np

from shc import places
from shc.selflab import _design_effect, _needed_per_arm
from shc.training.mesocycle import _CAPPED_E1RM, _MAX_E1RM_MEDIAN_DEVIATION
from shc.training.volume import _RPE_GATE, _STIMULATING

log = logging.getLogger(__name__)

_NORMAL = NormalDist()
# A question that can't answer within this many days at the current pace is
# underpowered: the value score discounts it and the methodologist should send
# it back for a stronger design.
MAX_DAYS_TO_ANSWER = 120
_MIN_PER_ARM = 10
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
            "Apple Health",
            _q(
                "SELECT date, AVG(value_avg) * 2.20462 FROM v_daily_metrics WHERE metric = 'body_mass_kg' GROUP BY date"
            ),
        ),
        Feature(
            "body_mass_7d", "Body weight, 7-day mean of weigh-ins", "lb", "day", "Apple Health"
        ),
        Feature(
            "vo2_max",
            "VO₂ max estimate",
            "mL/kg/min",
            "day",
            "Apple Health",
            _q(
                "SELECT date, AVG(value_avg) FROM v_daily_metrics WHERE metric = 'vo2_max' GROUP BY date"
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
EMPHASIS_MUSCLES = ("biceps", "glutes")

# What each outcome is for, in the subject's goal order: muscle first, then body
# composition, then aerobic fitness. Recovery signals are mediators, not goals.
GOAL_WEIGHTS = {"muscle": 1.0, "body": 0.85, "cardio": 0.7, "recovery": 0.6}
_OTHER_GOAL_WEIGHT = 0.5
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
    parts = [_e1rm_pct14(conn, m) for m in EMPHASIS_MUSCLES]
    days = set.intersection(*(set(p) for p in parts))
    return {d: mean(p[d] for p in parts) for d in days}


def _weekend(_conn: duckdb.DuckDBPyConnection) -> dict[date, float]:
    """1 on Saturday and Sunday: the confounder for anything that happens on weekends."""
    d, end, out = date(2014, 1, 1), date.today() + timedelta(days=1), {}
    while d <= end:
        out[d] = 1.0 if d.weekday() >= 5 else 0.0
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


def estimate(conn: duckdb.DuckDBPyConnection, spec: dict, today: date | None = None) -> dict:
    """Run a spec on current data: B − A adjusted for covariates, with a
    carryover-widened 95% range, a verdict, and a power estimate."""
    today = today or date.today()
    unit = spec.get("unit", "day")
    lag = int(spec.get("lag", 1))
    window = int(spec.get("window_days", 730))
    start = today - timedelta(days=window)
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
    # Consecutive units carry over; measure it on the residuals, keyed to a
    # daily index so a week-unit study's neighbours read as consecutive.
    idx = [
        (start + timedelta(days=int((r[0] - start) / step)), float(e))
        for r, e in zip(rows, resid, strict=True)
    ]
    de = _design_effect(idx)
    effect = float(beta[1])
    se = math.sqrt(float(cov[1, 1]) * de)
    ci = (effect - 1.96 * se, effect + 1.96 * se)
    p = 2 * (1 - _NORMAL.cdf(abs(effect) / se)) if se > 0 else 1.0
    m = float(spec["min_effect"])
    want_pos = spec["expected_sign"] == "+"
    if ci[0] > 0 or ci[1] < 0:
        verdict = "supported" if (effect > 0) == want_pos else "against"
    elif (want_pos and ci[1] < m) or (not want_pos and ci[0] > -m):
        verdict = "ruled_out"
    else:
        verdict = "inconclusive"
    power = _power(rows, math.sqrt(sigma2), m, de, today, unit)
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
            f"B − A = {effect:+.2f} {unit_label} (95% {ci[0]:+.2f} to {ci[1]:+.2f}), "
            f"{n_a} A / {n_b} B {unit}s, adjusted for {', '.join(adj) or 'nothing'}. → {verdict}"
        ),
    }


def _power(rows: list, sd: float, min_effect: float, de: float, today: date, unit: str) -> dict:
    needed = _needed_per_arm(sd, min_effect, de)
    have = {0: sum(1 for r in rows if r[1] == 0), 1: sum(1 for r in rows if r[1] == 1)}
    since = today - timedelta(days=_PACE_WINDOW_DAYS)
    per_day = 7 if unit == "week" else 1
    waits = []
    for arm in (0, 1):
        short = needed - have[arm]
        pace = sum(1 for r in rows if r[1] == arm and r[0] >= since) / (_PACE_WINDOW_DAYS / per_day)
        if short <= 0:
            waits.append(0)
        elif pace > 0:
            waits.append(math.ceil(short / pace) * per_day)
        else:
            waits.append(None)
    wait = None if None in waits else max(waits)
    return {"needed_per_arm": needed, "days_to_answer": wait, "outcome_sd": round(sd, 3)}


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
        f"answer in {pw['days_to_answer'] if pw['days_to_answer'] is not None else 'no finite number of'} days."
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
    same days twice.
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
        WHERE h.belief_id = ? AND r.effect IS NOT NULL AND r.run_at = (
            SELECT MAX(run_at) FROM research_results WHERE hypothesis_id = h.id)
        """,
        [belief_id],
    ).fetchall()
    post_mean, post_sd = _combine(b[0], b[1], [(e, s) for e, s in latest])
    conn.execute(
        "UPDATE research_beliefs SET post_mean = ?, post_sd = ?, n_results = ?, updated_at = now() WHERE id = ?",
        [post_mean, post_sd, len(latest), belief_id],
    )


def run(conn: duckdb.DuckDBPyConnection, slug: str, author: str = "runner") -> dict:
    h = conn.execute(
        "SELECT id, question, spec, belief_id FROM research_hypotheses WHERE slug = ?", [slug]
    ).fetchone()
    if h is None:
        raise SpecError(f"no hypothesis {slug!r}")
    hid, question, spec_json, belief_id = h
    res = estimate(conn, json.loads(spec_json))
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


def run_all(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    out = []
    for (slug,) in conn.execute(
        "SELECT slug FROM research_hypotheses WHERE status = 'active' ORDER BY created_at"
    ).fetchall():
        try:
            out.append(run(conn, slug, author="nightly"))
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
        # How much the data has narrowed the prior: 0 = untouched, → 1 = data dominates.
        d["learned"] = round(1 - (d["post_sd"] / d["prior_sd"]) ** 2, 3) if d["prior_sd"] else None
        out.append(d)
    return out


def hypotheses(conn: duckdb.DuckDBPyConnection) -> list[dict]:
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
        out.append(
            {
                "id": hid,
                "slug": r[0],
                "question": r[1],
                "spec": json.loads(r[2]),
                "belief_id": r[3],
                "author": r[4],
                "status": r[5],
                "power": json.loads(r[6]) if r[6] else None,
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
STRENGTH_METRIC = "strength_emphasis_pct14"
# Monthly cut-offs refit on data up to each one, then scored on the next 30
# days: every scored point is one the model never saw.
_BACKTEST_ORIGINS = 6
_BACKTEST_HORIZON = 30


@dataclass(frozen=True)
class ForecastTarget:
    metric: str
    label: str
    # 0: the morning not yet read. >0: the value that many days ahead, so only
    # beliefs whose lag reaches that far can be known when the bet is made.
    horizon_days: int
    # Score one point per step: a 14-day rolling outcome scored daily would
    # count the same fortnight fourteen times.
    step_days: int
    min_scored: int


FORECAST_TARGETS: dict[str, ForecastTarget] = {
    t.metric: t
    for t in [
        ForecastTarget(FORECAST_METRIC, "Next-morning HRV vs baseline", 0, 1, 30),
        ForecastTarget(STRENGTH_METRIC, "Emphasis-muscle strength, 14 days vs prior 14", 7, 7, 12),
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
    horizon = forecast_target(metric).horizon_days
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
            or int(spec.get("lag", 1)) < horizon
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


def backtest(
    conn: duckdb.DuckDBPyConnection, today: date | None = None, metric: str = FORECAST_METRIC
) -> dict:
    """Rolling-origin backtest of one forecast target, with each belief's contribution.

    The baseline guess is zero (no change from the outcome's own baseline). The
    skill is withheld, with a `reason`, when no belief predicts the target or
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
    claims: dict[str, str] = {}
    first = max(1, target.horizon_days)
    for k in range(_BACKTEST_ORIGINS, 0, -1):
        origin = today - timedelta(days=k * _BACKTEST_HORIZON)
        terms = _models(conn, origin, metric)
        claims |= {t.belief_id: t.claim for t in terms}
        feats = _features_for(conn, terms, (origin - timedelta(days=30), today))
        for i in range(first, _BACKTEST_HORIZON + 1, target.step_days):
            m = origin + timedelta(days=i)
            if m > today or m not in actual:
                continue
            lab = _predict(terms, feats, m)
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
    return {
        "metric": metric,
        "label": target.label,
        "skill": skill,
        "n": len(scored),
        "reason": reason,
        "rmse_lab": math.sqrt(mean((a - p) ** 2 for _, a, p, _ in scored)) if scored else None,
        "rmse_base": math.sqrt(mean(a * a for _, a, _, _ in scored)) if scored else None,
        "gains": gains,
        "series": [
            {"date": str(m), "actual": round(a, 2), "predicted": round(p, 2)}
            for m, a, p, _ in scored
        ],
    }


def _bet_date(target: ForecastTarget, today: date, actual: dict[date, float]) -> date:
    if target.horizon_days:
        return today + timedelta(days=target.horizon_days)
    return today + timedelta(days=1) if today in actual else today


def forecast_today(
    conn: duckdb.DuckDBPyConnection, today: date | None = None, metric: str = FORECAST_METRIC
) -> dict | None:
    """Score past live forecasts, then log today's bet before its value exists.

    A morning target is bet on for this morning; a day target for `horizon_days`
    ahead, and scored only once that day is over.

    Returns:
        The new forecast, or None when the target's value is already in (a
        forecast made after the fact would score itself) or one is logged.
    """
    today = today or date.today()
    target = forecast_target(metric)
    actual = series(conn, metric)
    for (d,) in conn.execute(
        "SELECT target_date FROM research_forecasts WHERE metric = ? AND actual IS NULL",
        [metric],
    ).fetchall():
        if d in actual and (target.horizon_days == 0 or d < today):
            conn.execute(
                "UPDATE research_forecasts SET actual = ? WHERE target_date = ? AND metric = ?",
                [actual[d], d, metric],
            )
    when = today + timedelta(days=target.horizon_days)
    exists = conn.execute(
        "SELECT 1 FROM research_forecasts WHERE target_date = ? AND metric = ?",
        [when, metric],
    ).fetchone()
    if (target.horizon_days == 0 and today in actual) or exists:
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
        helps = sum(1 for g in bt["gains"].values() if g is not None and g > 0)
        what = "mornings" if bt["metric"] == FORECAST_METRIC else f"{bt['metric']} points"
        note(
            conn,
            author,
            "forecast",
            f"Forecast skill {bt['skill']:+.3f} over {bt['n']} unseen {what}",
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
    return {
        "backtest": None
        if row is None
        else {
            "run_at": row[0].isoformat(),
            "metric": row[1],
            "skill": row[2],
            "n": row[3],
            "rmse_lab": row[4],
            "rmse_base": row[5],
            "gains": json.loads(row[6]),
            "series": json.loads(row[7]),
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
            "horizon_days": target.horizon_days,
            "unit": _unit_of(target.metric),
        },
        "targets": [{"metric": t.metric, "label": t.label} for t in FORECAST_TARGETS.values()],
    }


# ── The team's workflow: value, review, brief ───────────────────────────────

# Typical prior width when a question isn't tied to a belief yet.
_DEFAULT_PRIOR_SD = 5.0


def value_score(
    conn: duckdb.DuckDBPyConnection, spec: dict, belief_id: str | None, power: dict | None = None
) -> dict:
    """Fixed value-of-information score, so no proposer can argue its way up.

    value = uncertainty × decision × feasibility × novelty × goal, where
    uncertainty is the belief's current 95% half-width in units of the smallest
    effect worth acting on (capped at 3), decision is 1 when an answer would
    change what the engine does and 0.5 otherwise, feasibility is 1 inside 120
    days and decays beyond, novelty drops for a question the team has already
    asked, and goal weights the outcome by what it serves (GOAL_WEIGHTS: muscle
    above body composition above cardio above recovery mediators).
    """
    sd, decision = _DEFAULT_PRIOR_SD, 0.5
    if belief_id:
        b = conn.execute(
            "SELECT post_sd, decision FROM research_beliefs WHERE id = ?", [belief_id]
        ).fetchone()
        if b is not None:
            sd, decision = float(b[0]), 1.0 if b[1] else 0.5
    uncertainty = min(3.0, 1.96 * sd / float(spec["min_effect"]))
    days = (power or {}).get("days_to_answer")
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
    goal_weight = GOAL_WEIGHTS.get(goal, _OTHER_GOAL_WEIGHT)
    return {
        "value": round(uncertainty * decision * feasibility * novelty * goal_weight, 3),
        "uncertainty": round(uncertainty, 3),
        "decision": decision,
        "feasibility": round(feasibility, 3),
        "novelty": novelty,
        "goal": goal,
        "goal_weight": goal_weight,
    }


def review(
    conn: duckdb.DuckDBPyConnection, slug: str, decision: str, reasons: str, author: str
) -> dict:
    """The methodologist's call on a proposed question: approve makes it active,
    reject retires it with the reasons in the notebook."""
    if decision not in ("approve", "reject"):
        raise SpecError("decision must be 'approve' or 'reject'")
    row = conn.execute(
        "SELECT id, question, status FROM research_hypotheses WHERE slug = ?", [slug]
    ).fetchone()
    if row is None:
        raise SpecError(f"no hypothesis {slug!r}")
    hid, question, status = row
    if status != "proposed":
        raise SpecError(f"{slug!r} is {status}, not awaiting review")
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
    behind each feature. Never the analyst's rationale, so the review is blind."""
    rows = conn.execute(
        "SELECT slug, question, spec, power, value_score, created_at FROM research_hypotheses "
        "WHERE status = 'proposed' ORDER BY value_score DESC NULLS LAST, created_at"
    ).fetchall()
    feats = {f["name"]: f for f in dictionary(conn)}
    out = []
    for slug, question, spec_json, pw, value, created in rows:
        spec = json.loads(spec_json)
        names = [spec["exposure"]["feature"], spec["outcome"], *spec.get("adjust", [])]
        out.append(
            {
                "slug": slug,
                "question": question,
                "spec": spec,
                "power": json.loads(pw) if pw else None,
                "value_score": value,
                "created_at": created.isoformat(),
                "features": [feats.get(n, {"name": n}) for n in names],
            }
        )
    return out


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


def brief(conn: duckdb.DuckDBPyConnection) -> dict:
    """Everything the analyst reads before proposing, rebuilt from the database on
    every call so no agent works from memory of a previous conversation."""
    fc = forecast_view(conn).get("backtest") or {}
    return {
        "rules": {
            "outcome_scale": "lnhrv_dev_pct is % change in HRV vs your 28-day baseline; 3% is the smallest change worth acting on.",
            "max_days_to_answer": MAX_DAYS_TO_ANSWER,
            "min_per_arm": _MIN_PER_ARM,
            "value_formula": "uncertainty × decision × feasibility × novelty × goal_weight (see value_score); computed by the server, not the proposer.",
            "goal_weights": GOAL_WEIGHTS | {"other": _OTHER_GOAL_WEIGHT},
            "goals": "Build muscle first (biceps and glutes emphasis), then body recomposition at maintenance, then aerobic fitness. HRV, sleep and RHR are mediators. Outcomes: e1rm_pct14:<muscle>, sets:<muscle>, strength_emphasis_pct14, session_quality, body_mass_lb, body_mass_7d, vo2_max.",
            "spec_shape": {
                "exposure": {
                    "feature": "<feature name>",
                    "a": {"max": "<number>"},
                    "b": {"min": "<number>"},
                },
                "outcome": "<feature name>",
                "lag": "days (or weeks when unit is week) from exposure to outcome, 0-14",
                "unit": "day | week",
                "adjust": ["<feature names measured on the exposure date>"],
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
    tgt = forecast_target(metric)
    target = _bet_date(tgt, today, series(conn, metric))
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
