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
import math
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
# accumulation runway (panel review M3).
#
# This frozenset is the DEFAULT/PRIOR only. The live emphasis set is derived at
# prescription time by :func:`_resolve_emphasis`, which folds in the metrics
# engine's physique_volume_bias() so emphasis shifts as muscles catch up — a
# muscle the silhouette/critique trend no longer flags drops out; a softening
# taper muscle (e.g. side_delts, lats) is promoted. This prior is Rob's stated
# focus set (biceps/glutes/traps) and applies when the physique signal is absent.
EMPHASIS_MUSCLES: frozenset[str] = frozenset({"biceps", "glutes", "traps"})

# A physique-bias factor at/above this promotes a muscle into the emphasis set
# even if it isn't in the biceps/glutes prior. The factor is in
# [1-_PHYSIQUE_BIAS_MAX, 1+_PHYSIQUE_BIAS_MAX] (metrics.py); >1 means the trended
# silhouette/critique signal wants more volume there.
EMPHASIS_PROMOTE_FACTOR = 1.05

# Confidence floor at/above which an ADD gets full authority; below it the add is
# scaled by confidence/_CONFIDENCE_FULL. CALIBRATION (fixed 2026-06-27): confidence
# is size_factor × signal_stability, and perf-score noise caps stability ~0.4, so
# even a muscle with 300+ scored weeks tops out near 0.34 — it can NEVER reach the
# old 0.5. Set on that real achievable range so a well-tracked muscle earns full
# add authority instead of being permanently throttled (the cause of every plan
# collapsing to 1 set/muscle). MEV is separately floored below so this only governs
# the ramp ABOVE minimum effective volume.
_CONFIDENCE_FULL = 0.30

# A large ADD (more than one set) requires at least this confidence. Set below the
# best-tracked muscles' ~0.34 ceiling (was 0.45 — unreachable, so it always fired
# and capped every muscle to +1/wk forever) so a well-sampled muscle can ramp +2.
_LARGE_ADD_CONFIDENCE_BAR = 0.22

# Per-muscle historical hit-rate at/below which the engine is hedged: a muscle
# the engine has prescribed poorly gets its ADD damped further (#10). Above this
# accuracy the prescription is trusted unweighted. None accuracy → no hedge.
_ACCURACY_HEDGE_BELOW = 0.55

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
    threshold: int | None = None,
) -> dict:
    """Decide whether a fatigue-driven deload is warranted from real signals.

    A deload fires when training is broadly unproductive or maxed out, NOT on a
    calendar (panel review M4): ≥``threshold`` muscles regressing (perf ≤ 2), or
    that many at/over MRV. ``threshold`` defaults to the RP population value
    (:data:`DELOAD_MUSCLE_THRESHOLD`); pass a personal value fitted by
    ``calibrate_deload_trigger`` to override. Returns the recommendation + the
    specific triggers so the prescription can explain itself.
    """
    thr = threshold if threshold is not None else DELOAD_MUSCLE_THRESHOLD
    regressing = sorted(m for m, p in perfs.items() if p is not None and p <= 2)
    at_mrv = sorted(r.muscle for r in report if r.mrv is not None and r.actual_sets >= r.mrv)
    triggers: list[str] = []
    if len(regressing) >= thr:
        triggers.append(f"{len(regressing)} muscles regressing ({', '.join(regressing[:5])})")
    if len(at_mrv) >= thr:
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


def _conditioning_pressure(
    conn: duckdb.DuckDBPyConnection,
    use_rpe_only: bool = False,
) -> float | None:
    """Conditioning ACWR — proxy for how much pickleball/cardio load is live.

    Read lazily from the daily state; None if unavailable. > 1.3 means the
    lower body is already absorbing meaningful court/cardio stimulus.

    When ``use_rpe_only=True`` (propranolol day), returns None to bypass the
    WHOOP-derived conditioning ACWR — HR is suppressed by the beta-blocker,
    making strain systematically understate real load; RPE is the only unbiased
    signal on dosed days.
    """
    if use_rpe_only:
        return None
    try:
        from shc.metrics import compute_daily_state

        return compute_daily_state(conn)["training_load"].get("conditioning_acwr")
    except Exception as exc:  # noqa: BLE001 — state optional; missing → no debit
        log.debug("conditioning pressure unavailable: %s", exc)
        return None


