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
from shc.training.load_mechanics import effective_reps_sql, per_hand_sql
from shc.training.self_learning import fit_all

log = logging.getLogger(__name__)


DEFAULT_PLANNED_WEEKS = 7
"""Accumulation weeks in a new block, before the one-week deload.

Raised 5 -> 7 on 2026-07-28 at Rob's request for "a longer runway". A 5-week
block is really a 6-week cycle (5 accumulate + 1 shed), so ~17% of calendar time
was deload; at 7 it is ~12.5%. Deliberately applied only to blocks created from
here on — the block in flight keeps the 5 it was planned at, so raising this
cannot yank him out of a deload week mid-shed (`_build_state` derives
`is_deload_week` live from `planned_weeks`, so editing the active row would take
effect immediately, which is the opposite of what a deload is for).

This is a calendar bound, not the real stopping rule. The outcome triggers —
muscles regressing, muscles at MRV, effort overreach — still end a block early
when fatigue actually arrives, so a longer calendar buys runway without removing
the brake.
"""


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
    mv: int = 2  # Maintenance Volume — the 4th landmark (migration 0078)
    tier: str = "grow"  # 'grow' | 'maintain' — explicit intent, never fitted


@dataclass
class WeeklyE1RM:
    week_start: date
    e1rm_kg: float
    work_sets: int
    perf_score: int | None
    trend: str | None
    tonnage_kg: float | None = None
    # Mean RPE across this week's WORKING sets (migration 0079). None when Rob
    # logged no RPE that week — which is most of history, so every consumer must
    # treat None as "no effort claim", never as zero effort.
    avg_rpe: float | None = None
    rpe_set_count: int = 0


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


# Intra-mesocycle effort ramp (RIR periodization). Week 1 of an accumulation
# block starts at ~3-2 RIR (RPE 7-8) and the band climbs linearly to ~1-0.5 RIR
# (RPE 8.5-9.5) in the final accumulation week, so fatigue arrives on schedule
# and the calendar deload sheds something real. The top stays below 10: RPE 10
# is reserved for a deliberate PR attempt (invariant 5 / PR re-anchor), never a
# routine target. Values are the TARGET band; the day's recovery gates still
# own the CAP (`rpe_cap_for`) and always win when lower.
_MESO_RPE_START = (7.0, 8.0)
_MESO_RPE_END = (8.5, 9.5)
_MESO_DELOAD_BAND = (6.0, 6.0)


def _round_half(x: float) -> float:
    """Round to the nearest 0.5 — RPE's real-world resolution."""
    return round(x * 2) / 2


def meso_rpe_band(week_number: int, planned_weeks: int) -> tuple[float, float]:
    """Target working-set RPE band for this week of the mesocycle.

    Linear ramp across the accumulation weeks from :data:`_MESO_RPE_START` to
    :data:`_MESO_RPE_END`; past ``planned_weeks`` (the shed week) it returns the
    deload band. A one-week block has no ramp and holds the start band. This is
    the missing time axis: sets already ramp across the block (`_decide`), and
    without this week 1 and week ``planned_weeks`` prescribed identical effort.
    """
    if planned_weeks <= 0 or week_number > planned_weeks:
        return _MESO_DELOAD_BAND
    if planned_weeks == 1:
        return _MESO_RPE_START
    f = max(0.0, min(1.0, (week_number - 1) / (planned_weeks - 1)))
    lo = _round_half(_MESO_RPE_START[0] + (_MESO_RPE_END[0] - _MESO_RPE_START[0]) * f)
    hi = _round_half(_MESO_RPE_START[1] + (_MESO_RPE_END[1] - _MESO_RPE_START[1]) * f)
    return lo, hi


