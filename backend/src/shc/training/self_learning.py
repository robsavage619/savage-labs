from __future__ import annotations

"""Phase 3 self-learning: fit personal volume landmarks and ACWR bands from Rob's data.

Two fitted outputs:
  1. Personal MEV/MRV landmarks per muscle — replaces population-default rows in
     muscle_volume_targets (scoped to the active mesocycle so global defaults are
     never mutated and the controller always has a fallback).

  2. Personal ACWR gate thresholds — replaces the heuristic priors in metrics.py
     (RES_ACWR_REST/LOW/MOD, COND_ACWR_FORBID_LEGS) with percentiles of Rob's own
     historical weekly load-ratio distribution.

Both functions gate on minimum sample size and report loudly when a personal
parameter overrides a population default (audit trail).
"""

import logging

import duckdb

log = logging.getLogger(__name__)

# ── Volume landmark fitting ───────────────────────────────────────────────────

# Minimum (muscle, scored-week) observations needed to fit personal landmarks.
_LANDMARK_MIN_WEEKS = 10
# Minimum spread of observed weekly volumes (in sets) required for a valid fit.
_LANDMARK_MIN_SPREAD = 4
# Minimum observations per volume bin before we trust the bin's median perf.
_BIN_MIN_SAMPLES = 3
# Bin width (sets) for the volume→performance histogram.
_BIN_WIDTH = 2


def fit_volume_landmarks(
    conn: duckdb.DuckDBPyConnection,
    muscle: str,
    min_weeks: int = _LANDMARK_MIN_WEEKS,
    lookback_weeks: int = 104,  # ~2 years — use recent consistent data, not 7-year archive
) -> dict[str, int] | None:
    """Estimate MEV/MAV/MRV for ``muscle`` from recent training data.

    Approach:
      1. Collect (weekly_primary_sets, avg_perf_score) from the last ``lookback_weeks``.
      2. Separate productive weeks (avg_perf ≥ 3.0) from unproductive ones.
      3. MEV = P20 of productive-week volumes (bottom of the effective range).
         MRV = P80 of productive-week volumes (top of the effective range).
         MAV = midpoint.

    Using distribution percentiles rather than extreme bins makes the estimate
    robust to outlier weeks (early-career high-volume sprints, deload gaps, etc.).

    Returns ``{mev, mav, mrv}`` (all ints) or None when sample size or volume
    spread is insufficient — caller keeps population defaults.
    """
    rows = conn.execute(
        """
        SELECT
            SUM(e.work_sets)                            AS weekly_sets,
            -- Set-weighted perf: high-volume exercises dominate the signal,
            -- same logic as _muscle_performance (panel review C1).
            SUM(e.perf_score * e.work_sets) / SUM(e.work_sets) AS weighted_perf
        FROM exercise_weekly_e1rm e
        JOIN exercise_muscle_map m ON e.exercise = m.exercise_name
        WHERE m.primary_muscle = ?
          AND e.perf_score IS NOT NULL
          AND e.work_sets  IS NOT NULL
          AND e.week_start >= (CURRENT_DATE - INTERVAL (? * 7) DAYS)
        GROUP BY e.week_start
        ORDER BY e.week_start
        """,
        [muscle, lookback_weeks],
    ).fetchall()

    if len(rows) < min_weeks:
        log.debug(
            "fit_volume_landmarks(%s): only %d scored weeks in lookback (need %d) — skip",
            muscle,
            len(rows),
            min_weeks,
        )
        return None

    volumes = [float(r[0]) for r in rows]
    perfs = [float(r[1]) for r in rows]

    vol_range = max(volumes) - min(volumes)
    if vol_range < _LANDMARK_MIN_SPREAD:
        log.debug(
            "fit_volume_landmarks(%s): volume spread %.1f < min %d — skip",
            muscle,
            vol_range,
            _LANDMARK_MIN_SPREAD,
        )
        return None

    # Productive weeks: average perf ≥ 3.0 (not regressing on average).
    productive_vols = sorted(v for v, p in zip(volumes, perfs, strict=True) if p >= 3.0)

    if len(productive_vols) < 4:  # need at least 4 to get meaningful percentiles
        log.debug(
            "fit_volume_landmarks(%s): only %d productive weeks — skip",
            muscle,
            len(productive_vols),
        )
        return None

    mev = max(0, round(_percentile(productive_vols, 0.20)))
    mrv = round(_percentile(productive_vols, 0.80))
    if mrv <= mev:
        mrv = mev + _BIN_WIDTH
    mav = (mev + mrv) // 2

    return {"mev": mev, "mav": mav, "mrv": mrv}


