"""Snap a prescribed weight onto a load the gym can actually produce.

The planner is an external LLM handed non-round anchors (the DB is kg-native and
every display converts with an inline ``x 2.20462``), and it returns
``weight_lbs`` as an unconstrained float that nothing validated. Audited over the
last 25 stored plans, **53 of 144 weighted prescriptions landed BETWEEN two
weights Rob has actually used** — not beyond his max, in a physical gap: a 235 lb
Hip Thrust on a machine that only offers 230 and 270, a 430 lb Standing Calf
Raise between 400 and 495.

There is no equipment table to consult and inventing one would be fabrication.
**The logged history IS the ground truth for each implement's real increment** —
machine pitch varies wildly (Hip Thrust steps by 40, Leg Extension by 5) so a
blanket "round to 5 lb" is wrong for most of them.

Two scoping rules make that evidence mean the right thing:

* **A dumbbell rack is gym-wide; a machine stack is per-machine.** Dumbbell
  grids therefore POOL across every dumbbell lift Rob logs, while machine, cable
  and barbell grids stay per-exercise. Scoping dumbbells per-exercise reads a
  thin history as a coarse rack and cuts hard for no reason — ``Shrug
  (Dumbbell)`` at 70 lb has only 60 in its own history (a -14.3% cut) while 70 lb
  dumbbells are plainly on the rack, used on other movements.
* **Everything is measured PER HAND**, through
  :func:`shc.training.load_mechanics.per_hand_kg` — the same choke point
  invariant 19 routes every e1RM through. A plan's ``weight_lbs`` is already the
  per-hand number for per-hand lifts (that is the unit the WORKING WEIGHTS block
  and the coherence check both speak), so the grid must be too. Rows that imply
  an impossible one-hand load are dropped via
  :func:`~shc.training.load_mechanics.exceeds_per_hand_max`, which keeps the
  known-contaminated pre-2026 dumbbell history (Shrugs logged up to 220 as
  two-dumbbell totals) from injecting phantom 220 lb dumbbells into the rack.

Snapping is deliberately NOT a validator. A 409 on a non-round number would
block a plan for a cosmetic cause; snapping is fail-safe and simply corrects it.
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field

from shc.training.load_mechanics import (
    LoadType,
    classify_load,
    exceeds_per_hand_max,
    per_hand_kg,
)

log = logging.getLogger(__name__)

_LB_PER_KG = 2.20462

_CLUSTER_TOL_LB = 1.0
"""Two logged values this close are the SAME physical notch, recorded twice.

The DB is kg-native, so lb values carry round-trip junk: the cable grid holds
both 132.0 and 132.3 (= 60 kg), the dumbbell rack 33.1 (= 15 kg) beside a clean
32.5. Without clustering the snapper emits ``132 -> 132.3``, which is noise
wearing a fix's clothing.
"""

_TRIVIAL_LB = 0.25
"""Below this the snap is not worth making, let alone reporting."""

_NOTABLE_MOVE_PCT = 2.0
"""A snap past this much of the asked load is logged at WARNING, not DEBUG.

"Fail visibly, not silently" — a 0.5 lb tidy-up is bookkeeping, a 5% cut is a
different set than the planner asked for and Rob should be able to see why.
"""

_SPARSE_GRID_MIN = 3
"""Fewer distinct notches than this is not an increment, it is an anecdote."""

_MIN_SETS_TO_PROVE_A_GAP = 10
"""Logged sets an exercise needs before its grid may argue a weight does NOT exist.