def meso_rpe_midpoint_rise(week_number: int, planned_weeks: int) -> float:
    """How far this week's PLANNED effort midpoint sits above week 1's.

    The effort-overreach detector compares recent weekly RPE to the athlete's
    own trailing baseline; with the ramp above, a late-accumulation week is
    SUPPOSED to read higher. This is the planned component of that rise, so the
    detector can require effort above what the plan itself asked for. Zero in
    week 1, on a deload, or with no active ramp.
    """
    if planned_weeks <= 0 or week_number > planned_weeks:
        return 0.0
    lo0, hi0 = meso_rpe_band(1, planned_weeks)
    lo, hi = meso_rpe_band(week_number, planned_weeks)
    return max(0.0, (lo + hi) / 2 - (lo0 + hi0) / 2)


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
        VALUES (CURRENT_DATE, ?, 'active', 'Auto-created by ensure_active_mesocycle')
        """,
        [DEFAULT_PLANNED_WEEKS],
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

    Mesocycle-scoped rows take precedence over global defaults. The global-
    default sentinel is mesocycle_id = '' (empty string, NOT NULL — the
    column is NOT NULL DEFAULT ''); a future "fix" toward comparing against
    NULL here would silently zero out every landmark.

    ``mv`` / ``tier`` (migration 0078) are the maintenance landmark and the
    explicit training intent. Both fail SAFE: a missing column, a NULL, or an
    unrecognised tier string resolves to ``mv=2`` / ``tier='grow'`` — i.e.
    exactly the pre-0078 behaviour, where every muscle is a growth target.
    Under-training must never be reachable by absence of data.
    """
    try:
        rows = conn.execute(
            """
            SELECT muscle_group, mev_sets, mav_sets, mrv_sets, mesocycle_id,
                   mv_sets, tier
            FROM muscle_volume_targets
            ORDER BY mesocycle_id ASC
            """
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — pre-0078 schema → grow-for-all
        log.debug("mv_sets/tier unavailable (pre-0078), defaulting to grow: %s", exc)
        rows = [
            (*r, None, None)
            for r in conn.execute(
                """
                SELECT muscle_group, mev_sets, mav_sets, mrv_sets, mesocycle_id
                FROM muscle_volume_targets
                ORDER BY mesocycle_id ASC
                """
            ).fetchall()
        ]

    def _tier(raw: object) -> str:
        # Only the exact string 'maintain' demotes a muscle. Anything else —
        # NULL, empty, a typo, a future value this build doesn't know — grows.
        return "maintain" if str(raw) == "maintain" else "grow"

    def _mv(raw: object, mev: int) -> int:
        try:
            v = int(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 2
        # MV above MEV is incoherent (maintenance can't exceed the growth
        # minimum); clamp rather than let a bad row invert the landmarks.
        return max(0, min(v, mev))

    # Build two passes: global defaults first, then personal overrides.
    defaults: dict[str, VolumeTarget] = {}
    personal: dict[str, VolumeTarget] = {}
    for mg, mev, mav, mrv, mid, mv_raw, tier_raw in rows:
        vt_kwargs = {"mv": _mv(mv_raw, mev), "tier": _tier(tier_raw)}
        if mid == "":
            defaults[mg] = VolumeTarget(mg, mev, mav, mrv, source="population", **vt_kwargs)
        elif mid == (meso_id or ""):
            personal[mg] = VolumeTarget(mg, mev, mav, mrv, source="personal", **vt_kwargs)

    brief_low = _brief_weekly_low(conn)
    targets: dict[str, VolumeTarget] = dict(defaults)
    for mg, vt in personal.items():
        pop = defaults.get(mg)
        # Tier is a training decision, not a fitted landmark: a mesocycle-scoped
        # row that predates 0078 carries no tier, so inherit the default's
        # rather than silently promoting the muscle back to 'grow'.
        tier = vt.tier if vt.tier == "maintain" else (pop.tier if pop else vt.tier)
        # Undertrained-fit guard. The fit measures HABIT, not physiology: MEV is
        # the P20 of weeks actually performed, so a muscle that has never been
        # trained hard can never be prescribed hard. Two independent triggers:
        #
        #  * MRV at or below half the population MRV. Was `<`, which missed the
        #    exact-boundary case — quads fitted MRV 10 against a population 20
        #    evaluated `10 < 10` and stayed "personal", pinning the CEILING at 10
        #    while the curated brief asks for 12–18.
        #  * MEV below the curated `muscle_development` weekly floor. The brief is
        #    the evidence-based dose and is already rendered into the planner
        #    context; a fitted MEV underneath it means the two authorities printed
        #    in the same block disagree, and the lower one was silently winning
        #    (abs: brief 12–20, fitted MEV 6 → 6 sets/wk → one exercise a session).
        low = brief_low.get(mg)
        undertrained_mrv = pop is not None and vt.mrv <= pop.mrv * 0.5
        undertrained_mev = low is not None and vt.mev < low
        if pop and (undertrained_mrv or undertrained_mev):
            # Floor to the population landmarks, then lift MEV to the curated
            # brief when even those sit under it. Never LOWER a fitted value.
            mev = max(pop.mev, low or 0, vt.mev if not undertrained_mev else 0)
            mrv = max(pop.mrv, vt.mrv)
            mav = min(max(pop.mav, mev), mrv)
            targets[mg] = VolumeTarget(
                mg, mev, mav, mrv, source="personal_floored", mv=pop.mv, tier=tier
            )
        else:
            targets[mg] = VolumeTarget(
                mg, vt.mev, vt.mav, vt.mrv, source="personal", mv=vt.mv, tier=tier
            )
    return targets


def _brief_weekly_low(conn: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """Curated evidence-based weekly set floor per muscle from ``muscle_development``.

    Absent table (pre-migration) returns empty, so the fitted landmarks stand
    unchanged and this guard degrades to the population-MRV trigger alone.
    """
    try:
        rows = conn.execute(
            "SELECT muscle, weekly_sets_low FROM muscle_development "
            "WHERE weekly_sets_low IS NOT NULL"
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — curated brief optional
        log.debug("muscle_development unavailable for landmark floor: %s", exc)
        return {}
    return {r[0]: int(r[1]) for r in rows}


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
            SELECT week_start, e1rm_kg, work_sets, perf_score, trend, weekly_tonnage_kg,
                   weekly_avg_rpe, rpe_set_count
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
            SELECT week_start, e1rm_kg, work_sets, perf_score, trend, weekly_tonnage_kg,
                   weekly_avg_rpe, rpe_set_count
            FROM exercise_weekly_e1rm
            WHERE exercise = ?
            ORDER BY week_start DESC
            LIMIT ?
            """,
            [exercise, n_weeks],
        ).fetchall()
    return [
        WeeklyE1RM(r[0], r[1], r[2], r[3], r[4], r[5], r[6], int(r[7] or 0)) for r in reversed(rows)
    ]


# e1RM scoring is deliberately conservative: a hypertrophy controller must not
# chase noise. Epley overestimates above ~10–12 reps, so reps are capped before
# estimating; and the performance signal is a multi-week TREND (OLS slope), never
# a single-week delta whose ~2–5% error (RIR/rep-selection/CNS state) swamps real
# change. See the sports-science panel review (C1).
_EPLEY_REP_CAP = 12  # re-exported for tests; canonical value lives in load_mechanics
# Best estimated 1RM for a set, reps capped so high-rep sets don't inflate it.
# weight_kg is per-hand-normalized via per_hand_sql (the identity except the
# verified _LOGGED_AS_COMBINED handful) — the same choke point e1rm_by_exercise
# (the load-ceiling path) routes through, so a dumbbell lift logged as a combined
# total doesn't read 2x its real per-hand value in the progression trend.
_PER_HAND_WEIGHT = per_hand_sql("weight_kg", "exercise", "started_at::DATE")
_EFFECTIVE_REPS = effective_reps_sql("reps", "rpe")
# Epley over RIR-ADJUSTED reps: the input set is assumed taken to failure, and
# Rob's best sets sit at RPE 7-8. Raw reps understate e1RM, and the load ceiling
# is a percentage OF e1RM, so the understatement compounds into the prescription.
# A set with no logged RPE is unchanged. See load_mechanics.effective_reps_sql.
_CAPPED_E1RM = f"({_PER_HAND_WEIGHT}) * (1 + {_EFFECTIVE_REPS} / 30.0)"
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


def _rpe_slope_per_week(rpes: list[float]) -> float:
    """OLS slope of a weekly-average-RPE series (oldest→newest), in RPE pts/week.

    Raw points, not a percentage: RPE is an ordinal 1–10 effort scale logged at
    0.5 resolution, so a percent-of-mean slope would compress the very signal
    being measured (0.5 RPE is a large change at 6.0 and the same change at 9.0).
    """
    n = len(rpes)
    if n < 2:
        return 0.0
    mean_x = (n - 1) / 2.0
    mean_y = sum(rpes) / n
    num = sum((i - mean_x) * (y - mean_y) for i, y in enumerate(rpes))
    den = sum((i - mean_x) ** 2 for i in range(n))
    return num / den if den else 0.0


# A real effort trend against n-of-1 noise. 0.10 RPE/week is ~1 full RPE point
# across a 10-week window — well above the 0.5-point logging resolution and the
# session-to-session jitter of a self-reported scale, but sensitive enough to
# surface a drift long before it shows up in e1RM.
_RPE_MEANINGFUL_SLOPE = 0.10
# A week needs this many RPE-logged working sets before its mean is allowed to
# speak for the week. One set carrying a whole week would let a single hard or
# easy set flip a muscle's volume decision.
_RPE_MIN_SETS_PER_WEEK = 2


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
    e1rms: list[float],
    tonnages: list[float | None],
    rpes: list[float | None] | None = None,
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

    # ── Effort corroboration (migration 0079) ────────────────────────────────
    # e1RM and tonnage both measure OUTPUT. RPE measures what that output COST,
    # and at a flat output the cost trend is the only thing that separates real
    # adaptation from hidden regression:
    #
    #   flat e1RM + FALLING RPE → same load, less effort → adapting  → upgrade
    #   flat e1RM + RISING  RPE → same load, more cost   → regressing → downgrade
    #
    # Both were previously scored 3 ("stalled") and given the same remedy (+1
    # set), which is right for one of them and actively wrong for the other.
    #
    # Scoped deliberately to the flat band only. A rising e1RM is unambiguous
    # progress whatever it cost, and demoting it on effort would re-create the
    # anti-progression trap invariant 6 exists to prevent. The downgrade
    # additionally requires that volume-load is not climbing: more tonnage
    # SHOULD cost more RPE, and reading that as regression would punish a
    # working hypertrophy block for working.
    #
    # Only the DOWNGRADE lives here. The falling-RPE case (flat e1RM getting
    # easier) is deliberately NOT scored as progression, because scoring it 4
    # would route it to `_decide`'s perf>=4 branch and add SETS — silently
    # overriding the existing `rpe_headroom` branch, which argues the opposite
    # for exactly this situation and is right: a flat e1RM that keeps getting
    # easier means the LOAD is too light, and adding volume to a too-light load
    # is the wrong lever. Falling RPE feeds `_muscle_rpe_headroom` instead, so
    # the remedy stays "raise load, hold sets" — now decided per muscle rather
    # than by a cross-muscle session average.
    if rpes is not None and perf_score == 3:
        rpe_series = [r for r in rpes[-window:] if r is not None]
        if len(rpe_series) >= 3:
            rpe_slope = _rpe_slope_per_week(rpe_series)
            if rpe_slope >= _RPE_MEANINGFUL_SLOPE and (tonnage_pct is None or tonnage_pct < 0.5):
                perf_score, trend = 2, "regressing"
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

    # A week's mean RPE only speaks for that week if enough sets carried one;
    # below the floor it is passed as None ("no effort claim") rather than a
    # thin average that could flip the call on a single set.
    result = _score_series(
        [h.e1rm_kg for h in history],
        [h.tonnage_kg for h in history],
        [h.avg_rpe if h.rpe_set_count >= _RPE_MIN_SETS_PER_WEEK else None for h in history],
    )
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
            SELECT week_start, e1rm_kg, weekly_tonnage_kg, perf_score,
                   weekly_avg_rpe, rpe_set_count
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
        # Same adequacy floor score_exercise applies, so a historical row scores
        # identically to how the live path would have scored it that week.
        rpes = [
            float(r[4]) if r[4] is not None and (r[5] or 0) >= _RPE_MIN_SETS_PER_WEEK else None
            for r in rows
        ]

        for i in range(len(rows)):
            if scored[i] is not None:
                continue  # already scored — preserve

            # Same 14-week cap weekly_e1rm() fetches for live scoring; _score_series
            # picks the dynamic 6/9/12 window from within it, so a historical row
            # scores identically to how it would have scored live that week.
            result = _score_series(
                e1rms[max(0, i - 14) : i],
                tonnages[max(0, i - 14) : i],
                rpes[max(0, i - 14) : i],
            )
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
             weekly_avg_rpe, rpe_set_count, perf_score, trend, computed_at)
        SELECT exercise,
               date_trunc('week', started_at)::DATE AS week_start,
               MAX({_CAPPED_E1RM})                  AS e1rm_kg,
               COUNT(*)                             AS work_sets,
               SUM({_CAPPED_TONNAGE})                AS weekly_tonnage_kg,
               AVG(rpe)                             AS weekly_avg_rpe,
               COUNT(rpe)                           AS rpe_set_count,
               NULL, NULL, now()
        FROM workout_sets_dedup
        WHERE weight_kg > 0 AND reps > 0
          AND source = 'hevy' AND is_warmup = FALSE
        GROUP BY exercise, date_trunc('week', started_at)::DATE
        ON CONFLICT (exercise, week_start) DO UPDATE SET
            e1rm_kg          = excluded.e1rm_kg,
            work_sets        = excluded.work_sets,
            weekly_tonnage_kg = excluded.weekly_tonnage_kg,
            weekly_avg_rpe   = excluded.weekly_avg_rpe,
            rpe_set_count    = excluded.rpe_set_count,
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

        # Resistance is never fitted (floor_only downstream — a personal fit
        # can't move the gate, see self_learning.fit_acwr_bands); only
        # conditioning forbid_legs is ever "personal (fitted)".
        acwr_src = (
            "conditioning personal (fitted) · resistance population (by design)"
            if read_acwr_bands(conn)
            else "population defaults"
        )
    except Exception:
        acwr_src = "unknown"

    # Signal quality for the confidence column in the volume table.
    from shc.training.self_learning import compute_all_muscle_signal_quality

    sq = compute_all_muscle_signal_quality(conn)

    # Tier/MV for the volume table. Without these the table printed only MEV, so
    # every maintenance muscle read "below MEV" and looked like a deficit to fix
    # — the exact misreading that kept putting direct volume on lats after they
    # were deliberately moved to the maintain tier (migration 0087). A muscle
    # held at maintenance is judged against MV, not MEV, and the table has to say
    # so or the reader re-derives the wrong conclusion every week.
    try:
        tiers = {
            m: (t or "grow", int(v) if v is not None else 2)
            for m, t, v in conn.execute(
                "SELECT muscle_group, tier, mv_sets FROM muscle_volume_targets"
            ).fetchall()
        }
    except Exception as exc:  # noqa: BLE001 — table predates 0078 in old copies
        log.debug("tier lookup unavailable for volume table: %s", exc)
        tiers = {}

    # Rebuild vol_rows with tier + confidence columns.
    vol_rows_conf: list[str] = []
    for r in report:
        tier, mv = tiers.get(r.muscle, ("grow", 2))
        maintaining = tier == "maintain"
        if r.mev is None:
            mav_str, landmarks, status = "—", "untargeted", r.status
        else:
            fitted = "*" if r.muscle in personal_muscles else ""
            mav_str = str(r.mav)
            # Show the floor this muscle is actually judged against.
            landmarks = f"{mv}/{r.mrv}{fitted}" if maintaining else f"{r.mev}/{r.mrv}{fitted}"
            status = (
                ("at MV — hold" if r.actual_sets >= mv else f"below MV ({mv}) — top up")
                if maintaining
                else r.status
            )
        muscle_sq = sq.get(r.muscle, {})
        conf = muscle_sq.get("confidence", 0.0)
        conf_str = f"{conf:.0%}" if conf else "—"
        tier_str = "maintain" if maintaining else "GROW"
        vol_rows_conf.append(
            f"| {r.muscle:<12} | {tier_str:<8} | {r.actual_sets:>6.1f} | {mav_str:>6} | "
            f"{landmarks:>9} | {status} | {conf_str} |"
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
        "GROW-tier muscles are judged against MEV and are where weekly volume belongs.",
        "MAINTAIN-tier muscles are judged against **MV**, not MEV — a maintain muscle at "
        "or above MV is DONE, not deficient. Do not add direct volume to it; its sets come "
        "free as spillover from grow-tier compounds. The floor column shows the relevant "
        "floor for each muscle's own tier.",
        "| Muscle | Tier | Actual | MAV | Floor/MRV | Status | Confidence |",
        "|--------------|----------|--------|--------|----------|---------|------------|",
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
            VALUES (CURRENT_DATE, ?, 'active', 'Auto-started after deload')
            """,
            [DEFAULT_PLANNED_WEEKS],
        )
    return ensure_active_mesocycle(conn)
