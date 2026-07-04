from __future__ import annotations

"""n-of-1 self-experiment engine — the EXPERIMENTAL counterpart to lab.py.

lab.py mines associations from data Rob passively generates (observational →
correlational). This runs DESIGNED single-subject experiments: Rob deliberately
manipulates one variable under a controlled, pre-registered design, so a
confirmed result is causal. The public loop:

    preregister(...)            → lock hypothesis + design + analysis plan
    arm_for_day(exp, day)       → deterministic, balanced, fixed BEFORE outcomes
    log_day(conn, ...)          → record adherence for a day (arm computed)
    refresh_outcomes(conn, id)  → pull the outcome metric from the data stream
    score(conn, id)             → N-gated verdict + effect + bootstrap CI
                                  → a CONFIRMED result emits a governed prior

Every statistic is deterministic (no LLM) and reuses lab.py's tested machinery.
A CONFIRMED experiment writes an ``experiment_prior`` the engine may act on under
the same gate-and-audit discipline as the fitted ACWR/volume bands.
"""

import hashlib
import logging
from dataclasses import dataclass
from datetime import date
from statistics import mean

import duckdb

from shc.lab import _ALPHA, _welch_t

log = logging.getLogger(__name__)

# Bootstrap resamples for the effect CI. Deterministic (seeded from the slug) so
# a re-score of the same data returns the identical interval.
_BOOTSTRAP_N = 2000


@dataclass
class Experiment:
    id: str
    slug: str
    hypothesis: str
    manipulated: str
    condition_a: str
    condition_b: str
    outcome_metric: str
    outcome_direction: str
    design: str
    min_per_arm: int
    min_effect: float
    washout_hours: int
    started_on: date
    status: str


# ── Pre-registration ─────────────────────────────────────────────────────────


