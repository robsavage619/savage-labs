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

from shc.training.volume import muscle_weekly_volume_series

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
    # Correctly-credited weekly volume using the same warmup/rep/RPE gates and
    # primary+secondary credit rates as weekly_muscle_volume — so fitted landmarks
    # and the live controller are on the same scale.
    vol_series = muscle_weekly_volume_series(conn, muscle, lookback_weeks)

    # Perf signal (exercise-level trend, set-weighted) — unchanged.
    perf_rows = conn.execute(
        """
        SELECT
            e.week_start,
            SUM(e.perf_score * e.work_sets) / NULLIF(SUM(e.work_sets), 0) AS weighted_perf
        FROM exercise_weekly_e1rm e
        JOIN exercise_muscle_map m ON e.exercise = m.exercise_name
        WHERE m.primary_muscle = ?
          AND e.perf_score IS NOT NULL
          AND e.work_sets  IS NOT NULL
          AND e.week_start >= (CURRENT_DATE - INTERVAL (? || ' weeks'))
        GROUP BY e.week_start
        """,
        [muscle, str(lookback_weeks)],
    ).fetchall()
    perf_by_week: dict[str, float] = {str(r[0]): float(r[1]) for r in perf_rows}

    # Deload weeks — intentionally reduced volume, must not anchor the MRV floor.
    deload_weeks: set[str] = {
        str(r[0])
        for r in conn.execute(
            """
            SELECT DISTINCT week_start
            FROM muscle_prescription_log
            WHERE muscle = ? AND action = 'deload'
            """,
            [muscle],
        ).fetchall()
    }

    if len(vol_series) < min_weeks:
        log.debug(
            "fit_volume_landmarks(%s): only %d credited-volume weeks in lookback (need %d) — skip",
            muscle,
            len(vol_series),
            min_weeks,
        )
        return None

    # Merge volume + perf, skipping deload weeks.
    volumes: list[float] = []
    perfs: list[float] = []
    for week_str, credited_sets in vol_series:
        if week_str in deload_weeks:
            continue
        perf = perf_by_week.get(week_str)
        if perf is None:
            continue
        volumes.append(credited_sets)
        perfs.append(perf)

    if len(volumes) < min_weeks:
        log.debug(
            "fit_volume_landmarks(%s): only %d weeks after deload exclusion (need %d) — skip",
            muscle,
            len(volumes),
            min_weeks,
        )
        return None

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
        mev = result["mev"]
        floored = False
        mev_floored = False
        if default:
            pop_mev, pop_mrv = default[0], default[2]
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
            # MEV is the ADAPTATION FLOOR (vault: ~10 hard sets/wk for most muscles;
            # "volume below MEV maintains fitness but does not produce new
            # hypertrophy"). A personal MEV fitted below population reflects a
            # low-volume HABIT, not a lower growth threshold — and would silently
            # park the muscle below the volume that grows it (it reads "in range"
            # while actually starved). Unlike MRV (a ceiling that only floors when
            # the higher range was never tried), MEV floors ALWAYS: dropping below
            # the growth floor is never the right call for a hypertrophy goal.
            if mev < pop_mev:
                log.info(
                    "MEV floor %s: fitted MEV=%d below population MEV=%d — flooring "
                    "(below-MEV habit would starve the muscle)",
                    muscle,
                    mev,
                    pop_mev,
                )
                mev = pop_mev
                mev_floored = True

        # MAV is the midpoint of the (possibly floored) MEV/MRV.
        mav = (mev + mrv) // 2

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
            [muscle, mev, mav, mrv, meso_id],
        )
        stored += 1

        if default:
            notes = []
            if floored:
                notes.append("MRV FLOORED — likely undertrained")
            if mev_floored:
                notes.append("MEV FLOORED to growth floor")
            floor_note = f" [{'; '.join(notes)}]" if notes else ""
            log.info(
                "personal landmark %s: MEV %d→%d  MAV %d→%d  MRV %d→%d%s  (meso %s)",
                muscle,
                default[0],
                mev,
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
                mev,
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

    Mirrors the live ``_arm_acwr`` formula in metrics.py (lines ~890-899) EXACTLY —
    the personal percentile bands are only meaningful if fitted on the same ratio
    scale the live gate scores against:
      acute   = mean(column) over the 7-day acute week  [ws, ws+7)     = SUM/7
      chronic = mean(column) over the 21 days IMMEDIATELY BEFORE it     = SUM/21
                [ws-21, ws)  — contiguous with acute, no gap, no overlap (uncoupled)
      ratio   = acute / chronic  (only when chronic > 0)

    HISTORY: this fitter previously used a 28-day chronic window [ws-35, ws-7)/28
    whose docstring wrongly claimed metrics.py "uses a 28-day chronic window."
    metrics.py uses a 21-day UNCOUPLED chronic ([today-27, today-7)/21), so that
    "fix" moved the fitter AWAY from the live gate — every personal band (rest/low/
    mod resistance + conditioning forbid_legs) was fitted on a distribution the gate
    never produces, biasing the conditioning leg-forbid band (the one that can
    tighten). Now realigned to the live 7:21 uncoupled window.

    Also mirrors metrics._ACWR_MIN_CHRONIC_DAYS: a week whose chronic window has
    fewer than that many nonzero-load days is excluded from the fitted sample —
    the live gate treats that ratio as unscoreable (too thin to trust, see
    metrics._arm_acwr), so a fitted percentile band must not be built partly
    from ratios the gate itself would never produce.

    Lookback is capped at 104 weeks (same horizon as the volume-landmark
    fitter). Unbounded history pulled in ~7 years of pre-platform low-volume
    eras (sample_weeks=373), whose near-zero ratios dragged every percentile
    threshold down — the bands must describe the current training era.
    """
    from shc.metrics import _ACWR_MIN_CHRONIC_DAYS

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
             WHERE d.date >= w.ws - INTERVAL 21 DAYS
               AND d.date < w.ws) / 21.0 AS chronic,
            (SELECT COUNT(*)
             FROM v_daily_load d
             WHERE d.date >= w.ws - INTERVAL 21 DAYS
               AND d.date < w.ws
               AND d.{column} > 0) AS chronic_days
        FROM weeks w
        """
    ).fetchall()
    return [
        float(r[0]) / float(r[1])
        for r in rows
        if r[1] and float(r[1]) > 0 and r[2] and int(r[2]) >= _ACWR_MIN_CHRONIC_DAYS
    ]


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


