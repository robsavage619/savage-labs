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

from shc.selflab import _design_effect, _needed_per_arm

log = logging.getLogger(__name__)

_NORMAL = NormalDist()
# A question that can't answer within this many days at the current pace is
# registered as underpowered: the methodologist's cue to change the design.
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
            "°F",
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
            _q(
                "SELECT date, MAX(value_avg) FROM v_daily_metrics WHERE metric = 'step_count' GROUP BY date"
            ),
        ),
        Feature(
            "daylight_min",
            "Time in daylight",
            "min",
            "day",
            "Apple Health",
            _q(
                "SELECT date, MAX(value_avg) FROM v_daily_metrics WHERE metric = 'time_in_daylight_min' GROUP BY date"
            ),
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
    ]
}

# Days a feature counts as zero when absent rather than missing: no pickleball
# session that day means zero minutes, not an unknown.
_ZERO_FILL = {"pickleball_min", "working_sets", "lift_tonnes"}


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


def _rolling7(base: dict[date, float]) -> dict[date, float]:
    out: dict[date, float] = {}
    for d in base:
        w = [base[d - timedelta(days=k)] for k in range(7) if d - timedelta(days=k) in base]
        if len(w) >= 4:
            out[d] = mean(w)
    return out


_DERIVED: dict[str, Callable[[duckdb.DuckDBPyConnection], dict[date, float]]] = {
    "lnhrv_dev_pct": _lnhrv_dev,
    "lnhrv_7d_pct": lambda c: _rolling7(series(c, "lnhrv_dev_pct")),
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
    if name in _DERIVED:
        return _DERIVED[name](conn)
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
    return name in FEATURES


def dictionary(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """The data dictionary agents read before proposing: what exists, how much, how fresh."""
    today = date.today()
    out = []
    for f in FEATURES.values():
        s = series(conn, f.name)
        recent = sum(1 for d in s if d >= today - timedelta(days=90))
        last = max(s) if s else None
        out.append(
            {
                "name": f.name,
                "label": f.label,
                "unit": f.unit,
                "timing": f.timing,
                "source": f.source,
                "first": str(min(s)) if s else None,
                "last": str(last) if last else None,
                "days": len(s),
                "coverage_90d_pct": round(100 * recent / 90),
                "stale": last is None or (today - last).days > 7,
            }
        )
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
                "first": str(first),
                "last": str(last),
                "days": n,
                "coverage_90d_pct": 0 if (today - last).days > 90 else None,
                "stale": (today - last).days > 7,
            }
        )
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
    names = [exp["feature"], spec.get("outcome", ""), *spec.get("adjust", [])]
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
    if name not in _ZERO_FILL:
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
    for d, x in raw[exp_name].items():
        if d < start:
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
    base = {"n_a": n_a, "n_b": n_b, "unit": unit}
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
    unit_label = FEATURES[out_name].unit if out_name in FEATURES else ""
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
) -> str:
    if prior_sd <= 0:
        raise SpecError("prior_sd must be positive")
    bid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO research_beliefs (id, claim, outcome, prior_mean, prior_sd, prior_source, "
        "post_mean, post_sd, decision) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [bid, claim, outcome, prior_mean, prior_sd, prior_source, prior_mean, prior_sd, decision],
    )
    note(
        conn,
        author,
        "belief",
        f"New belief: {claim}",
        f"Prior {prior_mean:+g} ± {prior_sd:g} from {prior_source}.",
        ref=bid,
    )
    return bid


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
    status = (
        "registered"
        if pw and pw["days_to_answer"] is not None and pw["days_to_answer"] <= MAX_DAYS_TO_ANSWER
        else "underpowered"
    )
    canon = json.dumps(spec, sort_keys=True)
    hid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO research_hypotheses (id, slug, question, spec, spec_hash, belief_id, author, status, power) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        f"{'Registered' if status == 'registered' else 'Underpowered'}: {question}",
        f"{rationale}\n{why}".strip(),
        ref=hid,
        data={"spec": spec, "power": pw},
    )
    return {"id": hid, "slug": slug, "status": status, "power": pw}


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
        "design_effect, verdict, summary, power) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
        "SELECT slug FROM research_hypotheses WHERE status <> 'retired' ORDER BY created_at"
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
        "decision, updated_at FROM research_beliefs ORDER BY updated_at DESC"
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
    ]
    out = []
    for r in rows:
        d = dict(zip(keys, r, strict=True))
        d["updated_at"] = d["updated_at"].isoformat() if d["updated_at"] else None
        # How much the data has narrowed the prior: 0 = untouched, → 1 = data dominates.
        d["learned"] = round(1 - (d["post_sd"] / d["prior_sd"]) ** 2, 3) if d["prior_sd"] else None
        out.append(d)
    return out


def hypotheses(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT h.slug, h.question, h.spec, h.belief_id, h.author, h.status, h.power, h.created_at,
               r.verdict, r.effect, r.ci_low, r.ci_high, r.p, r.n_a, r.n_b, r.design_effect, r.summary, r.run_at
        FROM research_hypotheses h
        LEFT JOIN research_results r ON r.hypothesis_id = h.id
            AND r.run_at = (SELECT MAX(run_at) FROM research_results WHERE hypothesis_id = h.id)
        ORDER BY h.created_at DESC
        """
    ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "slug": r[0],
                "question": r[1],
                "spec": json.loads(r[2]),
                "belief_id": r[3],
                "author": r[4],
                "status": r[5],
                "power": json.loads(r[6]) if r[6] else None,
                "created_at": r[7].isoformat(),
                "result": None
                if r[8] is None
                else {
                    "verdict": r[8],
                    "effect": r[9],
                    "ci_low": r[10],
                    "ci_high": r[11],
                    "p": r[12],
                    "n_a": r[13],
                    "n_b": r[14],
                    "design_effect": r[15],
                    "summary": r[16],
                    "run_at": r[17].isoformat() if r[17] else None,
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
