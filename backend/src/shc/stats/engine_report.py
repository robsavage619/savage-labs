"""The engine's report card: does it prescribe accurately, and does it predict?

Two questions this system has never asked about itself, on two different axes.

**Calibration** — when the planner writes "3 x 11 @ 55 lb, RPE 8", does that set
actually land at RPE 8? This measures the load model: whether the weight it
picks produces the effort it intended.

**Predictive validity** — does the morning readiness score have any relationship
to what the training day turns out to be? The gate's entire authority rests on
readiness carrying information about capacity. If it does not, the gate is
ceremony.

NOT the same thing as `training.self_learning.prescription_accuracy`, and the
distinction is worth stating because both will be on screen. That one scores
per-MUSCLE volume decisions against strength OUTCOMES ("did prescribing this
much volume produce the expected e1RM move?"). This one scores per-EXERCISE
effort against INTENT ("did the load land where I aimed it?"). A system can be
excellent at one and useless at the other — as of 2026-09-06 this one is, in
fact, well calibrated and predictively null, which is a real and specific thing
to know about it.

Read-only. Nothing here gates anything.
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from statistics import mean, pstdev

from shc.stats.correlation import correlate

log = logging.getLogger(__name__)

# A miss smaller than this is inside the resolution of a 0-10 RPE scale that
# humans report in halves. Calling a 0.3 discrepancy an error would be
# measuring the scale, not the engine.
_ON_TARGET_RPE = 0.5

# Below this, a correlation is not worth publishing a verdict on.
_MIN_PAIRS = 12


def prescription_calibration(conn, days: int = 365) -> dict:
    """Did prescribed RPE match logged RPE? Bias, spread, and hit rate.

    Args:
        conn: read-only DuckDB connection.
        days: lookback for plans.

    Returns:
        A payload whose headline is `within_target_pct`. `bias` is signed:
        positive means sessions ran HARDER than programmed.
    """
    since = (date.today() - timedelta(days=days)).isoformat()
    plans = conn.execute(
        "SELECT date, plan_json FROM workout_plans WHERE date >= ? ORDER BY date",
        [since],
    ).fetchall()

    # `rpe_target`, not `target_rpe` — the key is easy to guess wrong, and
    # guessing it wrong yields a silent zero-row result rather than an error.
    targets: dict[tuple, float] = {}
    for plan_date, raw in plans:
        try:
            plan = json.loads(raw)
        except (TypeError, ValueError):
            continue
        for block in plan.get("blocks") or []:
            for ex in block.get("exercises") or []:
                target, name = ex.get("rpe_target"), ex.get("name")
                if target is not None and name:
                    targets[(plan_date, name.strip().lower())] = float(target)

    logged = {
        (d, ex): float(rpe)
        for d, ex, rpe in conn.execute(
            """
            SELECT w.started_at::DATE, lower(s.exercise), AVG(s.rpe)
            FROM workouts w JOIN workout_sets s ON s.workout_id = w.id
            WHERE s.is_warmup = FALSE AND s.rpe IS NOT NULL
              AND w.started_at::DATE >= ?
            GROUP BY 1, 2
            """,
            [since],
        ).fetchall()
    }

    pairs = [
        {"date": str(d), "exercise": ex, "target": targets[(d, ex)], "actual": logged[(d, ex)]}
        for (d, ex) in targets
        if (d, ex) in logged
    ]
    for p in pairs:
        p["error"] = round(p["actual"] - p["target"], 2)

    if len(pairs) < _MIN_PAIRS:
        return {
            "n_prescribed": len(targets),
            "n_matched": len(pairs),
            "verdict": "insufficient",
            "detail": f"{len(pairs)} matched pairs; need {_MIN_PAIRS}.",
        }

    errors = [p["error"] for p in pairs]
    bias = mean(errors)
    sd = pstdev(errors)
    se = sd / (len(errors) ** 0.5)
    on_target = sum(1 for e in errors if abs(e) <= _ON_TARGET_RPE)
    biased = abs(bias) > 1.96 * se

    return {
        "n_prescribed": len(targets),
        "n_matched": len(pairs),
        "bias_rpe": round(bias, 3),
        "bias_ci95": [round(bias - 1.96 * se, 3), round(bias + 1.96 * se, 3)],
        "sd_rpe": round(sd, 3),
        "within_target_pct": round(100.0 * on_target / len(errors), 1),
        "harder_than_programmed_pct": round(
            100.0 * sum(1 for e in errors if e > _ON_TARGET_RPE) / len(errors), 1
        ),
        "easier_than_programmed_pct": round(
            100.0 * sum(1 for e in errors if e < -_ON_TARGET_RPE) / len(errors), 1
        ),
        "verdict": "biased" if biased else "calibrated",
        # Named so they can be inspected, because a systematic miss usually
        # belongs to one movement pattern rather than to the model as a whole.
        "worst_misses": sorted(pairs, key=lambda p: -abs(p["error"]))[:5],
        "on_target_window_rpe": _ON_TARGET_RPE,
    }


def readiness_validity(conn, days: int = 365) -> dict:
    """Does the morning readiness score relate to the training day that follows?

    Three correlations, each with a 95% interval. The honest headline is
    `informative`: True only when at least one interval excludes zero.

    A null here does not mean readiness is wrong — it can also mean the gate is
    working (holding volume constant by design) or that the score simply does
    not vary enough to correlate. Which is why the sample and the intervals ship
    alongside the verdict rather than a single word.
    """
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """
        WITH sess AS (
          SELECT w.started_at::DATE d,
                 SUM(s.weight_kg * s.reps) vol,
                 AVG(s.rpe) rpe,
                 COUNT(*) n_sets
          FROM workouts w JOIN workout_sets s ON s.workout_id = w.id
          WHERE s.is_warmup = FALSE AND s.weight_kg > 0 AND s.reps > 0
            AND w.started_at::DATE >= ?
          GROUP BY 1 HAVING COUNT(*) >= 8)
        SELECT r.score, sess.vol, sess.rpe, sess.n_sets
        FROM sess JOIN recovery r ON r.date = sess.d
        WHERE r.score IS NOT NULL AND sess.rpe IS NOT NULL
        """,
        [since],
    ).fetchall()

    if len(rows) < _MIN_PAIRS:
        return {"n": len(rows), "verdict": "insufficient", "correlations": {}}

    score = [float(r[0]) for r in rows]
    against = {
        "session_volume_load": [float(r[1]) for r in rows],
        "mean_session_rpe": [float(r[2]) for r in rows],
        "working_sets": [float(r[3]) for r in rows],
    }
    correlations = {k: correlate(score, v) for k, v in against.items()}
    informative = any(c["excludes_zero"] for c in correlations.values())

    return {
        "n": len(rows),
        "correlations": correlations,
        "informative": informative,
        "verdict": "predictive" if informative else "no detectable relationship",
        "caveat": (
            "A null is not proof readiness is meaningless: the gate may be holding "
            "the session constant by design, which is what a working gate looks "
            "like. It does mean readiness cannot currently be shown to carry "
            "information about capacity."
        ),
    }


# The four inputs to `metrics._readiness_snapshot`, mapped to the raw columns
# that stand in for each subscore. Weights are the live DEFAULT_WEIGHTS; they
# are quoted here only so the report can show weight against evidence side by
# side. Nothing here reads or writes them.
_READINESS_COMPONENTS = (
    ("hrv", 0.40, "recovery.hrv"),
    ("sleep", 0.30, "sleep hours"),
    ("rhr", 0.20, "recovery.rhr"),
)


def component_validity(conn, days: int = 365) -> dict:
    """Which INPUT to the readiness composite actually predicts the session?

    The composite is a weighted blend, so a null on the whole score cannot say
    which part is dead weight. This splits it.

    Two things make the split worth reporting rather than acting on directly:
    HRV and RHR correlate at about -0.75 across this subject's history, so 0.60
    of the composite is largely one underlying signal wearing two hats; and the
    codebase ALREADY contains a weighting that trusts sleep over autonomic tone
    (`metrics.BETA_BLOCKER_WEIGHTS`, sleep 0.50 / hrv 0.15 / rhr 0.10) which
    fires only on beta-blocker days — and the beta-blocker here is PRN, so it
    almost never runs.

    This function does NOT change any weight. Re-weighting readiness is a gate
    change and needs an invariant update plus a DECISIONS.md entry
    (ENGINE_INVARIANTS.md, "the rule for changing the engine"), not one
    marginal correlation on a small sample. The point of shipping it is that
    the evidence accumulates in the open until it is or is not strong enough.
    """
    since = (date.today() - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """
        WITH sess AS (
          SELECT w.started_at::DATE d, SUM(s.weight_kg * s.reps) vol,
                 AVG(s.rpe) rpe, COUNT(*) n_sets
          FROM workouts w JOIN workout_sets s ON s.workout_id = w.id
          WHERE s.is_warmup = FALSE AND s.weight_kg > 0 AND s.reps > 0
            AND w.started_at::DATE >= ?
          GROUP BY 1 HAVING COUNT(*) >= 8),
        sl AS (
          SELECT night_date d,
                 arg_max(epoch(ts_out - ts_in) / 3600.0, epoch(ts_out - ts_in)) hrs
          FROM sleep
          WHERE COALESCE(is_nap, FALSE) = FALSE AND ts_in IS NOT NULL AND ts_out IS NOT NULL
          GROUP BY 1)
        SELECT r.hrv, sl.hrs, r.rhr, sess.vol, sess.rpe, sess.n_sets
        FROM sess JOIN recovery r ON r.date = sess.d LEFT JOIN sl ON sl.d = sess.d
        WHERE sess.rpe IS NOT NULL
        """,
        [since],
    ).fetchall()

    if len(rows) < _MIN_PAIRS:
        return {"n": len(rows), "verdict": "insufficient", "components": {}}

    outcomes = {"session_volume_load": 3, "mean_session_rpe": 4, "working_sets": 5}
    out: dict[str, dict] = {}
    for i, (name, weight, source) in enumerate(_READINESS_COMPONENTS):
        per = {}
        for oname, oi in outcomes.items():
            pairs = [(float(r[i]), float(r[oi])) for r in rows if r[i] is not None and r[oi] is not None]
            per[oname] = correlate([p[0] for p in pairs], [p[1] for p in pairs])
        out[name] = {
            "weight": weight,
            "source": source,
            "vs": per,
            # The headline per component: does it predict ANY outcome at all?
            "predicts_anything": any(v["excludes_zero"] for v in per.values()),
        }

    carrying = [k for k, v in out.items() if v["predicts_anything"]]
    dead_weight = round(sum(v["weight"] for k, v in out.items() if not v["predicts_anything"]), 2)
    return {
        "n": len(rows),
        "components": out,
        "components_carrying_signal": carrying,
        # How much of the composite's weight sits on inputs with no detectable
        # relationship to the session. Reported, never acted on.
        "weight_on_silent_components": dead_weight,
        "note": (
            "Re-weighting readiness is a gate change requiring an invariant update "
            "and a DECISIONS.md entry. This measures; it does not decide."
        ),
    }


def report_card(conn, days: int = 365) -> dict:
    """Both axes, plus the one-line read."""
    cal = prescription_calibration(conn, days)
    val = readiness_validity(conn, days)
    comp = component_validity(conn, days)
    return {
        "as_of": date.today().isoformat(),
        "window_days": days,
        "calibration": cal,
        "predictive_validity": val,
        "component_validity": comp,
        "summary": _summarise(cal, val),
    }


def _summarise(cal: dict, val: dict) -> str:
    if cal.get("verdict") == "insufficient" or val.get("verdict") == "insufficient":
        return "Not enough matched history yet to grade the engine."
    c = (
        f"lands within {cal['on_target_window_rpe']} RPE of target "
        f"{cal['within_target_pct']:.0f}% of the time"
        if cal["verdict"] == "calibrated"
        else f"runs {cal['bias_rpe']:+.2f} RPE off target systematically"
    )
    v = (
        "and readiness predicts the session that follows"
        if val.get("informative")
        else "but readiness shows no detectable relationship to the session that follows"
    )
    return f"The planner {c}, {v}."