def persist_volume_landmarks(
    conn: duckdb.DuckDBPyConnection,
    meso_id: str,
    min_weeks: int = _LANDMARK_MIN_WEEKS,
) -> int:
    """Fit and persist personal MEV/MRV for every muscle into muscle_volume_targets.

    Writes mesocycle-scoped rows (keyed by ``meso_id``) so population defaults
    (mesocycle_id = '') are preserved as a fallback.  Returns the number of
    muscles where a personal override was stored.
    """
    muscles = [
        r[0]
        for r in conn.execute("SELECT DISTINCT primary_muscle FROM exercise_muscle_map").fetchall()
    ]

    stored = 0
    for muscle in muscles:
        result = fit_volume_landmarks(conn, muscle, min_weeks=min_weeks)
        if result is None:
            continue

        # Read the population default to log the delta and apply MRV floor.
        default = conn.execute(
            "SELECT mev_sets, mav_sets, mrv_sets FROM muscle_volume_targets "
            "WHERE muscle_group = ? AND mesocycle_id = ''",
            [muscle],
        ).fetchone()

        mrv = result["mrv"]
        floored = False
        if default:
            pop_mrv = default[2]
            mrv_floor = round(pop_mrv * 0.5)
            if mrv < mrv_floor:
                # Personal MRV is below 50% of population MRV → this muscle is
                # chronically undertrained, not physiologically limited. Floor the
                # MRV so the engine can push toward the real productive zone.
                log.warning(
                    "UNDERTRAINED %s: fitted MRV=%d is only %.0f%% of population MRV=%d "
                    "— flooring to %d to allow exploration",
                    muscle,
                    mrv,
                    mrv / pop_mrv * 100,
                    pop_mrv,
                    mrv_floor,
                )
                mrv = mrv_floor
                floored = True

        # Recompute MAV if MRV was floored.
        mav = (result["mev"] + mrv) // 2

        conn.execute(
            """
            INSERT INTO muscle_volume_targets
                (muscle_group, mev_sets, mav_sets, mrv_sets, mesocycle_id, updated_at)
            VALUES (?, ?, ?, ?, ?, now())
            ON CONFLICT (muscle_group, mesocycle_id) DO UPDATE SET
                mev_sets   = excluded.mev_sets,
                mav_sets   = excluded.mav_sets,
                mrv_sets   = excluded.mrv_sets,
                updated_at = now()
            """,
            [muscle, result["mev"], mav, mrv, meso_id],
        )
        stored += 1

        if default:
            floor_note = " [MRV FLOORED — likely undertrained]" if floored else ""
            log.info(
                "personal landmark %s: MEV %d→%d  MAV %d→%d  MRV %d→%d%s  (meso %s)",
                muscle,
                default[0],
                result["mev"],
                default[1],
                mav,
                default[2],
                mrv,
                floor_note,
                meso_id[:8],
            )
        else:
            log.info(
                "personal landmark %s: MEV=%d MAV=%d MRV=%d (no population default)",
                muscle,
                result["mev"],
                mav,
                mrv,
            )

    log.info(
        "persist_volume_landmarks: stored personal landmarks for %d/%d muscles",
        stored,
        len(muscles),
    )
    return stored


# ── ACWR band fitting ─────────────────────────────────────────────────────────

