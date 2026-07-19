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

from shc.lab import _ALPHA

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
    min_effect: float,
    outcome_direction: str = "higher_better",
    min_per_arm: int = 6,
    washout_hours: int = 0,
    started_on: date | None = None,
    planned_end: date | None = None,
    notes: str | None = None,
) -> str:
    """Register a study before any data is collected. Returns the experiment id.

    ``min_effect`` is the smallest effect worth acting on (in outcome units) and
    is REQUIRED, not optional: it is what makes a REFUTED verdict possible at
    all (see `score()` — `refuted` requires `min_effect > 0` structurally), and
    at the default of 0.0 the study can never be refuted and CONFIRMS on a
    trivially small effect the moment p clears alpha. A study that can't be
    wrong isn't a test of anything — state the smallest effect worth acting on
    before looking at data, not after.

    Raises:
        ValueError: if ``min_effect`` is not strictly positive.
    """
    if min_effect <= 0:
        raise ValueError(
            f"min_effect must be > 0 (got {min_effect}) — a study preregistered at "
            "min_effect=0 can never be REFUTED and trivially CONFIRMS; state the "
            "smallest effect worth acting on before collecting data."
        )
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


def _permutation_p(a: list[float], b: list[float], slug: str) -> float:
    """Two-sided permutation (randomization) test on mean(B) − mean(A).

    The correct significance test for n-of-1: it makes no normality assumption and
    is DEFINED even when an arm has zero within-arm variance (where Welch's t is
    not — a perfectly consistent effect is the *strongest* evidence, and this test
    says so). Exact enumeration of every label split when the count is small; a
    seeded Monte-Carlo approximation otherwise. p is never 0 (the observed split
    always counts), so it can't manufacture false certainty.
    """
    import itertools
    import math
    import random

    pooled = a + b
    n, k = len(pooled), len(a)
    obs = abs(sum(b) / len(b) - sum(a) / len(a))
    total = math.comb(n, k)
    if total <= 20_000:  # exact — every way to split the pooled data into two arms
        ge = 0
        for combo in itertools.combinations(range(n), k):
            idx = set(combo)
            ga = [pooled[i] for i in idx]
            gb = [pooled[i] for i in range(n) if i not in idx]
            if abs(sum(gb) / len(gb) - sum(ga) / len(ga)) >= obs - 1e-9:
                ge += 1
        return round(ge / total, 4)
    # Monte Carlo (add-one smoothing so p is bounded away from 0).
    seed = int(hashlib.sha256(slug.encode()).hexdigest(), 16) % (2**32)
    rng = random.Random(seed)
    n_iter, ge = 5000, 0
    for _ in range(n_iter):
        perm = pooled[:]
        rng.shuffle(perm)
        if abs(sum(perm[k:]) / (n - k) - sum(perm[:k]) / k) >= obs - 1e-9:
            ge += 1
    return round((ge + 1) / (n_iter + 1), 4)


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


def _score_raw(conn: duckdb.DuckDBPyConnection, exp: Experiment) -> dict:
    """Compute an experiment's verdict + effect + bootstrap CI WITHOUT
    persisting or emitting a prior — the pure-compute core shared by `score()`
    (single experiment, no cross-experiment correction) and `score_all()`
    (batch, Benjamini–Hochberg corrected across the batch's p-values before
    anything is written)."""
    rows = conn.execute(
        "SELECT assigned_arm, outcome_value FROM experiment_log "
        "WHERE experiment_id = ? AND adhered = TRUE AND outcome_value IS NOT NULL",
        [exp.id],
    ).fetchall()
    a = [float(v) for arm, v in rows if arm == "A"]
    b = [float(v) for arm, v in rows if arm == "B"]
    n_a, n_b = len(a), len(b)

    result: dict = {"experiment_id": exp.id, "n_a": n_a, "n_b": n_b}

    # A study preregistered before min_effect became required (or written
    # directly to the DB) can have min_effect<=0 — REFUTED is structurally
    # impossible for it (see the `refuted` computation below) and CONFIRMED is
    # reachable on a trivially small effect the moment p clears alpha. Flag it
    # rather than silently scoring a claim that can't be wrong.
    if exp.min_effect <= 0:
        result |= {
            "verdict": "UNFALSIFIABLE", "mean_a": None, "mean_b": None, "effect": None,
            "effect_ci_low": None, "effect_ci_high": None, "p_value": None,
            "summary": (
                f"min_effect={exp.min_effect} — this study cannot be REFUTED and "
                "would CONFIRM on any statistically significant effect regardless "
                "of size. Re-preregister with a positive min_effect to score it."
            ),
        }
        return result

    if n_a < exp.min_per_arm or n_b < exp.min_per_arm:
        result |= {
            "verdict": "INSUFFICIENT_N", "mean_a": None, "mean_b": None, "effect": None,
            "effect_ci_low": None, "effect_ci_high": None, "p_value": None,
            "summary": (
                f"Only {n_a}/{n_b} adhered {exp.condition_a}/{exp.condition_b} days with an "
                f"outcome — need ≥{exp.min_per_arm} per arm."
            ),
        }
        return result

    mean_a, mean_b = round(mean(a), 4), round(mean(b), 4)
    effect = round(mean_b - mean_a, 4)
    p = _permutation_p(a, b, exp.slug)
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
    return result