def _confidence_add_factor(
    confidence: float,
    scored_weeks: int,
    accuracy: float | None,
) -> float:
    """Multiplier in [0, 1] applied to a positive (ADD) volume delta.

    Converts the per-muscle noise floor from display-only to actuating (#1) and
    folds in historical prescription hit-rate (#10). Three conservative,
    multiplicative shrinks — never amplifies above 1.0:

    * **Confidence shrink**: below :data:`_CONFIDENCE_FULL` the add is scaled by
      ``confidence / _CONFIDENCE_FULL`` so a low-confidence muscle adds a
      fraction of a set, not a full one. With no signal at all (confidence 0,
      scored_weeks 0) the factor collapses to 0 and the add is suppressed.
    * **Accuracy hedge**: a muscle whose historical hit-rate is at/below
      :data:`_ACCURACY_HEDGE_BELOW` is damped proportionally to how poor it is,
      so the engine is more conservative where it has been wrong before. None
      accuracy (no scoreable history) applies no hedge — innocent until proven.

    Cuts are never passed here: backing off fatigue is a safety response and
    must stay at full authority (asymmetric clamp, panel review M10).
    """
    if scored_weeks <= 0 and confidence <= 0.0:
        return 0.0
    factor = 1.0
    if confidence < _CONFIDENCE_FULL:
        factor *= max(0.0, confidence / _CONFIDENCE_FULL)
    if accuracy is not None and accuracy <= _ACCURACY_HEDGE_BELOW:
        # Linear hedge: accuracy 0 → 0.5×, at the threshold → 1.0×.
        factor *= 0.5 + 0.5 * (accuracy / _ACCURACY_HEDGE_BELOW)
    return max(0.0, min(1.0, factor))


