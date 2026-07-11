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
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta

import duckdb

from shc.training.mesocycle import (
    _iso_week_start,
    active_mesocycle,
    score_exercise,
    volume_targets,
)
from shc.training.volume import (
    MuscleVolume,
    build_muscle_report,
    weekly_muscle_volume,
    weekly_region_volume,
)

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
    # Sports-science-grounded picks per muscle (lengthened-position + head
    # coverage + rep target + citation). Curated muscles only; the rest stay in
    # exercise_menu (recency). See :func:`evidence_menu`.
    exercise_science: dict[str, list[dict]] = field(default_factory=dict)
    # Per-muscle head/region trained-volume this week ({muscle: {region: sets}}),
    # so the plan can see which head (long/short/brachialis) is under-stimulated.
    region_coverage: dict[str, dict[str, float]] = field(default_factory=dict)
    development: dict[str, dict] = field(default_factory=dict)  # per-muscle dev brief
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
            # Fail VISIBLY: a corrupt check-in silently dropped here means a sore
            # muscle reads as 0 soreness and gets ramped instead of held. Warn so
            # the bad row surfaces rather than quietly degrading the gate.
            log.warning(
                "soreness check-in row is not valid JSON — skipping (soreness signal degraded)"
            )
            continue
        if not isinstance(data, dict):
            log.warning("soreness check-in payload is not an object — skipping: %r", data)
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


def load_emphasis(conn: duckdb.DuckDBPyConnection) -> dict[str, float]:
    """Load Rob's persisted muscle-emphasis priorities from the DB.

    Returns ``{muscle: weight}``. An empty dict when the ``muscle_emphasis`` table
    is missing or empty, so the caller falls back to the :data:`EMPHASIS_MUSCLES`
    prior — the engine stays robust whether or not the migration has run. This is
    the path that lets what Rob sets (via ``POST /training/emphasis``) actually
    reach the prescription, instead of living only in chat memory.
    """
    try:
        rows = conn.execute("SELECT muscle, weight FROM muscle_emphasis").fetchall()
    except Exception as exc:  # noqa: BLE001 — table optional → prior fallback
        log.debug("muscle_emphasis unavailable, using prior: %s", exc)
        return {}
    return {str(m): float(w) for m, w in rows}