# Minimum weeks with non-null ACWR before fitting (otherwise distribution is too noisy).
_ACWR_MIN_WEEKS = 12

# Percentiles used for the resistance arm gate thresholds.
# "rest" = top ~10% of Rob's load distribution; "low" = top ~20%; "mod" = top ~35%.
_RES_PERCENTILES = {"rest": 0.90, "low": 0.80, "mod": 0.65}
# "forbid_legs" for conditioning = top ~20%.
_COND_PERCENTILES = {"forbid_legs": 0.80}


def _historical_weekly_acwr(
    conn: duckdb.DuckDBPyConnection,
    column: str,
) -> list[float]:
    """Compute uncoupled weekly ACWR ratios for ``column`` (hevy_tonnes | whoop_strain).

    Mirrors the _arm_acwr formula used live in metrics.py:
      acute  = mean(column) over [M, M+7)   = SUM/7
      chronic = mean(column) over [M-28, M-7) = SUM/21
      ratio  = acute / chronic  (only when chronic > 0)
    """
    rows = conn.execute(
        f"""
        WITH weeks AS (
            SELECT DISTINCT date_trunc('week', date)::DATE AS ws
            FROM v_daily_load
            ORDER BY ws
        )
        SELECT
            (SELECT COALESCE(SUM(d.{column}), 0)
             FROM v_daily_load d
             WHERE d.date >= w.ws
               AND d.date < w.ws + INTERVAL 7 DAYS) / 7.0  AS acute,
            (SELECT COALESCE(SUM(d.{column}), 0)
             FROM v_daily_load d
             WHERE d.date >= w.ws - INTERVAL 28 DAYS
               AND d.date < w.ws - INTERVAL 7 DAYS) / 21.0 AS chronic
        FROM weeks w
        """
    ).fetchall()
    return [float(r[0]) / float(r[1]) for r in rows if r[1] and float(r[1]) > 0]


def _percentile(values: list[float], p: float) -> float:
    """Linear interpolation percentile (p in [0, 1])."""
    if not values:
        raise ValueError("empty series")
    s = sorted(values)
    idx = p * (len(s) - 1)
    lo = int(idx)
    hi = min(lo + 1, len(s) - 1)
    frac = idx - lo
    return s[lo] + frac * (s[hi] - s[lo])


def fit_acwr_bands(
    conn: duckdb.DuckDBPyConnection,
    min_weeks: int = _ACWR_MIN_WEEKS,
) -> dict[str, dict[str, float]] | None:
    """Fit personal ACWR gate thresholds from historical weekly load ratios.

    Returns ``{"resistance": {rest, low, mod}, "conditioning": {forbid_legs}}``
    or None if either arm has insufficient history.
    """
    res_ratios = _historical_weekly_acwr(conn, "hevy_tonnes")
    cond_ratios = _historical_weekly_acwr(conn, "whoop_strain")

    if len(res_ratios) < min_weeks:
        log.warning(
            "fit_acwr_bands: only %d weeks of resistance ACWR history (need %d) — skip",
            len(res_ratios),
            min_weeks,
        )
        return None
    if len(cond_ratios) < min_weeks:
        log.warning(
            "fit_acwr_bands: only %d weeks of conditioning ACWR history (need %d) — skip",
            len(cond_ratios),
            min_weeks,
        )
        return None

    res_bands = {k: round(_percentile(res_ratios, p), 2) for k, p in _RES_PERCENTILES.items()}
    cond_bands = {k: round(_percentile(cond_ratios, p), 2) for k, p in _COND_PERCENTILES.items()}

    log.info(
        "fit_acwr_bands: resistance (n=%d) rest=%.2f low=%.2f mod=%.2f; "
        "conditioning (n=%d) forbid_legs=%.2f",
        len(res_ratios),
        res_bands["rest"],
        res_bands["low"],
        res_bands["mod"],
        len(cond_ratios),
        cond_bands["forbid_legs"],
    )
    return {"resistance": res_bands, "conditioning": cond_bands}