def _finalize_score(conn: duckdb.DuckDBPyConnection, exp: Experiment, result: dict) -> dict:
    """Persist a scored result and actuate its prior — shared tail of `score()`
    and `score_all()`, called AFTER any cross-experiment correction has already
    settled the final verdict."""
    _persist_result(conn, result)
    if result["verdict"] == "CONFIRMED":
        _emit_prior(
            conn, exp, result["effect"], result["effect_ci_low"], result["effect_ci_high"],
            result["mean_a"],
        )
    else:
        # A study that is no longer CONFIRMED must not keep actuating a stale prior.
        conn.execute("DELETE FROM experiment_prior WHERE experiment_id = ?", [exp.id])
    return result


def score(conn: duckdb.DuckDBPyConnection, exp_id: str) -> dict:
    """Score ONE experiment: N-gated verdict + effect + bootstrap CI, and —
    when CONFIRMED — emit a governed personal prior. Returns the result dict.

    No cross-experiment correction is applied here — scoring a single study in
    isolation has nothing to correct against. Prefer `score_all()` when scoring
    more than one experiment in the same pass; running many single-experiment
    scores back-to-back skips the Benjamini–Hochberg control that path applies.
    """
    exp = load(conn, exp_id)
    if exp is None:
        raise ValueError(f"no experiment {exp_id!r}")
    result = _score_raw(conn, exp)
    return _finalize_score(conn, exp, result)


def _apply_fdr(results: list[dict], alpha: float = _ALPHA) -> None:
    """Benjamini–Hochberg correction across concurrently-scored experiments, in
    place on `results`. Mirrors `lab._apply_fdr`.

    Running N experiments through the same scoring pass without correction
    risks a false CONFIRMED verdict by chance alone as N grows — the audit
    that flagged the missing `min_effect` gate also flagged this: no
    multiplicity control across the portfolio, unlike the observational lab
    catalogue's `_apply_fdr`. A CONFIRMED verdict whose p-value doesn't clear
    the BH step-up critical value is downgraded to INCONCLUSIVE.
    """
    indexed = [(i, r["p_value"]) for i, r in enumerate(results) if r.get("p_value") is not None]
    m = len(indexed)
    if m == 0:
        return
    ordered = sorted(indexed, key=lambda t: t[1])
    max_k = 0
    for rank, (_, p) in enumerate(ordered, start=1):
        if p <= (rank / m) * alpha:
            max_k = rank
    crit_p = ordered[max_k - 1][1] if max_k > 0 else -1.0
    for r in results:
        if r.get("verdict") == "CONFIRMED" and r.get("p_value") is not None and r["p_value"] > crit_p:
            r["verdict"] = "INCONCLUSIVE"
            r["summary"] += (
                " · did not survive Benjamini–Hochberg correction across "
                f"{m} simultaneously-scored experiments — treat as suggestive, not confirmed."
            )