def _resolve_emphasis(
    physique_bias: dict[str, float] | None,
    db_emphasis: dict[str, float] | None = None,
) -> tuple[set[str], dict[str, float]]:
    """Resolve the live emphasis set + per-muscle factor (#26/#3).

    Starts from Rob's persisted priorities (``db_emphasis``, from
    :func:`load_emphasis`) — falling back to the biceps/glutes prior
    (:data:`EMPHASIS_MUSCLES`) when none are stored — and folds in the metrics
    engine's ``physique_volume_bias()`` so emphasis tracks both stated intent and
    measured development instead of a static frozenset:

    * Any muscle the physique signal nudges at/above
      :data:`EMPHASIS_PROMOTE_FACTOR` joins the emphasis set (a softening taper
      promotes side_delts/lats, say).
    * The stored/prior muscles stay in the set regardless, but their ramp/floor
      can be relaxed if the physique signal no longer flags them (factor → 1.0).

    Returns ``(emphasis_muscles, factor_by_muscle)``. The factor defaults to 1.0
    for muscles the physique signal does not mention.
    """
    emphasis = set(db_emphasis) if db_emphasis else set(EMPHASIS_MUSCLES)
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
    # A muscle is "emphasized" if it's in the set or carries a strong physique
    # nudge; emphasized muscles ramp at +2 (not just on the progressing branch)
    # so a LAGGING priority muscle — which rarely shows perf≥4 and has thin,
    # low-confidence direct history — actually climbs instead of crawling +1.
    emphasized = emphasis or emphasis_factor >= EMPHASIS_PROMOTE_FACTOR
    ramp_step = 2 if emphasized else 1
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
        desired = cur + ramp_step
        tag = " + emphasis" if emphasized else ""
        reason = f"progressing (perf {perf}/5){tag} → add toward MRV"
    elif perf == 3:
        # Stalled: emphasized muscles break the stall at +2 (the whole point of
        # flagging a bring-up is to push it harder than a maintenance muscle).
        desired = cur + ramp_step
        tag = " (emphasis)" if emphasized else ""
        reason = f"stalled e1RM{tag} → +{ramp_step} set to break the stall"
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
        # A muscle that is MEASURABLY progressing (perf >= 4) has an unambiguous
        # OUTCOME signal. The confidence shrink exists to damp SPECULATIVE adds on
        # noisy data — not to freeze a muscle that is demonstrably adapting. Without
        # this floor, confidence (which tops out ~0.34 by design) rounds every add
        # to zero and pins a progressing muscle at its grow-floor forever: e.g.
        # glutes at max PR for 8 weeks stuck at 7 sets, unable to climb toward MRV
        # 16. Guarantee a progressing add survives at >= 1 set/wk (the RP
        # accumulation floor). Speculative adds (no perf signal) are still shrunk.
        if perf is not None and perf >= 4 and scaled < 1:
            scaled = 1
            hedge_note = " [progressing (perf ≥4) → +1 floor applied despite low confidence]"
        elif scaled < add_delta and not hedge_note:
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
    # An emphasized muscle's productive floor (grow_floor = MEV–MAV midpoint) is
    # non-speculative the same way MEV is: bringing a lagging priority muscle up
    # to a productive baseline is the whole reason emphasis exists, so the
    # confidence shrink — which governs only the speculative ramp ABOVE the floor
    # — must not pull it back down. Applies only when the tree wants to grow/hold
    # (tree_target >= cur) and the muscle isn't held below MEV for recovery; a
    # safety cut (regressing) is never floored above its decision. The climb to
    # this floor is still rate-limited above MEV by the step clamp below.
    if emphasized and not hold_below_mev and tree_target >= cur:
        desired = max(desired, min(grow_floor, mrv))
    elif emphasized and leg_interference and not under_recovered:
        # An emphasis lower-body muscle (e.g. glutes) is never frozen below MEV
        # by conditioning interference alone. Court/cardio load debits leg
        # RECOVERY, which is why quads/hams/adductors — the tissues that absorb
        # the real eccentric court load — still hold in place (they fall to the
        # else branch). But a lagging *priority* muscle that pickleball does not
        # heavily damage still earns its minimum effective volume: without this,
        # glutes sit at 0 for every week cond. ACWR > 1.5 (i.e. most weeks, given
        # 1000+ min/mo of play), which is the silent under-train invariant 3
        # forbids. Floor at MEV, not the emphasis midpoint — present but
        # conservative while sport volume is high. The +MAX_WEEKLY_ADD step clamp
        # below still eases the climb in over ~2–3 weeks rather than dumping it.
        if mev > desired:
            reason += " — but emphasis muscle floored at MEV (not frozen at 0 by court load)"
        desired = max(desired, mev)
    else:
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


_LENGTH_RANK = {"lengthened": 0, "mid": 1, "shortened": 2}
_SFR_RANK = {"high": 0, "moderate": 1, "low": 2}