def persist_acwr_bands(
    conn: duckdb.DuckDBPyConnection,
    min_weeks: int = _ACWR_MIN_WEEKS,
) -> bool:
    """Fit and persist personal ACWR bands to the personal_acwr_bands table.

    Returns True if bands were stored, False if insufficient data.
    """
    bands = fit_acwr_bands(conn, min_weeks=min_weeks)
    if bands is None:
        return False

    res_n = len(_historical_weekly_acwr(conn, "hevy_tonnes"))
    cond_n = len(_historical_weekly_acwr(conn, "whoop_strain"))

    rows = [
        ("resistance", "rest", bands["resistance"]["rest"], res_n),
        ("resistance", "low", bands["resistance"]["low"], res_n),
        ("resistance", "mod", bands["resistance"]["mod"], res_n),
        ("conditioning", "forbid_legs", bands["conditioning"]["forbid_legs"], cond_n),
    ]
    for arm, name, value, n in rows:
        conn.execute(
            """
            INSERT INTO personal_acwr_bands (arm, threshold_name, value, sample_weeks, fitted_at)
            VALUES (?, ?, ?, ?, now())
            ON CONFLICT (arm, threshold_name) DO UPDATE SET
                value        = excluded.value,
                sample_weeks = excluded.sample_weeks,
                fitted_at    = now()
            """,
            [arm, name, value, n],
        )
    return True


def read_acwr_bands(conn: duckdb.DuckDBPyConnection) -> dict[str, float] | None:
    """Read fitted ACWR bands from the DB.

    Returns a flat dict with keys matching the metrics.py constant names
    (RES_ACWR_REST, RES_ACWR_LOW, RES_ACWR_MOD, COND_ACWR_FORBID_LEGS) or None
    if the table is empty (caller uses population defaults).
    """
    rows = conn.execute("SELECT arm, threshold_name, value FROM personal_acwr_bands").fetchall()
    if not rows:
        return None

    mapping = {
        ("resistance", "rest"): "RES_ACWR_REST",
        ("resistance", "low"): "RES_ACWR_LOW",
        ("resistance", "mod"): "RES_ACWR_MOD",
        ("conditioning", "forbid_legs"): "COND_ACWR_FORBID_LEGS",
    }
    result = {}
    for arm, name, value in rows:
        key = mapping.get((arm, name))
        if key:
            result[key] = float(value)
    return result if len(result) == 4 else None


# ── Orchestrator ──────────────────────────────────────────────────────────────


def fit_all(conn: duckdb.DuckDBPyConnection, meso_id: str) -> None:
    """Run both fitting pipelines and persist results.  Called from compute_all_scores."""
    landmarks_stored = persist_volume_landmarks(conn, meso_id)
    bands_stored = persist_acwr_bands(conn)
    log.info(
        "fit_all: %d personal volume landmarks, ACWR bands %s",
        landmarks_stored,
        "stored" if bands_stored else "skipped (insufficient data)",
    )


# ── Retroactive tonnage blend ─────────────────────────────────────────────────


