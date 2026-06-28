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

    # vmax = highest weekly volume ever attempted (productive or not) — lets
    # the caller distinguish "fitted low because he fails at higher volume"
    # from "fitted low because higher volume was never tried".
    return {"mev": mev, "mav": mav, "mrv": mrv, "vmax": round(max(volumes))}


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
            if mrv < pop_mrv and result["vmax"] < pop_mrv:
                # Fitted MRV is below population AND no week ever reached the
                # population MRV: the fit reflects historical habit, not a
                # recoverability ceiling — a percentile of volumes never tried
                # can't measure a limit. Floor at population MRV so the engine
                # can prescribe into the unexplored range. A genuine personal
                # limit (high-volume weeks attempted and unproductive) keeps
                # its fitted value because vmax >= pop_mrv in that case.
                log.warning(
                    "UNDERTRAINED %s: fitted MRV=%d (max week ever %d) below "
                    "population MRV=%d with no evidence of failure at higher "
                    "volume — flooring to population",
                    muscle,
                    mrv,
                    result["vmax"],
                    pop_mrv,
                )
                mrv = pop_mrv
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

    Mirrors the _arm_acwr formula used live in metrics.py exactly:
      acute   = mean(column) over [ws, ws+7)     = SUM/7
      chronic = mean(column) over [ws-35, ws-7)  = SUM/28  ← 28-day window, not 21
      ratio   = acute / chronic  (only when chronic > 0)

    The chronic window was previously [ws-28, ws-7)/21 (21 days), but metrics.py
    uses a 28-day chronic window. Mismatched windows meant personal ACWR bands
    were fitted on different ratio distributions than the live gates apply — biasing
    all personal thresholds downward (Bug 5).

    Lookback is capped at 104 weeks (same horizon as the volume-landmark
    fitter). Unbounded history pulled in ~7 years of pre-platform low-volume
    eras (sample_weeks=373), whose near-zero ratios dragged every percentile
    threshold down — the bands must describe the current training era.
    """
    rows = conn.execute(
        f"""
        WITH weeks AS (
            SELECT DISTINCT date_trunc('week', date)::DATE AS ws
            FROM v_daily_load
            WHERE date >= (CURRENT_DATE - INTERVAL 728 DAYS)
            ORDER BY ws
        )
        SELECT
            (SELECT COALESCE(SUM(d.{column}), 0)
             FROM v_daily_load d
             WHERE d.date >= w.ws
               AND d.date < w.ws + INTERVAL 7 DAYS) / 7.0  AS acute,
            (SELECT COALESCE(SUM(d.{column}), 0)
             FROM v_daily_load d
             WHERE d.date >= w.ws - INTERVAL 35 DAYS
               AND d.date < w.ws - INTERVAL 7 DAYS) / 28.0 AS chronic
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
    deload_cal = calibrate_deload_trigger(conn)
    log.info(
        "fit_all: %d personal volume landmarks, ACWR bands %s, deload threshold %s",
        landmarks_stored,
        "stored" if bands_stored else "skipped (insufficient data)",
        deload_cal.get("status"),
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

# Coefficient of variation that maps to zero stability. perf scores live on a
# 1–5 scale; a CV of 0.50 (e.g. mean 3, SD 1.5) means the muscle swings across
# most of the scale week to week — no usable trend signal. CVs at/above this
# floor stability to 0.0; everything below scales linearly toward 1.0.
_SIGNAL_CV_REF = 0.50


def compute_muscle_signal_quality(
    conn: duckdb.DuckDBPyConnection,
    muscle: str,
) -> dict[str, float | int]:
    """Compute confidence and signal stability for a muscle's prescription.

    Returns:
        scored_weeks: int — total weeks with a perf_score for this muscle
        signal_stability: float [0–1] — calibrated inverse-dispersion of the
            scored-week perf series. Computed from the coefficient of variation
            (SD / mean) of the perf scores, mapped to [0,1] as
            ``1 − min(1, CV / CV_REF)`` where CV_REF is the CV that maps to zero
            stability. A flat series → 1.0; a wildly noisy one → ~0.0. This
            replaces the old coarse "|Δperf| ≤ 1 step" pair-fraction rule, which
            was insensitive to magnitude and not on a calibrated scale.
        perf_cv: float — raw coefficient of variation of the perf series (0 = no
            dispersion). Exposed so consumers can gate decisions on the underlying
            measure rather than only the squashed stability score.
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
        return {"scored_weeks": 0, "signal_stability": 0.0, "perf_cv": 0.0, "confidence": 0.0}

    # Signal stability from dispersion of the scored-week perf series. We use the
    # coefficient of variation (SD / mean) so the measure is scale-relative and
    # comparable across muscles, then squash to a calibrated [0,1] stability.
    from statistics import mean, pstdev

    perfs = [float(r[1]) for r in rows]
    if len(perfs) >= 2:
        mu = mean(perfs)
        sd = pstdev(perfs)  # population SD: we have the full observed series
        cv = sd / mu if mu > 0 else _SIGNAL_CV_REF
        stability = max(0.0, 1.0 - min(1.0, cv / _SIGNAL_CV_REF))
    else:
        cv = 0.0
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
        "perf_cv": round(cv, 3),
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


# ── Per-(muscle_category, action_type) outcome scoring window ─────────────────
# Hypertrophy signal lag differs by muscle size and action (add vs cut).
# Cut windows are longer because the supercompensation rebound (performance
# temporarily improves post-cut) takes 1-3 weeks — scoring at 3w falsely
# confirms cuts that should have been holds.
# Sources: Schoenfeld 2019; Baz-Valle 2022 meta (N=2058 dose-response).

_MUSCLE_SIZE_CATEGORY: dict[str, str] = {
    "biceps": "small",
    "triceps": "small",
    "delts": "small",
    "shoulders": "small",
    "chest": "medium",
    "back": "medium",
    "lats": "medium",
    "traps": "medium",
    "quads": "large",
    "hamstrings": "large",
    "glutes": "large",
    "legs": "large",
    "calves": "small",
    "core": "medium",
    "abs": "medium",
    "adductors": "medium",
    "forearms": "small",
}

_FEEDBACK_LAG_WEEKS: dict[tuple[str, str], int] = {
    ("small", "add"): 3,
    ("small", "cut"): 4,
    ("small", "hold"): 3,
    ("medium", "add"): 4,
    ("medium", "cut"): 5,
    ("medium", "hold"): 4,
    ("large", "add"): 5,
    ("large", "cut"): 6,
    ("large", "hold"): 4,
}


def _feedback_lag(muscle_group: str, action: str) -> int:
    """Return the number of weeks to wait before scoring a prescription outcome."""
    cat = _MUSCLE_SIZE_CATEGORY.get(muscle_group.lower(), "medium")
    return _FEEDBACK_LAG_WEEKS.get((cat, action), 4)  # default medium/add if unknown


def score_prescription_outcomes(conn: duckdb.DuckDBPyConnection) -> int:
    """Score logged prescriptions against actual outcomes using per-muscle lag windows.

    Correctness definition (directional-outcome semantics — a prescription is
    "correct" only when it produced the change it was prescribed to produce):
      add  (push volume on a progressing muscle) → correct if outcome_perf ≥ 4
            (progression sustained; a slide to a stall means the add was wrong)
      hold (maintain)                            → correct if outcome_perf ≥ 3
            (maintained; a slide to regression is a missed call, not a hit)
      cut  (back off a regressing muscle)        → correct if outcome_perf ≥ 3
            (recovered out of the regression band)
      deload                                      → always correct (safety call)

    Returns the number of prescriptions scored this call.
    """
    from datetime import date, timedelta

    today_week = _iso_week_start_str(date.today())

    # Pull unscored rows that might now be within a scoreable window.
    # We check per-row whether enough lag has passed (lag depends on muscle + action).
    unscored = conn.execute(
        """
        SELECT week_start, muscle, action
        FROM muscle_prescription_log
        WHERE outcome_perf IS NULL
        ORDER BY week_start
        """,
    ).fetchall()

    scored = 0
    for pweek, muscle, action in unscored:
        lag = _feedback_lag(muscle, action)
        this_outcome_week = pweek + timedelta(weeks=lag)
        if this_outcome_week > today_week:
            continue  # not enough time has elapsed yet

        # Deload-confound guard: an ADD/HOLD scored against an outcome week the
        # muscle was DELOADED in is unfair — volume was deliberately halved, so
        # perf naturally dips and the call looks "wrong" when it was not a
        # training failure. Skip (leave unscored) rather than record a false
        # miss. A CUT is still fair to score: a cut and a deload both reduce
        # load, and recovery remains the expected outcome either way.
        if action in ("add", "hold"):
            deloaded = conn.execute(
                "SELECT 1 FROM muscle_prescription_log "
                "WHERE week_start = ? AND muscle = ? AND action = 'deload'",
                [this_outcome_week.isoformat(), muscle],
            ).fetchone()
            if deloaded:
                continue

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
                this_outcome_week.isoformat(),
                (this_outcome_week + timedelta(days=7)).isoformat(),
            ],
        ).fetchone()

        if not outcome_perf_row or outcome_perf_row[0] is None:
            continue  # no data for this muscle that week

        outcome_perf = round(float(outcome_perf_row[0]))
        if action == "deload":
            correct = True
        elif action == "add":
            correct = outcome_perf >= 4  # progression must be sustained, not just stalled
        elif action == "hold":
            correct = outcome_perf >= 3  # maintained, not slid into regression
        else:  # cut — must clear the regression band
            correct = outcome_perf >= 3

        conn.execute(
            """
            UPDATE muscle_prescription_log
            SET outcome_perf = ?, outcome_week = ?, correct = ?, scored_at = now()
            WHERE week_start = ? AND muscle = ?
            """,
            [outcome_perf, this_outcome_week.isoformat(), correct, pweek.isoformat(), muscle],
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


def snapshot_accuracy(conn: duckdb.DuckDBPyConnection) -> dict[str, object]:
    """Persist this ISO week's overall prescription accuracy for drift tracking.

    Idempotent per week (upsert on week_start). Called from compute_all_scores so
    the dashboard can chart whether the engine's calls are improving over time —
    the only honest guard against a single-user fit silently degrading.
    """
    from datetime import date

    acc = prescription_accuracy(conn)
    week = _iso_week_start_str(date.today())
    overall = acc["overall"]
    n_scored = acc["n_scored"]
    conn.execute(
        """
        INSERT INTO engine_accuracy_history (week_start, overall, n_scored, snapshot_at)
        VALUES (?, ?, ?, now())
        ON CONFLICT (week_start) DO UPDATE SET
            overall     = excluded.overall,
            n_scored    = excluded.n_scored,
            snapshot_at = now()
        """,
        [week, overall, n_scored],
    )
    return {"week_start": str(week), "overall": overall, "n_scored": n_scored}


def read_accuracy_history(
    conn: duckdb.DuckDBPyConnection, weeks: int = 26
) -> list[dict[str, object]]:
    """Return the most recent ``weeks`` accuracy snapshots, oldest first."""
    rows = conn.execute(
        """
        SELECT week_start, overall, n_scored
        FROM engine_accuracy_history
        ORDER BY week_start DESC
        LIMIT ?
        """,
        [weeks],
    ).fetchall()
    return [
        {
            "week_start": str(r[0]),
            "overall": float(r[1]) if r[1] is not None else None,
            "n_scored": int(r[2]),
        }
        for r in reversed(rows)
    ]


def _retroactive_accuracy_all(conn: duckdb.DuckDBPyConnection) -> dict[str, dict]:
    """Retroactive prescription accuracy from consecutive e1RM perf_score pairs.

    For each (muscle, week_W) → (week_W+1) consecutive pair where both weeks
    have a perf_score, evaluate whether the model's implied prescription produced
    its *intended directional outcome*. The old predicates rewarded a non-event
    (a regressing muscle that stayed regressing still scored "correct"), which
    inflated the headline accuracy. The tightened logic:

      perf_W ≥ 4 ("add load") — the muscle was progressing and we pushed volume.
        Correct only if it kept progressing: perf_W+1 ≥ 4. Dropping to a stall
        (3) or regression (≤2) means the added load was the wrong call.

      perf_W == 3 ("hold") — maintenance prescription. Correct only if it *stayed*
        maintained or broke upward: perf_W+1 ≥ 3. A slide to ≤2 (the old
        predicate's "nxt ≥ 2") is a missed regression, not a hit.

      perf_W ≤ 2 ("cut" / back-off) — the muscle was regressing and we backed off
        to let it recover. Correct only if it actually recovered or at minimum
        stopped getting worse: perf_W+1 > cur (strict improvement) OR
        perf_W+1 ≥ 3 (cleared the regression band). Staying at the same
        regressing level (nxt == cur ≤ 2) is *not* the intended outcome and now
        scores incorrect — that is the inflation this fix removes.
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
            if cur >= 4:  # "add load" — must keep progressing
                correct += int(nxt >= 4)
            elif cur == 3:  # "hold" — must stay maintained, not slide
                correct += int(nxt >= 3)
            else:  # cur <= 2 "cut" — must recover or at least improve
                correct += int(nxt >= 3 or nxt > cur)

        if total >= 4:
            results[muscle] = {"n": total, "accuracy": round(correct / total, 2)}

    return results


# ── Deload calibration ────────────────────────────────────────────────────────

# Minimum signal-driven deload events needed before we trust a personal threshold.
_DELOAD_MIN_EVENTS = 4
# Clamp the fitted threshold to a sane range. Below 2, a single regressing muscle
# would deload (too twitchy); above 4, fatigue is allowed to compound too far.
_DELOAD_THRESHOLD_FLOOR = 2
_DELOAD_THRESHOLD_CEIL = 4
# Calendar/scheduled deloads carry no fatigue-threshold information — exclude them
# so the fit reflects only deloads Rob took because his body signalled for one.
_CALENDAR_DELOAD_TRIGGERS = ("scheduled",)


def _regressing_precursor_count(
    conn: duckdb.DuckDBPyConnection, deload_start: object
) -> int | None:
    """Regressing-muscle count in the ISO week immediately before a deload.

    Counts distinct primary muscles whose mean perf_score that week was ≤ 2 — the
    same regression definition deload_check() uses live. Returns None when no
    scored exercises exist in that week (the precursor is unobservable).
    """
    from datetime import timedelta

    precursor_week = _iso_week_start_str(deload_start) - timedelta(days=7)  # type: ignore[operator]
    row = conn.execute(
        """
        WITH muscle_perf AS (
            SELECT m.primary_muscle AS muscle, AVG(e.perf_score) AS avg_perf
            FROM exercise_weekly_e1rm e
            JOIN exercise_muscle_map m ON e.exercise = m.exercise_name
            WHERE e.perf_score IS NOT NULL AND e.week_start = ?
            GROUP BY m.primary_muscle
        )
        SELECT COUNT(*) FILTER (WHERE avg_perf <= 2), COUNT(*)
        FROM muscle_perf
        """,
        [precursor_week],
    ).fetchone()
    if not row or not row[1]:  # no scored muscles that week — unobservable
        return None
    return int(row[0])


def calibrate_deload_trigger(conn: duckdb.DuckDBPyConnection) -> dict[str, object]:
    """Fit and persist a personal deload-trigger threshold from deload history.

    For each *signal-driven* deload (excludes scheduled/calendar deloads, which
    carry no fatigue information), measures how many muscles were regressing in
    the week before it fired. The personal threshold is the median of those
    precursor counts, clamped to [2, 4]. Persisted to ``personal_deload_threshold``
    and read live by ``deload_check`` via ``read_deload_threshold``.

    Returns an honest status dict; keeps the population default (3) until enough
    signal deloads exist to fit.
    """
    from statistics import median

    deloads = conn.execute(
        """
        SELECT started_on, deload_week, deload_trigger
        FROM mesocycles
        WHERE deload_week IS NOT NULL
        ORDER BY started_on
        """
    ).fetchall()

    signal_deloads = [d for d in deloads if (d[2] or "scheduled") not in _CALENDAR_DELOAD_TRIGGERS]

    def _insufficient(n: int) -> dict[str, object]:
        return {
            "status": "insufficient_data",
            "n_events": n,
            "threshold": None,
            "population_threshold": 3,
            "message": (
                f"Only {n} signal-driven deload event(s) on record — need "
                f"≥{_DELOAD_MIN_EVENTS} to fit a personal threshold. Using population "
                "default (DELOAD_MUSCLE_THRESHOLD=3)."
            ),
            "using_population_defaults": True,
        }

    if len(signal_deloads) < _DELOAD_MIN_EVENTS:
        return _insufficient(len(signal_deloads))

    from datetime import date, timedelta

    # A deload_week of 1..N indexes which week of the mesocycle the deload landed
    # on; the precursor (last hard week) is started_on + (deload_week - 1) weeks.
    # Guard the calendar math: a missing/out-of-range deload_week or an implausible
    # derived date (before the mesocycle start, or in the future) means the row is
    # mis-recorded — skip it and warn rather than silently locating a wrong week.
    _MAX_MESO_WEEKS = 24  # generous upper bound on a single mesocycle length

    counts: list[int] = []
    skipped = 0
    for started_on, deload_week, _trigger in signal_deloads:
        if deload_week is None:
            skipped += 1
            log.warning(
                "calibrate_deload_trigger: deload (started_on=%s) has no deload_week — skipping",
                started_on,
            )
            continue
        try:
            dw = int(deload_week)
        except (TypeError, ValueError):
            skipped += 1
            log.warning(
                "calibrate_deload_trigger: non-numeric deload_week=%r (started_on=%s) — skipping",
                deload_week,
                started_on,
            )
            continue
        if dw < 1 or dw > _MAX_MESO_WEEKS:
            skipped += 1
            log.warning(
                "calibrate_deload_trigger: deload_week=%d out of range [1,%d] "
                "(started_on=%s) — skipping",
                dw,
                _MAX_MESO_WEEKS,
                started_on,
            )
            continue
        deload_start = started_on + timedelta(weeks=dw - 1)
        if deload_start < started_on or deload_start > date.today():
            skipped += 1
            log.warning(
                "calibrate_deload_trigger: derived deload_start=%s implausible "
                "(started_on=%s, deload_week=%d) — skipping",
                deload_start,
                started_on,
                dw,
            )
            continue
        c = _regressing_precursor_count(conn, deload_start)
        if c is not None:
            counts.append(c)

    if skipped:
        log.warning(
            "calibrate_deload_trigger: skipped %d/%d signal deloads with bad deload_week semantics",
            skipped,
            len(signal_deloads),
        )

    if len(counts) < _DELOAD_MIN_EVENTS:
        # Events exist but their precursor weeks have no scored history.
        return _insufficient(len(counts))

    precursor_median = float(median(counts))
    threshold = max(_DELOAD_THRESHOLD_FLOOR, min(_DELOAD_THRESHOLD_CEIL, round(precursor_median)))

    conn.execute(
        """
        INSERT INTO personal_deload_threshold (id, threshold, n_events, precursor_median, fitted_at)
        VALUES (1, ?, ?, ?, now())
        ON CONFLICT (id) DO UPDATE SET
            threshold        = excluded.threshold,
            n_events         = excluded.n_events,
            precursor_median = excluded.precursor_median,
            fitted_at        = now()
        """,
        [threshold, len(counts), precursor_median],
    )
    log.info(
        "calibrate_deload_trigger: fitted threshold=%d from %d signal deloads "
        "(precursor median=%.1f regressing muscles)",
        threshold,
        len(counts),
        precursor_median,
    )
    return {
        "status": "fitted",
        "n_events": len(counts),
        "threshold": threshold,
        "population_threshold": 3,
        "precursor_median": round(precursor_median, 1),
        "message": (
            f"Personal deload threshold = {threshold} muscle(s) regressing, fitted "
            f"from {len(counts)} signal-driven deloads (median precursor "
            f"{precursor_median:.1f}). Replaces population default of 3."
        ),
        "using_population_defaults": False,
    }


def read_deload_threshold(conn: duckdb.DuckDBPyConnection) -> int | None:
    """Read the fitted personal deload threshold, or None if never fitted."""
    row = conn.execute("SELECT threshold FROM personal_deload_threshold WHERE id = 1").fetchone()
    return int(row[0]) if row and row[0] is not None else None


def read_deload_calibration(conn: duckdb.DuckDBPyConnection) -> dict[str, object]:
    """Read-only deload calibration status for the status endpoint.

    Reports the persisted personal threshold (fitted by ``calibrate_deload_trigger``
    in the write pipeline) without re-fitting. Falls back to the population default
    when no personal threshold has been stored yet.
    """
    row = conn.execute(
        "SELECT threshold, n_events, precursor_median, fitted_at "
        "FROM personal_deload_threshold WHERE id = 1"
    ).fetchone()
    if not row or row[0] is None:
        n_signal = conn.execute(
            "SELECT COUNT(*) FROM mesocycles "
            "WHERE deload_week IS NOT NULL AND COALESCE(deload_trigger, 'scheduled') <> 'scheduled'"
        ).fetchone()
        n = int(n_signal[0]) if n_signal else 0
        return {
            "status": "insufficient_data",
            "n_events": n,
            "threshold": None,
            "population_threshold": 3,
            "using_population_defaults": True,
            "message": (
                f"{n} signal-driven deload(s) on record — need ≥{_DELOAD_MIN_EVENTS} "
                "to fit. Using population default (DELOAD_MUSCLE_THRESHOLD=3)."
            ),
        }
    return {
        "status": "fitted",
        "n_events": int(row[1]),
        "threshold": int(row[0]),
        "population_threshold": 3,
        "precursor_median": round(float(row[2]), 1) if row[2] is not None else None,
        "fitted_at": str(row[3]) if row[3] else None,
        "using_population_defaults": False,
        "message": (
            f"Personal deload threshold = {int(row[0])} regressing muscle(s), fitted "
            f"from {int(row[1])} signal deloads."
        ),
    }


# ── Read paths for autoregulation + training router ───────────────────────────


def read_muscle_prescription_accuracy(
    conn: duckdb.DuckDBPyConnection,
) -> dict[str, dict[str, object]]:
    """Per-muscle historical prescription hit-rate, for weighting next prescriptions.

    Clean read path over the logged/retroactive accuracy already computed by
    ``prescription_accuracy``. Autoregulation can consult a muscle's historical
    accuracy to decide how much to trust the engine's next call for that muscle:
    a muscle the engine has consistently called correctly can take a more
    aggressive prescription; a muscle with a poor hit-rate should be hedged.

    Returns a mapping ``muscle -> {accuracy, n, source}`` where:
        accuracy: float [0–1] | None — None when there is no scoreable history.
        n: int — number of scored (muscle, week) prescription outcomes behind it.
        source: "logged" | "retroactive" | "insufficient" — provenance of the
            estimate so the consumer can down-weight retroactive figures if wanted.

    This is a pure read; it never re-scores. Callers should treat ``accuracy is
    None`` or ``source == "insufficient"`` as "no prior — use the unweighted
    prescription".
    """
    acc = prescription_accuracy(conn)
    per_muscle = acc.get("per_muscle", {})
    out: dict[str, dict[str, object]] = {}
    for muscle, v in per_muscle.items():  # type: ignore[union-attr]
        out[muscle] = {
            "accuracy": v.get("accuracy"),
            "n": int(v.get("n", 0)),
            "source": v.get("source", "insufficient"),
        }
    return out


# Minimum snapshots required before a degradation verdict is meaningful.
_DEGRADATION_MIN_SNAPSHOTS = 6
# Accuracy drop (absolute, on the [0,1] scale) between the older and recent
# halves of the window that counts as a real degradation rather than noise.
_DEGRADATION_DROP_THRESHOLD = 0.08


def detect_accuracy_degradation(
    conn: duckdb.DuckDBPyConnection, weeks: int = 12
) -> dict[str, object]:
    """Detect whether engine prescription accuracy is declining over recent weeks.

    Reads the snapshot history (``read_accuracy_history``) and compares the mean
    accuracy of the older half of the window against the recent half. A material
    drop is surfaced as a structured degradation signal with a suggested
    remediation, so the training-router agent can act (widen the feedback-lag
    windows, flag personal landmarks for a re-fit) without re-deriving the trend.

    The cron wiring lives elsewhere — this function only computes and returns the
    signal; it has no side effects.

    Returns:
        degrading: bool — True when a material, sustained accuracy drop is seen.
        recent_mean / older_mean: float | None — mean accuracy of each half.
        delta: float | None — recent_mean − older_mean (negative = worse).
        n_snapshots: int — snapshots considered.
        suggested_action: str | None — remediation hint when degrading, e.g.
            "widen_feedback_lag" or "refit_landmarks"; None otherwise.
        message: str — human-readable summary (honest about insufficient data).
    """
    history = read_accuracy_history(conn, weeks=weeks)
    scored = [h for h in history if h.get("overall") is not None]
    n = len(scored)
    if n < _DEGRADATION_MIN_SNAPSHOTS:
        return {
            "degrading": False,
            "recent_mean": None,
            "older_mean": None,
            "delta": None,
            "n_snapshots": n,
            "suggested_action": None,
            "message": (
                f"Only {n} accuracy snapshot(s) — need ≥{_DEGRADATION_MIN_SNAPSHOTS} "
                "to judge a trend. No degradation verdict."
            ),
        }

    mid = n // 2
    older = [float(h["overall"]) for h in scored[:mid]]  # type: ignore[arg-type]
    recent = [float(h["overall"]) for h in scored[mid:]]  # type: ignore[arg-type]
    older_mean = sum(older) / len(older)
    recent_mean = sum(recent) / len(recent)
    delta = recent_mean - older_mean
    degrading = delta <= -_DEGRADATION_DROP_THRESHOLD

    if degrading:
        # A deeper drop suggests the landmarks themselves drifted; a shallower one
        # is more consistent with a feedback-lag that's scoring outcomes too early.
        suggested_action = (
            "refit_landmarks" if delta <= -2 * _DEGRADATION_DROP_THRESHOLD else "widen_feedback_lag"
        )
        message = (
            f"Accuracy degrading: {older_mean:.2f} → {recent_mean:.2f} "
            f"(Δ {delta:+.2f}) over {n} snapshots. Suggested action: {suggested_action}."
        )
    else:
        suggested_action = None
        message = (
            f"Accuracy stable: {older_mean:.2f} → {recent_mean:.2f} "
            f"(Δ {delta:+.2f}) over {n} snapshots."
        )

    return {
        "degrading": degrading,
        "recent_mean": round(recent_mean, 2),
        "older_mean": round(older_mean, 2),
        "delta": round(delta, 2),
        "n_snapshots": n,
        "suggested_action": suggested_action,
        "message": message,
    }