def preregister(
    conn: duckdb.DuckDBPyConnection,
    *,
    slug: str,
    hypothesis: str,
    manipulated: str,
    condition_a: str,
    condition_b: str,
    outcome_metric: str,
    outcome_direction: str = "higher_better",
    min_per_arm: int = 6,
    min_effect: float = 0.0,
    washout_hours: int = 0,
    started_on: date | None = None,
    planned_end: date | None = None,
    notes: str | None = None,
) -> str:
    """Register a study before any data is collected. Returns the experiment id.

    ``min_effect`` is the smallest effect worth acting on (in outcome units); it
    is what makes a REFUTED verdict possible — you can only rule out an effect
    relative to a defined "meaningful" threshold.
    """
    started = started_on or date.today()
    conn.execute(
        """
        INSERT INTO experiments
            (slug, hypothesis, manipulated, condition_a, condition_b, outcome_metric,
             outcome_direction, min_per_arm, min_effect, washout_hours, started_on,
             planned_end, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        [
            slug, hypothesis, manipulated, condition_a, condition_b, outcome_metric,
            outcome_direction, min_per_arm, min_effect, washout_hours, started.isoformat(),
            planned_end.isoformat() if planned_end else None, notes,
        ],
    )
    row = conn.execute("SELECT id FROM experiments WHERE slug = ?", [slug]).fetchone()
    assert row is not None
    return str(row[0])


def load(conn: duckdb.DuckDBPyConnection, exp_id: str) -> Experiment | None:
    row = conn.execute(
        "SELECT id, slug, hypothesis, manipulated, condition_a, condition_b, outcome_metric, "
        "outcome_direction, design, min_per_arm, min_effect, washout_hours, started_on, status "
        "FROM experiments WHERE id = ? OR slug = ?",
        [exp_id, exp_id],
    ).fetchone()
    if not row:
        return None
    started = row[12] if isinstance(row[12], date) else date.fromisoformat(str(row[12]))
    return Experiment(
        id=str(row[0]), slug=row[1], hypothesis=row[2], manipulated=row[3], condition_a=row[4],
        condition_b=row[5], outcome_metric=row[6], outcome_direction=row[7], design=row[8],
        min_per_arm=int(row[9]), min_effect=float(row[10]), washout_hours=int(row[11]),
        started_on=started, status=row[13],
    )


# ── Assignment (deterministic + balanced, fixed before outcomes) ─────────────


def arm_for_day(slug: str, started_on: date, day: date) -> str:
    """Assign 'A' or 'B' for a given day — block-balanced randomized alternating.

    Days are grouped into blocks of two; a coin seeded by (slug, block) decides
    which position in the block is the intervention. This yields exactly one A and
    one B per block (balanced) while the sequence is unpredictable, and — because
    it is a pure function of (slug, day) — the assignment is fixed the moment the
    study is registered and can never be reverse-engineered after seeing outcomes.
    """
    idx = (day - started_on).days
    if idx < 0:
        raise ValueError("day precedes the experiment start")
    block, pos = divmod(idx, 2)
    coin = int(hashlib.sha256(f"{slug}:{block}".encode()).hexdigest(), 16) % 2
    return "B" if pos == coin else "A"


def log_day(
    conn: duckdb.DuckDBPyConnection,
    exp_id: str,
    day: date,
    *,
    adhered: bool | None = True,
    note: str | None = None,
) -> str:
    """Record adherence for a day. The assigned arm is computed, not chosen."""
    exp = load(conn, exp_id)
    if exp is None:
        raise ValueError(f"no experiment {exp_id!r}")
    arm = arm_for_day(exp.slug, exp.started_on, day)
    conn.execute(
        """
        INSERT INTO experiment_log (experiment_id, day, assigned_arm, adhered, note)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT (experiment_id, day) DO UPDATE SET
            assigned_arm = excluded.assigned_arm,
            adhered      = excluded.adhered,
            note         = excluded.note
        """,
        [exp.id, day.isoformat(), arm, adhered, note],
    )
    return arm


# ── Outcome extraction from the live data stream ─────────────────────────────


def _top_set_e1rm(conn: duckdb.DuckDBPyConnection, exercise: str, day: date) -> float | None:
    """Best working-set Epley e1RM for an exercise on a day (reps capped at 12)."""
    row = conn.execute(
        """
        SELECT MAX(weight_kg * (1 + LEAST(reps, 12) / 30.0))
        FROM workout_sets_dedup
        WHERE exercise = ? AND day_d = ? AND is_warmup = FALSE
          AND weight_kg > 0 AND reps > 0
        """,
        [exercise, day.isoformat()],
    ).fetchone()
    return float(row[0]) if row and row[0] is not None else None


def _outcome_value(conn: duckdb.DuckDBPyConnection, metric: str, day: date) -> float | None:
    """Resolve one day's outcome for a metric spec. MVP supports 'top_set_e1rm:<ex>'."""
    kind, _, arg = metric.partition(":")
    if kind == "top_set_e1rm" and arg:
        return _top_set_e1rm(conn, arg, day)
    raise ValueError(f"unsupported outcome metric {metric!r}")


def refresh_outcomes(conn: duckdb.DuckDBPyConnection, exp_id: str) -> int:
    """Fill outcome_value for every logged day from the data stream. Returns n filled."""
    exp = load(conn, exp_id)
    if exp is None:
        raise ValueError(f"no experiment {exp_id!r}")
    days = conn.execute(
        "SELECT day FROM experiment_log WHERE experiment_id = ?", [exp.id]
    ).fetchall()
    filled = 0
    for (d,) in days:
        day = d if isinstance(d, date) else date.fromisoformat(str(d))
        val = _outcome_value(conn, exp.outcome_metric, day)
        if val is not None:
            conn.execute(
                "UPDATE experiment_log SET outcome_value = ? WHERE experiment_id = ? AND day = ?",
                [val, exp.id, day.isoformat()],
            )
            filled += 1
    return filled


# ── Scoring ──────────────────────────────────────────────────────────────────


def _bootstrap_ci(a: list[float], b: list[float], slug: str) -> tuple[float, float]:
    """Seeded percentile bootstrap 95% CI on mean(B) − mean(A)."""
    import random

    seed = int(hashlib.sha256(slug.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    diffs: list[float] = []
    for _ in range(_BOOTSTRAP_N):
        ra = [rng.choice(a) for _ in a]
        rb = [rng.choice(b) for _ in b]
        diffs.append(mean(rb) - mean(ra))
    diffs.sort()
    lo = diffs[int(0.025 * (len(diffs) - 1))]
    hi = diffs[int(0.975 * (len(diffs) - 1))]
    return round(lo, 4), round(hi, 4)


def score(conn: duckdb.DuckDBPyConnection, exp_id: str) -> dict:
    """Score an experiment: N-gated verdict + effect + bootstrap CI, and — when
    CONFIRMED — emit a governed personal prior. Returns the result dict."""
    exp = load(conn, exp_id)
    if exp is None:
        raise ValueError(f"no experiment {exp_id!r}")

    rows = conn.execute(
        "SELECT assigned_arm, outcome_value FROM experiment_log "
        "WHERE experiment_id = ? AND adhered = TRUE AND outcome_value IS NOT NULL",
        [exp.id],
    ).fetchall()
    a = [float(v) for arm, v in rows if arm == "A"]
    b = [float(v) for arm, v in rows if arm == "B"]
    n_a, n_b = len(a), len(b)

    result: dict = {"experiment_id": exp.id, "n_a": n_a, "n_b": n_b}

    if n_a < exp.min_per_arm or n_b < exp.min_per_arm:
        result |= {
            "verdict": "INSUFFICIENT_N", "mean_a": None, "mean_b": None, "effect": None,
            "effect_ci_low": None, "effect_ci_high": None, "p_value": None,
            "summary": (
                f"Only {n_a}/{n_b} adhered {exp.condition_a}/{exp.condition_b} days with an "
                f"outcome — need ≥{exp.min_per_arm} per arm."
            ),
        }
        _persist_result(conn, result)
        return result

    mean_a, mean_b = round(mean(a), 4), round(mean(b), 4)
    effect = round(mean_b - mean_a, 4)
    tw = _welch_t(a, b)  # returns (t, two-tailed p) or None (e.g. zero within-arm variance)
    p = round(tw[1], 4) if tw else None
    ci_low, ci_high = _bootstrap_ci(a, b, exp.slug)

    ci_excludes_zero = ci_low > 0 or ci_high < 0
    significant = p is not None and p < _ALPHA
    meaningful = abs(effect) >= exp.min_effect
    # REFUTED requires a defined smallest-effect-of-interest: only then can the
    # whole CI sit inside the "no meaningful effect" band and rule an effect out.
    refuted = (
        exp.min_effect > 0
        and not significant
        and ci_low > -exp.min_effect
        and ci_high < exp.min_effect
    )

    if significant and meaningful and ci_excludes_zero:
        verdict = "CONFIRMED"
    elif refuted:
        verdict = "REFUTED"
    else:
        verdict = "INCONCLUSIVE"

    result |= {
        "verdict": verdict, "mean_a": mean_a, "mean_b": mean_b, "effect": effect,
        "effect_ci_low": ci_low, "effect_ci_high": ci_high, "p_value": p,
        "summary": (
            f"{exp.condition_b} vs {exp.condition_a} on {exp.outcome_metric}: "
            f"Δ={effect:+g} (95% CI {ci_low:+g}..{ci_high:+g}), p={p}, "
            f"n={n_a}/{n_b}. → {verdict}"
        ),
    }
    _persist_result(conn, result)

    if verdict == "CONFIRMED":
        _emit_prior(conn, exp, effect, ci_low, ci_high, mean_a)
    else:
        # A study that is no longer CONFIRMED must not keep actuating a stale prior.
        conn.execute("DELETE FROM experiment_prior WHERE experiment_id = ?", [exp.id])
    return result


def _persist_result(conn: duckdb.DuckDBPyConnection, r: dict) -> None:
    conn.execute(
        """
        INSERT INTO experiment_result
            (experiment_id, verdict, n_a, n_b, mean_a, mean_b, effect,
             effect_ci_low, effect_ci_high, p_value, summary, scored_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now())
        ON CONFLICT (experiment_id) DO UPDATE SET
            verdict = excluded.verdict, n_a = excluded.n_a, n_b = excluded.n_b,
            mean_a = excluded.mean_a, mean_b = excluded.mean_b, effect = excluded.effect,
            effect_ci_low = excluded.effect_ci_low, effect_ci_high = excluded.effect_ci_high,
            p_value = excluded.p_value, summary = excluded.summary, scored_at = now()
        """,
        [
            r["experiment_id"], r["verdict"], r["n_a"], r["n_b"], r["mean_a"], r["mean_b"],
            r["effect"], r["effect_ci_low"], r["effect_ci_high"], r["p_value"], r["summary"],
        ],
    )


def _emit_prior(
    conn: duckdb.DuckDBPyConnection,
    exp: Experiment,
    effect: float,
    ci_low: float,
    ci_high: float,
    mean_a: float,
) -> None:
    """Write the governed personal prior a CONFIRMED experiment justifies. Stored
    as a percent-of-baseline effect so the engine can apply it scale-free."""
    pct = round(effect / mean_a * 100.0, 2) if mean_a else effect
    metric_short = exp.outcome_metric.split(":", 1)[0]
    conn.execute(
        """
        INSERT INTO experiment_prior
            (experiment_id, prior_key, effect, effect_ci_low, effect_ci_high, outcome_metric, active)
        VALUES (?, ?, ?, ?, ?, ?, TRUE)
        ON CONFLICT (experiment_id) DO UPDATE SET
            prior_key = excluded.prior_key, effect = excluded.effect,
            effect_ci_low = excluded.effect_ci_low, effect_ci_high = excluded.effect_ci_high,
            outcome_metric = excluded.outcome_metric, active = TRUE, created_at = now()
        """,
        [exp.id, f"{exp.manipulated}.{metric_short}_pct", pct, ci_low, ci_high, exp.outcome_metric],
    )
    log.info("experiment %s CONFIRMED → prior %s.%s_pct = %+g%%", exp.slug, exp.manipulated,
             metric_short, pct)


def overview(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """One row per experiment with its config, latest result, prior, and per-arm
    adherence counts — everything the Lab UI needs in a single call."""
    exps = conn.execute(
        "SELECT id, slug, hypothesis, manipulated, condition_a, condition_b, outcome_metric, "
        "outcome_direction, min_per_arm, min_effect, started_on, status "
        "FROM experiments ORDER BY preregistered_at DESC"
    ).fetchall()
    out: list[dict] = []
    for e in exps:
        eid = e[0]
        res = conn.execute(
            "SELECT verdict, n_a, n_b, mean_a, mean_b, effect, effect_ci_low, effect_ci_high, "
            "p_value, summary, scored_at FROM experiment_result WHERE experiment_id = ?",
            [eid],
        ).fetchone()
        prior = conn.execute(
            "SELECT prior_key, effect, effect_ci_low, effect_ci_high FROM experiment_prior "
            "WHERE experiment_id = ? AND active = TRUE",
            [eid],
        ).fetchone()
        counts = conn.execute(
            "SELECT assigned_arm, COUNT(*), "
            "COUNT(*) FILTER (WHERE adhered), COUNT(*) FILTER (WHERE outcome_value IS NOT NULL) "
            "FROM experiment_log WHERE experiment_id = ? GROUP BY assigned_arm",
            [eid],
        ).fetchall()
        arms = {
            c[0]: {"days": c[1], "adhered": c[2], "measured": c[3]} for c in counts
        }
        out.append(
            {
                "id": eid,
                "slug": e[1],
                "hypothesis": e[2],
                "manipulated": e[3],
                "condition_a": e[4],
                "condition_b": e[5],
                "outcome_metric": e[6],
                "outcome_direction": e[7],
                "min_per_arm": e[8],
                "min_effect": e[9],
                "started_on": str(e[10]),
                "status": e[11],
                "arms": arms,
                "result": (
                    {
                        "verdict": res[0], "n_a": res[1], "n_b": res[2], "mean_a": res[3],
                        "mean_b": res[4], "effect": res[5], "effect_ci_low": res[6],
                        "effect_ci_high": res[7], "p_value": res[8], "summary": res[9],
                        "scored_at": res[10].isoformat() if res[10] else None,
                    }
                    if res
                    else None
                ),
                "prior": (
                    {"key": prior[0], "effect": prior[1], "ci_low": prior[2], "ci_high": prior[3]}
                    if prior
                    else None
                ),
            }
        )
    return out


def active_priors(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """Confirmed, causal personal priors the engine may act on (read-only)."""
    rows = conn.execute(
        """
        SELECT p.prior_key, p.effect, p.effect_ci_low, p.effect_ci_high, p.outcome_metric,
               e.slug, e.hypothesis
        FROM experiment_prior p JOIN experiments e ON e.id = p.experiment_id
        WHERE p.active = TRUE
        ORDER BY p.created_at DESC
        """
    ).fetchall()
    return [
        {
            "key": r[0], "effect": r[1], "ci_low": r[2], "ci_high": r[3],
            "outcome_metric": r[4], "slug": r[5], "hypothesis": r[6],
        }
        for r in rows
    ]