# Max downward move (tightening) of the personal conditioning forbid_legs band
# per fit, and the hard floor it can never cross. Conditioning is the one ACWR
# band that can actually tighten the gate (resistance is floor_only downstream —
# see metrics._gates). That creates a feedback risk the audit named: a tighter
# forbid_legs suppresses leg training → lowers the load distribution the NEXT
# fit draws from → tightens further. Loosening (the band moving UP) is
# unclamped — only the direction that reduces training gets rate-limited.
_COND_TIGHTEN_MAX_STEP = 0.1
_COND_TIGHTEN_FLOOR_FACTOR = 0.85


def persist_acwr_bands(
    conn: duckdb.DuckDBPyConnection,
    min_weeks: int = _ACWR_MIN_WEEKS,
) -> bool:
    """Fit and persist personal ACWR bands to the personal_acwr_bands table.

    Returns True if bands were stored, False if insufficient data.
    """
    from shc.metrics import COND_ACWR_FORBID_LEGS

    bands = fit_acwr_bands(conn, min_weeks=min_weeks)
    if bands is None:
        return False

    res_n = len(_historical_weekly_acwr(conn, "hevy_tonnes"))
    cond_n = len(_historical_weekly_acwr(conn, "whoop_strain"))

    prior_forbid = conn.execute(
        "SELECT value FROM personal_acwr_bands "
        "WHERE arm = 'conditioning' AND threshold_name = 'forbid_legs'"
    ).fetchone()
    new_forbid = bands["conditioning"]["forbid_legs"]
    if prior_forbid is not None:
        prior_value = float(prior_forbid[0])
        hard_floor = COND_ACWR_FORBID_LEGS * _COND_TIGHTEN_FLOOR_FACTOR
        if new_forbid < prior_value:
            clamped = max(new_forbid, prior_value - _COND_TIGHTEN_MAX_STEP, hard_floor)
            if clamped != new_forbid:
                log.info(
                    "persist_acwr_bands: conditioning forbid_legs tighten clamped "
                    "%.2f -> %.2f -> %.2f (max step %.2f, floor %.2f)",
                    prior_value,
                    new_forbid,
                    clamped,
                    _COND_TIGHTEN_MAX_STEP,
                    hard_floor,
                )
            new_forbid = clamped
    bands["conditioning"]["forbid_legs"] = new_forbid

    rows = [
        ("resistance", "rest", bands["resistance"]["rest"], res_n),
        ("resistance", "low", bands["resistance"]["low"], res_n),
        ("resistance", "mod", bands["resistance"]["mod"], res_n),
        ("conditioning", "forbid_legs", new_forbid, cond_n),
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


def acwr_fit_data_changed_since_last_fit(conn: duckdb.DuckDBPyConnection) -> bool:
    """Whether any workout/sleep/cardio data is newer than the last ACWR fit.

    Re-fitting deterministic percentile bands on an UNCHANGED dataset produces
    the same parameters — a logged "re-fit triggered" that is actually a no-op.
    The nightly job's accuracy-degradation branch calls fit_all() moments after
    compute_all_scores() already fit on the same data in the same run; without
    this guard that call always re-fits nothing while looking like a
    self-correction (and feeds the conditioning-tighten spiral risk
    _COND_TIGHTEN_MAX_STEP exists to bound). No prior fit at all counts as
    "changed" — there's nothing to skip re-fitting.
    """
    last_fit = conn.execute("SELECT MAX(fitted_at) FROM personal_acwr_bands").fetchone()
    if not last_fit or last_fit[0] is None:
        return True
    fitted_at = last_fit[0]

    latest_data = conn.execute(
        """
        SELECT GREATEST(
            COALESCE((SELECT MAX(started_at) FROM workouts), TIMESTAMP '1970-01-01'),
            COALESCE((SELECT MAX(night_date)::TIMESTAMP FROM sleep), TIMESTAMP '1970-01-01'),
            COALESCE((SELECT MAX(date)::TIMESTAMP FROM cardio_sessions), TIMESTAMP '1970-01-01')
        )
        """
    ).fetchone()
    if not latest_data or latest_data[0] is None:
        return False
    return bool(latest_data[0] > fitted_at)


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


# ── Sleep-architecture band fitting ───────────────────────────────────────────
#
# disturbance_count and sleep_cycle_count gates in metrics.py used fixed
# population thresholds with no personal baseline, unlike every other
# autonomic gate. Rob has diagnosed, off-CPAP obstructive sleep apnea, which
# structurally elevates disturbance counts and fragments cycle counts most
# nights regardless of whether a given night is unusually bad for him. This
# fits personal percentiles so the gate reacts to deviation from his own
# baseline instead of a population norm his condition guarantees he'll clear.

# Minimum nights with non-null values before fitting (otherwise the
# distribution is too noisy to trust). Nightly data accrues far faster than
# the weekly ACWR series, so 30 nights (~1 month) is enough to describe a
# stable baseline without waiting a full quarter.
_SLEEP_MIN_NIGHTS = 30

# Lookback window for the historical query. Capped (unlike an unbounded scan)
# so a stale early-WHOOP or pre-diagnosis era doesn't bias the percentile —
# same rationale as the ACWR fitter's 728-day cap, just tighter since sleep
# architecture is a more stable trait than training load.
_SLEEP_LOOKBACK_DAYS = 180

# disturbance_count: gate fires ABOVE the threshold, so "high but normal for
# Rob" sits in the upper tail — 80th percentile of his own nights.
# sleep_cycle_count: gate fires BELOW the threshold, so "low but normal for
# Rob" sits in the lower tail — 20th percentile of his own nights.
_SLEEP_PERCENTILES = {"disturbance_count": 0.80, "sleep_cycle_count": 0.20}


def _historical_sleep_metric(conn: duckdb.DuckDBPyConnection, column: str) -> list[float]:
    """Per-night history of ``column`` (disturbance_count | sleep_cycle_count).

    Collapses multi-segment nights to the longest session and excludes naps —
    mirrors the dedup in metrics.py's ``_sleep()`` so the fitted distribution
    matches what the live gate actually sees.
    """
    rows = conn.execute(
        f"""
        SELECT night_date, epoch(ts_out - ts_in) AS dur, {column}
        FROM sleep
        WHERE night_date >= (CURRENT_DATE - INTERVAL '{_SLEEP_LOOKBACK_DAYS} DAYS')
          AND ts_in IS NOT NULL AND ts_out IS NOT NULL
          AND COALESCE(is_nap, FALSE) = FALSE
          AND {column} IS NOT NULL
        ORDER BY night_date, ts_in
        """
    ).fetchall()
    by_night: dict[str, tuple[float, float]] = {}
    for night_date, dur, val in rows:
        key = str(night_date)
        prev = by_night.get(key)
        if prev is None or (dur or 0) > prev[0]:
            by_night[key] = (dur or 0, val)
    return [float(v) for _, v in by_night.values()]


def fit_sleep_bands(
    conn: duckdb.DuckDBPyConnection,
    min_nights: int = _SLEEP_MIN_NIGHTS,
) -> dict[str, float] | None:
    """Fit personal sleep-architecture gate thresholds from nightly history.

    Returns ``{"disturbance_p80", "cycle_p20", "disturbance_n", "cycle_n"}``
    or None if either metric has insufficient history.
    """
    disturbance_vals = _historical_sleep_metric(conn, "disturbance_count")
    cycle_vals = _historical_sleep_metric(conn, "sleep_cycle_count")

    if len(disturbance_vals) < min_nights or len(cycle_vals) < min_nights:
        log.warning(
            "fit_sleep_bands: only %d/%d nights of disturbance/cycle history (need %d) — skip",
            len(disturbance_vals),
            len(cycle_vals),
            min_nights,
        )
        return None

    disturbance_p80 = round(
        _percentile(disturbance_vals, _SLEEP_PERCENTILES["disturbance_count"]), 1
    )
    cycle_p20 = round(_percentile(cycle_vals, _SLEEP_PERCENTILES["sleep_cycle_count"]), 1)

    log.info(
        "fit_sleep_bands: disturbance p80=%.1f (n=%d), cycle p20=%.1f (n=%d)",
        disturbance_p80,
        len(disturbance_vals),
        cycle_p20,
        len(cycle_vals),
    )
    return {
        "disturbance_p80": disturbance_p80,
        "cycle_p20": cycle_p20,
        "disturbance_n": len(disturbance_vals),
        "cycle_n": len(cycle_vals),
    }


def persist_sleep_bands(
    conn: duckdb.DuckDBPyConnection,
    min_nights: int = _SLEEP_MIN_NIGHTS,
) -> bool:
    """Fit and persist personal sleep bands to the personal_sleep_bands table.

    Returns True if bands were stored, False if insufficient data.
    """
    bands = fit_sleep_bands(conn, min_nights=min_nights)
    if bands is None:
        return False

    rows = [
        ("disturbance_count", "p80", bands["disturbance_p80"], bands["disturbance_n"]),
        ("sleep_cycle_count", "p20", bands["cycle_p20"], bands["cycle_n"]),
    ]
    for metric, name, value, n in rows:
        conn.execute(
            """
            INSERT INTO personal_sleep_bands (metric, threshold_name, value, sample_nights, fitted_at)
            VALUES (?, ?, ?, ?, now())
            ON CONFLICT (metric, threshold_name) DO UPDATE SET
                value         = excluded.value,
                sample_nights = excluded.sample_nights,
                fitted_at     = now()
            """,
            [metric, name, value, n],
        )
    return True


def read_sleep_bands(conn: duckdb.DuckDBPyConnection) -> dict[str, float] | None:
    """Read fitted sleep bands from the DB.

    Returns a flat dict with keys matching the metrics.py constant names
    (DISTURBANCE_P80, CYCLE_P20) or None if the table is empty (caller uses
    population defaults).
    """
    rows = conn.execute("SELECT metric, threshold_name, value FROM personal_sleep_bands").fetchall()
    if not rows:
        return None

    mapping = {
        ("disturbance_count", "p80"): "DISTURBANCE_P80",
        ("sleep_cycle_count", "p20"): "CYCLE_P20",
    }
    result = {}
    for metric, name, value in rows:
        key = mapping.get((metric, name))
        if key:
            result[key] = float(value)
    return result if len(result) == 2 else None


# ── Orchestrator ──────────────────────────────────────────────────────────────


def fit_all(conn: duckdb.DuckDBPyConnection, meso_id: str) -> None:
    """Run both fitting pipelines and persist results.  Called from compute_all_scores."""
    landmarks_stored = persist_volume_landmarks(conn, meso_id)
    bands_stored = persist_acwr_bands(conn)
    sleep_bands_stored = persist_sleep_bands(conn)
    deload_cal = calibrate_deload_trigger(conn)
    log.info(
        "fit_all: %d personal volume landmarks, ACWR bands %s, sleep bands %s, deload threshold %s",
        landmarks_stored,
        "stored" if bands_stored else "skipped (insufficient data)",
        "stored" if sleep_bands_stored else "skipped (insufficient data)",
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

# An OLS line burns 2 degrees of freedom, so its residual scatter is only a
# trustworthy noise estimate once at least this many are left (n - 2 >= 3, i.e.
# n >= 5). Below that, 3-4 coincidentally-linear points (trivial with integer
# 1-5 perf scores — "3, 4, 5" fits a line with zero residual) read as PERFECT
# stability by pure chance, not genuine signal quality. Capping stability at the
# same 0.5 neutral prior the <3-point case already uses closes that gap (the
# audit found a muscle with exactly 3 scored weeks could reach stability=1.0 and,
# combined with the old size_factor step, land at confidence == _CONFIDENCE_FULL
# — full +2/wk ADD authority on three data points).
_STABILITY_MIN_RESIDUAL_DOF = 3

# (scored_weeks, size_factor) anchors for a monotone piecewise-linear ramp — the
# continuous replacement for the old step function, which jumped straight from
# 0.30 (n<10) to 0.50 (n=10): a muscle scored on the last day of one bucket vs
# the first day of the next got a confidence discontinuity for one more week of
# data. Anchored so size_factor(10) == 0.30 == _CONFIDENCE_FULL: a muscle needs
# BOTH >=10 scored weeks AND perfect stability to earn full ADD authority — the
# n=3 case above could reach 0.30 at n=9 under the old buckets. 30/60/120/300
# preserve the old right-edge values so the "well-tracked muscle" calibration
# story in autoregulation.py's _CONFIDENCE_FULL/_LARGE_ADD_CONFIDENCE_BAR
# comments stays accurate. Biological noise caps stability well under 1.0 in
# practice, so 0.90 at n>=600 is asymptotic, not a real per-muscle ceiling.
_SIZE_FACTOR_ANCHORS: tuple[tuple[int, float], ...] = (
    (0, 0.0),
    (6, 0.20),
    (10, 0.30),
    (30, 0.50),
    (60, 0.65),
    (120, 0.75),
    (300, 0.85),
    (600, 0.90),
)


def _signal_size_factor(n: int) -> float:
    """Confidence weight from sample size — see :data:`_SIZE_FACTOR_ANCHORS`."""
    anchors = _SIZE_FACTOR_ANCHORS
    if n <= anchors[0][0]:
        return anchors[0][1]
    if n >= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:], strict=False):
        if x0 <= n <= x1:
            frac = (n - x0) / (x1 - x0)
            return y0 + frac * (y1 - y0)
    return anchors[-1][1]  # unreachable given the bounds checks above


