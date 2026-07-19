from __future__ import annotations

"""Mesocycle state machine and per-exercise progression scoring.

Public API:
    active_mesocycle(conn)           → MesocycleState | None
    ensure_active_mesocycle(conn)    → MesocycleState
    volume_targets(conn, meso_id)    → dict[str, VolumeTarget]
    weekly_e1rm(conn, exercise, n)   → list[WeeklyE1RM]
    score_exercise(conn, exercise)   → ProgressionScore
    backfill_weekly_e1rm(conn)       → None  (upsert history into exercise_weekly_e1rm)
    backfill_perf_scores(conn)       → None  (score all unscored historical rows)
    compute_all_scores(conn)         → None  (backfill + score all + fit this week)
    mesocycle_context_block(conn)    → str   (markdown injected into planner)
    advance_mesocycle(conn, trigger) → MesocycleState
"""

import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import duckdb

from shc.training.exercise_classifier import backfill_exercise_map
from shc.training.load_mechanics import per_hand_sql
from shc.training.self_learning import fit_all

log = logging.getLogger(__name__)


# Epley 1RM estimate
def _epley(weight_kg: float, reps: int) -> float:
    return weight_kg * (1 + reps / 30.0)


@dataclass
class VolumeTarget:
    muscle_group: str
    mev: int
    mav: int
    mrv: int
    source: str = "population"  # 'population' | 'personal' | 'personal_floored'


@dataclass
class WeeklyE1RM:
    week_start: date
    e1rm_kg: float
    work_sets: int
    perf_score: int | None
    trend: str | None
    tonnage_kg: float | None = None


@dataclass
class ProgressionScore:
    """Israetel 1–5 performance score for a single exercise this week."""

    exercise: str
    week_start: date
    e1rm_kg: float
    e1rm_lbs: float
    work_sets: int
    perf_score: int  # 1=regression  3=stalled  5=PR
    trend: str  # 'progressing' | 'stalled' | 'regressing'
    recommendation: str  # 'add weight' | 'hold' | 'deload'
    history: list[WeeklyE1RM] = field(default_factory=list)


@dataclass
class MesocycleState:
    id: str
    started_on: date
    planned_weeks: int
    status: str
    week_number: int  # 1-based current week
    weeks_remaining: int
    is_deload_week: bool
    deload_trigger: str | None
    notes: str | None


def _iso_week_start(d: date) -> date:
    """Return the Monday of the ISO week containing d."""
    return d - timedelta(days=d.weekday())


def active_mesocycle(conn: duckdb.DuckDBPyConnection) -> MesocycleState | None:
    row = conn.execute(
        """
        SELECT id, started_on, planned_weeks, status, deload_week, deload_trigger, notes
        FROM mesocycles
        WHERE status IN ('active', 'deloading')
        ORDER BY started_on DESC
        LIMIT 1
        """
    ).fetchone()
    if not row:
        return None
    return _build_state(*row)


def ensure_active_mesocycle(conn: duckdb.DuckDBPyConnection) -> MesocycleState:
    """Return the active mesocycle, creating one today if none exists."""
    state = active_mesocycle(conn)
    if state:
        return state
    conn.execute(
        """
        INSERT INTO mesocycles (started_on, planned_weeks, status, notes)
        VALUES (CURRENT_DATE, 5, 'active', 'Auto-created by ensure_active_mesocycle')
        """
    )
    state = active_mesocycle(conn)
    assert state is not None
    return state


def _build_state(
    meso_id: str,
    started_on: date,
    planned_weeks: int,
    status: str,
    deload_week: int | None,
    deload_trigger: str | None,
    notes: str | None,
) -> MesocycleState:
    today = date.today()
    # Align to ISO-week Monday before counting elapsed weeks so a block started
    # mid-week doesn't drift week_number by training-day timing (Bug 6).
    week_number = (today - _iso_week_start(started_on)).days // 7 + 1
    weeks_remaining = max(0, planned_weeks - week_number + 1)
    # Deload is the week AFTER planned_weeks accumulation weeks
    is_deload_week = week_number > planned_weeks or status == "deloading"
    return MesocycleState(
        id=meso_id,
        started_on=started_on,
        planned_weeks=planned_weeks,
        status=status,
        week_number=week_number,
        weeks_remaining=weeks_remaining,
        is_deload_week=is_deload_week,
        deload_trigger=deload_trigger,
        notes=notes,
    )