def score_all(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """Score every active experiment together, applying Benjamini–Hochberg
    correction across the batch's p-values BEFORE any result is persisted or
    prior emitted — so a downgraded verdict never briefly writes a stale
    CONFIRMED row or prior. This is the FDR-controlled path; prefer it over
    repeated single-experiment `score()` calls whenever scoring more than one
    experiment."""
    exps = [
        load(conn, row[0])
        for row in conn.execute("SELECT id FROM experiments WHERE status = 'active'").fetchall()
    ]
    exps = [e for e in exps if e is not None]
    results = [_score_raw(conn, e) for e in exps]
    _apply_fdr(results)
    return [_finalize_score(conn, e, r) for e, r in zip(exps, results, strict=True)]


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


# Curated map: lab question_id → candidate n-of-1 experiment spec.
# Only questions whose exposure is a *controllable behavior* are included.
# Non-manipulable questions (skin_temp, strain, energy correlations, etc.)
# are deliberately absent — you can't randomize an arm on them.
_EXPERIMENT_CANDIDATES: dict[str, dict] = {
    "sleep_short_hrv_drop": {
        "slug": "suggest-sleep-timing-hrv",
        "hypothesis": "Getting ≥8h sleep (vs <6.5h) improves next-morning HRV by ≥5ms.",
        "manipulated": "sleep_hours",
        "condition_a": "<6.5h sleep",
        "condition_b": "≥8h sleep",
        "outcome_metric": "hrv_next_morning",
        "outcome_direction": "higher_better",
        "min_per_arm": 8,
        "min_effect": 5.0,
        "vault_ref": "Walker 2017 — Why We Sleep, ch.7",
    },
    "long_sleep_hrv_lift": {
        "slug": "suggest-sleep-timing-hrv",
        "hypothesis": "Getting ≥8h sleep (vs <6.5h) improves next-morning HRV by ≥5ms.",
        "manipulated": "sleep_hours",
        "condition_a": "<6.5h sleep",
        "condition_b": "≥8h sleep",
        "outcome_metric": "hrv_next_morning",
        "outcome_direction": "higher_better",
        "min_per_arm": 8,
        "min_effect": 5.0,
        "vault_ref": "Walker 2017 — Why We Sleep, ch.7",
    },
    "consecutive_training_recovery_drop": {
        "slug": "suggest-rest-day-spacing",
        "hypothesis": "Inserting a rest day between strength sessions improves next-day recovery score by ≥5pts.",
        "manipulated": "training_spacing",
        "condition_a": "consecutive strength days",
        "condition_b": "rest day between sessions",
        "outcome_metric": "recovery_score_next_day",
        "outcome_direction": "higher_better",
        "min_per_arm": 8,
        "min_effect": 5.0,
        "vault_ref": "Israetel 2020 — Ch3 Fatigue Management",
    },
    "rest_day_hrv_rebound": {
        "slug": "suggest-full-rest-day-hrv",
        "hypothesis": "A full rest day (no gym, no cardio) improves next-morning HRV vs any training day.",
        "manipulated": "rest_vs_training",
        "condition_a": "any training session",
        "condition_b": "full rest (no gym, no cardio)",
        "outcome_metric": "hrv_next_morning",
        "outcome_direction": "higher_better",
        "min_per_arm": 10,
        "min_effect": 3.0,
        "vault_ref": "Plews & Laursen 2014 — HRV-guided training",
    },
    "two_pb_3d_hrv_drop": {
        "slug": "suggest-pickleball-density-hrv",
        "hypothesis": "Playing pickleball twice in 3 days depresses next-morning HRV vs once in 3 days.",
        "manipulated": "pickleball_sessions_3d",
        "condition_a": "1 pickleball session in 3 days",
        "condition_b": "2 pickleball sessions in 3 days",
        "outcome_metric": "hrv_next_morning",
        "outcome_direction": "lower_better",
        "min_per_arm": 8,
        "min_effect": 3.0,
        "vault_ref": "Bourdillon 2017 — exercise-HRV recovery",
    },
}


def suggest_experiments(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """Return candidate n-of-1 experiment specs derived from unresolved lab findings.

    Only findings with verdict 'inconclusive' or 'insufficient' are eligible.
    Only question IDs with a *controllable behavior* exposure are mapped (see
    _EXPERIMENT_CANDIDATES). Candidates are suppressed when a study with the
    same slug is already registered in experiments.
    """
    # Latest finding per question
    rows = conn.execute(
        """
        SELECT DISTINCT ON (question_id)
               question_id, verdict
        FROM lab_findings
        WHERE verdict IN ('inconclusive', 'insufficient')
        ORDER BY question_id, run_at DESC
        """
    ).fetchall()
    if not rows:
        return []

    registered_slugs: set[str] = {
        r[0]
        for r in conn.execute("SELECT slug FROM experiments").fetchall()
    }

    seen_suggestion_slugs: set[str] = set()
    candidates: list[dict] = []
    for qid, verdict in rows:
        spec = _EXPERIMENT_CANDIDATES.get(qid)
        if spec is None:
            continue
        slug = spec["slug"]
        if slug in registered_slugs or slug in seen_suggestion_slugs:
            continue
        seen_suggestion_slugs.add(slug)
        # Attach the vault_ref and verdict context
        candidates.append({**spec, "from_question_id": qid, "lab_verdict": verdict})

    return candidates


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
