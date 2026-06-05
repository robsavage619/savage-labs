from __future__ import annotations

"""Self-learning volume autoregulation — the prescriptive control loop.

Deterministic, per-muscle, runs weekly. For each muscle it decides next week's
working-set target by combining Rob's own logged signals — the Renaissance
Periodization / Israetel set-progression logic, made data-driven:

    progressing + recovered      → ADD sets toward MRV
    stalled (flat e1RM trend)    → ADD a set to break the stall (until MRV)
    regressing / under-recovered → CUT toward MEV
    at/over MRV                  → HOLD (ceiling)

On top of the base tree:
  * Fatigue deload — when several muscles regress or hit MRV at once, a real
    fatigue-driven deload (:func:`deload_check`) halves volume toward MEV. This
    overrides the per-muscle tree and is independent of the calendar mesocycle.
  * Lagging-emphasis bias — EMPHASIS muscles (biceps, glutes) ramp faster and
    floor at the MEV–MAV midpoint (not MAV — that would skip the accumulation
    runway).
  * Interference debit — when conditioning/pickleball load is high, lower-body
    volume is held back so court load doesn't blow the leg recovery budget.

No LLM is involved. The output (:func:`weekly_prescription`) is the structured
program the chat assembles the actual session from.
"""

import json
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import duckdb

from shc.training.mesocycle import (
    _iso_week_start,
    active_mesocycle,
    score_exercise,
    volume_targets,
)
from shc.training.volume import build_muscle_report, weekly_muscle_volume

log = logging.getLogger(__name__)

# Lagging muscles Rob wants prioritized — they RAMP FASTER (+2/wk) and floor at
# the MEV–MAV midpoint, not at MEV. They do NOT start at MAV: MAV is the maximum
# adaptive volume, not a baseline, and starting there removes the low-fatigue
# accumulation runway (panel review M3). Static for v1; Phase 3 will derive
# emphasis from a measured per-muscle development index.
EMPHASIS_MUSCLES: frozenset[str] = frozenset({"biceps", "glutes"})

# Lower-body muscles whose recovery competes with pickleball/cardio conditioning.
LOWER_BODY: frozenset[str] = frozenset({"quads", "hamstrings", "glutes", "calves", "adductors"})

# Soreness severity (1 mild / 2 moderate / 3 acute) at/above which a muscle is
# treated as under-recovered for volume decisions.
SORENESS_BLOCK = 2.0

# Weekly set-count change is ASYMMETRIC (panel review M10): adding volume is
# gated by recovery so it ramps slowly (RP accumulation is +1–2/wk), but cutting
# is a safety/fatigue response that may need to move faster on a bad read.
MAX_WEEKLY_ADD = 2
MAX_WEEKLY_CUT = 4


@dataclass
class MusclePrescription:
    muscle: str
    current_sets: float
    target_sets: int
    delta: int
    action: str  # 'add' | 'hold' | 'cut' | 'deload'
    reason: str
    emphasis: bool = False


@dataclass
class Prescription:
    week_start: date
    mesocycle_id: str
    deload: dict = field(default_factory=dict)  # {recommended, reason, triggers}
    muscles: list[MusclePrescription] = field(default_factory=list)
    lift_progressions: list[dict] = field(default_factory=list)
    exercise_menu: dict[str, list[str]] = field(default_factory=dict)


# Number of muscles that must independently signal fatigue to trigger a deload.
DELOAD_MUSCLE_THRESHOLD = 3


def deload_check(
    perfs: dict[str, int | None],
    report: list[MuscleVolume],
) -> dict:
    """Decide whether a fatigue-driven deload is warranted from real signals.

    A deload fires when training is broadly unproductive or maxed out, NOT on a
    calendar (panel review M4): ≥``DELOAD_MUSCLE_THRESHOLD`` muscles regressing
    (perf ≤ 2), or that many at/over MRV. Returns the recommendation + the
    specific triggers so the prescription can explain itself.
    """
    regressing = sorted(m for m, p in perfs.items() if p is not None and p <= 2)
    at_mrv = sorted(r.muscle for r in report if r.mrv is not None and r.actual_sets >= r.mrv)
    triggers: list[str] = []
    if len(regressing) >= DELOAD_MUSCLE_THRESHOLD:
        triggers.append(f"{len(regressing)} muscles regressing ({', '.join(regressing[:5])})")
    if len(at_mrv) >= DELOAD_MUSCLE_THRESHOLD:
        triggers.append(f"{len(at_mrv)} muscles at/over MRV ({', '.join(at_mrv[:5])})")
    return {
        "recommended": bool(triggers),
        "reason": "; ".join(triggers) if triggers else "no systemic fatigue signal",
        "triggers": triggers,
    }