def volume_targets(
    conn: duckdb.DuckDBPyConnection, meso_id: str | None = None
) -> dict[str, VolumeTarget]:
    """Return MEV/MAV/MRV per muscle group.

    Mesocycle-scoped rows take precedence over global (NULL) defaults.
    """
    rows = conn.execute(
        """
        SELECT muscle_group, mev_sets, mav_sets, mrv_sets, mesocycle_id
        FROM muscle_volume_targets
        ORDER BY mesocycle_id ASC
        """
    ).fetchall()
    # Build two passes: global defaults first, then personal overrides.
    defaults: dict[str, VolumeTarget] = {}
    personal: dict[str, VolumeTarget] = {}
    for mg, mev, mav, mrv, mid in rows:
        if mid == "":
            defaults[mg] = VolumeTarget(mg, mev, mav, mrv, source="population")
        elif mid == (meso_id or ""):
            personal[mg] = VolumeTarget(mg, mev, mav, mrv, source="personal")

    targets: dict[str, VolumeTarget] = dict(defaults)
    for mg, vt in personal.items():
        pop = defaults.get(mg)
        # If the fitted MRV is below 50% of the population MRV, flag as
        # undertrained — the fit is measuring habit, not physiology.
        if pop and vt.mrv < pop.mrv * 0.5:
            targets[mg] = VolumeTarget(mg, pop.mev, pop.mav, pop.mrv, source="personal_floored")
        else:
            targets[mg] = vt
    return targets