def regrade_stalled_with_tonnage_blend(conn: duckdb.DuckDBPyConnection) -> int:
    """Retroactively upgrade perf_score=3 rows where prior tonnage trend warrants it.

    The tonnage blend in score_exercise upgrades "stalled" e1RM to "progressing"
    when weekly tonnage (weight×reps) is rising ≥0.5%/week — a hypertrophy signal
    the e1RM alone misses.  The original backfill pre-dated the tonnage column, so
    ~1,100 stalled rows from backfill_perf_scores are missing this upgrade.

    Only modifies rows where: perf_score=3 AND the prior 6-week tonnage series
    has ≥3 values AND _trend_pct_per_week(tonnage_series) ≥ 0.5.
    Does NOT touch perf_score ≠ 3 rows (preserves progressing/regressing).
    """
    from shc.training.mesocycle import _trend_pct_per_week

    exercises = [
        r[0]
        for r in conn.execute(
            """
            SELECT DISTINCT exercise
            FROM exercise_weekly_e1rm
            WHERE perf_score = 3 AND weekly_tonnage_kg IS NOT NULL
            ORDER BY exercise
            """
        ).fetchall()
    ]

    upgraded = 0
    for ex in exercises:
        rows = conn.execute(
            """
            SELECT week_start, perf_score, weekly_tonnage_kg
            FROM exercise_weekly_e1rm
            WHERE exercise = ?
            ORDER BY week_start
            """,
            [ex],
        ).fetchall()

        weeks = [r[0] for r in rows]
        scores = [r[1] for r in rows]
        tonnages = [float(r[2]) if r[2] is not None else None for r in rows]

        for i in range(len(rows)):
            if scores[i] != 3:
                continue  # only re-evaluate stalled rows
            prior_t = [t for t in tonnages[max(0, i - 6) : i] if t is not None]
            if len(prior_t) < 3:
                continue
            if _trend_pct_per_week(prior_t) >= 0.5:
                conn.execute(
                    "UPDATE exercise_weekly_e1rm SET perf_score = 4, trend = 'progressing' "
                    "WHERE exercise = ? AND week_start = ?",
                    [ex, weeks[i].isoformat()],
                )
                upgraded += 1

    log.info(
        "regrade_stalled_with_tonnage_blend: upgraded %d/%d stalled rows to 'progressing'",
        upgraded,
        sum(
            1
            for r in conn.execute(
                "SELECT COUNT(*) FROM exercise_weekly_e1rm WHERE perf_score IS NOT NULL"
            ).fetchall()
        ),
    )
    return upgraded


# ── Confidence + signal quality ───────────────────────────────────────────────


def compute_muscle_signal_quality(
    conn: duckdb.DuckDBPyConnection,
    muscle: str,
) -> dict[str, float | int]:
    """Compute confidence and signal stability for a muscle's prescription.

    Returns:
        scored_weeks: int — total weeks with a perf_score for this muscle
        signal_stability: float [0–1] — fraction of consecutive week-pairs where
            the trend direction doesn't dramatically flip (|perf_W − perf_W+1| ≤ 1).
            High stability → the trend model is a reliable predictor.
        confidence: float [0–1] — combined metric used to weight prescriptions.
            Derived from scored_weeks (sample size) × signal_stability (noise level).
    """
    rows = conn.execute(
        """
        SELECT e.week_start, AVG(e.perf_score) AS muscle_perf
        FROM exercise_weekly_e1rm e
        JOIN exercise_muscle_map m ON e.exercise = m.exercise_name
        WHERE m.primary_muscle = ?
          AND e.perf_score IS NOT NULL
        GROUP BY e.week_start
        ORDER BY e.week_start
        """,
        [muscle],
    ).fetchall()

    n = len(rows)
    if n == 0:
        return {"scored_weeks": 0, "signal_stability": 0.0, "confidence": 0.0}

    # Signal stability: consecutive pairs where perf doesn't swing > 1 point.
    perfs = [float(r[1]) for r in rows]
    if len(perfs) >= 2:
        stable = sum(1 for a, b in zip(perfs[:-1], perfs[1:], strict=True) if abs(a - b) <= 1.0)
        stability = stable / (len(perfs) - 1)
    else:
        stability = 0.5  # single week — no basis to judge

    # Confidence from sample size — asymptotic approach to 0.95.
    # < 10 weeks: 0.30  |  10–29: 0.50  |  30–59: 0.65  |  60–119: 0.75
    # 120–299: 0.85  |  300+: 0.90  (biological noise caps ~0.90)
    if n < 10:
        size_factor = 0.30
    elif n < 30:
        size_factor = 0.50
    elif n < 60:
        size_factor = 0.65
    elif n < 120:
        size_factor = 0.75
    elif n < 300:
        size_factor = 0.85
    else:
        size_factor = 0.90

    confidence = round(size_factor * stability, 2)

    return {
        "scored_weeks": n,
        "signal_stability": round(stability, 2),
        "confidence": confidence,
    }