def compute_muscle_signal_quality(
    conn: duckdb.DuckDBPyConnection,
    muscle: str,
) -> dict[str, float | int]:
    """Compute confidence and signal stability for a muscle's prescription.

    Deload weeks are EXCLUDED from the series (their perf is low by design), and
    stability is measured around the TREND, not the level — so a steadily climbing
    muscle reads as a clean signal, not noise.

    Returns:
        scored_weeks: int — non-deload weeks with a perf_score for this muscle
        signal_stability: float [0–1] — calibrated inverse-dispersion of the perf
            series AROUND ITS OLS TREND, mapped as ``1 − min(1, CV / CV_REF)``.
            A steady climb (3→4→5) → residual ~0 → 1.0; a series bouncing around
            its trend → ~0.0. Detrending is deliberate: measuring dispersion around
            the mean (the old rule) penalized progressing muscles for progressing.
        perf_cv: float — coefficient of variation of the TREND RESIDUALS (0 = a
            perfectly linear series). Exposed so consumers can gate on the raw
            measure rather than only the squashed stability score.
        confidence: float [0–1] — combined metric used to weight prescriptions.
            Derived from scored_weeks (sample size) × signal_stability (noise level).
    """
    # Exclude DELOAD weeks: their perf is depressed BY DESIGN (lighter loads), so
    # counting them made a normal accumulation block look "noisy" → crushed
    # confidence → froze the muscle → it never logged the clean weeks that would
    # rebuild confidence (a self-reinforcing suppression the 2026-07-03 audit
    # traced on glutes: 0.58 → 0.08 across a deload cycle). Same deload-week
    # identification the outcome scorer uses (muscle_prescription_log.action).
    rows = conn.execute(
        """
        SELECT e.week_start, AVG(e.perf_score) AS muscle_perf
        FROM exercise_weekly_e1rm e
        JOIN exercise_muscle_map m ON e.exercise = m.exercise_name
        WHERE m.primary_muscle = ?
          AND e.perf_score IS NOT NULL
          AND NOT EXISTS (
              SELECT 1 FROM muscle_prescription_log l
              WHERE l.week_start = e.week_start AND l.muscle = ? AND l.action = 'deload'
          )
        GROUP BY e.week_start
        ORDER BY e.week_start
        """,
        [muscle, muscle],
    ).fetchall()

    n = len(rows)
    if n == 0:
        return {"scored_weeks": 0, "signal_stability": 0.0, "perf_cv": 0.0, "confidence": 0.0}

    # Signal stability from dispersion around the TREND, not around the mean. A
    # muscle climbing 3→4→5 is the CLEAREST possible signal, yet its raw CV (SD/mean
    # of the level) is high — so the old measure read a steadily-progressing muscle
    # as "noisy" and throttled the exact muscles that were working. Fit an OLS line
    # and measure the residual scatter instead: a linear climb → ~0 residual → high
    # stability; a muscle bouncing around its trend → high residual → low stability.
    from statistics import mean, pstdev

    perfs = [float(r[1]) for r in rows]
    if len(perfs) >= 3:
        mu = mean(perfs)
        n_p = len(perfs)
        mean_x = (n_p - 1) / 2.0
        den = sum((i - mean_x) ** 2 for i in range(n_p))
        slope = (
            sum((i - mean_x) * (p - mu) for i, p in enumerate(perfs)) / den if den else 0.0
        )
        intercept = mu - slope * mean_x
        residuals = [p - (intercept + slope * i) for i, p in enumerate(perfs)]
        cv = pstdev(residuals) / mu if mu > 0 else _SIGNAL_CV_REF
        stability = max(0.0, 1.0 - min(1.0, cv / _SIGNAL_CV_REF))
        # An OLS fit burns 2 degrees of freedom; below _STABILITY_MIN_RESIDUAL_DOF
        # residual dof the scatter estimate isn't trustworthy — a handful of
        # coincidentally-linear points (trivial with integer 1-5 perf scores)
        # would otherwise read as PERFECT stability by chance. Cap at the same
        # neutral 0.5 the <3-point branch uses until there's enough dof to trust it.
        if n_p - 2 < _STABILITY_MIN_RESIDUAL_DOF:
            stability = min(stability, 0.5)
    else:
        # <3 points: two always fit a line perfectly (residual 0 → false certainty),
        # so there's no basis to judge noise yet. Neutral prior.
        cv = 0.0
        stability = 0.5

    # Confidence from sample size — see _SIZE_FACTOR_ANCHORS for the curve.
    size_factor = _signal_size_factor(n)

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
