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
    landmark_source: str = "population"  # 'population' | 'personal' | 'personal_floored'
    confidence: float = 0.0  # 0–1; how much to trust this call
    scored_weeks: int = 0  # raw sample size behind the confidence estimate


@dataclass
class Prescription:
    week_start: date
    mesocycle_id: str
    deload: dict = field(default_factory=dict)  # {recommended, reason, triggers}
    muscles: list[MusclePrescription] = field(default_factory=list)
    lift_progressions: list[dict] = field(default_factory=list)
    exercise_menu: dict[str, list[str]] = field(default_factory=dict)
    session_split: list[dict] = field(default_factory=list)  # [{session, muscles, sets}]
    protein_gate: dict = field(default_factory=dict)  # {adequate, avg_7d, target, pct}


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
    landmark_source: str = "population",
) -> MusclePrescription:
    """Apply the RP set-progression tree + emphasis + interference for one muscle.

    ``action`` is derived from the final delta so it can never contradict the
    target, and every change is clamped asymmetrically (``MAX_WEEKLY_ADD`` up,
    ``MAX_WEEKLY_CUT`` down) so volume ramps gradually but can back off faster.
    When ``deload`` is set, the normal tree is bypassed: volume is halved toward
    MEV in a single deliberate drop (the step clamp does not apply to a deload).
    """
    emphasis = muscle in EMPHASIS_MUSCLES

    # Append landmark source to reason for auditing — tells the planner (and Rob)
    # whether the MEV/MRV boundaries come from personal data or RP population norms.
    def _src_tag() -> str:
        if landmark_source == "personal":
            return f" [personal MEV={mev}/MRV={mrv}]"
        if landmark_source == "personal_floored":
            return f" [personal MEV={mev}, MRV={mrv}↑ floored — may be undertrained]"
        return ""

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
            landmark_source=landmark_source,
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
            reason = (
                f"regressing (perf {perf}/5) but below MEV → build to minimum productive volume"
            )
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
        reason=reason + _src_tag(),
        emphasis=emphasis,
        landmark_source=landmark_source,
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


def _session_split(
    muscle_rx: list[MusclePrescription],
) -> list[dict]:
    """Recommend how to split the weekly set prescription across training sessions.

    RP guideline: ≤10 sets per muscle per session for hypertrophy.  Rob trains
    4 days (Tue–Fri); session labels are Upper-A/Lower-A/Upper-B/Lower-B.
    Lower-body muscles are split across the two lower days, upper-body across
    the two upper days.  Arm muscles get 3 mini-sessions if target > 10 sets.
    """
    LOWER = frozenset({"quads", "hamstrings", "glutes", "calves", "adductors"})
    UPPER_SESSIONS = ["Upper-A (Tue)", "Upper-B (Thu)"]
    LOWER_SESSIONS = ["Lower-A (Wed)", "Lower-B (Fri)"]

    split_map: dict[str, list[dict]] = {s: [] for s in UPPER_SESSIONS + LOWER_SESSIONS}

    for rx in muscle_rx:
        if rx.target_sets <= 0:
            continue
        sessions = LOWER_SESSIONS if rx.muscle in LOWER else UPPER_SESSIONS

        n = len(sessions)
        base, extra = divmod(rx.target_sets, n)
        for i, sess in enumerate(sessions):
            sets_this = base + (1 if i < extra else 0)
            if sets_this > 0:
                split_map[sess].append({"muscle": rx.muscle, "sets": sets_this})

    return [{"session": sess, "muscles": entries} for sess, entries in split_map.items() if entries]


# Protein target: 1g per lb of bodyweight is the RP/sports-science standard for recomp.
# Rob's bodyweight ≈ 239 lb → 239g. Stored in personal_context but approximated here.
_PROTEIN_TARGET_G = 239