def _recent_soreness(conn: duckdb.DuckDBPyConnection, days: int = 7) -> dict[str, float]:
    """Mean per-muscle soreness severity over the last ``days`` check-ins."""
    rows = conn.execute(
        """
        SELECT muscle_soreness
        FROM daily_checkin
        WHERE date >= ? AND muscle_soreness IS NOT NULL
        """,
        [(date.today() - timedelta(days=days)).isoformat()],
    ).fetchall()
    acc: dict[str, list[float]] = {}
    for (raw,) in rows:
        try:
            data = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(data, dict):
            continue
        for muscle, sev in data.items():
            if sev is not None:
                acc.setdefault(muscle, []).append(float(sev))
    return {m: sum(v) / len(v) for m, v in acc.items() if v}


def _muscle_performance(conn: duckdb.DuckDBPyConnection, muscle: str) -> int | None:
    """Set-weighted central tendency of Israetel perf scores for a muscle.

    Averages the perf score across exercises whose ``primary_muscle`` is
    ``muscle``, weighted by each exercise's recent work-set count, then rounds.
    Weighting by volume keeps a single fluke PR on a minor accessory from
    speaking for the whole muscle — the upward-bias failure of the old ``max()``
    aggregation (panel review C1). None when no exercise has enough history.
    """
    exercises = [
        r[0]
        for r in conn.execute(
            "SELECT exercise_name FROM exercise_muscle_map WHERE primary_muscle = ?",
            [muscle],
        ).fetchall()
    ]
    weighted = 0.0
    total_w = 0.0
    for ex in exercises:
        ps = score_exercise(conn, ex)
        if ps is None:
            continue
        w = max(1, ps.work_sets)  # never zero-weight a scored lift
        weighted += ps.perf_score * w
        total_w += w
    if total_w == 0:
        return None
    return round(weighted / total_w)


def _conditioning_pressure(conn: duckdb.DuckDBPyConnection) -> float | None:
    """Conditioning ACWR — proxy for how much pickleball/cardio load is live.

    Read lazily from the daily state; None if unavailable. > 1.3 means the
    lower body is already absorbing meaningful court/cardio stimulus.
    """
    try:
        from shc.metrics import compute_daily_state

        return compute_daily_state(conn)["training_load"].get("conditioning_acwr")
    except Exception as exc:  # noqa: BLE001 — state optional; missing → no debit
        log.debug("conditioning pressure unavailable: %s", exc)
        return None


