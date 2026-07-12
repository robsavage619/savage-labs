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
_CAPPED_E1RM = f"weight_kg * (1 + LEAST(reps, {_EPLEY_REP_CAP}) / 30.0)"


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
    # Fetch up to 14 weeks; thresholds below are calibrated to this cap.
    history = weekly_e1rm(conn, exercise, n_weeks=14, before=this_week)
    if len(history) < 3:
        return None

    # Dynamic OLS window: advanced lifters gain strength slowly; a 6-week
    # window produces too much noise for exercises progressing <0.5%/week.
    # Longer window reduces false "stalled" calls for experienced athletes.
    n = len(history)
    window = 12 if n >= 12 else (9 if n >= 8 else 6)
    series = [h.e1rm_kg for h in history[-window:]]
    pct_per_week = _trend_pct_per_week(series)
    perf_score, trend = _score_from_trend(pct_per_week)

    # Tonnage blend: flat e1RM + rising volume-load = hypertrophy progress, not stall.
    if perf_score == 3:
        tonnage_series = [h.tonnage_kg for h in history[-6:] if h.tonnage_kg is not None]
        if len(tonnage_series) >= 3:
            tonnage_pct = _trend_pct_per_week(tonnage_series)
            if tonnage_pct >= 0.5:
                perf_score = 4
                trend = "progressing"

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

            prior_e1rms = e1rms[max(0, i - 6) : i]
            if len(prior_e1rms) < 3:
                continue

            pct = _trend_pct_per_week(prior_e1rms)
            ps, trend = _score_from_trend(pct)

            # Tonnage blend
            if ps == 3:
                prior_t = [t for t in tonnages[max(0, i - 6) : i] if t is not None]
                if len(prior_t) >= 3 and _trend_pct_per_week(prior_t) >= 0.5:
                    ps = 4
                    trend = "progressing"

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
               SUM(weight_kg * reps)                AS weekly_tonnage_kg,
               NULL, NULL, now()
        FROM workout_sets_dedup
        WHERE weight_kg > 0 AND reps > 0
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
            """,
            [this_week, this_week + timedelta(days=7)],
        ).fetchall()
    ]

    for ex in exercises:
        # Always store THIS week's rep-capped best-set e1RM + work sets, so the
        # weekly series the trend is built from accumulates one row per week.
        row = conn.execute(
            f"""
            SELECT MAX({_CAPPED_E1RM}), COUNT(*), SUM(weight_kg * reps)
            FROM workout_sets_dedup
            WHERE exercise = ?
              AND started_at::DATE >= ? AND started_at::DATE < ?
              AND weight_kg > 0 AND reps > 0
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