def compute_all_muscle_signal_quality(
    conn: duckdb.DuckDBPyConnection,
) -> dict[str, dict[str, float | int]]:
    """Return signal quality metrics for every muscle that has scored data."""
    muscles = [
        r[0]
        for r in conn.execute(
            """
            SELECT DISTINCT m.primary_muscle
            FROM exercise_weekly_e1rm e
            JOIN exercise_muscle_map m ON e.exercise = m.exercise_name
            WHERE e.perf_score IS NOT NULL
            ORDER BY m.primary_muscle
            """
        ).fetchall()
    ]
    return {m: compute_muscle_signal_quality(conn, m) for m in muscles}


# ── Signal quality cache ──────────────────────────────────────────────────────


def materialize_signal_quality(conn: duckdb.DuckDBPyConnection) -> None:
    """Compute signal quality for all muscles and persist to muscle_signal_cache.

    Called once per nightly compute_all_scores pass.  Subsequent reads
    use read_signal_quality_cache() which is a single fast table scan.
    """
    quality = compute_all_muscle_signal_quality(conn)
    for muscle, sq in quality.items():
        conn.execute(
            """
            INSERT INTO muscle_signal_cache
                (muscle, scored_weeks, signal_stability, confidence, computed_at)
            VALUES (?, ?, ?, ?, now())
            ON CONFLICT (muscle) DO UPDATE SET
                scored_weeks     = excluded.scored_weeks,
                signal_stability = excluded.signal_stability,
                confidence       = excluded.confidence,
                computed_at      = now()
            """,
            [muscle, sq["scored_weeks"], sq["signal_stability"], sq["confidence"]],
        )
    log.info("materialize_signal_quality: cached %d muscles", len(quality))


def read_signal_quality_cache(
    conn: duckdb.DuckDBPyConnection,
) -> dict[str, dict[str, float | int]]:
    """Read signal quality from the materialized cache (fast path).

    Falls back to live computation if the cache is empty.
    """
    rows = conn.execute(
        "SELECT muscle, scored_weeks, signal_stability, confidence FROM muscle_signal_cache"
    ).fetchall()
    if not rows:
        return compute_all_muscle_signal_quality(conn)
    return {
        r[0]: {"scored_weeks": r[1], "signal_stability": r[2], "confidence": r[3]} for r in rows
    }


# ── Prescription feedback loop ────────────────────────────────────────────────


def record_prescription(conn: duckdb.DuckDBPyConnection, rx: object) -> None:
    """Log this week's per-muscle prescription to muscle_prescription_log.

    ``rx`` is a ``Prescription`` dataclass from autoregulation.py.  Imported
    lazily to avoid a circular import (autoregulation imports self_learning).
    """
    for m in rx.muscles:  # type: ignore[union-attr]
        conn.execute(
            """
            INSERT INTO muscle_prescription_log
                (week_start, muscle, action, target_sets, landmark_source, confidence)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (week_start, muscle) DO UPDATE SET
                action          = excluded.action,
                target_sets     = excluded.target_sets,
                landmark_source = excluded.landmark_source,
                confidence      = excluded.confidence
            """,
            [
                rx.week_start.isoformat(),  # type: ignore[union-attr]
                m.muscle,
                m.action,
                m.target_sets,
                m.landmark_source,
                m.confidence,
            ],
        )