def load_muscle_development(conn: duckdb.DuckDBPyConnection) -> dict[str, dict]:
    """Per-muscle programming evidence (regions to cover, dose, freq, citation).

    Reads the curated ``muscle_development`` table. Empty dict if the table is
    absent (migration not yet run) so callers degrade to the legacy menu.
    """
    try:
        rows = conn.execute(
            "SELECT muscle, regions, length_priority, weekly_sets_low, "
            "weekly_sets_high, freq_per_week, rep_scheme, rationale, citation, "
            "citation_url FROM muscle_development"
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — evidence layer optional → legacy menu
        log.debug("muscle_development unavailable: %s", exc)
        return {}
    out: dict[str, dict] = {}
    for r in rows:
        try:
            regions = json.loads(r[1]) if r[1] else []
        except (json.JSONDecodeError, TypeError):
            regions = []
        out[r[0]] = {
            "regions": regions,
            "length_priority": r[2],
            "weekly_sets_low": r[3],
            "weekly_sets_high": r[4],
            "freq_per_week": r[5],
            "rep_scheme": r[6],
            "rationale": r[7],
            "citation": r[8],
            "citation_url": r[9],
        }
    return out


def _select_grounded(
    cands: list[tuple],
    per_muscle: int,
    region_volume: dict[str, float] | None = None,
    progress_rank: Mapping[str, int] | None = None,
) -> list[tuple]:
    """Pick exercises head-first, quality-ranked, and stable — swap only on plateau.

    Five-key ordering, most significant first:

    1. **Head deficit** — the region (long/short/brachialis) with the LEAST
       trained volume this week leads, so the neglected head gets programmed
       first. ``region_volume`` maps this muscle's ``region → credited sets``
       (from :func:`shc.training.volume.weekly_region_volume`); absent → all
       heads tie and ordering falls through to quality.
    2. **Length bias** — lengthened-position movements float up (stretch stimulus).
    3. **Stimulus-to-fatigue** — high-SFR options preferred.
    4. **Progress state** — among otherwise-equal options a lift Rob is actively
       PROGRESSING on is kept (rank 0), an untried option is neutral (1), and a
       PLATEAUED lift (stalled/regressing e1RM trend) is demoted (2) so an
       equal-quality alternative for that head surfaces. This is the
       evidence-based rotation trigger — swap on plateau, not on a weekly clock
       (Balsalobre; Rauch): fixed selection matches or beats variation for
       hypertrophy, so a movement is only rotated once progress on it stalls.
       ``progress_rank`` maps ``exercise_name → {0,1,2}``; absent → all neutral.
    5. **Name** — deterministic final tiebreaker (storage-order independent).

    Because the ordering carries no time term, selection is STABLE week to week
    (the same best set recurs) until a lift plateaus — exactly what the research
    prescribes. A coverage pass then takes one movement per distinct head in that
    order so every head is trained, before filling remaining slots with the next
    best.
    """
    rv = region_volume or {}
    pr = progress_rank or {}

    def _region(c) -> str:
        return c[2] or c[1]

    def _deficit(c) -> float:
        # Lower trained volume on this head → sorts earlier (trained first).
        return rv.get(_region(c), 0.0)

    def _progress(c) -> int:
        # 0 progressing (keep) < 1 untried (neutral) < 2 plateaued (swap-eligible).
        return pr.get(c[0], 1)

    ordered = sorted(
        cands,
        key=lambda c: (
            _deficit(c),
            _LENGTH_RANK.get(c[3], 1),
            _SFR_RANK.get(c[6], 1),
            _progress(c),
            c[0],  # exercise name — deterministic final tiebreaker (storage-order independent)
        ),
    )
    picks: list[tuple] = []
    seen_regions: set[str] = set()
    for c in ordered:  # coverage pass: one per head, most-neglected head first
        if len(picks) >= per_muscle:
            break
        region = _region(c)
        if region not in seen_regions:
            picks.append(c)
            seen_regions.add(region)
    for c in ordered:  # fill remaining slots with next-best
        if len(picks) >= per_muscle:
            break
        if c not in picks:
            picks.append(c)
    return picks[:per_muscle]


def _load_exercise_aliases(conn: duckdb.DuckDBPyConnection) -> dict[str, str]:
    """Curated ``exercise_science`` name → the string Rob actually logs it under.

    Bridges the naming gap between the curated science catalog and Hevy's logged
    exercise strings (e.g. ``Tricep Pushdown (Cable)`` → ``Cable Tricep Pushdown``)
    so a plateau signal can be read for staples logged under a variant name. Absent
    table (pre-migration) degrades to no aliases — every name resolves to itself.
    """
    try:
        return {
            r[0]: r[1]
            for r in conn.execute(
                "SELECT canonical_name, logged_name FROM exercise_alias"
            ).fetchall()
        }
    except Exception as exc:  # noqa: BLE001 — alias table optional
        log.debug("exercise_alias unavailable: %s", exc)
        return {}


def _progress_ranks(
    conn: duckdb.DuckDBPyConnection,
    names: set[str],
    aliases: Mapping[str, str] | None = None,
) -> dict[str, int]:
    """Map each curated exercise to a swap-priority rank from its e1RM trend.

    ``0`` = actively progressing (keep it), ``1`` = untried / too little history
    to judge (neutral), ``2`` = plateaued (stalled or regressing) and therefore
    eligible to be swapped for an equal-quality alternative. This is what turns
    :func:`_select_grounded` into a plateau-triggered rotator rather than a weekly
    one. Curated names are resolved to Rob's logged variant via ``aliases`` (e.g.
    ``Tricep Pushdown (Cable)`` → ``Cable Tricep Pushdown``) before scoring, so a
    staple logged under a different string still contributes a plateau signal.
    """
    al = aliases or {}
    ranks: dict[str, int] = {}
    for name in names:
        try:
            ps = score_exercise(conn, al.get(name, name))
        except Exception as exc:  # noqa: BLE001 — scoring optional, never blocks selection
            log.debug("score_exercise failed for %s: %s", name, exc)
            ps = None
        if ps is None:
            ranks[name] = 1
        elif ps.trend == "progressing":
            ranks[name] = 0
        else:  # stalled | regressing
            ranks[name] = 2
    return ranks


def evidence_menu(
    conn: duckdb.DuckDBPyConnection, muscles: list[str], per_muscle: int = 4
) -> dict[str, list[dict]]:
    """Sports-science-grounded exercise picks per muscle (the guiding light).

    For a muscle with curated ``exercise_science`` rows, selects movements to
    lead with a lengthened-position option and cover every head/region the
    evidence says to train (see :func:`_select_grounded`), each carrying its rep
    target, rationale, and citation. A muscle with no curated rows is omitted
    here and falls back to the legacy recency menu (:func:`_exercise_menu`).
    """
    try:
        avoid = {
            r[0]
            for r in conn.execute(
                "SELECT exercise FROM exercise_preferences WHERE status = 'no'"
            ).fetchall()
        }
    except Exception:  # noqa: BLE001
        avoid = set()
    # This week's per-head trained volume steers selection toward the neglected
    # head; degrade to recency/quality-only if the region ledger is unavailable.
    try:
        region_vol = weekly_region_volume(conn, _iso_week_start(date.today()))
    except Exception as exc:  # noqa: BLE001 — region ledger optional
        log.debug("weekly_region_volume unavailable: %s", exc)
        region_vol = {}

    # Pull each muscle's curated candidates, then score every distinct candidate's
    # progression once so selection can demote plateaued lifts (swap-on-plateau).
    per_muscle_rows: dict[str, list[tuple]] = {}
    for muscle in muscles:
        try:
            rows = conn.execute(
                """
                SELECT s.exercise_name, s.muscle, s.region, s.length_bias,
                       s.rep_low, s.rep_high, s.sfr_tier, s.rationale, s.citation,
                       s.citation_url
                FROM exercise_science s
                WHERE s.muscle = ?
                """,
                [muscle],
            ).fetchall()
        except Exception as exc:  # noqa: BLE001 — evidence layer optional
            log.debug("exercise_science unavailable for %s: %s", muscle, exc)
            continue
        cands = [r for r in rows if r[0] not in avoid]
        if cands:
            per_muscle_rows[muscle] = cands

    aliases = _load_exercise_aliases(conn)
    all_names = {c[0] for cands in per_muscle_rows.values() for c in cands}
    progress = _progress_ranks(conn, all_names, aliases)

    out: dict[str, list[dict]] = {}
    for muscle, cands in per_muscle_rows.items():
        out[muscle] = [
            {
                "exercise": c[0],
                "region": c[2],
                "length_bias": c[3],
                "rep_low": c[4],
                "rep_high": c[5],
                "sfr_tier": c[6],
                "rationale": c[7],
                "citation": c[8],
                "citation_url": c[9],
            }
            for c in _select_grounded(cands, per_muscle, region_vol.get(muscle), progress)
        ]
    return out


# Weeks of scored history at/above which a muscle's targets are treated as
# personalized rather than population defaults (matches the landmark-fit floor).
_PERSONALIZE_MIN_WEEKS = 10


def muscle_science_report(conn: duckdb.DuckDBPyConnection, muscle: str | None = None) -> list[dict]:
    """The build-a-muscle surface: cited brief + grounded exercises + data honesty.

    For each curated muscle (or just ``muscle`` if given) assemble: the
    ``muscle_development`` brief, the sports-science-grounded exercise selection
    (:func:`evidence_menu`), the active MEV/MAV/MRV landmarks, and an HONEST
    data-coverage read — whether those targets are personalized to Rob's logged
    history or still population defaults, and how many more weeks of data would
    personalize them. This is what lets the engine explain how to build any body
    part AND be transparent about how personal that advice currently is.
    """
    dev = load_muscle_development(conn)
    muscles = [muscle] if muscle else sorted(dev)
    from shc.training.self_learning import read_signal_quality_cache

    try:
        sq = read_signal_quality_cache(conn)
    except Exception as exc:  # noqa: BLE001 — signal cache optional
        log.debug("signal cache unavailable for science report: %s", exc)
        sq = {}
    state = active_mesocycle(conn)
    targets = volume_targets(conn, state.id if state else "")
    menus = evidence_menu(conn, muscles)

    out: list[dict] = []
    for m in muscles:
        brief = dev.get(m)
        q = sq.get(m, {})
        scored = int(q.get("scored_weeks", 0))
        conf = float(q.get("confidence", 0.0))
        vt = targets.get(m)
        source = vt.source if vt else "population"
        personalized = source != "population" or scored >= _PERSONALIZE_MIN_WEEKS
        if personalized:
            note = f"personalized from {scored} scored week(s) of your data"
        else:
            need = max(1, _PERSONALIZE_MIN_WEEKS - scored)
            note = (
                f"population default — log ~{need} more week(s) training this muscle "
                "to personalize the targets"
            )
        out.append(
            {
                "muscle": m,
                "grounded": brief is not None,
                "brief": brief,
                "exercises": menus.get(m, []),
                "targets": (
                    {"mev": vt.mev, "mav": vt.mav, "mrv": vt.mrv, "source": source} if vt else None
                ),
                "data_coverage": {
                    "scored_weeks": scored,
                    "confidence": round(conf, 2),
                    "personalized": personalized,
                    "note": note,
                },
            }
        )
    return out


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
    db_emphasis = load_emphasis(conn)
    emphasis_muscles, emphasis_factors = _resolve_emphasis(physique_bias, db_emphasis)

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
        # Only a LOGGED prescription-outcome hit-rate may actuate the ADD hedge.
        # Retroactive accuracy is an inferred proxy (it reads the prescription
        # back OUT of perf momentum), so it measures noise persistence, not call
        # quality — trusting it would damp a muscle for being noisy. Shown for
        # transparency, never trusted to throttle ("innocent until proven").
        acc_val = acc_row.get("accuracy") if acc_row.get("source") == "logged" else None
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
    # Sports-science-grounded selection (evidence_menu) leads; the legacy recency
    # menu fills any muscle not yet curated in the exercise-science layer.
    need_volume = [m.muscle for m in muscle_rx if m.action == "add" or m.emphasis]
    menu = _exercise_menu(conn, need_volume)
    science = evidence_menu(conn, need_volume)
    development = {m: d for m, d in load_muscle_development(conn).items() if m in need_volume}
    try:
        all_regions = weekly_region_volume(conn, this_week)
    except Exception as exc:  # noqa: BLE001 — region ledger optional
        log.debug("region coverage unavailable: %s", exc)
        all_regions = {}
    region_coverage = {m: all_regions[m] for m in need_volume if m in all_regions}

    return Prescription(
        week_start=this_week,
        mesocycle_id=meso_id,
        deload=deload,
        muscles=muscle_rx,
        lift_progressions=lift_progressions,
        exercise_menu=menu,
        exercise_science=science,
        region_coverage=region_coverage,
        development=development,
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
    if rx.exercise_menu or rx.exercise_science:
        lines.append(
            "\n**Exercise menu for muscles needing volume** — sports-science-grounded "
            "where curated (lengthened-position + head coverage); recency otherwise:"
        )
        for muscle, exs in rx.exercise_menu.items():
            picks = rx.exercise_science.get(muscle)
            if picks:
                dev = rx.development.get(muscle)
                if dev:
                    lines.append(
                        f"- **{muscle}** — target {dev['weekly_sets_low']}–{dev['weekly_sets_high']} "
                        f"sets/wk over {dev['freq_per_week']}×; {dev['rep_scheme']} "
                        f"[{dev['citation']}]"
                    )
                else:
                    lines.append(f"- **{muscle}** (evidence-based selection):")
                # Show EVERY head this muscle should cover — including the ones at
                # zero this week, since a neglected head is exactly what the plan
                # should lead. weekly_region_volume only returns trained heads, so
                # backfill the rest from the development brief's region list.
                cover = dict(rx.region_coverage.get(muscle) or {})
                heads = list(dev["regions"]) if dev and dev.get("regions") else list(cover)
                for h in cover:
                    if h not in heads:
                        heads.append(h)
                if heads:
                    vols = {h: cover.get(h, 0.0) for h in heads}
                    least = min(vols.values())
                    parts = [
                        f"{h} {v:g}" + (" ←lead" if v == least else "")
                        for h, v in sorted(vols.items(), key=lambda kv: kv[1])
                    ]
                    lines.append(
                        f"    - heads trained this wk: {' · '.join(parts)} "
                        "(lead the least-trained head)"
                    )
                for p in picks:
                    head = f"{p['region']}, " if p.get("region") else ""
                    lines.append(
                        f"    - {p['exercise']} — {head}{p['length_bias']}-biased, "
                        f"{p['rep_low']}–{p['rep_high']} reps · {p['rationale']} "
                        f"[{p['citation']}]"
                    )
            else:
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
