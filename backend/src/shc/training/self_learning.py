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
from datetime import date

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
            SUM(e.work_sets)    AS weekly_sets,
            AVG(e.perf_score)   AS mean_perf
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
    productive_vols = sorted(v for v, p in zip(volumes, perfs) if p >= 3.0)

    if len(productive_vols) < 4:  # need at least 4 to get meaningful percentiles
        log.debug(
            "fit_volume_landmarks(%s): only %d productive weeks — skip",
            muscle, len(productive_vols),
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

        # Read the population default to log the delta.
        default = conn.execute(
            "SELECT mev_sets, mav_sets, mrv_sets FROM muscle_volume_targets "
            "WHERE muscle_group = ? AND mesocycle_id = ''",
            [muscle],
        ).fetchone()

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
            [muscle, result["mev"], result["mav"], result["mrv"], meso_id],
        )
        stored += 1

        if default:
            log.info(
                "personal landmark %s: MEV %d→%d  MAV %d→%d  MRV %d→%d  (meso %s)",
                muscle,
                default[0],
                result["mev"],
                default[1],
                result["mav"],
                default[2],
                result["mrv"],
                meso_id[:8],
            )
        else:
            log.info(
                "personal landmark %s: MEV=%d MAV=%d MRV=%d (no population default to compare)",
                muscle,
                result["mev"],
                result["mav"],
                result["mrv"],
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