def _decide(
    muscle: str,
    current: float,
    mev: int,
    mav: int,
    mrv: int,
    perf: int | None,
    soreness: float,
    conditioning_acwr: float | None,
    deload: bool = False,
) -> MusclePrescription:
    """Apply the RP set-progression tree + emphasis + interference for one muscle.

    ``action`` is derived from the final delta so it can never contradict the
    target, and every change is clamped asymmetrically (``MAX_WEEKLY_ADD`` up,
    ``MAX_WEEKLY_CUT`` down) so volume ramps gradually but can back off faster.
    When ``deload`` is set, the normal tree is bypassed: volume is halved toward
    MEV in a single deliberate drop (the step clamp does not apply to a deload).
    """
    emphasis = muscle in EMPHASIS_MUSCLES

    if deload:
        cur0 = round(current)
        target = max(0, min(mrv, max(mev, round(cur0 * 0.5))))
        return MusclePrescription(
            muscle=muscle,
            current_sets=round(current, 1),
            target_sets=target,
            delta=target - cur0,
            action="deload",
            reason="deload week — volume ~halved toward MEV to shed accumulated fatigue",
            emphasis=emphasis,
        )

    # Emphasis muscles floor at the MEV–MAV midpoint (keeps an accumulation
    # runway), not at MAV; everything else floors at MEV (panel review M3).
    grow_floor = (mev + (mav - mev) // 2) if emphasis else mev
    cur = round(current)
    under_recovered = soreness >= SORENESS_BLOCK
    # Uncoupled conditioning ACWR runs higher than the old coupled scale (M2);
    # graded leg-volume hold kicks in above 1.5, below the gate's >1.8 forbid.
    leg_interference = (
        muscle in LOWER_BODY and conditioning_acwr is not None and conditioning_acwr > 1.5
    )

    if perf is not None and perf <= 2:
        # Regressing — target MEV. If already below MEV, ramp up to it
        # (more productive minimum volume is the remedy); if above, cut toward it.
        desired = max(mev, cur - 2)
        if cur < mev:
            reason = f"regressing (perf {perf}/5) but below MEV → build to minimum productive volume"
        else:
            reason = f"regressing (perf {perf}/5) → cut toward MEV"
    elif under_recovered:
        desired = max(mev, cur - 1)
        reason = f"under-recovered (soreness {soreness:.1f}/3) → back off a set"
    elif cur >= mrv:
        desired = mrv
        reason = "at MRV — volume ceiling; hold (deload candidate next block)"
    elif leg_interference:
        # Pickleball/cardio IS the leg stimulus this week — hold in place.
        desired = cur
        reason = f"court/cardio load high (cond. ACWR {conditioning_acwr:.2f}) → hold leg volume"
    elif perf is not None and perf >= 4:
        desired = cur + (2 if emphasis else 1)
        reason = f"progressing (perf {perf}/5){' + emphasis' if emphasis else ''} → add toward MRV"
    elif perf == 3:
        desired = cur + 1
        reason = "stalled e1RM → +1 set to break the stall"
    elif cur < grow_floor:
        # No performance signal yet, but below the floor it should be training at.
        desired = grow_floor
        floor_name = "emphasis floor" if emphasis else "MEV"
        reason = f"below {floor_name} → ramping up toward productive volume"
    else:
        desired = cur
        reason = "in range, no clear signal — hold and gather data"

    # Clamp to MRV, then to the asymmetric weekly step, then derive the action.
    target = max(0, min(mrv, desired))
    target = max(cur - MAX_WEEKLY_CUT, min(cur + MAX_WEEKLY_ADD, target))
    delta = target - cur
    action = "add" if delta > 0 else "cut" if delta < 0 else "hold"

    return MusclePrescription(
        muscle=muscle,
        current_sets=round(current, 1),
        target_sets=target,
        delta=delta,
        action=action,
        reason=reason,
        emphasis=emphasis,
    )


def _exercise_menu(
    conn: duckdb.DuckDBPyConnection, muscles: list[str], per_muscle: int = 4
) -> dict[str, list[str]]:
    """Candidate exercises per muscle, Rob's history first, excluding 'no' prefs."""
    avoid = {
        r[0]
        for r in conn.execute(
            "SELECT exercise FROM exercise_preferences WHERE status = 'no'"
        ).fetchall()
    }
    menu: dict[str, list[str]] = {}
    for muscle in muscles:
        rows = conn.execute(
            """
            SELECT m.exercise_name,
                   COALESCE(MAX(ws.started_at), '1900-01-01'::TIMESTAMP) AS last_done
            FROM exercise_muscle_map m
            LEFT JOIN workout_sets_dedup ws ON ws.exercise = m.exercise_name
            WHERE m.primary_muscle = ?
            GROUP BY m.exercise_name
            ORDER BY last_done DESC
            """,
            [muscle],
        ).fetchall()
        picks = [r[0] for r in rows if r[0] not in avoid][:per_muscle]
        if picks:
            menu[muscle] = picks
    return menu


def weekly_prescription(conn: duckdb.DuckDBPyConnection) -> Prescription:
    """Build this week's per-muscle volume prescription from Rob's logged data.

    The deterministic program: every targeted muscle gets a set target + action +
    reason; lagging lifts get a progression call; muscles needing volume get an
    exercise menu. The chat assembles the actual session from this.
    """
    state = active_mesocycle(conn)
    meso_id = state.id if state else ""
    this_week = _iso_week_start(date.today())

    targets = volume_targets(conn, meso_id)
    actuals = weekly_muscle_volume(conn, this_week)
    report = build_muscle_report(actuals, targets)
    soreness = _recent_soreness(conn)
    conditioning_acwr = _conditioning_pressure(conn)

    targeted = [r for r in report if r.mev is not None and r.mav is not None and r.mrv is not None]
    perfs = {r.muscle: _muscle_performance(conn, r.muscle) for r in targeted}
    deload = deload_check(perfs, targeted)

    muscle_rx: list[MusclePrescription] = []
    for r in targeted:
        muscle_rx.append(
            _decide(
                muscle=r.muscle,
                current=r.actual_sets,
                mev=r.mev,  # type: ignore[arg-type]
                mav=r.mav,  # type: ignore[arg-type]
                mrv=r.mrv,  # type: ignore[arg-type]
                perf=perfs[r.muscle],
                soreness=soreness.get(r.muscle, 0.0),
                conditioning_acwr=conditioning_acwr,
                deload=deload["recommended"],
            )
        )
    # Emphasis first, then the muscles being grown, then the rest.
    muscle_rx.sort(key=lambda m: (not m.emphasis, m.action != "add", m.muscle))

    # Lifts to progress: recently-trained exercises with a clear add/deload call.
    lift_progressions: list[dict] = []
    recent = conn.execute(
        """
        SELECT DISTINCT exercise FROM workout_sets_dedup
        WHERE started_at::DATE >= ? AND weight_kg > 0 AND reps > 0
        """,
        [(this_week - timedelta(days=14)).isoformat()],
    ).fetchall()
    for (ex,) in recent:
        ps = score_exercise(conn, ex)
        if ps is None:
            continue
        lift_progressions.append(
            {
                "exercise": ex,
                "e1rm_lbs": round(ps.e1rm_lbs),
                "perf_score": ps.perf_score,
                "trend": ps.trend,
                "recommendation": ps.recommendation,
            }
        )

    # Exercise menu for muscles that need volume (adding, or below MAV).
    need_volume = [m.muscle for m in muscle_rx if m.action == "add" or m.emphasis]
    menu = _exercise_menu(conn, need_volume)

    return Prescription(
        week_start=this_week,
        mesocycle_id=meso_id,
        deload=deload,
        muscles=muscle_rx,
        lift_progressions=lift_progressions,
        exercise_menu=menu,
    )


def prescription_context_block(conn: duckdb.DuckDBPyConnection) -> str:
    """Markdown block injected into the workout planner — the build order."""
    rx = weekly_prescription(conn)
    if not rx.muscles:
        return ""
    lines = ["## THIS WEEK'S PRESCRIPTION (build the session from this)"]
    if rx.deload.get("recommended"):
        lines.append(
            f"⚠ **DELOAD WEEK** — {rx.deload['reason']}. Volume is halved toward MEV "
            "across the board; keep loads moderate (RPE ≤7) and treat this as a "
            "fatigue-shedding week, not an accumulation week."
        )
    lines += [
        "Per-muscle volume targets the engine set from your performance + recovery.",
        "Prioritize muscles marked ADD and ★ emphasis; respect HOLD/CUT/DELOAD.",
        "",
        "| Muscle | Now | → Target | Action | Why |",
        "|--------|-----|----------|--------|-----|",
    ]
    for m in rx.muscles:
        star = " ★" if m.emphasis else ""
        lines.append(
            f"| {m.muscle}{star} | {m.current_sets:g} | {m.target_sets} "
            f"({m.delta:+d}) | {m.action.upper()} | {m.reason} |"
        )
    if rx.exercise_menu:
        lines.append("\n**Exercise menu for muscles needing volume** (your history first):")
        for muscle, exs in rx.exercise_menu.items():
            lines.append(f"- {muscle}: {', '.join(exs)}")
    return "\n".join(lines)