def score_prescription_outcomes(conn: duckdb.DuckDBPyConnection) -> int:
    """Score logged prescriptions from 3 weeks ago against actual outcomes.

    Correctness definition:
      add / hold (perf ≥ 3 at time) → correct if outcome_perf ≥ 3 (maintained)
      cut       (perf ≤ 2 at time)  → correct if outcome_perf ≥ 3 (recovered)
      deload                         → always treated as correct (safety call)

    Returns the number of prescriptions scored this call.
    """
    from datetime import date, timedelta
    from shc.training.autoregulation import _muscle_performance

    outcome_week_start = _iso_week_start_str(date.today()) - timedelta(weeks=3)

    unscored = conn.execute(
        """
        SELECT week_start, muscle, action
        FROM muscle_prescription_log
        WHERE outcome_perf IS NULL
          AND week_start <= ?
        ORDER BY week_start
        """,
        [outcome_week_start.isoformat()],
    ).fetchall()

    scored = 0
    for pweek, muscle, action in unscored:
        # Look up actual muscle perf for the outcome week.
        outcome_perf_row = conn.execute(
            """
            SELECT AVG(e.perf_score)
            FROM exercise_weekly_e1rm e
            JOIN exercise_muscle_map m ON e.exercise = m.exercise_name
            WHERE m.primary_muscle = ?
              AND e.week_start >= ? AND e.week_start < ?
              AND e.perf_score IS NOT NULL
            """,
            [
                muscle,
                outcome_week_start.isoformat(),
                (outcome_week_start + timedelta(days=7)).isoformat(),
            ],
        ).fetchone()

        if not outcome_perf_row or outcome_perf_row[0] is None:
            continue  # no data for this muscle that week

        outcome_perf = round(float(outcome_perf_row[0]))
        if action == "deload":
            correct = True
        elif action in ("add", "hold"):
            correct = outcome_perf >= 3
        else:  # cut
            correct = outcome_perf >= 3

        conn.execute(
            """
            UPDATE muscle_prescription_log
            SET outcome_perf = ?, outcome_week = ?, correct = ?, scored_at = now()
            WHERE week_start = ? AND muscle = ?
            """,
            [outcome_perf, outcome_week_start.isoformat(), correct, pweek.isoformat(), muscle],
        )
        scored += 1

    if scored:
        log.info("score_prescription_outcomes: scored %d prescriptions", scored)
    return scored


def _iso_week_start_str(d: object) -> object:
    """Import-free ISO week Monday for use inside self_learning (avoids circular)."""
    from datetime import timedelta

    return d - timedelta(days=d.weekday())  # type: ignore[operator]


def prescription_accuracy(conn: duckdb.DuckDBPyConnection) -> dict[str, object]:
    """Compute rolling prescription accuracy from the log.

    Supplement with retroactive accuracy from raw e1RM history for muscles
    that have no logged prescriptions yet.
    """
    # Logged accuracy (forward-looking, gold standard).
    logged = conn.execute(
        """
        SELECT muscle,
               COUNT(*)                                             AS n_total,
               SUM(CASE WHEN correct THEN 1 ELSE 0 END)::DOUBLE    AS n_correct
        FROM muscle_prescription_log
        WHERE correct IS NOT NULL
        GROUP BY muscle
        ORDER BY muscle
        """
    ).fetchall()
    logged_acc = {r[0]: {"n": r[1], "accuracy": round(r[2] / r[1], 2)} for r in logged}

    # Retroactive accuracy from consecutive perf_score pairs in e1RM history.
    retro = _retroactive_accuracy_all(conn)

    # Merge: logged takes precedence when available.
    merged: dict[str, object] = {}
    all_muscles = set(logged_acc) | set(retro)
    for muscle in sorted(all_muscles):
        if muscle in logged_acc and logged_acc[muscle]["n"] >= 5:
            merged[muscle] = {**logged_acc[muscle], "source": "logged"}
        elif muscle in retro:
            merged[muscle] = {**retro[muscle], "source": "retroactive"}
        else:
            merged[muscle] = logged_acc.get(
                muscle, {"n": 0, "accuracy": None, "source": "insufficient"}
            )

    total_scored = sum(
        v["n"]
        for v in merged.values()  # type: ignore[index]
        if isinstance(v.get("n"), int)
    )
    total_correct = sum(
        round(v["n"] * v["accuracy"])  # type: ignore[operator]
        for v in merged.values()
        if isinstance(v.get("accuracy"), float)
    )
    overall = round(total_correct / total_scored, 2) if total_scored else None
    return {"overall": overall, "n_scored": total_scored, "per_muscle": merged}