def _protein_gate(conn: duckdb.DuckDBPyConnection) -> dict:
    """Check recent protein adequacy from daily check-in.

    Returns adequacy assessment — used to gate volume-increase prescriptions.
    If protein has been < 80% of target for ≥4 of the last 7 days with data,
    flag as inadequate: adding volume won't produce hypertrophy without substrate.
    """
    rows = conn.execute(
        """
        SELECT protein_grams
        FROM daily_checkin
        WHERE date >= (CURRENT_DATE - INTERVAL 7 DAYS)
          AND protein_grams IS NOT NULL
        ORDER BY date DESC
        """
    ).fetchall()

    if not rows:
        return {
            "adequate": None,
            "avg_7d": None,
            "target": _PROTEIN_TARGET_G,
            "pct": None,
            "days_logged": 0,
            "note": "No protein data logged — start tracking daily protein in check-in",
        }

    values = [float(r[0]) for r in rows]
    avg = sum(values) / len(values)
    pct = avg / _PROTEIN_TARGET_G
    low_days = sum(1 for v in values if v < _PROTEIN_TARGET_G * 0.80)
    adequate = low_days < 4  # adequate if < 4 of last days were below 80% of target

    return {
        "adequate": adequate,
        "avg_7d": round(avg),
        "target": _PROTEIN_TARGET_G,
        "pct": round(pct, 2),
        "days_logged": len(values),
        "note": (
            None
            if adequate
            else f"Protein avg {round(avg)}g vs target {_PROTEIN_TARGET_G}g "
            f"({low_days} of {len(values)} days below 80%) — "
            "hold volume increases until protein is consistent"
        ),
    }


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

    # Protein gate: flag if recent intake is inadequate for hypertrophy.
    protein = _protein_gate(conn)

    # Signal quality from materialized cache (avoids per-request DB aggregation).
    from shc.training.self_learning import read_signal_quality_cache

    signal_quality = read_signal_quality_cache(conn)

    muscle_rx: list[MusclePrescription] = []
    for r in targeted:
        vt = targets.get(r.muscle)
        sq = signal_quality.get(r.muscle, {})
        rx = _decide(
            muscle=r.muscle,
            current=r.actual_sets,
            mev=r.mev,  # type: ignore[arg-type]
            mav=r.mav,  # type: ignore[arg-type]
            mrv=r.mrv,  # type: ignore[arg-type]
            perf=perfs[r.muscle],
            soreness=soreness.get(r.muscle, 0.0),
            conditioning_acwr=conditioning_acwr,
            deload=deload["recommended"],
            landmark_source=vt.source if vt else "population",
        )
        rx.confidence = float(sq.get("confidence", 0.0))
        rx.scored_weeks = int(sq.get("scored_weeks", 0))
        # If protein is inadequate, cap "add" actions at "hold" for non-emphasis muscles.
        if rx.action == "add" and not rx.emphasis and protein.get("adequate") is False:
            rx.action = "hold"
            rx.reason = (
                rx.reason + " [held: protein below target — substrate needed to convert stimulus]"
            )
        muscle_rx.append(rx)

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
        session_split=_session_split(muscle_rx),
        protein_gate=protein,
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

    # Session split.
    if rx.session_split:
        lines.append("\n## RECOMMENDED SESSION SPLIT (≤10 sets/muscle/session)")
        for sess in rx.session_split:
            entries = ", ".join(f"{e['muscle']} ×{e['sets']}" for e in sess["muscles"])
            lines.append(f"- **{sess['session']}**: {entries}")

    # Protein gate.
    pg = rx.protein_gate
    if pg.get("adequate") is False and pg.get("note"):
        lines.append(f"\n⚠ **PROTEIN GATE**: {pg['note']}")
    elif pg.get("adequate") is None:
        lines.append(
            f"\n📋 **PROTEIN**: Not yet tracked — add `protein_grams` to daily check-in. "
            f"Target {pg['target']}g/day for recomp."
        )
    else:
        lines.append(
            f"\n✓ **PROTEIN**: {pg.get('avg_7d')}g avg (target {pg['target']}g, "
            f"{round((pg.get('pct', 0) or 0) * 100)}%)"
        )
    return "\n".join(lines)
