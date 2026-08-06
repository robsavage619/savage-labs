"""Deterministic per-lift next-set prescription — double progression as code.

The engine has always output trend CALLS ("add load", set targets, ceilings,
rep windows) and left the actual sets×reps×load composition to the planning
LLM, fresh every session. That freedom is where the recurring failure modes
lived: hand-computed Epley ceilings, loads between physical notches, RPE
labels the load can't deliver. This module owns the arithmetic instead:

    last logged exposure  +  rep window  +  loadable notches  +  today's
    effort ceiling  →  the exact next load × rep target per lift

The rule is classic double progression: fill the rep window at a fixed load,
then step ONE notch (the implement's real increment, via
:mod:`shc.training.loadable`) and reset reps to the window bottom. Today's
effort cap (:func:`shc.ai.workout_planner.rpe_derived_ceiling_kg`) bounds the
step — a reduced day holds the window top instead of loading up, and a day
whose ceiling sits below the last working weight works at the ceiling.

Deliberately NOT decided here: how many sets (the volume controller owns
per-muscle set budgets) and which exercises (selection owns that). This is
the load×rep layer only, and it is advisory context for the planner — the
validators still enforce coherence independently, so a wrong number here is
caught the same way a wrong LLM number was.

Also here: :func:`pr_reanchor_due` — the e1RM refresh policy. Every ceiling
is a percentage of e1RM, and an e1RM whose underlying peak SET is weeks old
quietly distorts everything downstream. Invariant 15 defends the *legality*
of beating a stale e1RM; this is the first thing that *asks* for it.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

import duckdb

from shc.training.load_mechanics import exceeds_per_hand_max, per_hand_kg
from shc.training.loadable import LoadableGrids, build_grids

log = logging.getLogger(__name__)

_LB_PER_KG = 2.20462

# Same tolerance the loadable grids use for "this is the same notch".
_TOL_LB = 0.25
# Nudge past the tolerance so snap_up resolves the notch STRICTLY above the
# last working weight rather than snapping back onto it.
_NEXT_NOTCH_NUDGE_LB = 0.3

# Fallback rep window when a lift has no curated exercise_science row — the
# 8-12 hypertrophy default the catalog itself centres on.
_DEFAULT_REP_WINDOW = (8, 12)

# A logged RPE at/above this means the last exposure was a grind: repeat it
# and consolidate rather than advancing into a missed rep.
_GRIND_RPE = 9.5

# An e1RM whose underlying peak week is at least this old is a stale reference
# on a lift that isn't regressing — worth a deliberate top set to re-anchor.
_PR_STALE_WEEKS = 4
# How far back to look for the peak. Bounded so an ancient PR from a different
# training era doesn't hold the reference forever.
_PR_LOOKBACK_WEEKS = 26
# Keep the PR ask short — one or two re-anchors per session is realistic.
_PR_MAX_ASKS = 5


@dataclass(frozen=True)
class NextRx:
    """The deterministic next load×rep target for one lift."""

    exercise: str
    last_date: str
    last_weight_lbs: float  # per-hand, matching every other surfaced load
    last_reps: int
    last_rpe: float | None
    rep_low: int
    rep_high: int
    # 'add_rep' | 'step_load' | 'top_of_window' | 'hold_grind' | 'reduce_ceiling'
    action: str
    next_weight_lbs: float
    next_reps: int
    note: str


def _advance(
    exercise: str,
    last_w_lb: float,
    last_reps: int,
    last_rpe: float | None,
    rep_low: int,
    rep_high: int,
    grids: LoadableGrids,
    ceiling_lb_at: Callable[[int], float | None],
) -> tuple[str, float, int, str]:
    """The pure double-progression rule for one lift. Returns (action, w, reps, note).

    Order matters and each branch errs toward the safer read:

    1. **Today's ceiling below the last working weight** → work AT the ceiling
       (snapped down to a loadable notch). A reduced day reduces load; it does
       not pretend the last weight is prescribable.
    2. **Last exposure was a grind** (RPE ≥ :data:`_GRIND_RPE`) → repeat it.
       Advancing off a ground-out set programs a missed rep.
    3. **Rep window filled** → step ONE notch up, reps reset to the window
       bottom — unless today's ceiling can't hold the stepped load at those
       reps, in which case hold the window top and step when the cap lifts.
    4. Otherwise → same load, one more rep toward the window top.

    ``ceiling_lb_at(reps)`` returns today's effort-derived load ceiling at a
    rep count, or None when no e1RM exists — no ceiling claim, no cap applied
    (the planner's by-feel rule and the validators still stand).
    """
    ceil_last = ceiling_lb_at(last_reps)
    if ceil_last is not None and last_w_lb > ceil_last + _TOL_LB:
        w = grids.snap_down(exercise, ceil_last)
        return (
            "reduce_ceiling",
            w,
            last_reps,
            f"today's effort ceiling ({ceil_last:g} lb at {last_reps} reps) is below the "
            "last working weight — reduced day, work at the ceiling",
        )
    if last_rpe is not None and last_rpe >= _GRIND_RPE:
        return (
            "hold_grind",
            last_w_lb,
            min(last_reps, rep_high),
            f"last exposure was a grind (RPE {last_rpe:g}) — repeat it and consolidate "
            "before advancing",
        )
    if last_reps >= rep_high:
        cand = grids.snap_up(exercise, last_w_lb + _NEXT_NOTCH_NUDGE_LB)
        if cand <= last_w_lb + _TOL_LB:
            return (
                "top_of_window",
                last_w_lb,
                rep_high,
                "no higher notch resolvable from the logged grid — hold the window top",
            )
        ceil_low = ceiling_lb_at(rep_low)
        if ceil_low is not None and cand > ceil_low + _TOL_LB:
            return (
                "top_of_window",
                last_w_lb,
                rep_high,
                f"next notch ({cand:g} lb) sits above today's effort ceiling "
                f"({ceil_low:g} lb at {rep_low} reps) — hold the window top, step when "
                "the cap lifts",
            )
        return (
            "step_load",
            cand,
            rep_low,
            f"rep window filled at {last_w_lb:g} lb — step to the next notch, reps "
            f"reset to {rep_low}",
        )
    next_reps = min(last_reps + 1, rep_high)
    return (
        "add_rep",
        last_w_lb,
        next_reps,
        f"double progression: same load, {last_reps}→{next_reps} reps (window top {rep_high})",
    )


def _rep_windows(conn: duckdb.DuckDBPyConnection) -> dict[str, tuple[int, int]]:
    """Curated rep window per exercise (lowercased name), alias-resolved.

    An exercise curated under multiple muscles takes the widest window (MIN low,
    MAX high) — the union of what the evidence prescribes for it. The alias
    table maps each canonical name's window onto the string Rob actually logs,
    so a staple logged under a variant name still finds its window. Absent
    tables degrade to an empty map and every lift falls back to the default.
    """
    windows: dict[str, tuple[int, int]] = {}
    try:
        for name, lo, hi in conn.execute(
            "SELECT exercise_name, MIN(rep_low), MAX(rep_high) "
            "FROM exercise_science GROUP BY exercise_name"
        ).fetchall():
            if lo is not None and hi is not None:
                windows[str(name).strip().lower()] = (int(lo), int(hi))
    except Exception as exc:  # noqa: BLE001 — curated layer optional → default window
        log.debug("exercise_science rep windows unavailable: %s", exc)
        return {}
    try:
        for canonical, logged in conn.execute(
            "SELECT canonical_name, logged_name FROM exercise_alias"
        ).fetchall():
            ck, lk = str(canonical).strip().lower(), str(logged).strip().lower()
            if ck in windows and lk not in windows:
                windows[lk] = windows[ck]
    except Exception as exc:  # noqa: BLE001 — alias table optional
        log.debug("exercise_alias unavailable for rep windows: %s", exc)
    return windows


def next_prescriptions(
    conn: duckdb.DuckDBPyConnection,
    gates: dict,
    today: date,
    e1rm_by_ex: dict[str, float],
    grids: LoadableGrids | None = None,
    lookback_days: int = 14,
) -> list[NextRx]:
    """The deterministic next load×rep target for every recently-trained lift.

    Reads each lift's most recent session inside ``lookback_days``, takes its
    top working set (heaviest per-hand load; most reps at that load; the RPE
    logged there, if any), and runs :func:`_advance` against the curated rep
    window, the loadable-notch grid, and today's effort-derived ceiling.
    ``e1rm_by_ex`` is the caller's per-hand RIR-adjusted map
    (:func:`shc.ai.workout_planner.e1rm_by_exercise`) so this prescribes off
    the SAME e1RM basis every other surface uses (invariant 13).
    """
    from shc.ai.workout_planner import rpe_derived_ceiling_kg  # lazy — avoids a cycle

    grids = grids if grids is not None else build_grids(conn)
    rows = conn.execute(
        """
        WITH last_day AS (
            SELECT exercise, MAX(started_at::DATE) AS d
            FROM workout_sets_dedup
            WHERE is_warmup = FALSE AND source = 'hevy'
              AND weight_kg > 0 AND reps > 0
              AND started_at::DATE >= ?
            GROUP BY exercise
        )
        SELECT ws.exercise, ws.weight_kg, ws.reps, ws.rpe, ld.d
        FROM workout_sets_dedup ws
        JOIN last_day ld ON ld.exercise = ws.exercise AND ws.started_at::DATE = ld.d
        WHERE ws.is_warmup = FALSE AND ws.source = 'hevy'
          AND ws.weight_kg > 0 AND ws.reps > 0
        """,
        [(today - timedelta(days=lookback_days)).isoformat()],
    ).fetchall()

    by_ex: dict[str, list[tuple[float, int, float | None, date]]] = defaultdict(list)
    for ex, wkg, reps, rpe, d in rows:
        # A set implying an impossible one-hand load is contaminated data, not a
        # basis to progress from (same guard the grids apply on build).
        if exceeds_per_hand_max(ex, float(wkg), d):
            continue
        w_lb = round(per_hand_kg(ex, float(wkg), d) * _LB_PER_KG, 1)
        by_ex[ex].append((w_lb, int(reps), float(rpe) if rpe is not None else None, d))

    windows = _rep_windows(conn)
    out: list[NextRx] = []
    for ex, sets in by_ex.items():
        top_w = max(w for w, _r, _p, _d in sets)
        at_top = [s for s in sets if abs(s[0] - top_w) <= _TOL_LB]
        top_reps = max(r for _w, r, _p, _d in at_top)
        rpes = [p for _w, _r, p, _d in at_top if p is not None]
        top_rpe = max(rpes) if rpes else None
        last_date = max(d for _w, _r, _p, d in sets)
        rep_low, rep_high = windows.get(ex.strip().lower(), _DEFAULT_REP_WINDOW)
        e1 = e1rm_by_ex.get(ex)

        def _ceiling_lb_at(reps: int, _e1: float | None = e1) -> float | None:
            if not _e1:
                return None
            return round(rpe_derived_ceiling_kg(_e1, reps, gates) * _LB_PER_KG, 1)

        action, w, reps, note = _advance(
            ex, top_w, top_reps, top_rpe, rep_low, rep_high, grids, _ceiling_lb_at
        )
        out.append(
            NextRx(
                exercise=ex,
                last_date=last_date.isoformat(),
                last_weight_lbs=top_w,
                last_reps=top_reps,
                last_rpe=top_rpe,
                rep_low=rep_low,
                rep_high=rep_high,
                action=action,
                next_weight_lbs=w,
                next_reps=reps,
                note=note,
            )
        )
    return sorted(out, key=lambda n: n.exercise)


def pr_reanchor_due(
    conn: duckdb.DuckDBPyConnection,
    today: date,
    gates: dict,
    stale_weeks: int = _PR_STALE_WEEKS,
) -> list[dict]:
    """Lifts whose e1RM reference is stale enough to schedule a deliberate top set.

    Fires only on a genuine HIGH day (no deload) — the one day whose effort cap
    (RPE 10) permits a true PR attempt (invariant 5/15). A lift qualifies when
    its weekly-e1RM PEAK inside the lookback is at least ``stale_weeks`` old and
    its trend is progressing or stalled: progressing with an old peak means Rob
    is fitter than his reference; stalled with an old peak means the ceiling
    deserves a re-test before it keeps capping loads. A regressing or unscored
    lift is never asked for a max. Advisory, capped at :data:`_PR_MAX_ASKS`,
    ordered stalest-first — the planner still owns whether the muscle is
    trainable today.
    """
    if gates.get("deload_required") or gates.get("max_intensity", "high") != "high":
        return []
    try:
        rows = conn.execute(
            """
            WITH recent AS (
                SELECT DISTINCT exercise FROM workout_sets_dedup
                WHERE started_at::DATE >= ? AND source = 'hevy'
                  AND COALESCE(is_warmup, FALSE) = FALSE
                  AND weight_kg > 0 AND reps > 0
            )
            SELECT e.exercise,
                   arg_max(e.week_start, e.e1rm_kg) AS peak_week,
                   MAX(e.e1rm_kg)                   AS peak_kg
            FROM exercise_weekly_e1rm e
            JOIN recent r ON r.exercise = e.exercise
            WHERE e.week_start >= ?
            GROUP BY e.exercise
            """,
            [
                (today - timedelta(days=14)).isoformat(),
                (today - timedelta(weeks=_PR_LOOKBACK_WEEKS)).isoformat(),
            ],
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — pre-0079 schema → no claim
        log.debug("PR re-anchor unmeasurable: %s", exc)
        return []

    from shc.training.mesocycle import score_exercise

    due: list[dict] = []
    for ex, peak_week, peak_kg in rows:
        weeks_since = (today - peak_week).days // 7
        if weeks_since < stale_weeks:
            continue
        try:
            ps = score_exercise(conn, ex)
        except Exception as exc:  # noqa: BLE001 — scoring optional, never blocks
            log.debug("score_exercise failed for %s: %s", ex, exc)
            continue
        if ps is None or ps.trend == "regressing":
            continue
        due.append(
            {
                "exercise": ex,
                "trend": ps.trend,
                "peak_week": peak_week.isoformat(),
                "weeks_since_peak": weeks_since,
                "peak_e1rm_lbs": round(float(peak_kg) * _LB_PER_KG, 1),
            }
        )
    due.sort(key=lambda d: -d["weeks_since_peak"])
    return due[:_PR_MAX_ASKS]