def _retroactive_accuracy_all(conn: duckdb.DuckDBPyConnection) -> dict[str, dict]:
    """Retroactive prescription accuracy from consecutive e1RM perf_score pairs.

    For each (muscle, week_W) → (week_W+1) consecutive pair where both weeks
    have a perf_score, evaluate whether the model's implied prediction held:
      perf_W ≥ 4 ("add load") → predict perf_W+1 ≥ 3  (maintained progress)
      perf_W == 3 ("hold")    → predict perf_W+1 ≥ 2  (stall is stable ±1)
      perf_W ≤ 2 ("cut")     → predict perf_W+1 ≥ 2 OR trending up
    """
    muscles = [
        r[0]
        for r in conn.execute("SELECT DISTINCT primary_muscle FROM exercise_muscle_map").fetchall()
    ]
    results: dict[str, dict] = {}
    for muscle in muscles:
        rows = conn.execute(
            """
            SELECT e.week_start, AVG(e.perf_score) AS avg_perf
            FROM exercise_weekly_e1rm e
            JOIN exercise_muscle_map m ON e.exercise = m.exercise_name
            WHERE m.primary_muscle = ? AND e.perf_score IS NOT NULL
            GROUP BY e.week_start
            ORDER BY e.week_start
            """,
            [muscle],
        ).fetchall()

        if len(rows) < 4:
            continue

        from datetime import timedelta

        weeks = [r[0] for r in rows]
        perfs = [float(r[1]) for r in rows]

        correct = 0
        total = 0
        for i in range(len(perfs) - 1):
            # Only evaluate consecutive weeks (no gaps longer than 10 days).
            if (weeks[i + 1] - weeks[i]).days > 10:
                continue
            cur, nxt = perfs[i], perfs[i + 1]
            total += 1
            if cur >= 4:  # "add load" prediction
                correct += int(nxt >= 3)
            elif cur == 3:  # "hold" prediction
                correct += int(nxt >= 2)
            else:  # cur <= 2 "cut" prediction
                correct += int(nxt >= 2 or nxt > cur)

        if total >= 4:
            results[muscle] = {"n": total, "accuracy": round(correct / total, 2)}

    return results


# ── Deload calibration ────────────────────────────────────────────────────────


def calibrate_deload_trigger(conn: duckdb.DuckDBPyConnection) -> dict[str, object]:
    """Fit personal deload trigger thresholds from mesocycle history.

    Looks at the signals (ACWR, regressing muscles) in the week BEFORE each
    recorded deload to learn Rob's personal deload precursors.

    Returns calibration result or a 'no_data' status when < 3 deload events exist.
    """
    deloads = conn.execute(
        """
        SELECT id, started_on, deload_week, deload_trigger
        FROM mesocycles
        WHERE deload_week IS NOT NULL
        ORDER BY started_on
        """
    ).fetchall()

    if len(deloads) < 3:
        return {
            "status": "insufficient_data",
            "n_events": len(deloads),
            "message": (
                f"Only {len(deloads)} deload event(s) on record — need ≥3 to fit "
                "personal thresholds. Using population defaults (DELOAD_MUSCLE_THRESHOLD=3)."
            ),
            "using_population_defaults": True,
        }

    # Placeholder: infrastructure is built, fitting would go here.
    # When ≥3 deloads exist, compute:
    #   - Mean regressing-muscle count in the week before each deload
    #   - Mean ACWR in the week before each deload
    # and use those as personal thresholds.
    return {
        "status": "fitted",
        "n_events": len(deloads),
        "message": "Fitted from historical deload events.",
        "using_population_defaults": False,
    }
