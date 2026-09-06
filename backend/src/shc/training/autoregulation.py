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
import re
import statistics
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, timedelta

import duckdb

from shc.training.mesocycle import (
    MesocycleState,
    VolumeTarget,
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
EMPHASIS_MUSCLES: frozenset[str] = frozenset({"biceps", "glutes", "abs"})

# A physique-bias factor at/above this promotes a muscle into the emphasis set
# even if it isn't in the biceps/glutes prior. The factor is in
# [1-_PHYSIQUE_BIAS_MAX, 1+_PHYSIQUE_BIAS_MAX] (metrics.py); >1 means the trended
# silhouette/critique signal wants more volume there.
EMPHASIS_PROMOTE_FACTOR = 1.05

# Confidence floor at/above which an ADD gets full authority; below it the add is
# scaled by confidence/_CONFIDENCE_FULL. CALIBRATION (fixed 2026-06-27, re-verified
# 2026-07 remediation): confidence is size_factor × signal_stability, and perf-score
# noise caps stability well under 1.0 in practice, so most muscles never reach a
# clean 1.0 stability even with hundreds of scored weeks. size_factor's anchors
# (self_learning._SIZE_FACTOR_ANCHORS) are set so size_factor(10 weeks) == 0.30 —
# a muscle needs BOTH >=10 scored weeks AND near-perfect stability to earn full add
# authority; below 10 weeks size_factor stays under 0.30 regardless of stability, so
# a thin sample can't reach full authority even if its handful of points happen to
# fall on a perfect line (self_learning._STABILITY_MIN_RESIDUAL_DOF is the second
# belt: below 5 points, stability itself is capped at a neutral 0.5). MEV is
# separately floored below so this only governs the ramp ABOVE minimum effective
# volume.
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
    # True when a stalled call (perf==3) was redirected to a load-not-volume
    # remedy because the athlete has been running sustained under-target RPE
    # (2026-07-23 remediation — see _rpe_headroom). Machine-readable so the
    # planner can act on it directly rather than parsing `reason` text.
    rpe_headroom: bool = False
    # 'grow' | 'maintain' (migration 0078). A maintenance muscle is not a growth
    # target this mesocycle — it holds at MV so the weekly set budget can
    # concentrate on the grow tier. Explicit intent, never fitted or inferred.
    tier: str = "grow"


@dataclass
class Prescription:
    week_start: date
    mesocycle_id: str
    deload: dict = field(default_factory=dict)  # {recommended, reason, triggers}
    muscles: list[MusclePrescription] = field(default_factory=list)
    lift_progressions: list[dict] = field(default_factory=list)
    exercise_menu: dict[str, list[dict]] = field(default_factory=dict)
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
    # Visible fail-visibly notes for any signal this prescription had to run blind
    # on (e.g. stale WHOOP blinding the conditioning-interference hold below).
    data_gaps: list[str] = field(default_factory=list)
    # Weekly set-budget feasibility (migration 0078). Before the MV tier existed
    # the sum of per-muscle targets ran ~1.5x what Rob can actually deliver, so
    # the demand list was unsatisfiable AND unranked and the planner triaged
    # silently toward habitual compounds. Surfacing it makes over-prescription a
    # visible number instead of a hidden judgement call.
    # {demand_muscle_sets, capacity_muscle_sets, working_sets_needed,
    #  capacity_working_sets, feasible, credit_ratio}
    capacity: dict = field(default_factory=dict)
    # Mid-week reflow (see :func:`remaining_split`): what the week still owes,
    # redistributed over the sessions that haven't happened yet, so a missed or
    # gated day's sets land on the remaining days instead of evaporating.
    remaining_week: dict = field(default_factory=dict)
    # Muscles whose total credited volume reaches target but whose DIRECT
    # (primary-role) work does not — i.e. the muscle looks covered only because
    # compounds are paying into it. Selection stops these heads being led by yet
    # another synergist, and the context block says so out loud.
    direct_short: list[str] = field(default_factory=list)


# Direct-work floor (2026-08-20). Secondary credit moved to the vault's 1:1
# (`volume.SECONDARY_CREDIT`), and Helms ships that ratio with a companion rule —
# "don't rely entirely on indirect volume for any muscle group". Without it,
# spillover alone can satisfy a muscle's target and stop it being trained.
#
# The floor is judged on DIRECT (primary-role) sets; the MRV ceiling stays judged
# on the credited total. Indirect volume genuinely costs recovery, so it belongs
# in the ceiling; it does not reliably supply stimulus — on a compound the
# synergist is by construction not the limiting factor, and a set only counts as
# volume at all within ~5 RIR (`helms-2018-lv2-volume-intensity-frequency.md`) —
# so it cannot fill the floor.
#
# CHOSEN, NOT VAULT-STATED: the vault requires direct work but names no minimum.
# A grow-tier muscle's floor is its own MEV, because MEV is the dose that muscle
# needs and Rob's whole goal is growing it; a maintenance-tier muscle's floor is
# MV, the 1-2 hard sets/wk `volume-landmarks-mev-mav-mrv.md` says holds size, and
# its remaining sets legitimately do come free as spillover. Taking the bottom of
# that 1-2 range deliberately: this floor ADDS volume demand, so the conservative
# direction here is the smaller number.
_DIRECT_FLOOR_MV_SETS = 1.0


def _direct_floor(rx: MusclePrescription, mev: float | None) -> float:
    """Minimum DIRECT (primary-role) weekly sets before a muscle counts as trained.

    Never exceeds the muscle's own target — a floor above the prescription would
    demand work the week never asked for, which is how an "protective" rule turns
    into an unsatisfiable one.
    """
    if rx.tier == "maintain":
        return min(_DIRECT_FLOOR_MV_SETS, float(rx.target_sets))
    floor = float(mev) if mev is not None else _DIRECT_FLOOR_MV_SETS
    return min(floor, float(rx.target_sets))


# Number of muscles that must independently signal fatigue to trigger a deload.
DELOAD_MUSCLE_THRESHOLD = 3


def deload_check(
    perfs: dict[str, int | None],
    report: list[MuscleVolume],
    threshold: int | None = None,
    effort: dict | None = None,
) -> dict:
    """Decide whether a fatigue-driven deload is warranted from real signals.

    A deload fires when training is broadly unproductive or maxed out, NOT on a
    calendar (panel review M4): ≥``threshold`` muscles regressing (perf ≤ 2), or
    that many at/over MRV. ``threshold`` defaults to the RP population value
    (:data:`DELOAD_MUSCLE_THRESHOLD`); pass a personal value fitted by
    ``calibrate_deload_trigger`` to override. Returns the recommendation + the
    specific triggers so the prescription can explain itself.

    ``effort`` (from :func:`_effort_overreach`) adds the one fatigue input this
    check previously had no way to see. Both existing triggers are OUTPUT
    signals — they only fire once performance has already degraded or volume has
    already maxed out. Effort is the input side, and it moves first: grinding
    harder for the same result is the classic overreaching signature, visible
    weeks before e1RM turns over.

    It is deliberately NOT a standalone trigger. Sustained hard training with
    output still RISING is productive overreaching, which a deload would
    interrupt for no reason — so it fires only with at least one muscle actually
    regressing to corroborate it. "Working harder AND getting less" is the
    signal; "working harder" alone is just training.
    """
    thr = threshold if threshold is not None else DELOAD_MUSCLE_THRESHOLD
    regressing = sorted(m for m, p in perfs.items() if p is not None and p <= 2)
    at_mrv = sorted(r.muscle for r in report if r.mrv is not None and r.actual_sets >= r.mrv)
    triggers: list[str] = []
    if len(regressing) >= thr:
        triggers.append(f"{len(regressing)} muscles regressing ({', '.join(regressing[:5])})")
    if len(at_mrv) >= thr:
        triggers.append(f"{len(at_mrv)} muscles at/over MRV ({', '.join(at_mrv[:5])})")
    if effort and effort.get("overreaching") and regressing:
        triggers.append(
            f"effort overreach — weekly mean RPE {effort['recent_rpe']} vs "
            f"{effort['baseline_rpe']} baseline, with {len(regressing)} muscle(s) regressing"
        )
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


def _muscle_performance(
    conn: duckdb.DuckDBPyConnection, muscle: str, recency_weeks: int = 12
) -> int | None:
    """Set-weighted central tendency of Israetel perf scores for a muscle.

    Averages the perf score across exercises whose ``primary_muscle`` is
    ``muscle``, weighted by each exercise's recent work-set count, then rounds.
    Weighting by volume keeps a single fluke PR on a minor accessory from
    speaking for the whole muscle — the upward-bias failure of the old ``max()``
    aggregation (panel review C1). None when no exercise has enough history.

    Only exercises with at least one logged week within ``recency_weeks`` of
    today are included; exercises last trained months/years ago are excluded so
    their stale perf scores don't drag down the current muscle signal.
    """
    exercises = [
        r[0]
        for r in conn.execute(
            """
            SELECT exercise_name FROM exercise_muscle_map
            WHERE primary_muscle = ?
              AND exercise_name IN (
                  SELECT exercise FROM exercise_weekly_e1rm
                  WHERE week_start >= (CURRENT_DATE - INTERVAL (? || ' weeks'))
              )
            """,
            [muscle, str(recency_weeks)],
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
    state: dict | None = None,
) -> tuple[float | None, bool]:
    """Conditioning ACWR — proxy for how much pickleball/cardio load is live.

    Read lazily from the daily state (pass an already-computed one via ``state``
    to avoid recomputing it); > 1.3 means the lower body is already absorbing
    meaningful court/cardio stimulus.

    When ``use_rpe_only=True`` (propranolol day), returns ``(None, False)`` to
    bypass the WHOOP-derived conditioning ACWR — HR is suppressed by the
    beta-blocker, making strain systematically understate real load; RPE is the
    only unbiased signal on dosed days. This is a deliberate bypass, not a data
    blindness, so it does not set the blind flag.

    Returns ``(acwr, blind)``. ``blind=True`` when WHOOP hasn't synced in >2
    days — the exact same staleness ``_gates`` uses to null ``conditioning_acwr``
    before scoring the leg-protection gate (see ``metrics.py::_gates``). Without
    this, a sync outage makes the chronic conditioning window fill with zeros,
    the ratio silently reads ~0, and this controller would grow leg volume on a
    fabricated "no court load" signal in the same moment the gate is printing a
    BLIND warning about the same data.
    """
    if use_rpe_only:
        return None, False
    try:
        from shc.metrics import compute_daily_state

        s = state if state is not None else compute_daily_state(conn)
        if s.get("freshness", {}).get("whoop_stale"):
            return None, True
        return s["training_load"].get("conditioning_acwr"), False
    except Exception as exc:  # noqa: BLE001 — state optional; missing → no debit
        log.debug("conditioning pressure unavailable: %s", exc)
        return None, False


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
    rpe_headroom: bool = False,
    tier: str = "grow",
    mv: int = 2,
    # Default matches the population metrics.COND_ACWR_HOLD_LEGS; real callers
    # (weekly_prescription) pass the possibly-personalized value from
    # metrics.personalized_cond_thresholds() so this and the hard FORBID gate in
    # metrics._gates can never diverge (`_decide` stays a pure function of
    # primitives — no DB access — so the personalization happens one level up).
    leg_hold_threshold: float = 1.5,
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

    ``rpe_headroom`` (2026-07-23 remediation, see :func:`_rpe_headroom`) is a
    session-level signal — the athlete has been running sustained under-target
    RPE — that changes the STALLED (``perf == 3``) remedy: a flat e1RM with
    real effort headroom means the ceiling, not the volume, is the lever, so
    the tree holds sets and asks for more load instead of adding a set. It
    does not touch any other branch — progressing/regressing/under-recovered
    calls are unaffected.

    ``tier`` / ``mv`` (migration 0078) carry the fourth volume landmark. A
    ``'maintain'`` muscle is not a growth target this mesocycle: it is never
    ADDED to, and its floor is MV rather than MEV. It is deliberately NOT cut
    down to MV — compound spillover legitimately leaves several maintenance
    muscles well above it (at the 1:1 rate a row credits biceps 1.0 + traps 1.0),
    and stripping productive volume that costs no dedicated budget would be the
    opposite of the point. The tier only stops the engine *demanding* more.

    Two guards, both deliberate. (1) An ``emphasis`` muscle can never maintain,
    whatever the tier says — invariant 7 forbids freezing a lagging bring-up
    below MEV, and demoting it by tier is the same under-train through a
    different door. (2) Safety branches (regressing, under-recovered, MRV,
    conditioning interference) are evaluated BEFORE the tier, so maintenance
    can never override a back-off. Tier removes volume *demand*, never
    recovery protection.
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
        # The tier is an explicit human decision (invariant 10) and a deload must
        # not silently re-inflate it. A maintenance muscle's productive floor is
        # MV, not a fraction of MEV — deriving the deload floor from MEV ignored
        # `tier` entirely and RAISED maintenance muscles during the one week the
        # program is supposed to be shedding volume: lats (MEV 10, MV 2) sitting
        # at 2.0 sets were handed a target of 4, and triceps (MEV 12) a target of
        # 5. Mirrors the `floor`/`maintaining` pair computed below for the normal
        # tree; an emphasis muscle can never maintain (invariant 7), so it keeps
        # the MEV-derived floor.
        if tier == "maintain" and not emphasis:
            deload_floor = min(mv, mev)
        else:
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
    # graded leg-volume hold kicks in above leg_hold_threshold, below the gate's
    # hard forbid (metrics.personalized_cond_thresholds keeps hold < forbid).
    leg_interference = (
        muscle in LOWER_BODY
        and conditioning_acwr is not None
        and conditioning_acwr > leg_hold_threshold
    )

    # An emphasis muscle is never a maintenance muscle (invariant 7 in tier
    # form). `floor` is the productive minimum this muscle is entitled to:
    # MEV when growing, MV when explicitly held at maintenance.
    maintaining = tier == "maintain" and not emphasized
    floor = min(mv, mev) if maintaining else mev
    floor_label = "MV" if maintaining else "MEV"

    rpe_headroom_applied = False
    if perf is not None and perf <= 2:
        # Regressing — target the productive floor. If already below it, ramp up
        # (more productive minimum volume is the remedy); if above, cut toward it.
        desired = max(floor, cur - 2)
        if cur < floor:
            reason = (
                f"regressing (perf {perf}/5) but below {floor_label} "
                f"→ build to minimum productive volume"
            )
        else:
            reason = f"regressing (perf {perf}/5) → cut toward {floor_label}"
    elif under_recovered:
        # Below floor: hold at cur — don't push toward it while under-recovered.
        # At/above floor: back off one set, floored there.
        desired = max(min(cur, floor), cur - 1)
        reason = f"under-recovered (soreness {soreness:.1f}/3) → back off a set"
    elif cur >= mrv:
        desired = mrv
        reason = "at MRV — volume ceiling; hold (deload candidate next block)"
    elif leg_interference:
        # Pickleball/cardio IS the leg stimulus this week — hold in place.
        desired = cur
        reason = f"court/cardio load high (cond. ACWR {conditioning_acwr:.2f}) → hold leg volume"
    elif maintaining:
        # Not a growth target this mesocycle. Top up only if compound spillover
        # has left it under MV; otherwise hold exactly where it sits. Never add
        # above MV, never cut productive spillover back down to it.
        # Placed AFTER every safety branch so a back-off still wins.
        if cur < floor:
            desired = floor
            reason = f"maintenance tier, below MV → top up to {floor} set/wk to hold size"
        else:
            desired = cur
            reason = (
                f"maintenance tier — holding at {cur} set/wk "
                f"(MV {floor}); weekly budget goes to the grow-tier muscles"
            )
    elif perf is not None and perf >= 4:
        # Emphasis muscles ramp +2; a strong physique nudge (emphasis_factor well
        # above 1) can lift a non-emphasis progressing muscle to +2 too, so the
        # ramp tracks the live development signal rather than a static membership.
        desired = cur + ramp_step
        tag = " + emphasis" if emphasized else ""
        reason = f"progressing (perf {perf}/5){tag} → add toward MRV"
    elif perf == 3 and rpe_headroom and not emphasized:
        # Stalled AND the athlete has been running sustained under-target RPE
        # (rpe_drift_signed_mean <= -0.75, see _rpe_headroom): more sets is
        # the WRONG remedy when there's real effort left in the tank — a flat
        # e1RM with headroom means load, not volume, is the lever. Hold sets.
        # Exception: emphasis muscles (bring-ups Rob has explicitly flagged)
        # keep their +2 ramp regardless — the whole point of emphasis is to
        # push the lagging muscle harder even when other signals say hold.
        # rpe_headroom is session-level (cross-muscle average), so letting it
        # suppress an emphasis muscle's dedicated ramp is the wrong trade.
        desired = cur
        reason = "stalled e1RM with RPE headroom → raise load, hold sets"
        rpe_headroom_applied = True
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
    if raw_delta > 0:
        # Python's banker's rounding rounds 0.5 → 0 (nearest even), so
        # round(1 * 0.5) = 0 would silently freeze a progressing muscle.
        # Guarantee at least +1 when the branch intended an add.
        desired = cur + max(1, round(raw_delta * rpe_factor))
    else:
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
    # A maintenance-tier muscle's productive floor is MV, not MEV. Without this
    # the tier would be undone one line later: the MEV floor is unconditional by
    # design (it exists so a starved muscle re-seeds to minimum effective volume
    # regardless of confidence), so it would drag every parked muscle straight
    # back up and the whole budget reallocation would silently no-op.
    hold_below_mev = under_recovered or leg_interference
    effective_floor = floor
    mev_floor = min(tree_target, effective_floor) if hold_below_mev else effective_floor
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
    if not maintaining and cur < mev and target == mev and not hold_below_mev:
        reason = "below MEV → initialize at minimum productive volume"
        hedge_note = ""

    return MusclePrescription(
        muscle=muscle,
        current_sets=round(current, 1),
        target_sets=target,
        delta=delta,
        action=action,
        reason=(
            reason
            + _src_tag()
            + hedge_note
            + f" [final weekly target: {round(current, 1):g}→{target} sets ({delta:+d})]"
        ),
        emphasis=emphasis,
        landmark_source=landmark_source,
        confidence=round(confidence, 2),
        scored_weeks=scored_weeks,
        rpe_headroom=rpe_headroom_applied,
        # The EFFECTIVE tier, not the requested one: an emphasis muscle keeps
        # growing even if the table says maintain, and the output must say so
        # rather than mislabel a muscle that is in fact being ramped.
        tier="maintain" if maintaining else "grow",
    )


def _exercise_menu(
    conn: duckdb.DuckDBPyConnection, muscles: list[str], per_muscle: int = 4
) -> dict[str, list[dict]]:
    """Fallback candidates per muscle (no curated science) — STALE-FIRST rotation.

    Orders least-recently-trained first so a repeat is only shown once it is the
    freshest option, with never-logged movements LAST — a zero-log count often
    just means the equipment isn't in Rob's gym (catalog presence ≠ availability),
    so those shouldn't crowd out real rotatable candidates. The final slot is
    reserved for the most-recently-trained option so the menu isn't four abandoned
    lifts hiding what Rob actually runs. Each entry is ``{exercise, last_done}``
    (ISO date or None). Excludes 'no' preferences.
    """
    avoid = {
        r[0]
        for r in conn.execute(
            "SELECT exercise FROM exercise_preferences WHERE status = 'no'"
        ).fetchall()
    }
    menu: dict[str, list[dict]] = {}
    for muscle in muscles:
        rows = conn.execute(
            """
            SELECT m.exercise_name, MAX(ws.started_at)::DATE AS last_done
            FROM exercise_muscle_map m
            LEFT JOIN workout_sets_dedup ws
                ON ws.exercise = m.exercise_name
               AND COALESCE(ws.is_warmup, FALSE) = FALSE
            WHERE m.primary_muscle = ?
            GROUP BY m.exercise_name
            ORDER BY (last_done IS NULL), last_done ASC
            """,
            [muscle],
        ).fetchall()
        cand = [
            {"exercise": r[0], "last_done": r[1].isoformat() if r[1] else None}
            for r in rows
            if r[0] not in avoid
        ]
        if not cand:
            continue
        picks = cand[:per_muscle]
        # Reserve the last slot for the most-recent staple so the stalest-first
        # list still shows something Rob is currently running.
        logged = [c for c in cand if c["last_done"] is not None]
        if logged and per_muscle >= 2:
            recent = max(logged, key=lambda c: c["last_done"])
            if recent not in picks:
                picks = cand[: per_muscle - 1] + [recent]
        menu[muscle] = picks
    return menu


_LENGTH_RANK = {"lengthened": 0, "mid": 1, "shortened": 2}
_SFR_RANK = {"high": 0, "moderate": 1, "low": 2}

# Consecutive scored weeks a movement may lead its head before it becomes
# swap-eligible even while progressing. 6 = the top of the 4–6 week rotation
# window `exercise-selection-hypertrophy.md` prescribes for trained lifters —
# the conservative end, so a productive lift gets the longest run the evidence
# supports before an in-band alternative is tried. See _select_grounded key 4b.
_ROTATE_AFTER_WEEKS = 6

# A progression trend is only a live selection signal if the exercise was trained
# within this window; older than this, score_exercise is fitting stale weeks and
# the "progressing/plateaued" read no longer reflects what Rob is doing now.
_STALE_TREND_WEEKS = 6

# The window rotation tenure is counted over, and how recently a lift must have
# been trained for that count to mean it currently holds its slot. 12 weeks is
# wide enough that a lift trained most weeks reaches _ROTATE_AFTER_WEEKS even
# with skipped weeks, and 2 weeks is tight enough that a benched lift stops
# claiming tenure after roughly one rotation cooldown. See _rotation_tenure.
_TENURE_WINDOW_WEEKS = 12
_TENURE_LIVE_WEEKS = 2

# A movement is programmable evidence only if Rob has actually logged it recently
# enough to know the equipment exists and the name is loggable. Beyond this it is
# a TRIAL: still worth surfacing, never worth LEADING a head with. 9 of 17 muscles
# were leading with a movement never logged or last logged in 2018-2019.
_VERIFIED_WITHIN_DAYS = 365


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
    tenure_weeks: Mapping[str, int] | None = None,
    rotate_after_weeks: int = _ROTATE_AFTER_WEEKS,
    verified: Mapping[str, bool] | None = None,
    secondary_deficit: Mapping[str, float] | None = None,
    is_direct: Mapping[str, bool] | None = None,
) -> tuple[list[tuple], dict[str, str]]:
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
       equal-quality alternative for that head surfaces.
       ``progress_rank`` maps ``exercise_name → {0,1,2}``; absent → all neutral.

       Plateau is ONE of two rotation triggers, not the only one. This docstring
       previously claimed "(Balsalobre; Rauch): fixed selection matches or beats
       variation for hypertrophy" and rotated on plateau alone. That reading is
       wrong on both citations. The vault records Rauch 2017 as trained lifters
       choosing exercises per rep range **beating** fixed selection for
       upper-body strength and lean mass
       (``helms-2018-lv4-exercise-selection.md``), and Balsalobre as n=11 over 8
       weeks finding **no significant difference** in quad thickness — a
       non-significant trend in one muscle, not a basis for never rotating.
       ``exercise-selection-hypertrophy.md`` prescribes the opposite for a
       trained lifter: rotate every 4–6 weeks, because hypertrophy is regional
       (Fonseca: varied routine grew vastus medialis / rectus femoris where the
       Smith squat alone did not; Wakahara MRI: different exercises grew
       different triceps regions) and because the repeated bout effect
       extinguishes the EIMD stimulus within ~5 sessions of the same movement.
       The "constrain variety" guidance in that note is scoped to beginners in
       their first 8–12 weeks.

    4b. **Tenure** — a lift that has held its head for ``rotate_after_weeks``
       weeks inside the rotation window becomes swap-eligible *even while
       progressing*,
       via the same in-band machinery as a plateau. ``tenure_weeks`` maps
       ``exercise_name → completed weeks behind its trend``; absent → no tenure
       rotation. Compounds are protected structurally rather than by a
       compound/isolation flag (no such signal exists in the schema — every
       exercise carries exactly one primary muscle, Squat included): a heavy
       compound is typically the only in-band option for its head, so
       ``_in_band`` finds no alternative and the lead is held, while isolation
       movements sit in pools with genuine peers and do rotate. That approximates
       Helms' "compounds stable, isolation rotates" without inventing a
       classifier — it is an approximation, not a faithful implementation of it.
    4c. **Cross-muscle payoff** — among options still tied, the one whose
       SECONDARY credit serves another muscle's shortfall wins.
       ``secondary_deficit`` maps ``exercise_name -> sum(that muscle's deficit ×
       credit)``; absent → no effect. Deliberately placed BELOW every key that
       speaks for the muscle being programmed: a lift must never be chosen for
       what it does to some other muscle at this one's expense. It only decides
       ties, and ties are pervasive — every curated muscle has candidates equal
       on region/length/SFR, which is exactly where "and it also feeds the
       lagging muscle" is free information rather than a compromise.

    5. **Name** — deterministic final tiebreaker (storage-order independent).

    Because the ordering carries no time term, selection is STABLE week to week
    (the same best set recurs) until a lift plateaus. But progress is only the 4th
    key, so a plateaued lift that WINS on head/length/SFR (keys 1–3) would still
    lead its head forever — the swap signal is real but never actuates. So after
    the coverage pass takes one movement per head, a plateaued lead is displaced by
    the best non-plateaued same-head alternative **within science bands**: the swap
    may relax length lengthened→mid but never step INTO shortened (length bias is
    RCT-grade — a hard floor), and may drop at most one SFR tier (high→moderate ok,
    high→low never). No in-band alternative → the plateaued lead is held. The
    displaced lead reappears when the remaining slots are filled with next-best, so
    it stays visible (tagged) rather than vanishing.

    **Availability gates what may LEAD, not what may appear.** ``verified`` maps
    ``exercise_name -> logged recently enough to prove the equipment exists``;
    absent → everything counts as verified. Where a head has at least one
    verified option, unverified ones cannot take its coverage slot or win a swap
    into it. Without this the quality keys happily led nine of seventeen muscles
    with a movement never logged or last touched in 2018 — chest with a 2019
    barbell bench, lats with a Chin Up that has no logged set at all — which
    reads as noise and gets the whole menu discarded rather than followed. A head
    with NO verified option still surfaces its best candidate, tagged as a trial
    to verify, because that is real information (the pool may be dead) rather
    than an empty slot.

    Returns ``(picks, notes)`` where ``notes`` maps an exercise name to a one-line
    rank reason (``swapped in`` / ``swap candidate: plateaued`` / ``held`` /
    ``TRIAL``) for the menu to surface. Absence of a note means the pick led on
    merit.
    """
    rv = region_volume or {}
    pr = progress_rank or {}
    tw = tenure_weeks or {}
    vf = verified or {}
    sd = secondary_deficit or {}
    dr = is_direct

    def _region(c) -> str:
        return c[2] or c[1]

    def _verified(c) -> bool:
        return vf.get(c[0], True) if vf else True

    def _direct(c) -> bool:
        # None → the caller is not gating on role for this muscle.
        return True if dr is None else dr.get(c[0], False)

    def _stale(c) -> bool:
        """Swap-eligible: plateaued, or leading its head past the rotation window."""
        return _progress(c) == 2 or tw.get(c[0], 0) >= rotate_after_weeks

    def _deficit(c) -> float:
        # Lower trained volume on this head → sorts earlier (trained first).
        return rv.get(_region(c), 0.0)

    def _progress(c) -> int:
        # 0 progressing (keep) < 1 untried (neutral) < 2 plateaued (swap-eligible).
        return pr.get(c[0], 1)

    def _in_band(lead: tuple, alt: tuple) -> bool:
        # A swap may relax length lengthened→mid but never into shortened, and
        # may drop at most one SFR tier — the "acceptable science" envelope.
        len_ok = _LENGTH_RANK.get(alt[3], 1) <= max(_LENGTH_RANK.get(lead[3], 1), 1)
        sfr_ok = _SFR_RANK.get(alt[6], 1) <= _SFR_RANK.get(lead[6], 1) + 1
        return len_ok and sfr_ok

    ordered = sorted(
        cands,
        key=lambda c: (
            _deficit(c),
            _LENGTH_RANK.get(c[3], 1),
            _SFR_RANK.get(c[6], 1),
            _progress(c),
            -sd.get(c[0], 0.0),  # more of another muscle's shortfall served → earlier
            c[0],  # exercise name — deterministic final tiebreaker (storage-order independent)
        ),
    )
    # Heads that have a verified option: within these, an unverified candidate may
    # not take the coverage slot or be swapped in. A head absent from this set has
    # nothing verified to offer, so its best candidate leads as a tagged trial.
    verified_regions = {_region(c) for c in ordered if _verified(c)}
    # Heads with a genuine direct (primary-role) option, used only when the
    # caller says this muscle is short on direct work. Synergist credit is real
    # but it is not a substitute for training the muscle: measured across eight
    # weeks, nine of seventeen muscles had a week where total volume cleared MEV
    # while direct work alone did not — glutes three times, hamstrings and traps
    # twice. Leading such a head with another synergist compounds exactly that.
    direct_regions = {_region(c) for c in ordered if _direct(c)}

    notes: dict[str, str] = {}
    picks: list[tuple] = []
    seen_regions: set[str] = set()
    for c in ordered:  # coverage pass: one per head, most-neglected head first
        if len(picks) >= per_muscle:
            break
        region = _region(c)
        if region in seen_regions:
            continue
        if region in verified_regions and not _verified(c):
            continue  # a usable option exists for this head — let it lead instead
        if region in direct_regions and not _direct(c):
            continue  # this muscle needs training, not more synergist credit
        pick = c
        if _stale(c):  # plateaued or past its rotation window — try an in-band swap
            why = "plateaued" if _progress(c) == 2 else f"held this head {tw.get(c[0], 0)}wk"
            for alt in ordered:
                if _region(alt) != region or alt is c or _stale(alt):
                    continue
                if region in verified_regions and not _verified(alt):
                    continue  # never rotate a working lift out for an unproven one
                if _in_band(c, alt):
                    pick = alt
                    notes[alt[0]] = f"swapped in: replaces {c[0]} ({why})"
                    notes[c[0]] = f"swap candidate: {why}"
                    break
            else:
                notes[c[0]] = f"held: {why}, no in-band alternative"
        if not _verified(pick):
            notes[pick[0]] = "TRIAL — no verified option for this head; verify equipment exists"
        picks.append(pick)
        seen_regions.add(region)
    for c in ordered:  # fill remaining slots with next-best (displaced lead resurfaces here)
        if len(picks) >= per_muscle:
            break
        if c not in picks:
            picks.append(c)
    return picks[:per_muscle], notes


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


def _rotation_tenure(conn: duckdb.DuckDBPyConnection) -> dict[str, int]:
    """``logged name -> weeks trained inside the rotation window``, 0 if benched.

    This is the number :func:`_select_grounded` needs to answer "has this lift
    led its head long enough to rotate", and it is measured two ways at once:

    * **Exposure, not a streak.** A consecutive-week counter resets on every
      skipped week, and Rob trains a lift twice one week then skips the next —
      so a streak fires on only 5 of his 16 monopoly lifts and misses the worst
      of them (triceps streak 1, traps 2, adductors 0, all while one exercise
      owns 63-100% of that muscle's sets). Counting the weeks a lift appears in
      the trailing window fires on 12 of 16 instead.
    * **Gated on recency.** Exposure alone flags a lift that is already out of
      rotation — Seated Cable Row shows 6 window-weeks but has not been trained
      in 4, so it needs no rotation, it has had one. Only a lift trained within
      :data:`_TENURE_LIVE_WEEKS` counts as currently holding its slot.

    The pairing also removes the ping-pong a streak metric creates. Benching a
    lift zeroes a streak immediately, so it is re-eligible to lead the very next
    week; exposure decays a week at a time and the recency gate releases it after
    ~3 weeks off, which is the cooldown the rotation window wants anyway.
    """
    try:
        rows = conn.execute(
            f"""
            SELECT exercise,
                   COUNT(DISTINCT date_trunc('week', started_at)::DATE) AS window_weeks,
                   MAX(date_trunc('week', started_at)::DATE) AS last_week
            FROM workout_sets_dedup
            WHERE COALESCE(is_warmup, FALSE) = FALSE
              AND date_trunc('week', started_at)::DATE
                  > (date_trunc('week', CURRENT_DATE)::DATE
                     - INTERVAL '{_TENURE_WINDOW_WEEKS} weeks')
            GROUP BY exercise
            """
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — rotation signal optional, never blocks selection
        log.debug("rotation tenure unavailable: %s", exc)
        return {}
    this_week = _iso_week_start(date.today())
    live_after = this_week - timedelta(weeks=_TENURE_LIVE_WEEKS)
    return {r[0]: int(r[1] or 0) for r in rows if r[2] is not None and r[2] >= live_after}


def _progress_info(
    conn: duckdb.DuckDBPyConnection,
    names: set[str],
    aliases: Mapping[str, str] | None = None,
) -> dict[str, dict]:
    """Per curated exercise: swap-priority rank + the evidence behind it.

    Returns ``{name: {rank, trend, weeks, tenure, last_done, logged_name}}``:

    * ``rank`` — ``0`` progressing (keep) < ``1`` untried/young (neutral) < ``2``
      plateaued (stalled/regressing, swap-eligible). Drives :func:`_select_grounded`.
    * ``trend`` — ``progressing`` | ``stalled`` | ``regressing`` | ``young``
      (logged but <3 completed weeks) | ``stale`` (last trained too long ago for
      its trend to be a live signal) | ``untrained`` (no logs at all under the
      name or its alias — the "verify the equipment exists" case, distinct from
      ``young``).
    * ``weeks`` — completed weeks of e1RM behind the trend (0 when unscored).
      This is a measure of EVIDENCE DEPTH and nothing else. It was previously
      handed to selection as the rotation trigger, which it never was: it counts
      weeks with e1RM data anywhere in history, capped at 14, so Deadlift last
      done in 2019 reported 6 and Overhead Press last done Feb 2025 reported 14.
      60% of candidates read as over-tenured against 4% under a real measure,
      and since a swap-in is rejected when it is itself over-tenured, every
      alternative WITH history was disqualified — leaving only never-logged and
      years-stale movements to rotate into. Use ``tenure`` for rotation.
    * ``tenure`` — weeks this lift has actually held its slot recently, from
      :func:`_rotation_tenure`. This is the rotation trigger.
    * ``last_done`` — ISO date of the most recent working set, alias-resolved.

    Curated names are resolved to Rob's logged variant via ``aliases`` before
    scoring, so a staple logged under a different string still shows its trend.

    A trend is only a LIVE signal if the exercise was trained recently:
    :func:`score_exercise` fits the most recent *available* weeks regardless of
    age, so a lift last done years ago (or whose alias now points at a name Rob
    stopped logging) would otherwise read ``progressing`` off ancient data and be
    pinned as a "kept" lead forever. Beyond :data:`_STALE_TREND_WEEKS` the trend is
    demoted to neutral (``stale``) so a fresh alternative can surface.
    """
    al = aliases or {}
    last_done: dict[str, str] = {}
    try:
        for ex, dt in conn.execute(
            "SELECT exercise, MAX(started_at)::DATE FROM workout_sets_dedup "
            "WHERE COALESCE(is_warmup, FALSE) = FALSE GROUP BY exercise"
        ).fetchall():
            if dt is not None:
                last_done[ex] = dt.isoformat()
    except Exception as exc:  # noqa: BLE001 — last-done lookup optional
        log.debug("last-done lookup unavailable: %s", exc)

    stale_before = date.today() - timedelta(weeks=_STALE_TREND_WEEKS)
    tenure_by_logged = _rotation_tenure(conn)
    info: dict[str, dict] = {}
    for name in names:
        # An alias is only useful while the curated name has NO history of its
        # own. Once Rob logs under the curated string directly, following the
        # redirect reads the OLDER name's history and reports a lift done days
        # ago as "stale: not trained in >6wk" — which then hands its slot to a
        # worse option. Seen live on Lateral Raise (Dumbbell) (own history
        # 2026-08-05, alias target last logged 2026-02-17) and on Bulgarian Split
        # Squat (Dumbbell). Prefer whichever name Rob actually trained most
        # recently, so a stale or inverted alias row degrades to a no-op instead
        # of corrupting the selection signal.
        logged = al.get(name, name)
        if logged != name:
            own, aliased = last_done.get(name), last_done.get(logged)
            if own and (not aliased or own > aliased):
                logged = name
        ld = last_done.get(logged)
        try:
            ps = score_exercise(conn, logged)
        except Exception as exc:  # noqa: BLE001 — scoring optional, never blocks selection
            log.debug("score_exercise failed for %s: %s", name, exc)
            ps = None
        latest_week = ps.history[-1].week_start if ps and ps.history else None
        if ps is None:
            rank, weeks = 1, 0
            trend = "young" if ld is not None else "untrained"
        elif latest_week is not None and latest_week < stale_before:
            # Trend fitted on old data — not a live signal. Neutral, not "kept".
            rank, weeks, trend = 1, len(ps.history), "stale"
        elif ps.trend == "progressing":
            rank, weeks, trend = 0, len(ps.history), "progressing"
        else:  # stalled | regressing
            rank, weeks, trend = 2, len(ps.history), ps.trend
        info[name] = {
            "rank": rank,
            "trend": trend,
            "weeks": weeks,
            "tenure": tenure_by_logged.get(logged, 0),
            "last_done": ld,
            "logged_name": logged,
        }
    return info


def _default_status(trend: str, tenure: int = 0) -> str:
    """One-line rank reason when selection left no explicit swap/held note.

    Tenure is reported even on picks the rotation machinery never inspected. Only
    the coverage-pass LEAD for a head goes through the swap logic, so a staple
    that fills a later slot — Lateral Raise (Dumbbell) at twelve weeks in its
    slot, on a muscle with a single head — otherwise rendered as
    "kept: progressing", which reads as an endorsement of the exact repetition
    the rotation window exists to break.
    """
    if tenure >= _ROTATE_AFTER_WEEKS and trend in ("progressing", "young"):
        return f"past the rotation window (held {tenure}wk) — prefer an alternative above"
    return {
        "progressing": "kept: progressing",
        "stalled": "stalled: swap-eligible",
        "regressing": "regressing: swap-eligible",
        "young": "young: <3wk data — building signal",
        "stale": f"stale: not trained in >{_STALE_TREND_WEEKS}wk — trend not live",
        "untrained": "untrained: no logs — verify equipment exists",
    }.get(trend, "kept")


# An implement whose real load step is at/above this share of its top loaded
# notch is COARSE: a load step there is a big jump (a 15 lb pin on a 200 lb
# stack ≈ 7.5%), so double progression should ride the rep window and the
# plateau detector should expect load to move in lurches, not per-week creep.
_COARSE_INCREMENT_PCT = 7.0


def _progressibility(grids, logged_name: str) -> dict | None:
    """How finely this lift's load can actually move — from its logged grid.

    Returns ``{increment_lb, pct_of_top, coarse}`` or None when the grid is too
    thin to speak (same evidence bar the snapper uses — an anecdote must not
    claim a pitch). ``pct_of_top`` is the dominant step as a share of the top
    logged notch, a working-weight proxy that needs no extra query. A ``coarse``
    lift stalls ARTIFICIALLY on load: the honest read of a flat e1RM there is
    "the next notch is a 7%+ jump", not "the stimulus stopped working" — worth
    surfacing at selection time so a small muscle isn't judged on a big-pitch
    machine's terms.
    """
    from shc.training.loadable import _SPARSE_GRID_MIN, _dominant_step

    grid = grids.for_exercise(logged_name)
    if len(grid) < _SPARSE_GRID_MIN or not grids.proves_gaps(logged_name):
        return None
    step = _dominant_step(grid)
    if not step or grid[-1] <= 0:
        return None
    pct = step / grid[-1] * 100.0
    return {
        "increment_lb": step,
        "pct_of_top": round(pct, 1),
        "coarse": pct >= _COARSE_INCREMENT_PCT,
    }


_EQUIP_SYNONYMS = {"tricep": "triceps", "bicep": "biceps", "hamstring": "hamstrings"}


def _movement_key(name: str) -> str:
    """Identity of the MOVEMENT, independent of how the name is punctuated.

    ``Bench Press (Dumbbell)`` and ``Dumbbell Bench Press`` are one exercise
    logged under two strings. Equipment words are deliberately KEPT (a machine
    press is not a dumbbell press); only punctuation, plural, word order, and
    the tricep/bicep spelling drift are normalized away.
    """
    n = name.lower()
    for a, b in _EQUIP_SYNONYMS.items():
        n = re.sub(rf"\b{a}\b", b, n)
    n = re.sub(r"[^a-z0-9 ]", " ", n)
    toks = [t[:-1] if t.endswith("s") and len(t) > 3 else t for t in n.split()]
    return " ".join(sorted(toks))


def loggable_names(conn: duckdb.DuckDBPyConnection) -> set[str]:
    """Exercise names Rob can actually put in Hevy — the planner's legal vocabulary.

    Two sources, both exact:
      * ``hevy_exercise_templates`` — the catalog the planner is told to quote
        VERBATIM.
      * exercises logged with ``workouts.source = 'hevy'`` — a few genuine
        customs (e.g. "Cable Core Pallof Press", "Bulgarian Split Squat
        (Dumbbell)") exist that the template endpoint does not return.

    Fitbod-imported strings are deliberately EXCLUDED. The log carries a decade
    of them ("Hammer Curls", "Leg Extension", "Cable Row") and they must keep
    crediting historical volume, but Rob cannot select one in Hevy today — so
    offering it as a rotation is the same dead end as a name that never existed.
    Provenance is the precise test here; recency is only a proxy for it.

    A curated movement outside this set cannot be programmed no matter how good
    the science is, so surfacing it only burns a rotation slot.
    """
    names: set[str] = set()
    sources = (
        ("hevy_exercise_templates", "SELECT title FROM hevy_exercise_templates"),
        (
            "workout_sets",
            "SELECT DISTINCT ws.exercise FROM workout_sets ws "
            "JOIN workouts w ON w.id = ws.workout_id "
            "WHERE ws.exercise IS NOT NULL AND w.source = 'hevy'",
        ),
    )
    for label, sql in sources:
        try:
            names.update(r[0] for r in conn.execute(sql).fetchall() if r[0])
        except Exception as exc:  # noqa: BLE001 — either source alone is usable
            log.warning("loggable_names: %s unavailable: %s", label, exc)
    return names


def unloggable_curated(conn: duckdb.DuckDBPyConnection) -> list[str]:
    """Curated movements the planner is forbidden to name — the selection dead-list.

    Every entry here is science the engine can rank but Rob can never log, so it
    silently consumes a menu slot and, when it wins a rotation, kills the swap.
    Exposed for the alias-gap diagnostic and guarded by a coverage test.
    """
    loggable = loggable_names(conn)
    if not loggable:
        return []
    try:
        rows = conn.execute("SELECT DISTINCT exercise_name FROM exercise_science").fetchall()
    except Exception as exc:  # noqa: BLE001 — evidence layer optional
        log.debug("exercise_science unavailable for unloggable audit: %s", exc)
        return []
    return sorted(r[0] for r in rows if r[0] not in loggable)


def _logged_recency(conn: duckdb.DuckDBPyConnection, names: list[str]) -> dict[str, tuple]:
    """``name -> (last_hevy_date, set_count)`` — which twin Rob trains under NOW.

    Recency leads, and it must: 'Dumbbell Lateral Raise' carries 438 lifetime
    sets from the Fitbod era against 57 for 'Lateral Raise (Dumbbell)', the name
    he actually logs today. Ranking the pair by lifetime volume surfaced the dead
    string — tagged "stale: not trained in >6wk" — and hid the lift he did three
    days ago. Lifetime count only breaks ties between names of equal recency.
    """
    if not names:
        return {}
    try:
        rows = conn.execute(
            "SELECT ws.exercise, MAX(CASE WHEN w.source = 'hevy' THEN w.started_at::DATE END), "
            "COUNT(*) FROM workout_sets ws JOIN workouts w ON w.id = ws.workout_id "
            "WHERE COALESCE(ws.is_warmup, FALSE) = FALSE AND ws.exercise IN "
            f"({','.join('?' * len(names))}) GROUP BY ws.exercise",
            names,
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — tie-break only, never load-bearing
        log.debug("logged recency unavailable: %s", exc)
        return {}
    return {r[0]: (r[1] or date.min, int(r[2] or 0)) for r in rows}


def _cross_muscle_credit(conn: duckdb.DuckDBPyConnection) -> dict[str, list[tuple[str, float]]]:
    """``exercise -> [(secondary muscle, credit), ...]`` — what else a lift pays into.

    The accounting layer has always known this (359 secondary rows, and indirect
    work is the MAJORITY of several muscles' volume — forearms 100%, mid_back
    76%, traps 61%, triceps 57%). Selection never saw it: the candidate pool is
    built per-muscle, so picking for lats could not tell that a Chin Up buys
    biceps volume a Lat Pulldown does not. Under an hour that fits ~20 sets, that
    is the difference between covering a muscle and skipping it.
    """
    try:
        rows = conn.execute(
            "SELECT exercise_name, muscle, credit FROM exercise_muscle "
            "WHERE role = 'secondary' AND credit > 0"
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — annotation optional
        log.debug("cross-muscle credit unavailable: %s", exc)
        return {}
    out: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for ex, muscle, credit in rows:
        out[ex].append((muscle, float(credit or 0)))
    return dict(out)


def evidence_menu(
    conn: duckdb.DuckDBPyConnection,
    muscles: list[str],
    per_muscle: int = 4,
    muscle_deficit: Mapping[str, float] | None = None,
    direct_short: set[str] | None = None,
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
    except Exception as exc:  # noqa: BLE001
        log.warning("exercise_preferences unavailable — 'no' list not applied: %s", exc)
        avoid = set()
    # This week's per-head trained volume steers selection toward the neglected
    # head; degrade to recency/quality-only if the region ledger is unavailable.
    try:
        region_vol = weekly_region_volume(conn, _iso_week_start(date.today()))
    except Exception as exc:  # noqa: BLE001 — region ledger optional
        log.debug("weekly_region_volume unavailable: %s", exc)
        region_vol = {}

    # The planner may only name exercises Rob can log. A curated movement outside
    # that vocabulary is unprogrammable, so admitting it to the menu costs a slot
    # and — when it wins the rotation — silently kills the swap (the lift it
    # displaced stays in the plan because the replacement cannot be written).
    loggable = loggable_names(conn)

    # Pull each muscle's curated candidates, then score every distinct candidate's
    # progression once so selection can demote plateaued lifts (swap-on-plateau).
    per_muscle_rows: dict[str, list[tuple]] = {}
    dropped: dict[str, list[str]] = {}
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
        if loggable:
            writable = [c for c in cands if c[0] in loggable]
            if writable:
                unwritable = [c[0] for c in cands if c[0] not in loggable]
                if unwritable:
                    dropped[muscle] = sorted(set(unwritable))
                cands = writable
            elif cands:
                # Every option for this muscle is unloggable. That is far more
                # likely a stale/partial template sync than a real dead end, and
                # blanking the muscle would read downstream as "nothing to train
                # here" — strictly worse than the naming gap this filters. Keep
                # the candidates and say so.
                log.warning(
                    "evidence_menu: every curated option for %s is unloggable "
                    "(%d) — keeping them; check the Hevy template sync",
                    muscle,
                    len(cands),
                )
        # One movement, one slot: the catalog carries the same lift under two
        # name conventions, and without this both twins can be picked — or worse,
        # one is "swapped in" to replace the other, burning a rotation on a
        # rename. Prefer the twin Rob has actually logged (it carries the real
        # progression history); tie-break on name for determinism.
        recency = _logged_recency(conn, [c[0] for c in cands])
        by_movement: dict[str, tuple] = {}
        for c in sorted(
            cands,
            key=lambda r: (
                -recency.get(r[0], (date.min, 0))[0].toordinal(),
                -recency.get(r[0], (date.min, 0))[1],
                r[0],
            ),
        ):
            by_movement.setdefault(f"{c[1]}|{_movement_key(c[0])}", c)
        cands = sorted(by_movement.values(), key=lambda r: r[0])
        if cands:
            per_muscle_rows[muscle] = cands
    if dropped:
        # Fail visibly: a muscle silently losing its best-evidence option to a
        # naming gap reads downstream as "no good exercise exists".
        log.warning(
            "evidence_menu: %d curated movement(s) dropped as unloggable — %s",
            sum(len(v) for v in dropped.values()),
            "; ".join(f"{m}: {', '.join(v)}" for m, v in sorted(dropped.items())),
        )

    aliases = _load_exercise_aliases(conn)
    all_names = {c[0] for cands in per_muscle_rows.values() for c in cands}
    info = _progress_info(conn, all_names, aliases)
    ranks = {n: v["rank"] for n, v in info.items()}
    # Weeks this movement has actually held its slot — NOT the depth of its e1RM
    # history, which is what used to be passed here and meant a lift last trained
    # in 2019 read as a six-week incumbent. Drives the 4–6 week rotation trigger.
    tenure = {n: int(v.get("tenure") or 0) for n, v in info.items()}
    # Whether Rob has logged the movement recently enough to prove the equipment
    # exists and the name is loggable. Gates what may LEAD a head, not what may
    # appear on the menu.
    verified_cutoff = (date.today() - timedelta(days=_VERIFIED_WITHIN_DAYS)).isoformat()
    verified = {n: (v.get("last_done") or "") >= verified_cutoff for n, v in info.items()}

    # What each candidate also pays into, and how much of another muscle's
    # shortfall that buys. Used ONLY to break ties below the quality keys — see
    # _select_grounded — so a lift is never chosen for what it does to some other
    # muscle at the expense of the one being programmed.
    cross = _cross_muscle_credit(conn)
    deficit = muscle_deficit or {}
    secondary_deficit = {
        name: sum(deficit.get(mu, 0.0) * cr for mu, cr in cross.get(name, [])) for name in all_names
    }
    # Role per (exercise, muscle): a muscle short on DIRECT work must not have its
    # head led by a lift that only trains it as a synergist.
    try:
        direct_pairs = {
            (r[0], r[1])
            for r in conn.execute(
                "SELECT exercise_name, muscle FROM exercise_muscle WHERE role = 'primary'"
            ).fetchall()
        }
    except Exception as exc:  # noqa: BLE001 — gate optional, degrade to no gate
        log.debug("primary-role lookup unavailable: %s", exc)
        direct_pairs = set()

    # Loadable grids for the progressibility annotation (advisory — selection
    # ordering is untouched). Optional: absent grids just omit the field.
    grids = None
    try:
        from shc.training.loadable import build_grids

        grids = build_grids(conn)
    except Exception as exc:  # noqa: BLE001 — annotation optional
        log.debug("loadable grids unavailable for progressibility: %s", exc)

    short_on_direct = direct_short or set()
    out: dict[str, list[dict]] = {}
    for muscle, cands in per_muscle_rows.items():
        # Only gate on role where the muscle is actually short of DIRECT work.
        # Elsewhere a synergist-role option is a legitimate pick — a row really
        # does build mid-back — and blocking it everywhere would empty the pools
        # that are mostly compound.
        is_direct = (
            {c[0]: (c[0], muscle) in direct_pairs for c in cands}
            if muscle in short_on_direct and direct_pairs
            else None
        )
        selected, notes = _select_grounded(
            cands,
            per_muscle,
            region_vol.get(muscle),
            ranks,
            tenure,
            verified=verified,
            secondary_deficit=secondary_deficit,
            is_direct=is_direct,
        )
        picks: list[dict] = []
        for c in selected:
            pi = info.get(c[0], {})
            trend = pi.get("trend", "untrained")
            pick = {
                "exercise": c[0],
                "region": c[2],
                "length_bias": c[3],
                "rep_low": c[4],
                "rep_high": c[5],
                "sfr_tier": c[6],
                "rationale": c[7],
                "citation": c[8],
                "citation_url": c[9],
                "trend": trend,
                "weeks": pi.get("weeks", 0),
                "tenure": pi.get("tenure", 0),
                "also_credits": sorted(cross.get(c[0], []), key=lambda mc: -mc[1]),
                "last_done": pi.get("last_done"),
                "status": notes.get(c[0]) or _default_status(trend, pi.get("tenure", 0)),
            }
            if grids is not None:
                prog = _progressibility(grids, pi.get("logged_name") or c[0])
                if prog is not None:
                    pick["progressibility"] = prog
            picks.append(pick)
        out[muscle] = picks
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
            "credited_muscle_sets": int,  # volume credit; not physical exercise sets
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
                "credited_muscle_sets": sum(e["sets"] for e in entries),
                "muscles": entries,
            }
        )
    return out


_WEEKDAY_NUM = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}


def remaining_split(
    muscle_rx: list[MusclePrescription],
    today: date,
    split: tuple[dict[str, str], ...] = WEEKLY_SPLIT,
) -> dict:
    """Reflow each muscle's REMAINING weekly sets over the sessions still ahead.

    :func:`_session_split` distributes the whole weekly target evenly across the
    fixed Tue–Fri skeleton, once — so when a session is missed or a day is
    gated, the sets it carried silently evaporate and the weekly target degrades
    from a controlled quantity to an aspiration. This is the daily re-planner:
    ``target_sets − current_sets`` (what the week still owes; ``current_sets``
    is the in-progress week's credited volume) spread over the split sessions
    whose weekday is today or later, same even-divmod allocation, same
    :data:`PER_SESSION_SET_CAP` over-cap flagging (never silent truncation).

    Returns ``{"sessions": [...], "unplaceable": [...], "days_left": int}``.
    ``unplaceable`` lists muscles that still owe sets but have no matching
    session left this week (e.g. a leg target after Friday) — surfaced, not
    dropped, so a shortfall is a visible number. A muscle whose week is already
    at/over target (holds, cuts, deloads mid-shed) simply has nothing left to
    place and is absent.
    """
    ahead = [s for s in split if _WEEKDAY_NUM.get(s["weekday"], 7) >= today.weekday()]
    upper_labels = [s["label"] for s in ahead if s["region"] != "lower"]
    lower_labels = [s["label"] for s in ahead if s["region"] == "lower"]
    meta = {s["label"]: s for s in ahead}
    split_map: dict[str, list[dict]] = {s["label"]: [] for s in ahead}
    unplaceable: list[dict] = []

    for rx in muscle_rx:
        rem = rx.target_sets - round(rx.current_sets)
        if rem <= 0:
            continue
        labels = lower_labels if rx.muscle in LOWER_BODY else upper_labels
        if not labels:
            unplaceable.append({"muscle": rx.muscle, "remaining": rem, "emphasis": rx.emphasis})
            continue
        base, extra = divmod(rem, len(labels))
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

    sessions = [
        {
            "session": label,
            "weekday": meta[label]["weekday"],
            "region": meta[label]["region"],
            "cap": PER_SESSION_SET_CAP,
            "credited_muscle_sets": sum(e["sets"] for e in entries),
            "muscles": entries,
        }
        for label, entries in split_map.items()
        if entries
    ]
    return {"sessions": sessions, "unplaceable": unplaceable, "days_left": len(ahead)}


def trainable_today(
    muscle_rx: list[MusclePrescription],
    gates: dict,
    muscle_recovery: dict[str, dict] | None = None,
) -> list[dict]:
    """Daily projection of the weekly prescription onto today's live gates.

    :data:`WEEKLY_SPLIT` allocates volume across a FIXED Tue–Fri skeleton — a
    muscle sits on whichever day-label the split assigned it, regardless of
    whether today's actual gates allow training it. On 2026-07-23 this made a
    genuinely trainable ~15-set day (abs, lower_back, forearms all had
    positive weekly targets and none of them were gated) render as
    "glutes ×1", because the only muscle with volume on THAT day's fixed
    label was glutes — core/forearms sat on the wrong label and never
    surfaced. This recomputes what's actually available RIGHT NOW: every
    muscle with a positive weekly target, classified against today's live
    per-muscle/group gates instead of the static skeleton. It does not
    replace the weekly split (still the mesocycle-level skeleton); it is the
    daily lens on top of it.

    Classification (first match wins):
      * ``rest_gated`` — the muscle itself is in ``gates["forbid_muscles"]``.
      * ``group_gated`` — the muscle's push/pull/legs group is in
        ``gates["forbid_muscle_groups"]`` (conditioning-ACWR legs forbid,
        same-day pickleball, soreness — genuinely group-scoped signals).
      * ``held`` — the weekly controller's action is ``"hold"`` (e.g. the
        conditioning leg-interference hold, an MRV ceiling, a protein-gate
        cap): trainable at its CURRENT volume, just not where to add sets.
      * ``available`` — clear to train toward this week's target.

    Muscles outside :data:`shc.metrics.MUSCLE_TO_GROUP`'s push/pull/legs
    membership (core: abs, lower_back; forearms) can never be rest_gated or
    group_gated — mirrors the per-muscle rest gate's scope (metrics._gates) —
    so they fall straight to held/available, which is the exact fix for the
    2026-07-23 incident.
    """
    from shc.metrics import MUSCLE_TO_GROUP

    forbid_muscles = set(gates.get("forbid_muscles", []))
    forbid_groups = set(gates.get("forbid_muscle_groups", []))
    recovery = muscle_recovery or {}
    out: list[dict] = []
    for m in muscle_rx:
        if m.target_sets <= 0:
            continue
        group = MUSCLE_TO_GROUP.get(m.muscle)
        if m.muscle in forbid_muscles:
            days = recovery.get(m.muscle, {}).get("days_since")
            status = "rest_gated"
            detail = f"rest-gated — {days}d since last dose" if days is not None else "rest-gated"
        elif group in forbid_groups:
            status = "group_gated"
            detail = f"{group} group forbidden today"
        elif m.action == "hold":
            status = "held"
            detail = m.reason
        else:
            status = "available"
            detail = None
        out.append(
            {
                "muscle": m.muscle,
                "target_sets": m.target_sets,
                "status": status,
                "detail": detail,
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
    if signed_mean <= 0:
        # Under-RPE: sessions were easier than target — don't reduce volume (only dampens, never amplifies).
        return 1.0
    # Over-RPE: athlete consistently working harder than prescribed — dampen the volume add.
    raw = 1.0 - min(signed_mean / 3.0, 0.5)
    return max(0.5, raw)


def _rpe_headroom(conn: duckdb.DuckDBPyConnection, min_magnitude: float = 0.75) -> bool:
    """True when the athlete has been running SUSTAINED under-target RPE.

    2026-07-23 remediation: `_rpe_drift_factor` reads the same underlying
    signal (`rpe_drift_signed_mean`, a 14-day mean of avg_rpe_actual minus
    avg_rpe_target) but is deliberately one-way — it dampens volume on
    over-RPE and is a no-op on under-RPE, because "you worked easier than
    target" should never by itself justify LESS volume. But it was also a
    dead end: the signal had no OTHER consumer, so an athlete running
    consistently under target RPE (plenty of headroom) got no response from
    the engine at all. This is the missing other half — a session-level
    boolean `_decide` uses to redirect the STALLED remedy from "add a set"
    to "raise the load" when a flat e1RM comes with real effort left in the
    tank. It does not touch volume itself (that stays `_rpe_drift_factor`'s
    job, unchanged) — this only changes what kind of ADVICE a stall gets.

    Threshold (0.75) is intentionally looser than the damper's 0.8 floor
    (min_magnitude) — surfacing headroom sooner is low-risk (it only changes
    a text recommendation to lift more, never a hard gate), whereas damping
    volume on a false positive has a real cost, so the damper stays more
    conservative.
    """
    from shc.ai.quality import rpe_drift_signed_mean

    signed_mean = rpe_drift_signed_mean(conn)
    return signed_mean is not None and signed_mean <= -min_magnitude


_OVERREACH_RPE_RISE = 0.5
"""How far weekly mean RPE must climb above the athlete's own norm to count."""
_OVERREACH_RPE_FLOOR = 8.0
"""...and the absolute level it must also clear. Both bounds are required: a
rise from 6.0 to 6.6 is a return to normal training, not grinding, while a
steady 8.5 with no rise is simply how someone trains."""


def _effort_overreach(
    conn: duckdb.DuckDBPyConnection,
    baseline_weeks: int = 8,
    meso_state: MesocycleState | None = None,
) -> dict:
    """Is Rob grinding — weekly mean RPE elevated against his own baseline?

    Reads the weekly rollup (migration 0079), NOT ``plan_adherence``. That table
    holds one actual/target RPE pair per PLANNED session, and it is sparse: only
    4 rows carry an RPE, so ``rpe_drift_signed_mean`` — which needs 5 sessions in
    14 days — currently returns None and every signal built on it is inert. The
    rollup has 100% set-level coverage over the last 30 days.

    Requires BOTH a rise above his own baseline AND an absolute level, because
    either alone misreads: a rise from 6.0 to 6.6 is a return to normal training,
    and a flat 8.5 is just how somebody trains. Returns ``overreaching: False``
    with whatever it could measure when there isn't enough history — never a
    guess, since this feeds a deload decision.

    ``meso_state`` makes the check PHASE-AWARE. The intra-meso RIR ramp
    (:func:`shc.training.mesocycle.meso_rpe_band`) deliberately raises the
    effort target across the accumulation weeks, so a late-block week is
    SUPPOSED to read above the trailing baseline — without this, following the
    plan trips the detector and (with any regressing muscle as corroboration)
    recommends deloading Rob for doing what the plan asked. The planned
    midpoint rise is added to the required rise: only effort above what the
    plan itself asked for counts as grinding. Erring toward NOT deloading is
    deliberate — this trigger is corroboration-gated anyway, and the other
    deload triggers (regression count, MRV count) are untouched.
    """
    try:
        rows = conn.execute(
            """
            SELECT week_start, SUM(weekly_avg_rpe * rpe_set_count) / SUM(rpe_set_count) AS rpe
            FROM exercise_weekly_e1rm
            WHERE weekly_avg_rpe IS NOT NULL AND COALESCE(rpe_set_count, 0) > 0
              AND week_start >= (CURRENT_DATE - INTERVAL (? || ' weeks'))
            GROUP BY week_start
            ORDER BY week_start DESC
            """,
            [str(baseline_weeks + 1)],
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — pre-0079 schema → no claim
        log.debug("effort overreach unmeasurable: %s", exc)
        return {"overreaching": False, "reason": "no RPE history"}

    if len(rows) < 3:
        return {"overreaching": False, "reason": f"only {len(rows)} scored week(s)"}
    recent = float(rows[0][1])
    prior = [float(r[1]) for r in rows[1:]]
    baseline = sum(prior) / len(prior)
    planned_rise = 0.0
    if meso_state is not None:
        from shc.training.mesocycle import meso_rpe_midpoint_rise

        planned_rise = meso_rpe_midpoint_rise(meso_state.week_number, meso_state.planned_weeks)
    return {
        "overreaching": (recent - baseline) >= _OVERREACH_RPE_RISE + planned_rise
        and recent >= _OVERREACH_RPE_FLOOR,
        "recent_rpe": round(recent, 2),
        "baseline_rpe": round(baseline, 2),
        "planned_rise": round(planned_rise, 2),
        "weeks": len(rows),
    }


def _muscle_rpe_headroom(
    conn: duckdb.DuckDBPyConnection,
    weeks: int = 8,
    min_weeks: int = 3,
) -> dict[str, bool]:
    """Per-muscle "this is getting easier" flag, from the weekly RPE trend.

    Returns ``{muscle: True}`` for muscles whose primary exercises show a
    meaningfully FALLING average RPE across recent weeks — the same load costing
    steadily less effort.

    Exists because :func:`_rpe_headroom` is a single cross-muscle number: it
    reads `plan_adherence`, which stores one actual/target RPE pair per SESSION,
    so one muscle coasting could unlock the load-not-volume remedy for every
    muscle in the plan, and one muscle grinding could deny it to all of them.
    Its own docstring flags this ("rpe_headroom is session-level"). With weekly
    per-exercise RPE now materialised (migration 0079) the signal can be
    resolved per muscle, which is the granularity the decision actually needs.

    Deliberately measures the TREND, not distance from target: this asks "is
    this muscle adapting to its current load", which is a property of the muscle,
    whereas actual-vs-target is a property of the session prescription and stays
    with :func:`_rpe_headroom`. The two are complementary, and `_decide` treats
    either as sufficient.

    Empty dict when the data isn't there — callers fall back to the session
    signal, i.e. exactly the pre-0079 behaviour.
    """
    try:
        rows = conn.execute(
            """
            SELECT m.primary_muscle, e.week_start, AVG(e.weekly_avg_rpe) AS rpe
            FROM exercise_weekly_e1rm e
            JOIN exercise_muscle_map m ON m.exercise_name = e.exercise
            WHERE e.weekly_avg_rpe IS NOT NULL
              AND COALESCE(e.rpe_set_count, 0) >= 2
              AND e.week_start >= (CURRENT_DATE - INTERVAL (? || ' weeks'))
            GROUP BY m.primary_muscle, e.week_start
            ORDER BY m.primary_muscle, e.week_start
            """,
            [str(weeks)],
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 — pre-0079 schema → session signal
        log.debug("per-muscle RPE headroom unavailable: %s", exc)
        return {}

    by_muscle: dict[str, list[float]] = {}
    for muscle, _wk, rpe in rows:
        by_muscle.setdefault(str(muscle), []).append(float(rpe))

    from shc.training.mesocycle import _RPE_MEANINGFUL_SLOPE, _rpe_slope_per_week

    out: dict[str, bool] = {}
    for muscle, series in by_muscle.items():
        if len(series) < min_weeks:
            continue
        if _rpe_slope_per_week(series) <= -_RPE_MEANINGFUL_SLOPE:
            out[muscle] = True
    return out


def _weekly_capacity(
    conn: duckdb.DuckDBPyConnection,
    targets: list[MusclePrescription],
    lookback_weeks: int = 10,
) -> dict:
    """Is this week's set demand deliverable in the sessions Rob actually does?

    Compares DEDICATED demand — muscle-sets that need a working set allocated to
    that muscle as its PRIMARY — against the median working sets/week measured
    over ``lookback_weeks`` completed weeks. Both sides are in the same unit
    (one working set buys one primary muscle-set), so the comparison is direct.

    The distinction matters and an earlier cut of this function got it wrong by
    summing every ``target_sets``. A maintenance muscle that is HOLDING needs
    zero dedicated sets: its volume arrives as secondary spillover from the
    grow-tier work (one row pays its primary AND every synergist it lists), and
    the same working set cannot be charged twice. Counting those holds as demand
    inflated the requirement by ~35 muscle-sets and reported a feasible week as
    infeasible. Dedicated demand is therefore:

        every grow-tier target  +  the TOP-UP delta for a maintenance muscle
                                   still below MV (that part is real new work)

    ``credit_ratio`` is still reported for context — it says how much total
    muscle-stimulus each working set generates once spillover is counted — but
    it is deliberately NOT used to discount the requirement, because the spill
    lands on whichever muscles the movement happens to hit, not necessarily the
    ones being grown. NOTE the ratio below is measured off ``exercise_muscle``'s
    STORED ``credit`` weights (0.5/secondary), which are not the rate the volume
    validator counts by — :data:`shc.training.volume.SECONDARY_CREDIT` is 1.0
    since 9eb6aab. Left as-is here on purpose: this is only a context number and
    changing it would move the ``feasible`` verdict, which is a behaviour call,
    not a doc fix.

    Exists because the pre-0078 engine had no notion of a budget at all: with
    MEV the floor for all 17 muscles, demand summed to ~137 muscle-sets/wk
    against ~94 deliverable — unsatisfiable AND unranked, so silent triage was
    the planner's only option. Reporting ``feasible`` makes that visible.

    Degrades to an empty dict (no claim) rather than guessing when there isn't
    enough history to measure — a fabricated budget would be worse than none.
    """
    try:
        rows = conn.execute(
            """
            SELECT COUNT(*) AS n_sets
            FROM workout_sets w
            JOIN workouts k ON k.id = w.workout_id
            WHERE k.started_at > CURRENT_DATE - INTERVAL (? || ' weeks')
              AND COALESCE(w.is_warmup, FALSE) = FALSE
            GROUP BY date_trunc('week', k.started_at)
            """,
            [str(lookback_weeks)],
        ).fetchall()
        credit = conn.execute(
            """
            SELECT AVG(total_w) FROM (
                SELECT exercise_name,
                       SUM(CASE WHEN role = 'primary' THEN 1.0 ELSE 0.5 END) AS total_w
                FROM exercise_muscle
                GROUP BY exercise_name
            )
            """
        ).fetchone()
    except Exception as exc:  # noqa: BLE001 — measurement optional → no claim
        log.debug("weekly capacity unmeasurable: %s", exc)
        return {}

    weekly = sorted(int(r[0]) for r in rows)
    if len(weekly) < 3:
        return {}
    capacity_working = float(statistics.median(weekly))

    # Realised credit ratio: muscle-sets awarded per working set. Measured off
    # the mapping table so it tracks curation rather than a hardcoded guess.
    ratio = float(credit[0]) if credit and credit[0] else 1.5
    ratio = max(1.0, min(ratio, 3.0))

    # Dedicated: needs its own working set. A holding maintenance muscle does
    # not — its sets come free as spillover from the grow-tier work.
    dedicated = 0.0
    spillover_held = 0.0
    for t in targets:
        if t.tier == "maintain":
            top_up = max(0.0, t.target_sets - t.current_sets)
            dedicated += top_up
            spillover_held += t.target_sets - top_up
        else:
            dedicated += t.target_sets
    return {
        "dedicated_demand_sets": round(dedicated, 1),
        "held_by_spillover_sets": round(spillover_held, 1),
        "total_prescribed_muscle_sets": round(float(sum(t.target_sets for t in targets)), 1),
        "capacity_working_sets": round(capacity_working, 1),
        "credit_ratio": round(ratio, 2),
        "feasible": dedicated <= capacity_working,
        "over_by_sets": round(max(0.0, dedicated - capacity_working), 1),
    }


def _weekly_deload_context(
    conn: duckdb.DuckDBPyConnection,
) -> tuple[
    MesocycleState | None,
    dict[str, VolumeTarget],
    list[MuscleVolume],
    dict[str, int | None],
    dict,
]:
    """Compute the shared calendar/systemic deload decision and its inputs."""
    state = active_mesocycle(conn)
    meso_id = state.id if state else ""
    this_week = _iso_week_start(date.today())
    targets = volume_targets(conn, meso_id)
    actuals = weekly_muscle_volume(conn, this_week)
    report = build_muscle_report(actuals, targets)
    targeted = [r for r in report if r.mev is not None and r.mav is not None and r.mrv is not None]
    perfs = {r.muscle: _muscle_performance(conn, r.muscle) for r in targeted}

    from shc.metrics import _deload_in_cooldown
    from shc.training.self_learning import read_deload_threshold

    signal_deload = deload_check(
        perfs,
        targeted,
        threshold=read_deload_threshold(conn),
        effort=_effort_overreach(conn, meso_state=state),
    )
    if signal_deload["recommended"] and _deload_in_cooldown(conn, date.today()):
        signal_deload = {
            **signal_deload,
            "recommended": False,
            "reason": "signal deload suppressed during post-deload cooldown",
        }

    is_calendar = bool(state and state.is_deload_week)
    is_signal = bool(signal_deload["recommended"])
    if is_calendar and is_signal:
        deload_reason = "both"
    elif is_calendar:
        deload_reason = "calendar"
    elif is_signal:
        deload_reason = "signal"
    else:
        deload_reason = None
    deload = {
        **signal_deload,
        "recommended": is_calendar or is_signal,
        "deload_reason": deload_reason,
        "reason": (
            signal_deload["reason"]
            if is_signal
            else (
                f"calendar deload — week {state.week_number} exceeds planned {state.planned_weeks}"
                if is_calendar and state
                else signal_deload["reason"]
            )
        ),
    }
    return state, targets, report, perfs, deload


def weekly_deload_status(conn: duckdb.DuckDBPyConnection) -> dict:
    """Return the canonical weekly calendar/systemic deload decision."""
    return _weekly_deload_context(conn)[4]


def weekly_prescription(
    conn: duckdb.DuckDBPyConnection,
    propranolol_day: bool = False,
    daily_state: dict | None = None,
) -> Prescription:
    """Build this week's per-muscle volume prescription from Rob's logged data.

    The deterministic program: every targeted muscle gets a set target + action +
    reason; lagging lifts get a progression call; muscles needing volume get an
    exercise menu. The chat assembles the actual session from this.

    ``propranolol_day`` bypasses WHOOP-derived conditioning ACWR (HR-suppressed,
    unreliable on dosed days) and restores full RPE-drift authority to the
    volume decision.

    Pass ``daily_state`` (an already-computed ``DailyState`` dict) when the
    caller has one in scope, to avoid recomputing it just to read the
    conditioning ACWR + staleness flag.
    """
    meso_state, targets, report, perfs, deload = _weekly_deload_context(conn)
    meso_id = meso_state.id if meso_state else ""
    this_week = _iso_week_start(date.today())
    soreness = _recent_soreness(conn)
    conditioning_acwr, conditioning_blind = _conditioning_pressure(
        conn, use_rpe_only=propranolol_day, state=daily_state
    )
    from shc.metrics import personalized_cond_thresholds

    leg_hold_threshold, _cond_forbid_legs = personalized_cond_thresholds(conn)
    try:
        from shc.selflab import read_active_volume_target_actuations

        prior_multipliers = read_active_volume_target_actuations(conn)
    except Exception as exc:  # noqa: BLE001 — prior actuation optional
        log.debug("prior volume-target actuations unavailable: %s", exc)
        prior_multipliers = {}
    data_gaps: list[str] = []
    if conditioning_blind:
        data_gaps.append(
            "WHOOP not synced >2d — conditioning ACWR blind; the leg-volume "
            "interference hold cannot actuate this week (verify court/cardio "
            "load manually before trusting a leg ADD)"
        )
    if not soreness:
        # soreness.get(muscle, 0.0) reads a genuinely sore, un-checked-in muscle
        # as 0.0 (relies on exact key parity between the check-in JSON and the
        # 17-muscle vocabulary — no per-muscle warn on a miss). When the WHOLE
        # map is empty, under-recovery holds can't fire for anyone this week —
        # visible enough to warrant a note even though a single missing key
        # doesn't.
        data_gaps.append(
            "No soreness check-in data this week — under-recovery hold cannot "
            "actuate for any muscle (verify recovery manually)"
        )

    targeted = [r for r in report if r.mev is not None and r.mav is not None and r.mrv is not None]

    # Protein gate: flag if recent intake is inadequate for hypertrophy.
    protein = _protein_gate(conn)

    # RPE drift factor: dampen volume deltas when athlete is consistently
    # working harder than target (persistent over-RPE). On propranolol days
    # RPE is the only unbiased signal, so restore full authority (factor = 1.0).
    rpe_factor = 1.0 if propranolol_day else _rpe_drift_factor(conn)
    # RPE headroom: the OTHER half of the same signal — sustained under-target
    # RPE redirects a stalled muscle's remedy toward load, not volume (see
    # _rpe_headroom). Computed unconditionally (not gated by propranolol_day):
    # it reads plan_adherence's logged-vs-target RPE directly, unaffected by
    # HR suppression.
    rpe_headroom = _rpe_headroom(conn)
    # Per-muscle effort trend (0079). Either signal is sufficient: the session
    # one says "you undershot the prescribed target", the per-muscle one says
    # "this muscle's load is getting easier". Both point at the same remedy
    # (raise load before adding sets) from different evidence.
    muscle_headroom = _muscle_rpe_headroom(conn)

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
    # Captured for the direct-work floor below: floors are judged on DIRECT sets,
    # ceilings on the credited total, so both landmarks have to survive the loop.
    landmark_floor: dict[str, float] = {}
    landmark_ceiling: dict[str, float] = {}
    for r in targeted:
        if r.mev is not None:
            landmark_floor[r.muscle] = float(r.mev)
        if r.mrv is not None:
            landmark_ceiling[r.muscle] = float(r.mrv)
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
            rpe_headroom=rpe_headroom or muscle_headroom.get(r.muscle, False),
            leg_hold_threshold=leg_hold_threshold,
            tier=vt.tier if vt else "grow",
            mv=vt.mv if vt else 2,
        )
        # If protein is inadequate, cap "add" actions at "hold" for non-emphasis muscles.
        if rx.action == "add" and not rx.emphasis and protein.get("adequate") is False:
            rx.action = "hold"
            rx.reason = (
                rx.reason + " [held: protein below target — substrate needed to convert stimulus]"
            )
        # Deterministic actuation of a CONFIRMED n-of-1 prior (see
        # selflab.read_active_volume_target_actuations): scales this week's
        # FINAL target, clamped to [MEV, MRV] so a prior can adjust the ramp
        # but never push a muscle below its productive floor or above its
        # tested ceiling — the same non-negotiable bounds every other branch
        # of this function respects.
        prior_mult = prior_multipliers.get(r.muscle)
        if prior_mult is not None and r.mev is not None and r.mrv is not None:
            adjusted = round(rx.target_sets * prior_mult)
            # Floor at the muscle's OWN productive minimum, not unconditionally at
            # MEV: a maintenance-tier muscle's floor is MV, and clamping it up to
            # MEV here would silently re-grow a muscle Rob deliberately parked.
            prior_floor = min(rx.target_sets, r.mev) if rx.tier == "maintain" else r.mev
            adjusted = max(prior_floor, min(r.mrv, adjusted))
            if adjusted != rx.target_sets:
                rx.reason = (
                    rx.reason + f" [confirmed prior: {rx.target_sets}→{adjusted} sets "
                    f"({prior_mult - 1.0:+.0%})]"
                )
                rx.delta += adjusted - rx.target_sets
                rx.target_sets = adjusted
        muscle_rx.append(rx)

    # Emphasis first, then the muscles being grown, then the rest.
    muscle_rx.sort(key=lambda m: (not m.emphasis, m.action != "add", m.muscle))

    # Lifts to progress: recently-trained exercises with a clear add/deload call.
    lift_progressions: list[dict] = []
    recent = conn.execute(
        """
        SELECT DISTINCT exercise FROM workout_sets_dedup
        WHERE started_at::DATE >= ? AND weight_kg > 0 AND reps > 0
          AND source = 'hevy' AND is_warmup = FALSE
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

    # Exercise menu for EVERY prescribed muscle, not just the ones gaining sets.
    #
    # This was previously gated on `action == "add" or emphasis`, which coupled
    # two independent training variables: how MUCH to train a muscle, and WHICH
    # movement to train it with. A muscle sitting exactly at its target got no
    # selection input at all, so the only exercise-shaped signal left for it was
    # the recency-sorted staple list — and it kept getting the same lift forever.
    #
    # The coupling is visible in the data: the seven muscles on HOLD were the
    # seven with the worst single-exercise monopolies (side_delts 95%, mid_back
    # 100%, traps 100%, front_delts 74%, rear_delts 73%, triceps 63%, lats 55%),
    # while every muscle that happened to be ADD-ing had a menu and a spread.
    #
    # A HOLD muscle's menu is a SUBSTITUTION list, not an invitation to add
    # volume — every one of them sits at delta +0, and the set-count validator
    # rejects a plan that exceeds target+1. `prescription_context_block` labels
    # them accordingly.
    need_volume = [m.muscle for m in muscle_rx]
    menu = _exercise_menu(conn, need_volume)

    # How short each muscle is of its target — the currency the cross-muscle
    # tiebreak spends, so a tie is settled by which option also feeds a lagging
    # muscle rather than by alphabetical order.
    muscle_deficit = {m.muscle: max(0.0, m.target_sets - m.current_sets) for m in muscle_rx}

    # Muscles whose DIRECT work is below MEV even though total credited volume is
    # not. Synergist credit is real volume but it is not a substitute for
    # training the muscle, and the total was hiding the difference: mid_back
    # draws 76% of its volume indirectly, traps 61%, triceps 57%. Where this
    # holds, the muscle's head may not be led by a lift that trains it only as a
    # synergist.
    direct_short: set[str] = set()
    try:
        direct_now = dict(
            conn.execute(
                """
                SELECT em.muscle, COUNT(*)::DOUBLE
                FROM workout_sets_dedup ws
                JOIN exercise_muscle em
                  ON em.exercise_name = ws.exercise AND em.role = 'primary'
                WHERE ws.started_at::DATE >= ? AND ws.started_at::DATE < ?
                  AND NOT ws.is_warmup AND ws.weight_kg > 0
                GROUP BY em.muscle
                """,
                [this_week.isoformat(), (this_week + timedelta(days=7)).isoformat()],
            ).fetchall()
        )
        for m in muscle_rx:
            direct = direct_now.get(m.muscle, 0.0)
            floor = _direct_floor(m, landmark_floor.get(m.muscle))
            if direct >= floor:
                continue
            # Only muscles that LOOK covered are "short on direct work". A muscle
            # still below its target is simply untrained-so-far and is already
            # emitting ADD; flagging it too would put all 17 on the banner every
            # Monday and make the signal worthless. The distinction is the whole
            # point of the flag: credited volume says done, direct work says no.
            if m.current_sets < m.target_sets:
                continue
            direct_short.add(m.muscle)
            # The floor BINDS, it does not merely annotate. With secondary credit
            # at the vault's 1:1 (volume.SECONDARY_CREDIT), a muscle can reach its
            # target on spillover alone and stop being trained: measured 2026-08-20
            # over 8 weeks, biceps — the ★ emphasis muscle — read 16.6 credited
            # sets/wk against a target of 12 while only 11.1 were direct, and
            # forearms read satisfied on 100% indirect work (0.0 direct). Helms
            # ships 1:1 WITH "don't rely entirely on indirect volume"; taking the
            # ratio without the constraint is what suppresses the muscle.
            #
            # Raising the target (rather than rejecting at the validator) is what
            # makes it SATISFIABLE: check #22 rejects a session that overshoots a
            # muscle's target, so a direct-work requirement the target has no room
            # for would be unmeetable by construction.
            deficit = floor - direct
            want = int(math.ceil(m.current_sets + deficit))
            ceiling = landmark_ceiling.get(m.muscle)
            if ceiling is not None:
                want = min(want, int(ceiling))
            if want > m.target_sets:
                m.delta += want - m.target_sets
                m.target_sets = want
                m.action = "add"
                m.reason += (
                    f" [direct-work floor: {direct:g} of {floor:g} required direct sets — "
                    "synergist credit is real volume but cannot supply the stimulus, "
                    "so the target makes room for direct work]"
                )
    except Exception as exc:  # noqa: BLE001 — gate optional, degrade to no gate
        log.debug("direct-volume lookup unavailable: %s", exc)

    science = evidence_menu(
        conn, need_volume, muscle_deficit=muscle_deficit, direct_short=direct_short
    )
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
        data_gaps=data_gaps,
        capacity=_weekly_capacity(conn, muscle_rx),
        remaining_week=remaining_split(muscle_rx, date.today()),
        direct_short=sorted(direct_short),
    )


def prescription_context_block(
    conn: duckdb.DuckDBPyConnection,
    daily_state: dict | None = None,
    prescription: Prescription | None = None,
) -> str:
    """Markdown block injected into the workout planner — the build order.

    Pass ``daily_state`` (an already-computed ``DailyState`` dict) when the
    caller has one in scope to avoid recomputing it.
    """
    # Callers that already computed the prescription pass it in rather than pay
    # for it twice (the context builder needs it before this block is rendered).
    rx = (
        prescription
        if prescription is not None
        else weekly_prescription(conn, daily_state=daily_state)
    )
    if not rx.muscles:
        return ""
    lines = ["## THIS WEEK'S PRESCRIPTION (build the session from this)"]
    for gap in rx.data_gaps:
        lines.append(f"⚠ **DATA GAP** — {gap}")
    if rx.deload.get("recommended"):
        lines.append(
            f"⚠ **DELOAD WEEK** — {rx.deload['reason']}. Volume is halved toward MEV "
            "across the board; keep loads moderate (RPE ≤7) and treat this as a "
            "fatigue-shedding week, not an accumulation week."
        )
    lines += [
        "Per-muscle volume targets the engine set from your performance + recovery.",
        "Prioritize muscles marked ADD and ★ emphasis; respect HOLD/CUT/DELOAD.",
    ]

    # Weekly budget. This was computed on every prescription and never rendered,
    # so an over-prescribed week reached the planner looking exactly like a
    # feasible one and the only available response was SILENT triage — drop
    # whatever didn't fit and never say which. The table below is already ranked
    # (emphasis first, then adds), so the honest handling is to publish the
    # shortfall and name the ranking, not to quietly trim targets that the
    # landmark logic set deliberately.
    cap = rx.capacity or {}
    if cap.get("feasible") is False:
        lines += [
            "",
            f"⚠ **OVER BUDGET — the full table does not fit this week.** It asks for "
            f"{cap['dedicated_demand_sets']:g} dedicated working sets against a measured "
            f"capacity of {cap['capacity_working_sets']:g}/wk "
            f"(your median over the last 10 weeks) — over by {cap['over_by_sets']:g}.",
            "  Do NOT silently drop the overflow. Work DOWN the table in order: ★ emphasis "
            "muscles get their full target first, then the other ADDs, then holds. Whatever "
            "does not fit is a deliberate shortfall — say which muscles you cut and by how "
            "much in the plan notes, so next week's targets inherit an honest number.",
            "  A muscle far below MEV is re-seeded to its minimum in ONE step by design "
            "(block initialization), so several muscles can land here at once after a "
            "deload or a landmark change. That is the ramp working, not an error — but it "
            "is exactly when the budget binds hardest.",
        ]
    elif cap.get("feasible") is True:
        lines.append(
            f"\nWeekly budget: {cap['dedicated_demand_sets']:g} dedicated sets against "
            f"~{cap['capacity_working_sets']:g}/wk measured capacity — fits."
        )

    lines += [
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
        lines += [
            "\n**Exercise menu — EVERY prescribed muscle** — sports-science-grounded "
            "where curated (lengthened-position + head coverage); recency otherwise.",
            "  A muscle marked HOLD/CUT still gets a menu: that is a SUBSTITUTION list "
            "for the sets it is already doing, NOT permission to add volume. Its set "
            "count comes from the table above and the validator enforces it.",
            "  `held Nwk` is how long that lift has occupied its slot. Past the "
            "rotation window the engine proposes a swap — if you program the incumbent "
            "anyway, say why in the plan notes rather than doing it silently.",
            "  `also credits` is what else the lift pays into at synergist rate. Under "
            "an hour that fits ~20 sets, a pick that covers a lagging muscle on the way "
            "past is worth more than one that doesn't — it breaks ties, it never "
            "outranks the target muscle's own stimulus.",
        ]
        if rx.direct_short:
            lines.append(
                "  ⚠ **DIRECT WORK SHORTFALL** — "
                + ", ".join(rx.direct_short)
                + ": total credited volume reaches target, but only because compounds "
                "are paying into it — primary-role work alone is still short. Synergist "
                "credit is real volume and NOT a substitute for training the muscle, so "
                "these heads lead with a movement that trains them directly."
            )
        action_by_muscle = {m.muscle: m.action for m in rx.muscles}
        for muscle, exs in rx.exercise_menu.items():
            picks = rx.exercise_science.get(muscle)
            act = (action_by_muscle.get(muscle) or "").upper()
            sub_sfx = " — SUBSTITUTE ONLY, do not add sets" if act in ("HOLD", "CUT") else ""
            if picks:
                dev = rx.development.get(muscle)
                if dev:
                    lines.append(
                        f"- **{muscle}** [{act}{sub_sfx}] — target "
                        f"{dev['weekly_sets_low']}–{dev['weekly_sets_high']} "
                        f"sets/wk over {dev['freq_per_week']}×; {dev['rep_scheme']} "
                        f"[{dev['citation']}]"
                    )
                else:
                    lines.append(f"- **{muscle}** [{act}{sub_sfx}] (evidence-based selection):")
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
                    also = p.get("also_credits") or []
                    also_sfx = (
                        " · also credits " + ", ".join(f"{mu} {cr:g}" for mu, cr in also)
                        if also
                        else ""
                    )
                    lines.append(
                        f"    - {p['exercise']} — {head}{p['length_bias']}-biased, "
                        f"{p['rep_low']}–{p['rep_high']} reps{also_sfx} · {p['rationale']} "
                        f"[{p['citation']}]"
                    )
                    # Legibility line: why this pick is here and its plateau state,
                    # so a repeat is visibly earned (progressing) vs a swap/verify.
                    if "status" in p:
                        last = p.get("last_done") or "never"
                        wk = p.get("weeks", 0)
                        # Tenure and evidence depth are different numbers and were
                        # being conflated: "Nwk data" was read as "has led this head
                        # N weeks" when it only ever meant "has N weeks of e1RM on
                        # record". Both are shown, each labelled for what it is.
                        lines.append(
                            f"        · last {last} · held {p.get('tenure', 0)}wk · "
                            f"{wk}wk e1RM data · {p.get('trend', 'untrained')} · {p['status']}"
                        )
                    prog = p.get("progressibility")
                    if prog and prog.get("coarse"):
                        lines.append(
                            f"        · ⚠ coarse increments: this implement steps "
                            f"{prog['increment_lb']:g} lb (~{prog['pct_of_top']:g}% of top "
                            "load) — progress by REPS across the window; a flat load "
                            "here is the machine's pitch, not a stall"
                        )
            else:
                names = ", ".join(
                    (
                        f"{e['exercise']} (last done {e['last_done']})"
                        if e.get("last_done")
                        else f"{e['exercise']} (never logged — verify equipment exists)"
                    )
                    for e in exs
                )
                lines.append(f"- {muscle} (stalest-first): {names}")

    # Session split (advisory — the validator agent enforces cap + allocation).
    if rx.session_split:
        lines.append(f"\n## RECOMMENDED SESSION SPLIT (≤{PER_SESSION_SET_CAP} sets/muscle/session)")
        for sess in rx.session_split:
            entries = ", ".join(
                f"{e['muscle']} ×{e['sets']}" + ("⚠" if e.get("over_cap") else "")
                for e in sess["muscles"]
            )
            day = sess.get("weekday", "")
            credited = sess.get("credited_muscle_sets", "")
            lines.append(
                f"- **{sess['session']} ({day})** "
                f"[{credited} credited muscle-sets; compounds overlap]: {entries}"
            )

    # Mid-week reflow: what the week still owes, over the sessions actually
    # left. Rendered ABOVE the trainable-today lens because this is the number
    # to build today's session from — the skeleton above is where the week was
    # SUPPOSED to land, this is where it still CAN.
    rw = rx.remaining_week
    if rw.get("sessions") or rw.get("unplaceable"):
        lines.append(
            "\n## REMAINING THIS WEEK (reflowed over the sessions left — "
            "build today from this, not the skeleton)"
        )
        for sess in rw.get("sessions", []):
            entries = ", ".join(
                f"{e['muscle']} ×{e['sets']}" + ("⚠over-cap" if e.get("over_cap") else "")
                for e in sess["muscles"]
            )
            lines.append(
                f"- **{sess['session']} ({sess['weekday']})** "
                f"[{sess['credited_muscle_sets']} muscle-sets remaining]: {entries}"
            )
        for u in rw.get("unplaceable", []):
            star = " ★" if u.get("emphasis") else ""
            lines.append(
                f"- ⚠ **{u['muscle']}{star}**: {u['remaining']} set(s) still owed but no "
                "matching session remains this week — either add them today if gates "
                "allow, or accept the shortfall (it will show in next week's targets)"
            )

    # Trainable-today: the daily lens on top of the weekly skeleton above —
    # what's actually available RIGHT NOW given today's live gates, so a
    # gated day never silently reads as emptier than it really is (the
    # 2026-07-23 "glutes-only" incident: abs/lower_back/forearms had positive
    # targets and were legally trainable but sat on the wrong day-label).
    if daily_state is not None:
        gates = daily_state.get("gates", {}) or {}
        muscle_recovery = (daily_state.get("training_load") or {}).get("muscle_recovery") or {}
        today_rx = trainable_today(rx.muscles, gates, muscle_recovery)
        if today_rx:
            available = [t for t in today_rx if t["status"] == "available"]
            held = [t for t in today_rx if t["status"] == "held"]
            gated = [t for t in today_rx if t["status"] in ("rest_gated", "group_gated")]
            lines.append(
                "\n## TRAINABLE TODAY (daily projection — the split above is the weekly skeleton)"
            )
            if available:
                lines.append(
                    "- **Available**: "
                    + ", ".join(f"{t['muscle']} (target {t['target_sets']})" for t in available)
                )
            if held:
                lines.append(
                    "- **Held** (trainable at current volume, don't add): "
                    + ", ".join(f"{t['muscle']} (target {t['target_sets']})" for t in held)
                )
            if gated:
                lines.append(
                    "- **Gated today**: "
                    + "; ".join(f"{t['muscle']} — {t['detail']}" for t in gated)
                )

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
