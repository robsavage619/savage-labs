from __future__ import annotations

"""Exercise load mechanics — how a logged weight maps to per-limb load.

Rob logs two-implement lifts (a dumbbell in each hand, a cable stack per hand)
as the COMBINED weight, but he actually loads — and the science reasons — in
PER-HAND terms. A 120 lb "Hammer Curl (Dumbbell)" is 60 lb in each hand; a
198 lb "Dumbbell Bench Press" is ~99 lb per hand. This module is the single
source of truth for that mapping: given an exercise name and its logged weight,
it returns the per-hand load and a human label, so e1RM, load ceilings, and
prescriptions all speak ONE unit.

Getting this wrong is what put a "95 lb each hand" hammer curl in front of Rob:
a per-hand target read against a total-load e1RM. The classifier is deterministic
and name-based, mirroring :mod:`shc.training.exercise_classifier`. Rules are
specific-before-generic; single-arm variants must name themselves.
"""

from enum import StrEnum


class LoadType(StrEnum):
    """How a logged weight relates to the load in one hand."""

    DUMBBELL_PAIR = "dumbbell_pair"  # two DBs, logged as the combined total → ÷2
    DUMBBELL_SINGLE = "dumbbell_single"  # one DB in one hand → already per-hand
    CABLE_PAIR = "cable_pair"  # two stacks (crossover), logged total → ÷2
    CABLE_SINGLE = "cable_single"  # one stack, one hand → already per-hand
    BILATERAL = "bilateral"  # barbell / machine / single-stack cable / bodyweight → as-is


# Lifts where each hand bears its own implement — the meaningful load reads
# "per hand", so the plan/table should label it and prescribe the per-hand number.
_PER_HAND = frozenset(
    {
        LoadType.DUMBBELL_PAIR,
        LoadType.DUMBBELL_SINGLE,
        LoadType.CABLE_PAIR,
        LoadType.CABLE_SINGLE,
    }
)
# Lifts Rob logs as the COMBINED weight of TWO implements — halve to get per-hand.
_TOTAL_OF_TWO = frozenset({LoadType.DUMBBELL_PAIR, LoadType.CABLE_PAIR})

_SINGLE_ARM_KEYS = (
    "single arm",
    "single-arm",
    "one arm",
    "one-arm",
    "1 arm",
    "1-arm",
    "single handed",
    "single-handed",
)

# Movements that are essentially ALWAYS a dumbbell pair when they arrive here
# un-suffixed (e.g. the Fitbod-imported "Hammer Curls", 1500+ logged sets, which
# lacks the "(Dumbbell)" tag Hevy adds). Cable/machine/barbell variants name
# their equipment and are caught by the keyword branches above before this, so a
# name reaching this layer with one of these patterns is the free-weight version.
_DUMBBELL_DEFAULT_MOVEMENTS = (
    "hammer curl",
    "zottman",
    "arnold press",
)


def classify_load(name: str) -> LoadType:
    """Classify how ``name``'s logged weight maps to per-hand load.

    Deterministic and name-based. A single-arm variant must say so in its name
    (``single arm`` / ``one arm`` / …); an unqualified dumbbell/crossover is
    assumed to be the two-implement version, matching Rob's total-load logging.
    """
    n = name.lower()
    single = any(k in n for k in _SINGLE_ARM_KEYS)

    # Concentration curl is inherently a one-arm dumbbell movement.
    if "concentration" in n:
        return LoadType.DUMBBELL_SINGLE
    if "dumbbell" in n or "(db)" in n or n.startswith("db ") or " db " in n:
        return LoadType.DUMBBELL_SINGLE if single else LoadType.DUMBBELL_PAIR
    # Two-stack cable movements: crossovers and cable/pec flyes run a stack per
    # hand. A pec-deck machine says "machine"/"pec deck" and is caught below.
    if "crossover" in n or ("cable" in n and "fly" in n and "machine" not in n):
        return LoadType.CABLE_SINGLE if single else LoadType.CABLE_PAIR
    if "cable" in n:
        # A single-stack cable movement (pushdown, pulldown, straight-bar curl,
        # seated row, rope curl) is ONE implement pulled with both hands — the
        # stack weight is the load, not a per-hand figure.
        return LoadType.CABLE_SINGLE if single else LoadType.BILATERAL
    # Un-suffixed free-weight movements that are always a dumbbell pair. Reached
    # only after the equipment-keyword branches, so a cable/machine variant has
    # already returned; halving here is also the safe direction on an ambiguous
    # name (a too-low ceiling can't prescribe an unsafe load).
    if any(m in n for m in _DUMBBELL_DEFAULT_MOVEMENTS):
        return LoadType.DUMBBELL_SINGLE if single else LoadType.DUMBBELL_PAIR
    return LoadType.BILATERAL


def is_per_hand(name: str) -> bool:
    """True when the load should be read/prescribed per hand (not combined)."""
    return classify_load(name) in _PER_HAND


def per_hand_kg(name: str, logged_kg: float) -> float:
    """Convert a logged weight (kg) to the load in ONE hand.

    Halves two-implement lifts Rob logs as a combined total (dumbbell pairs,
    cable crossovers); everything else is returned unchanged.
    """
    return logged_kg / 2.0 if classify_load(name) in _TOTAL_OF_TWO else logged_kg


def load_unit_label(name: str) -> str:
    """``'each hand'`` for per-hand lifts, ``''`` for bilateral single-implement lifts."""
    return "each hand" if is_per_hand(name) else ""