def _resolve_emphasis(
    physique_bias: dict[str, float] | None,
) -> tuple[set[str], dict[str, float]]:
    """Resolve the live emphasis set + per-muscle factor (#26/#3).

    Starts from the biceps/glutes prior (:data:`EMPHASIS_MUSCLES`) and folds in
    the metrics engine's ``physique_volume_bias()`` so emphasis tracks measured
    development instead of a static frozenset:

    * Any muscle the physique signal nudges at/above
      :data:`EMPHASIS_PROMOTE_FACTOR` joins the emphasis set (a softening taper
      promotes side_delts/lats, say).
    * The prior muscles stay in the set regardless, but their ramp/floor can be
      relaxed if the physique signal no longer flags them (factor toward 1.0).

    Returns ``(emphasis_muscles, factor_by_muscle)``. The factor defaults to 1.0
    for muscles the physique signal does not mention.
    """
    emphasis = set(EMPHASIS_MUSCLES)
    factors: dict[str, float] = {}
    if physique_bias:
        for muscle, factor in physique_bias.items():
            factors[muscle] = factor
            if factor >= EMPHASIS_PROMOTE_FACTOR:
                emphasis.add(muscle)
    return emphasis, factors


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
    rpe_factor: float = 1.0,
    emphasis: bool = False,
    emphasis_factor: float = 1.0,
    confidence: float = 0.0,
    scored_weeks: int = 0,
    accuracy: float | None = None,
) -> MusclePrescription:
    """Apply the RP set-progression tree + emphasis + interference for one muscle.

    ``action`` is derived from the final delta so it can never contradict the
    target, and every change is clamped asymmetrically (``MAX_WEEKLY_ADD`` up,
    ``MAX_WEEKLY_CUT`` down) so volume ramps gradually but can back off faster.
    When ``deload`` is set, the normal tree is bypassed: volume is halved toward
    MEV in a single deliberate drop (the step clamp does not apply to a deload).

    ``emphasis`` is now resolved dynamically by the caller (biceps/glutes prior
    modulated by physique_volume_bias) rather than read from a static frozenset.
    ``confidence``/``scored_weeks``/``accuracy`` gate the ADD: a low-confidence or
    historically-mis-prescribed muscle has its add shrunk toward zero, and a
    large (>1 set) add is suppressed unless confidence clears
    :data:`_LARGE_ADD_CONFIDENCE_BAR`. Cuts are never shrunk (safety asymmetry).
    """

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
        deload_floor = round(mev * 0.4)  # RP: deloads typically 30-50% of MEV
        target = max(0, min(mrv, max(deload_floor, round(cur0 * 0.5))))
        return MusclePrescription(
            muscle=muscle,
            current_sets=round(current, 1),
            target_sets=target,
            delta=target - cur0,
            action="deload",
            reason="deload week — volume ~halved to clear accumulated fatigue",
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
        # Emphasis muscles ramp +2; a strong physique nudge (emphasis_factor well
        # above 1) can lift a non-emphasis progressing muscle to +2 too, so the
        # ramp tracks the live development signal rather than a static membership.
        ramp = 2 if (emphasis or emphasis_factor >= EMPHASIS_PROMOTE_FACTOR) else 1
        desired = cur + ramp
        tag = " + emphasis" if emphasis else (" + physique nudge" if ramp == 2 else "")
        reason = f"progressing (perf {perf}/5){tag} → add toward MRV"
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

    # Apply RPE-drift damper before the asymmetric step clamp.
    # rpe_factor ∈ [0.5, 1.0]: only dampens, never amplifies.
    raw_delta = desired - cur
    desired = cur + round(raw_delta * rpe_factor)

    # The tree's `desired` is the volume this muscle SHOULD train at; below the
    # productive floor it was set to that floor. Confidence may throttle the
    # speculative ramp ABOVE minimum effective volume, but must never pull a
    # trainable muscle BELOW MEV — its minimum effective volume is non-negotiable.
    tree_target = desired

    # Confidence/accuracy gate on ADDs only (#1, #10). An add the engine is not
    # confident about — or has historically gotten wrong — is shrunk toward zero;
    # a cut keeps full authority. Done before the step clamp so the floor caps an
    # already-confidence-scaled add, never the other way round.
    hedge_note = ""
    if desired > cur:
        add_delta = desired - cur
        conf_factor = _confidence_add_factor(confidence, scored_weeks, accuracy)
        # A large add (>1 set) needs to clear a higher confidence bar; below it,
        # cap the add at a single set regardless of the tree's appetite.
        if add_delta > 1 and confidence < _LARGE_ADD_CONFIDENCE_BAR:
            add_delta = 1
            hedge_note = f" [add capped: confidence {confidence:.0%} below bar for a large add]"
        scaled = round(add_delta * conf_factor)
        if scaled < add_delta and not hedge_note:
            hedge_note = (
                f" [add shrunk {add_delta}→{scaled}: low confidence {confidence:.0%}"
                + (f"/accuracy {accuracy:.0%}" if accuracy is not None else "")
                + "]"
            )
        desired = cur + scaled

    # MEV floor: a trainable muscle must climb toward its minimum effective
    # volume regardless of confidence or which branch set `desired`. The perf
    # branches above ramp only +1/+2 from `cur`, so a muscle the deload spiral
    # left at 0 sets — but that still carries a stale "progressing" perf score —
    # would crawl up one set at a time instead of heading to MEV (the lockout
    # that collapsed every plan to ~1 set per muscle). Confidence governs the
    # ramp ABOVE MEV, never the climb to it. Only genuine recovery holds
    # (under-recovered, court/cardio leg interference) are allowed below MEV; the
    # climb is still rate-limited to +MAX_WEEKLY_ADD/wk by the clamp below, so a
    # starved muscle reaches MEV over a couple of weeks, not in a single jump.
    hold_below_mev = under_recovered or leg_interference
    mev_floor = min(tree_target, mev) if hold_below_mev else mev
    desired = max(desired, mev_floor)

    # Clamp to MRV, then to the asymmetric weekly step. The climb UP TO MEV is
    # exempt from the +per-week ceiling: at block start / after a deload a muscle
    # is re-seeded to its minimum effective volume in one step (RP block
    # initialization), not crawled there at +2/wk — that crawl was leaving a
    # fresh, recovered athlete with a 1-set-per-muscle session. Only the ramp
    # ABOVE MEV is rate-limited to +MAX_WEEKLY_ADD/wk.
    target = max(0, min(mrv, desired))
    add_ceiling = max(cur + MAX_WEEKLY_ADD, mev_floor)
    target = max(cur - MAX_WEEKLY_CUT, min(add_ceiling, target))
    delta = target - cur
    action = "add" if delta > 0 else "cut" if delta < 0 else "hold"

    return MusclePrescription(
        muscle=muscle,
        current_sets=round(current, 1),
        target_sets=target,
        delta=delta,
        action=action,
        reason=reason + _src_tag() + hedge_note,
        emphasis=emphasis,
        landmark_source=landmark_source,
        confidence=round(confidence, 2),
        scored_weeks=scored_weeks,
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


# Per-session hypertrophy set cap (RP guideline: ≤10 working sets per muscle per
# session before junk-volume / per-session fatigue dominates).
PER_SESSION_SET_CAP = 10

# The training-week split is the structured source of truth for #18 — it replaces
# the inline hardcoded "Upper-A (Tue)" strings. Each session declares its weekday
# and which body region it trains; the allocator derives labels and validates
# muscle→session assignment from this rather than a constant string buried in the
# function body. Matches Rob's logged schedule (lifts Tue–Fri). The planner /
# validator agent enforces the resulting per-session allocation + set cap.
WEEKLY_SPLIT: tuple[dict[str, str], ...] = (
    {"label": "Upper-A", "weekday": "Tue", "region": "upper"},
    {"label": "Lower-A", "weekday": "Wed", "region": "lower"},
    {"label": "Upper-B", "weekday": "Thu", "region": "upper"},
    {"label": "Lower-B", "weekday": "Fri", "region": "lower"},
)


def _session_split(
    muscle_rx: list[MusclePrescription],
    split: tuple[dict[str, str], ...] = WEEKLY_SPLIT,
) -> list[dict]:
    """Allocate the weekly set prescription across the real training-day split.

    Derives session labels and the muscle→session mapping from :data:`WEEKLY_SPLIT`
    (the structured schedule) instead of hardcoded strings (#18), so the split is
    validated against the actual training-day context and can be swapped without
    editing this function body. Lower-body muscles fan out across the lower days,
    everything else across the upper days; sets are distributed as evenly as the
    integer target allows.

    Each returned session is the structured allocation the validator/planner agent
    enforces::

        {
            "session": "Upper-A",          # label
            "weekday": "Tue",              # real training day
            "region": "upper" | "lower",
            "cap": PER_SESSION_SET_CAP,    # per-muscle ceiling to enforce
            "total_sets": int,             # sum across muscles this session
            "muscles": [{"muscle": str, "sets": int, "over_cap": bool}, ...],
        }

    ``over_cap`` flags any per-muscle allocation that breaches the cap so the
    validator can demand a re-split (it never silently truncates here — failing
    visibly beats degrading the prescription).
    """
    upper_labels = [s["label"] for s in split if s["region"] != "lower"]
    lower_labels = [s["label"] for s in split if s["region"] == "lower"]
    meta = {s["label"]: s for s in split}

    split_map: dict[str, list[dict]] = {s["label"]: [] for s in split}

    for rx in muscle_rx:
        if rx.target_sets <= 0:
            continue
        labels = lower_labels if rx.muscle in LOWER_BODY else upper_labels
        if not labels:  # schedule has no day for this region — surface, don't drop
            log.warning("no %s session in split for %s", rx.muscle, rx.muscle)
            continue

        n = len(labels)
        base, extra = divmod(rx.target_sets, n)
        for i, label in enumerate(labels):
            sets_this = base + (1 if i < extra else 0)
            if sets_this > 0:
                split_map[label].append(
                    {
                        "muscle": rx.muscle,
                        "sets": sets_this,
                        "over_cap": sets_this > PER_SESSION_SET_CAP,
                    }
                )

    out: list[dict] = []
    for label, entries in split_map.items():
        if not entries:
            continue
        m = meta[label]
        out.append(
            {
                "session": label,
                "weekday": m["weekday"],
                "region": m["region"],
                "cap": PER_SESSION_SET_CAP,
                "total_sets": sum(e["sets"] for e in entries),
                "muscles": entries,
            }
        )
    return out


def _protein_target_g(conn: duckdb.DuckDBPyConnection) -> int:
    """Protein target in grams: 1g per lb of bodyweight (RP/sports-science standard).

    Reads the most recent check-in weight rather than using a hardcoded snapshot.
    Falls back to 239g (Rob's bodyweight at the time of the original estimate) when
    no weight data is available.
    """
    row = conn.execute(
        """
        SELECT body_weight_kg
        FROM daily_checkin
        WHERE body_weight_kg IS NOT NULL
        ORDER BY date DESC
        LIMIT 1
        """
    ).fetchone()
    if row and row[0] is not None:
        # 1g/lb: kg → lbs × 1g/lb
        return int(round(float(row[0]) * 2.20462))
    return 239  # fallback to bodyweight snapshot


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

    target_g = _protein_target_g(conn)

    if not rows:
        return {
            "adequate": None,
            "avg_7d": None,
            "target": target_g,
            "pct": None,
            "days_logged": 0,
            "note": "No protein data logged — start tracking daily protein in check-in",
        }

    values = [float(r[0]) for r in rows]
    avg = sum(values) / len(values)
    pct = avg / target_g
    low_days = sum(1 for v in values if v < target_g * 0.80)
    adequate = low_days < 4  # adequate if < 4 of last days were below 80% of target

    return {
        "adequate": adequate,
        "avg_7d": round(avg),
        "target": target_g,
        "pct": round(pct, 2),
        "days_logged": len(values),
        "note": (
            None
            if adequate
            else f"Protein avg {round(avg)}g vs target {target_g}g "
            f"({low_days} of {len(values)} days below 80%) — "
            "hold volume increases until protein is consistent"
        ),
    }


def _rpe_drift_factor(
    conn: duckdb.DuckDBPyConnection,
    min_sessions: int = 5,
    min_magnitude: float = 0.8,
) -> float:
    """Volume-delta multiplier in [0.5, 1.0] from 14-day signed RPE drift.

    Returns 1.0 (no-op) when drift is absent, small, or there aren't enough
    sessions to establish a directional trend. Only dampens — never amplifies
    beyond 1.0 — so an athlete who is consistently working harder than target
    (over-RPE) gets a conservative volume correction, not a volume boost.
    """
    from shc.ai.quality import rpe_drift_signed_mean

    signed_mean = rpe_drift_signed_mean(conn)
    if signed_mean is None or abs(signed_mean) < min_magnitude:
        return 1.0
    raw = 1.0 + math.copysign(min(abs(signed_mean) / 3.0, 0.5), signed_mean)
    return max(0.5, min(1.0, raw))


def weekly_prescription(
    conn: duckdb.DuckDBPyConnection,
    propranolol_day: bool = False,
) -> Prescription:
    """Build this week's per-muscle volume prescription from Rob's logged data.

    The deterministic program: every targeted muscle gets a set target + action +
    reason; lagging lifts get a progression call; muscles needing volume get an
    exercise menu. The chat assembles the actual session from this.

    ``propranolol_day`` bypasses WHOOP-derived conditioning ACWR (HR-suppressed,
    unreliable on dosed days) and restores full RPE-drift authority to the
    volume decision.
    """
    state = active_mesocycle(conn)
    meso_id = state.id if state else ""
    this_week = _iso_week_start(date.today())

    targets = volume_targets(conn, meso_id)
    actuals = weekly_muscle_volume(conn, this_week)
    report = build_muscle_report(actuals, targets)
    soreness = _recent_soreness(conn)
    conditioning_acwr = _conditioning_pressure(conn, use_rpe_only=propranolol_day)

    targeted = [r for r in report if r.mev is not None and r.mav is not None and r.mrv is not None]
    perfs = {r.muscle: _muscle_performance(conn, r.muscle) for r in targeted}
    from shc.training.self_learning import read_deload_threshold

    deload_threshold = read_deload_threshold(conn)
    signal_deload = deload_check(perfs, targeted, threshold=deload_threshold)

    # Unify signal-based and calendar-based deloads under a single OR gate.
    # Either triggers a deload; the distinction is preserved in deload_reason
    # so the planner can apply the correct volume reduction depth.
    is_deload_week = state.is_deload_week if state else False
    signal_based = signal_deload["recommended"]
    is_deloading = is_deload_week or signal_based
    if is_deloading:
        if is_deload_week and signal_based:
            deload_reason_str = "both"
        elif is_deload_week:
            deload_reason_str = "calendar"
        else:
            deload_reason_str = "signal"
    else:
        deload_reason_str = None

    deload = {
        **signal_deload,
        "recommended": is_deloading,
        "deload_reason": deload_reason_str,
        "reason": (
            signal_deload["reason"]
            if signal_based
            else (
                f"calendar deload — week {state.week_number} exceeds planned {state.planned_weeks}"
                if is_deload_week and state
                else signal_deload["reason"]
            )
        ),
    }

    # Protein gate: flag if recent intake is inadequate for hypertrophy.
    protein = _protein_gate(conn)

    # RPE drift factor: dampen volume deltas when athlete is consistently
    # working harder than target (persistent over-RPE). On propranolol days
    # RPE is the only unbiased signal, so restore full authority (factor = 1.0).
    rpe_factor = 1.0 if propranolol_day else _rpe_drift_factor(conn)

    # Signal quality from materialized cache (avoids per-request DB aggregation).
    from shc.training.self_learning import read_signal_quality_cache

    signal_quality = read_signal_quality_cache(conn)

    # Dynamic emphasis (#26/#3): biceps/glutes prior modulated by the metrics
    # engine's physique signal. Degrade gracefully if the helper is unavailable.
    physique_bias: dict[str, float] | None = None
    try:
        from shc.metrics import physique_volume_bias

        physique_bias = physique_volume_bias(conn)
    except Exception as exc:  # noqa: BLE001 — physique signal optional → prior only
        log.debug("physique_volume_bias unavailable, using emphasis prior: %s", exc)
    emphasis_muscles, emphasis_factors = _resolve_emphasis(physique_bias)

    # Per-muscle historical prescription accuracy (#10): hedge muscles the engine
    # has called poorly. Helper is the self_learning read path; absent → no hedge.
    accuracy_by_muscle: dict[str, dict[str, object]] = {}
    try:
        from shc.training.self_learning import read_muscle_prescription_accuracy

        accuracy_by_muscle = read_muscle_prescription_accuracy(conn)
    except Exception as exc:  # noqa: BLE001 — accuracy optional → unweighted
        log.debug("read_muscle_prescription_accuracy unavailable: %s", exc)

    muscle_rx: list[MusclePrescription] = []
    for r in targeted:
        vt = targets.get(r.muscle)
        sq = signal_quality.get(r.muscle, {})
        acc_row = accuracy_by_muscle.get(r.muscle, {})
        acc_val = acc_row.get("accuracy")
        accuracy = float(acc_val) if isinstance(acc_val, (int, float)) else None
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
            rpe_factor=rpe_factor,
            emphasis=r.muscle in emphasis_muscles,
            emphasis_factor=emphasis_factors.get(r.muscle, 1.0),
            confidence=float(sq.get("confidence", 0.0)),
            scored_weeks=int(sq.get("scored_weeks", 0)),
            accuracy=accuracy,
        )
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

    # Session split (advisory — the validator agent enforces cap + allocation).
    if rx.session_split:
        lines.append(f"\n## RECOMMENDED SESSION SPLIT (≤{PER_SESSION_SET_CAP} sets/muscle/session)")
        for sess in rx.session_split:
            entries = ", ".join(
                f"{e['muscle']} ×{e['sets']}" + ("⚠" if e.get("over_cap") else "")
                for e in sess["muscles"]
            )
            day = sess.get("weekday", "")
            total = sess.get("total_sets", "")
            lines.append(f"- **{sess['session']} ({day})** [{total} sets]: {entries}")

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