def weekly_e1rm(
    conn: duckdb.DuckDBPyConnection,
    exercise: str,
    n_weeks: int = 8,
    before: date | None = None,
) -> list[WeeklyE1RM]:
    """Return the last n_weeks of stored e1RM data for an exercise, oldest first.

    If ``before`` is given, only weeks strictly before that date are returned
    (enables historical backfill scoring without today bleeding in).
    """
    if before is not None:
        rows = conn.execute(
            """
            SELECT week_start, e1rm_kg, work_sets, perf_score, trend, weekly_tonnage_kg
            FROM exercise_weekly_e1rm
            WHERE exercise = ? AND week_start < ?
            ORDER BY week_start DESC
            LIMIT ?
            """,
            [exercise, before.isoformat(), n_weeks],
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT week_start, e1rm_kg, work_sets, perf_score, trend, weekly_tonnage_kg
            FROM exercise_weekly_e1rm
            WHERE exercise = ?
            ORDER BY week_start DESC
            LIMIT ?
            """,
            [exercise, n_weeks],
        ).fetchall()
    return [WeeklyE1RM(r[0], r[1], r[2], r[3], r[4], r[5]) for r in reversed(rows)]


# e1RM scoring is deliberately conservative: a hypertrophy controller must not
# chase noise. Epley overestimates above ~10–12 reps, so reps are capped before
# estimating; and the performance signal is a multi-week TREND (OLS slope), never
# a single-week delta whose ~2–5% error (RIR/rep-selection/CNS state) swamps real
# change. See the sports-science panel review (C1).
_EPLEY_REP_CAP = 12
# Best estimated 1RM for a set, reps capped so high-rep sets don't inflate it.
# weight_kg is per-hand-normalized via per_hand_sql (the identity except the
# verified _LOGGED_AS_COMBINED handful) — the same choke point e1rm_by_exercise
# (the load-ceiling path) routes through, so a dumbbell lift logged as a combined
# total doesn't read 2x its real per-hand value in the progression trend.
_PER_HAND_WEIGHT = per_hand_sql("weight_kg", "exercise")
_CAPPED_E1RM = f"({_PER_HAND_WEIGHT}) * (1 + LEAST(reps, {_EPLEY_REP_CAP}) / 30.0)"
_CAPPED_TONNAGE = f"({_PER_HAND_WEIGHT}) * reps"


# A true weekly-e1RM series moves gradually — even aggressive strength gain is a
# few %/week. A point sitting >35% off the series' median is not physiology; it is
# a load-logging artifact (a per-hand lift logged as combined-stack total, a Fitbod
# import in different units, or a stray mis-typed weight). Left in, one such point
# anchors a 12-week OLS slope steeply negative and reads a healthy muscle as
# "regressing" — which is exactly what was falsely tripping the fatigue deload.
_MAX_E1RM_MEDIAN_DEVIATION = 0.35


def _drop_contaminated_e1rm(e1rms: list[float]) -> list[float]:
    """Drop weekly e1RM points that deviate >35% from the series median.

    Median is outlier-robust, so a minority of unit-inconsistent weeks doesn't move
    the reference. Genuine progression (even 100→160 over a block sits within ±35%
    of its median) survives untouched; only physiologically-impossible excursions —
    the per-hand/total-load contamination — are removed before the trend is fit.
    """
    positive = [y for y in e1rms if y > 0]
    if len(positive) < 3:
        return e1rms
    ordered = sorted(positive)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0
    if median <= 0:
        return e1rms
    lo, hi = median * (1 - _MAX_E1RM_MEDIAN_DEVIATION), median * (1 + _MAX_E1RM_MEDIAN_DEVIATION)
    return [y for y in e1rms if lo <= y <= hi]


def _trend_pct_per_week(e1rms: list[float]) -> float:
    """OLS slope of an e1RM series (oldest→newest) as % of its mean per week."""
    n = len(e1rms)
    if n < 2:
        return 0.0
    mean_y = sum(e1rms) / n
    if mean_y == 0:
        return 0.0
    mean_x = (n - 1) / 2.0
    num = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(e1rms))
    den = sum((i - mean_x) ** 2 for i in range(n))
    slope = num / den if den else 0.0
    return slope / mean_y * 100.0


def _score_from_trend(pct_per_week: float) -> tuple[int, str]:
    """Map a multi-week e1RM trend (%/week) to an Israetel 1–5 score + label.

    Bands sit on a noise-averaged OLS slope over ≥3 completed weeks, not a single
    delta — so the tight ±0.5%/wk 'stalled' band is defensible: the averaging has
    already removed the single-week measurement error a delta-band would absorb.
    """
    if pct_per_week >= 1.0:
        return 5, "progressing"
    if pct_per_week >= 0.5:
        return 4, "progressing"
    if pct_per_week >= -0.5:
        return 3, "stalled"
    if pct_per_week >= -1.0:
        return 2, "regressing"
    return 1, "regressing"


def _recommendation(score: int) -> str:
    """LOAD-only guidance. Set-count decisions belong to the autoregulation
    controller (single source of truth) — this never recommends adding sets."""
    if score >= 4:
        return "add load"
    if score == 3:
        return "hold load"
    return "reduce load or swap exercise"


def _score_series(
    e1rms: list[float], tonnages: list[float | None]
) -> tuple[int, str] | None:
    """Score a (oldest→newest) e1RM series — the single scoring core shared by
    the live path (:func:`score_exercise`) and the historical backfill
    (:func:`backfill_perf_scores`), so the same (exercise, week) can never get a
    different call depending on which path happened to write it (the audit found
    the backfill using a fixed 7-week window with no contamination guard and only
    half the tonnage blend, while live scoring used a dynamic window + both
    branches — silently different calls for the same data).

    Uses the OLS slope over a dynamic window (advanced lifters gain strength
    slowly; a 6-week window is too noisy below 0.5%/week, so more history widens
    it), strips load-logging artifacts before fitting (see
    :func:`_drop_contaminated_e1rm`), and corroborates against the tonnage trend
    over the same window so a rep-range/periodization shift isn't misread as
    strength loss. Returns ``(perf_score, trend)`` or ``None`` if too few clean
    weeks remain in the window.
    """
    n = len(e1rms)
    if n < 3:
        return None
    window = 12 if n >= 12 else (9 if n >= 8 else 6)
    series = e1rms[-window:]
    clean = _drop_contaminated_e1rm(series)
    if len(clean) < 3:
        return None
    pct_per_week = _trend_pct_per_week(clean)
    perf_score, trend = _score_from_trend(pct_per_week)

    # Estimated-1RM is rep-range-dependent: shifting from a low-rep strength block
    # into a higher-rep hypertrophy block drops the Epley e1RM even as the muscle
    # does MORE total work. So an e1RM decline is only real regression when weekly
    # volume-load (tonnage) fell too. Corroborate every call against the tonnage
    # trend over the same window — the primary progress signal for a hypertrophy
    # goal is volume-load, not a rep-capped 1RM proxy.
    tonnage_series = [t for t in tonnages[-window:] if t is not None]
    tonnage_pct = _trend_pct_per_week(tonnage_series) if len(tonnage_series) >= 3 else None
    if tonnage_pct is not None:
        if perf_score == 3 and tonnage_pct >= 0.5:
            # Flat e1RM + rising volume-load = hypertrophy progress, not a stall.
            perf_score, trend = 4, "progressing"
        elif perf_score <= 2 and tonnage_pct >= -0.5:
            # e1RM "regressing" but volume-load holding or rising: this is a
            # rep-range / periodization shift, NOT strength loss. Reclassify so it
            # cannot falsely trip the fatigue deload. Genuine regression (both
            # e1RM AND tonnage falling) is left untouched.
            perf_score, trend = (4, "progressing") if tonnage_pct >= 0.5 else (3, "stalled")
    return perf_score, trend


def score_exercise(
    conn: duckdb.DuckDBPyConnection,
    exercise: str,
    as_of: date | None = None,
) -> ProgressionScore | None:
    """Score an exercise from the TREND of its weekly e1RM over completed weeks.

    Uses the OLS slope across the last up to 12 COMPLETED weeks — the in-progress
    week is excluded, since a partial week understates the best set and would bias
    the call by training-day timing. Returns None until ≥3 completed weeks exist.

    ``as_of`` defaults to today's ISO-week Monday; pass a historical Monday to
    score as-of that point in time (used by backfill_perf_scores).

    Blends a tonnage-progression component: if the e1RM trend is flat (score=3)
    but weekly tonnage (weight×reps total) is rising ≥0.5%/week, upgrades to
    score=4. This prevents a hypertrophy block where muscle is growing under
    increasing volume from being misread as "stalled" (Phase 3 audit finding).
    """
    this_week = as_of if as_of is not None else _iso_week_start(date.today())
    # Fetch up to 14 weeks; _score_series' window thresholds are calibrated to
    # this cap.
    history = weekly_e1rm(conn, exercise, n_weeks=14, before=this_week)
    if len(history) < 3:
        return None

    result = _score_series([h.e1rm_kg for h in history], [h.tonnage_kg for h in history])
    if result is None:
        return None
    perf_score, trend = result

    latest = history[-1]
    return ProgressionScore(
        exercise=exercise,
        week_start=this_week,
        e1rm_kg=latest.e1rm_kg,
        e1rm_lbs=latest.e1rm_kg * 2.20462,
        work_sets=latest.work_sets,
        perf_score=perf_score,
        trend=trend,
        recommendation=_recommendation(perf_score),
        history=history,
    )


def backfill_perf_scores(conn: duckdb.DuckDBPyConnection) -> None:
    """Score every (exercise, week) row that has ≥3 prior completed weeks of e1RM.

    Only fills NULL perf_score cells — does NOT overwrite already-computed scores.
    Uses in-memory series per exercise (one DB read per exercise) so it's fast
    even on first run with 143+ exercises × hundreds of weeks.
    """
    exercises = [
        r[0]
        for r in conn.execute(
            """
            SELECT exercise FROM (
                SELECT exercise, COUNT(*) AS n
                FROM exercise_weekly_e1rm
                GROUP BY exercise
                HAVING n >= 4
            )
            ORDER BY exercise
            """
        ).fetchall()
    ]

    updated = 0
    for ex in exercises:
        rows = conn.execute(
            """
            SELECT week_start, e1rm_kg, weekly_tonnage_kg, perf_score
            FROM exercise_weekly_e1rm
            WHERE exercise = ?
            ORDER BY week_start
            """,
            [ex],
        ).fetchall()

        weeks = [r[0] for r in rows]
        e1rms = [float(r[1]) for r in rows]
        tonnages = [float(r[2]) if r[2] is not None else None for r in rows]
        scored = [r[3] for r in rows]

        for i in range(len(rows)):
            if scored[i] is not None:
                continue  # already scored — preserve

            # Same 14-week cap weekly_e1rm() fetches for live scoring; _score_series
            # picks the dynamic 6/9/12 window from within it, so a historical row
            # scores identically to how it would have scored live that week.
            result = _score_series(e1rms[max(0, i - 14) : i], tonnages[max(0, i - 14) : i])
            if result is None:
                continue
            ps, trend = result

            conn.execute(
                """
                UPDATE exercise_weekly_e1rm
                SET perf_score = ?, trend = ?
                WHERE exercise = ? AND week_start = ?
                """,
                [ps, trend, ex, weeks[i].isoformat()],
            )
            updated += 1

    log.info("backfill_perf_scores: scored %d (exercise, week) rows", updated)


def backfill_weekly_e1rm(conn: duckdb.DuckDBPyConnection) -> None:
    """Populate e1rm_kg + work_sets for every (exercise, ISO-week) from history.

    Does NOT overwrite perf_score/trend so previously computed scores are
    preserved.  Safe to call repeatedly — uses ON CONFLICT DO UPDATE only for
    the raw e1RM fields.
    """
    rows = conn.execute(
        f"""
        INSERT INTO exercise_weekly_e1rm
            (exercise, week_start, e1rm_kg, work_sets, weekly_tonnage_kg,
             perf_score, trend, computed_at)
        SELECT exercise,
               date_trunc('week', started_at)::DATE AS week_start,
               MAX({_CAPPED_E1RM})                  AS e1rm_kg,
               COUNT(*)                             AS work_sets,
               SUM({_CAPPED_TONNAGE})                AS weekly_tonnage_kg,
               NULL, NULL, now()
        FROM workout_sets_dedup
        WHERE weight_kg > 0 AND reps > 0
          AND source = 'hevy' AND is_warmup = FALSE
        GROUP BY exercise, date_trunc('week', started_at)::DATE
        ON CONFLICT (exercise, week_start) DO UPDATE SET
            e1rm_kg          = excluded.e1rm_kg,
            work_sets        = excluded.work_sets,
            weekly_tonnage_kg = excluded.weekly_tonnage_kg,
            computed_at      = now()
        """
    ).rowcount
    log.info("backfill_weekly_e1rm: upserted %d (exercise, week) rows", rows)


def compute_all_scores(conn: duckdb.DuckDBPyConnection) -> None:
    """Recompute e1RM + performance scores for every exercise trained this week.

    Writes results into exercise_weekly_e1rm (upsert).
    """
    backfill_exercise_map(conn)
    backfill_weekly_e1rm(conn)
    backfill_perf_scores(conn)
    # Retroactively apply tonnage blend to stalled rows that predate the tonnage column.
    from shc.training.self_learning import regrade_stalled_with_tonnage_blend

    regrade_stalled_with_tonnage_blend(conn)
    this_week = _iso_week_start(date.today())

    exercises = [
        r[0]
        for r in conn.execute(
            """
            SELECT DISTINCT exercise
            FROM workout_sets_dedup
            WHERE started_at::DATE >= ? AND started_at::DATE < ?
              AND weight_kg > 0 AND reps > 0
              AND source = 'hevy' AND is_warmup = FALSE
            """,
            [this_week, this_week + timedelta(days=7)],
        ).fetchall()
    ]

    for ex in exercises:
        # Always store THIS week's rep-capped best-set e1RM + work sets, so the
        # weekly series the trend is built from accumulates one row per week.
        row = conn.execute(
            f"""
            SELECT MAX({_CAPPED_E1RM}), COUNT(*), SUM({_CAPPED_TONNAGE})
            FROM workout_sets_dedup
            WHERE exercise = ?
              AND started_at::DATE >= ? AND started_at::DATE < ?
              AND weight_kg > 0 AND reps > 0
              AND source = 'hevy' AND is_warmup = FALSE
            """,
            [ex, this_week, this_week + timedelta(days=7)],
        ).fetchone()
        if not row or not row[0]:
            continue
        ps = score_exercise(conn, ex)
        perf_score = ps.perf_score if ps else None
        trend = ps.trend if ps else None
        conn.execute(
            """
            INSERT INTO exercise_weekly_e1rm
                (exercise, week_start, e1rm_kg, work_sets, weekly_tonnage_kg,
                 perf_score, trend, computed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, now())
            ON CONFLICT (exercise, week_start) DO UPDATE SET
                e1rm_kg          = excluded.e1rm_kg,
                work_sets        = excluded.work_sets,
                weekly_tonnage_kg = excluded.weekly_tonnage_kg,
                perf_score       = excluded.perf_score,
                trend            = excluded.trend,
                computed_at      = now()
            """,
            [ex, this_week, row[0], row[1], row[2], perf_score, trend],
        )
    log.info("compute_all_scores: updated %d exercises for week %s", len(exercises), this_week)

    # Phase 3: fit personal landmarks + ACWR bands from the now-populated data.
    state = active_mesocycle(conn)
    fit_all(conn, state.id if state else "")

    # Materialize signal quality cache (avoids per-request recomputation).
    from shc.training.self_learning import (
        materialize_signal_quality,
        record_prescription,
        score_prescription_outcomes,
        snapshot_accuracy,
    )

    materialize_signal_quality(conn)

    # Score any logged prescriptions from 3 weeks ago.
    score_prescription_outcomes(conn)

    # Snapshot this week's overall accuracy so engine drift is visible over time.
    snapshot_accuracy(conn)

    # Log this week's prescription for future accuracy tracking.
    from shc.training.autoregulation import weekly_prescription

    rx = weekly_prescription(conn)
    record_prescription(conn, rx)


# ─────────────────────────────────────────────────────────────────────────────
# Context block for workout_planner.py
# ─────────────────────────────────────────────────────────────────────────────


def mesocycle_context_block(conn: duckdb.DuckDBPyConnection) -> str:
    """Return a markdown block injected into the workout planner prompt."""
    state = active_mesocycle(conn)
    if state is None:
        return "## MESOCYCLE\nNo active mesocycle — start a new block.\n"

    from shc.training.volume import build_muscle_report, weekly_muscle_volume

    targets = volume_targets(conn, state.id)
    this_week = _iso_week_start(date.today())
    actuals = weekly_muscle_volume(conn, this_week)
    report = build_muscle_report(actuals, targets)

    # Which muscles have personal landmark overrides (fitted to Rob's data)?
    personal_muscles: set[str] = {
        r[0]
        for r in conn.execute(
            "SELECT muscle_group FROM muscle_volume_targets WHERE mesocycle_id = ?",
            [state.id],
        ).fetchall()
    }

    # Per-muscle volume table (anatomical; primary 1.0 + secondary 0.5 credit).
    # Landmarks marked with * are fitted to Rob's own data; others are RP population defaults.
    vol_rows: list[str] = []
    for r in report:
        if r.mev is None:
            mav_str, landmarks = "—", "untargeted"
        else:
            fitted = "*" if r.muscle in personal_muscles else ""
            mav_str = str(r.mav)
            landmarks = f"{r.mev}/{r.mrv}{fitted}"
        vol_rows.append(
            f"| {r.muscle:<12} | {r.actual_sets:>6.1f} | {mav_str:>6} | "
            f"{landmarks:>9} | {r.status} |"
        )

    # Per-exercise progression table (exercises trained in last 2 weeks)
    recent_exercises = [
        r[0]
        for r in conn.execute(
            """
            SELECT DISTINCT exercise
            FROM workout_sets_dedup
            WHERE started_at::DATE >= ? AND weight_kg > 0 AND reps > 0
              AND source = 'hevy' AND is_warmup = FALSE
            ORDER BY exercise
            """,
            [this_week - timedelta(days=14)],
        ).fetchall()
    ]

    prog_rows: list[str] = []
    for ex in recent_exercises[:20]:  # cap at 20 to stay concise
        ps = score_exercise(conn, ex)
        if ps is None:
            continue
        e1rm_lbs = round(ps.e1rm_lbs)
        prog_rows.append(
            f"- **{ex}**: score {ps.perf_score}/5 ({ps.trend}) — {ps.recommendation}. "
            f"e1RM {e1rm_lbs} lbs ({ps.work_sets} sets this week)"
        )

    block_label = (
        "DELOAD WEEK"
        if state.is_deload_week
        else f"Week {state.week_number} of {state.planned_weeks} (accumulation)"
    )
    # Self-learning summary line
    n_personal = len(personal_muscles)
    n_total = sum(1 for r in report if r.mev is not None)
    try:
        from shc.training.self_learning import read_acwr_bands

        acwr_src = "personal (fitted)" if read_acwr_bands(conn) else "population defaults"
    except Exception:
        acwr_src = "unknown"

    # Signal quality for the confidence column in the volume table.
    from shc.training.self_learning import compute_all_muscle_signal_quality

    sq = compute_all_muscle_signal_quality(conn)

    # Rebuild vol_rows with confidence column.
    vol_rows_conf: list[str] = []
    for r in report:
        if r.mev is None:
            mav_str, landmarks = "—", "untargeted"
        else:
            fitted = "*" if r.muscle in personal_muscles else ""
            mav_str = str(r.mav)
            landmarks = f"{r.mev}/{r.mrv}{fitted}"
        muscle_sq = sq.get(r.muscle, {})
        conf = muscle_sq.get("confidence", 0.0)
        conf_str = f"{conf:.0%}" if conf else "—"
        vol_rows_conf.append(
            f"| {r.muscle:<12} | {r.actual_sets:>6.1f} | {mav_str:>6} | "
            f"{landmarks:>9} | {r.status} | {conf_str} |"
        )

    lines = [
        "## MESOCYCLE POSITION",
        f"- Block status: {block_label}",
        f"- Block started: {state.started_on}",
        f"- Weeks remaining in accumulation: {state.weeks_remaining}",
        f"- Self-learning: {n_personal}/{n_total} muscles have personal landmarks (*); "
        f"ACWR gates from {acwr_src}",
        "",
        "## PER-MUSCLE VOLUME THIS WEEK (sets; primary 1.0 + secondary 0.5; * = fitted to Rob's data)",
        "| Muscle | Actual | MAV | MEV/MRV | Status | Confidence |",
        "|--------------|--------|--------|----------|---------|------------|",
        *vol_rows_conf,
        "",
    ]
    if prog_rows:
        lines += [
            "## PER-EXERCISE PROGRESSION SCORES",
            *prog_rows,
            "",
        ]
    return "\n".join(lines)


def advance_mesocycle(
    conn: duckdb.DuckDBPyConnection,
    trigger: str = "scheduled",
) -> MesocycleState:
    """Transition the current block to deloading, then close and start a new one.

    Call this at the end of the accumulation phase.
    """
    state = ensure_active_mesocycle(conn)
    if state.status == "active":
        conn.execute(
            "UPDATE mesocycles SET status = 'deloading', deload_trigger = ? WHERE id = ?",
            [trigger, state.id],
        )
    elif state.status == "deloading":
        conn.execute(
            "UPDATE mesocycles SET status = 'completed', ended_on = CURRENT_DATE WHERE id = ?",
            [state.id],
        )
        conn.execute(
            """
            INSERT INTO mesocycles (started_on, planned_weeks, status, notes)
            VALUES (CURRENT_DATE, 5, 'active', 'Auto-started after deload')
            """
        )
    return ensure_active_mesocycle(conn)