The asymmetry is the whole point: a logged value PROVES that notch is loadable,
but a missing value only proves Rob never chose it. Below ~10 sets an exercise
has been done two or three sessions — two or three load choices — which cannot
establish a stack's pitch. Trusting it anyway produced the sparse-history cut
this module's dumbbell pooling exists to avoid, in machine form: ``Crunch
(Machine)`` has 9 sets at 60/80/115, and snapping a prescribed 70 down to 60 is a
**-14.3%** move justified by nothing. Above the threshold the evidence is real
and the gaps bite correctly — ``Standing Calf Raise (Machine)`` (24 sets,
360/400/495) genuinely has no 430.
"""

# Per-implement fallback increments, used ONLY where the logged history is too
# thin to speak for itself. Inferred from the exercise NAME, mirroring what
# `load_mechanics.classify_load` and `exercise_classifier` already do — this
# module invents no equipment metadata. Values are the smallest plausible step
# for each class, because a smaller step snaps a shorter distance and this
# fallback fires exactly where the evidence is weakest.
_FALLBACK_STEP_LB = {
    "dumbbell": 5.0,  # rack pitch above ~25 lb; 2.5 below, so 5 is the safe read
    "machine": 5.0,  # pin stacks vary 5-40; 5 moves least when we cannot tell
    "cable": 5.0,
    "barbell": 5.0,  # a pair of 2.5 lb plates
}

_DUMBBELL_TYPES = frozenset({LoadType.DUMBBELL_PAIR, LoadType.DUMBBELL_SINGLE})


@dataclass(frozen=True)
class Snap:
    """The result of snapping one prescribed weight onto a loadable notch."""

    exercise: str
    weight_lbs: float
    original_lbs: float
    reason: str

    @property
    def moved(self) -> bool:
        """True when the snap actually changed the load by a non-trivial amount."""
        return abs(self.weight_lbs - self.original_lbs) > _TRIVIAL_LB

    @property
    def delta_pct(self) -> float:
        """Signed change as a percentage of the asked load (0.0 when asked <= 0)."""
        if self.original_lbs <= 0:
            return 0.0
        return (self.weight_lbs - self.original_lbs) / self.original_lbs * 100.0


def _implement(name: str) -> str:
    """Coarse implement class for the sparse-grid fallback, inferred from the name."""
    lt = classify_load(name)
    if lt in _DUMBBELL_TYPES:
        return "dumbbell"
    n = name.lower()
    if "cable" in n or "crossover" in n or "pulldown" in n or "pushdown" in n:
        return "cable"
    if "machine" in n or "smith" in n or "hammerstrength" in n or "press (plate" in n:
        return "machine"
    return "barbell"


def _roundness(v: float) -> int:
    """Rank how "round" a pound value looks — lower is rounder (5s < 2.5s < 1s)."""
    for rank, step in enumerate((5.0, 2.5, 1.0)):
        if abs(v / step - round(v / step)) < 1e-6:
            return rank
    return 3


def _cluster(values: set[float]) -> list[float]:
    """Collapse near-duplicate kg round-trip artifacts to one round representative."""
    out: list[float] = []
    group: list[float] = []
    for v in sorted(values):
        if group and v - group[0] > _CLUSTER_TOL_LB:
            out.append(min(group, key=lambda x: (_roundness(x), x)))
            group = []
        group.append(v)
    if group:
        out.append(min(group, key=lambda x: (_roundness(x), x)))
    return out


def _dominant_step(grid: list[float]) -> float | None:
    """Most common gap between adjacent notches; ties resolve to the SMALLER gap."""
    gaps = [round(b - a, 1) for a, b in zip(grid, grid[1:], strict=False) if b - a > _TRIVIAL_LB]
    if not gaps:
        return None
    counts = Counter(gaps)
    top = max(counts.values())
    return min(g for g, c in counts.items() if c == top)


@dataclass(frozen=True)
class LoadableGrids:
    """Every loadable notch Rob's logs prove exists, indexed for snapping.

    Built once per call-path with a single query — see :func:`build_grids`.
    """

    by_exercise: dict[str, list[float]]
    set_counts: dict[str, int]
    dumbbell_rack: list[float]
    rack_sets: int
    _canon: dict[str, str]
    # exercise key -> (increment_lb, anchor_lb), from `equipment_increment`.
    overrides: dict[str, tuple[float, float]] = field(default_factory=dict)

    def _override(self, name: str) -> tuple[float, float] | None:
        """Declared (increment, anchor) for ``name``, if a human recorded one."""
        key = name.strip().lower()
        if key in self.overrides:
            return self.overrides[key]
        return self.overrides.get(_strip_suffix(key))

    def _resolve(self, name: str) -> str | None:
        """Map a plan's exercise name to the key its logged history is stored under."""
        key = name.strip().lower()
        if key in self.by_exercise:
            return key
        # Fall back to the equipment-suffix-stripped name, the same canonicalisation
        # `workout_sets_dedup` uses, so a plan naming "Leg Extension" still finds
        # the "Leg Extension (Machine)" history it was anchored on.
        return self._canon.get(_strip_suffix(key))

    def for_exercise(self, name: str) -> list[float]:
        """Loadable pound values for ``name`` — pooled for dumbbells, per-lift otherwise."""
        if classify_load(name) in _DUMBBELL_TYPES:
            return self.dumbbell_rack
        key = self._resolve(name)
        return self.by_exercise.get(key, []) if key else []

    def proves_gaps(self, name: str) -> bool:
        """Whether ``name`` has enough logged sets for a MISSING value to mean anything.

        See :data:`_MIN_SETS_TO_PROVE_A_GAP` — a present value always proves a
        notch exists, but an absent one only proves absence on a well-sampled lift.
        """
        if classify_load(name) in _DUMBBELL_TYPES:
            return self.rack_sets >= _MIN_SETS_TO_PROVE_A_GAP
        key = self._resolve(name)
        return bool(key) and self.set_counts.get(key, 0) >= _MIN_SETS_TO_PROVE_A_GAP

    def snap(self, name: str, lbs: float) -> Snap:
        """Snap ``lbs`` onto the nearest notch this exercise can actually be loaded to.

        Four cases, each chosen for its failure mode rather than its symmetry:

        * **Between two logged notches** — the error this module exists for. Snap
          to the nearer; on an exact tie snap DOWN, so a rounding decision never
          silently makes a set heavier than the planner asked for.
        * **Above the highest logged value** — legitimate progression, never
          clamped back down. The grid's dominant step is extended upward and the
          ask snaps onto that lattice, so beating a personal best stays possible.
        * **Below the lowest logged value** — returned UNCHANGED. Snapping up is
          the one direction that can turn a deload into a harder set (a reference
          implementation that snapped to the nearest notch produced ``Seated
          Incline Curl 20 -> 25``, +25%, on a day the intent was to back off),
          and extrapolating down would invent notches below a pin stack's base
          that no evidence supports.
        * **Sparse or thinly-evidenced history** — under :data:`_SPARSE_GRID_MIN`
          distinct notches, or under :data:`_MIN_SETS_TO_PROVE_A_GAP` logged sets,
          the grid may not argue that a weight is absent, so a name-inferred
          per-implement default increment applies instead. With no history at all
          the ask is returned untouched and reported as ``no-history``, which is
          also an equipment-availability signal (an exercise Rob has never logged
          may not exist at his gym).
        """
        if lbs <= 0:
            return Snap(name, lbs, lbs, "bodyweight")
        ov = self._override(name)
        if ov:
            step, anchor = ov
            return Snap(name, _lattice(lbs, anchor, step), lbs, f"declared(step {step:g})")
        grid = self.for_exercise(name)
        if not grid:
            return Snap(name, lbs, lbs, "no-history")
        if len(grid) < _SPARSE_GRID_MIN or not self.proves_gaps(name):
            step = _FALLBACK_STEP_LB[_implement(name)]
            return Snap(name, _snap_to_step(lbs, step), lbs, f"thin-history(step {step:g})")

        below = [v for v in grid if v <= lbs + _TRIVIAL_LB]
        above = [v for v in grid if v >= lbs - _TRIVIAL_LB]
        if below and above and below[-1] == above[0]:
            return Snap(name, below[-1], lbs, "on-grid")
        if not below:
            return Snap(name, lbs, lbs, "below-min")
        if not above:
            step = _dominant_step(grid) or _FALLBACK_STEP_LB[_implement(name)]
            top = grid[-1]
            return Snap(name, top + _snap_to_step(lbs - top, step), lbs, "above-max(progression)")
        lo, hi = below[-1], above[0]
        # Ties go DOWN: never silently heavier than asked.
        snapped = lo if (lbs - lo) <= (hi - lbs) else hi
        return Snap(name, snapped, lbs, "between-notches")

    def snap_down(self, name: str, lbs: float) -> float:
        """Highest loadable notch at or below ``lbs`` — for CEILINGS, which may never round up.

        The nearest-notch rule in :meth:`snap` is wrong for a bound: a ceiling
        rounded up to the next notch is no longer a ceiling. Used where the number
        handed to the planner is a limit rather than a target.
        """
        if lbs <= 0:
            return lbs
        ov = self._override(name)
        if ov:
            step, anchor = ov
            return _lattice(lbs, anchor, step, mode="down")
        grid = self.for_exercise(name)
        if not grid:
            return lbs
        if len(grid) < _SPARSE_GRID_MIN or not self.proves_gaps(name):
            step = _FALLBACK_STEP_LB[_implement(name)]
            return round((lbs // step) * step, 1)
        below = [v for v in grid if v <= lbs + _TRIVIAL_LB]
        if below:
            return below[-1]
        # Under everything ever logged: no evidence for a lower notch, so leave the
        # bound where it is rather than invent one (see `snap`'s below-min case).
        return lbs

    def snap_up(self, name: str, lbs: float) -> float:
        """Lowest loadable notch at or above ``lbs`` — for a suggested TARGET load.

        The mirror of :meth:`snap_down`. Used where rounding the other way would
        walk the suggestion back into the very rejection it is trying to resolve.
        """
        if lbs <= 0:
            return lbs
        ov = self._override(name)
        if ov:
            step, anchor = ov
            return _lattice(lbs, anchor, step, mode="up")
        grid = self.for_exercise(name)
        if not grid:
            return lbs
        if len(grid) < _SPARSE_GRID_MIN or not self.proves_gaps(name):
            step = _FALLBACK_STEP_LB[_implement(name)]
            return round(-((-lbs) // step) * step, 1)
        above = [v for v in grid if v >= lbs - _TRIVIAL_LB]
        if above:
            return above[0]
        step = _dominant_step(grid) or _FALLBACK_STEP_LB[_implement(name)]
        top = grid[-1]
        return round(top + -((-(lbs - top)) // step) * step, 1)


def _lattice(lbs: float, anchor: float, step: float, mode: str = "nearest") -> float:
    """Snap onto the declared lattice ``anchor + k*step`` (k may be negative).

    ``anchor`` carries the PHASE that ``step`` alone cannot: a plate-loaded
    carriage weighs an unknown amount, so "a multiple of 20" is wrong while
    "230 plus multiples of 20" is right. Ties resolve downward, matching
    :meth:`LoadableGrids.snap` — a rounding decision never silently makes a set
    heavier than asked.
    """
    n = (lbs - anchor) / step
    floor_n = int(n // 1)
    if mode == "down":
        k = floor_n
    elif mode == "up":
        k = floor_n if abs(n - floor_n) < 1e-9 else floor_n + 1
    else:
        k = floor_n + (1 if (n - floor_n) > 0.5 else 0)
    return round(anchor + k * step, 1)


def _snap_to_step(lbs: float, step: float) -> float:
    """Round to the nearest multiple of ``step``, resolving an exact tie downward."""
    n = lbs / step
    floor_n = int(n // 1)
    frac = n - floor_n
    return round((floor_n + (1 if frac > 0.5 else 0)) * step, 1)


def _strip_suffix(name: str) -> str:
    """Drop a trailing ``(Machine)``-style equipment suffix, as ``workout_sets_dedup`` does."""
    import re

    return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()


def build_grids(conn) -> LoadableGrids:
    """Read every logged load once and index it into per-hand loadable grids."""
    rows = conn.execute(
        """
        SELECT ws.exercise, ws.weight_kg, ws.started_at::DATE AS logged_on
        FROM workout_sets_dedup ws
        WHERE ws.weight_kg IS NOT NULL AND ws.weight_kg > 0
        """
    ).fetchall()

    raw: dict[str, set[float]] = {}
    counts: dict[str, int] = {}
    rack: set[float] = set()
    rack_sets = 0
    for ex, wkg, logged_on in rows:
        # Pass the log date. The per-hand convention for the `_LOGGED_AS_COMBINED`
        # lifts changed on 2026-07-23 (invariant 19), and both the halving and the
        # impossible-load bound below read wrong without it.
        if exceeds_per_hand_max(ex, float(wkg), logged_on):
            continue
        lb = round(per_hand_kg(ex, float(wkg), logged_on) * _LB_PER_KG, 1)
        key = ex.strip().lower()
        raw.setdefault(key, set()).add(lb)
        counts[key] = counts.get(key, 0) + 1
        if classify_load(ex) in _DUMBBELL_TYPES:
            rack.add(lb)
            rack_sets += 1

    by_exercise = {k: _cluster(v) for k, v in raw.items()}
    canon: dict[str, str] = {}
    for key in by_exercise:
        canon.setdefault(_strip_suffix(key), key)

    try:
        for canonical, logged in conn.execute(
            "SELECT canonical_name, logged_name FROM exercise_alias"
        ).fetchall():
            lk, ck = str(logged).strip().lower(), str(canonical).strip().lower()
            if lk in by_exercise and ck not in by_exercise:
                by_exercise[ck] = by_exercise[lk]
                counts[ck] = counts.get(lk, 0)
    except Exception as exc:  # table may not exist on an older schema
        log.debug("exercise_alias unavailable for loadable grids: %s", exc)

    # Declared equipment facts (migration 0088). These OUTRANK the inferred grid:
    # `proves_gaps` correctly refuses to argue a weight is absent on a thinly
    # logged lift, which leaves exactly the cases a human has to answer.
    overrides: dict[str, tuple[float, float]] = {}
    try:
        for name, inc, anchor in conn.execute(
            "SELECT exercise_name, increment_lb, anchor_lb FROM equipment_increment"
        ).fetchall():
            if inc and float(inc) > 0:
                overrides[str(name).strip().lower()] = (float(inc), float(anchor))
    except Exception as exc:  # table absent on an older schema
        log.debug("equipment_increment unavailable for loadable grids: %s", exc)

    return LoadableGrids(
        by_exercise=by_exercise,
        set_counts=counts,
        dumbbell_rack=_cluster(rack),
        rack_sets=rack_sets,
        _canon=canon,
        overrides=overrides,
    )


def loadable_grid(conn, exercise: str) -> list[float]:
    """Distinct loadable pound values for ``exercise``, ascending (per-hand)."""
    return build_grids(conn).for_exercise(exercise)


def snap_to_loadable(conn, exercise: str, lbs: float) -> float:
    """Snap ``lbs`` to a load ``exercise`` can actually be set to — see :meth:`LoadableGrids.snap`."""
    return build_grids(conn).snap(exercise, lbs).weight_lbs


def snap_plan_weights(conn, plan: dict) -> list[Snap]:
    """Snap every ``weight_lbs`` in ``plan`` in place; return the snaps that moved.

    One grid build for the whole plan. Each moved exercise gains a ``snapped``
    note so the change is visible in the stored plan, not just in the log.
    """
    grids = build_grids(conn)
    moved: list[Snap] = []
    for block in plan.get("blocks") or []:
        for ex in block.get("exercises") or []:
            name = ex.get("name")
            w = ex.get("weight_lbs")
            if not name or not isinstance(w, (int, float)) or isinstance(w, bool):
                continue
            snap = grids.snap(name, float(w))
            if not snap.moved:
                continue
            ex["weight_lbs"] = snap.weight_lbs
            ex["snapped"] = {
                "from_lbs": snap.original_lbs,
                "reason": snap.reason,
            }
            moved.append(snap)
            emit = log.warning if abs(snap.delta_pct) >= _NOTABLE_MOVE_PCT else log.info
            emit(
                "loadable snap: %s %.4g -> %.4g lb (%+.1f%%, %s)",
                name,
                snap.original_lbs,
                snap.weight_lbs,
                snap.delta_pct,
                snap.reason,
            )
    return moved
