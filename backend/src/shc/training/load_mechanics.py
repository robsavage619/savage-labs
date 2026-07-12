from __future__ import annotations

"""Exercise load mechanics — how a logged weight maps to per-limb load.

Hevy logs two-implement lifts (a dumbbell in each hand, a cable stack per hand)
as the weight of a SINGLE implement — one 20 lb dumbbell is logged "20", not
"40". So the logged weight IS already the per-hand load; there is nothing to
halve. This module's job is therefore only to *label* the number correctly
("20 lb each hand" vs a bilateral "185 lb") so e1RM, load ceilings, and
prescriptions all read in the same, honest unit.

History: this module previously ASSUMED Rob logged the combined weight and
halved every dumbbell/crossover lift. That was wrong for Hevy's per-hand logging
and silently corrupted the load ceiling — e.g. a real 20 lb lateral raise
(logged 20, done at RPE 7) was halved to a phantom "10 lb each hand", dropping
its e1RM from 28 to 14 and prescribing an absurd 7.5 lb. The e1RM basis is
already Hevy-only (``e1rm_by_exercise`` filters ``source = 'hevy'``), so the
logged number needs no conversion. Physically-impossible values that survive
(e.g. a "150 lb Romanian Deadlift (Dumbbell)" — no such dumbbell exists) are
DATA artifacts to correct at the source, not a reason to halve clean logs.

The classifier stays name-based and deterministic, mirroring
:mod:`shc.training.exercise_classifier`, and is now used purely for the per-hand
LABEL, not for any weight math.
"""

from enum import StrEnum


class LoadType(StrEnum):
    """How a logged weight relates to the load in one hand."""

    DUMBBELL_PAIR = "dumbbell_pair"  # a dumbbell in each hand — logged per-hand
    DUMBBELL_SINGLE = "dumbbell_single"  # one dumbbell, one hand — logged per-hand
    CABLE_PAIR = "cable_pair"  # a stack per hand (crossover) — logged per-hand
    CABLE_SINGLE = "cable_single"  # one stack, one hand — logged per-hand
    BILATERAL = "bilateral"  # barbell / machine / single-stack cable / bodyweight


# Lifts where each hand bears its own implement — the load reads "per hand", so
# the plan/table labels it as such. (Hevy already logs the per-hand number, so
# this drives the LABEL only, not any halving.)
_PER_HAND = frozenset(
    {
        LoadType.DUMBBELL_PAIR,
        LoadType.DUMBBELL_SINGLE,
        LoadType.CABLE_PAIR,
        LoadType.CABLE_SINGLE,
    }
)

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

# Movements that are essentially ALWAYS a dumbbell lift when they arrive here
# un-suffixed (e.g. the Fitbod-imported "Hammer Curls", which lacks the
# "(Dumbbell)" tag Hevy adds). Cable/machine/barbell variants name their
# equipment and are caught by the keyword branches above first.
_DUMBBELL_DEFAULT_MOVEMENTS = (
    "hammer curl",
    "zottman",
    "arnold press",
)


def classify_load(name: str) -> LoadType:
    """Classify how ``name``'s logged weight maps to per-hand load.

    Deterministic and name-based. Used for the per-hand *label* only — Hevy logs
    the per-hand number directly, so no variant implies a weight conversion. A
    single-arm variant must say so in its name (``single arm`` / ``one arm`` /…).
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
        # stack weight is the load, read bilaterally.
        return LoadType.CABLE_SINGLE if single else LoadType.BILATERAL
    if any(m in n for m in _DUMBBELL_DEFAULT_MOVEMENTS):
        return LoadType.DUMBBELL_SINGLE if single else LoadType.DUMBBELL_PAIR
    return LoadType.BILATERAL


def is_per_hand(name: str) -> bool:
    """True when the load should be read/labelled per hand (not bilateral)."""
    return classify_load(name) in _PER_HAND


def per_hand_kg(name: str, logged_kg: float) -> float:
    """Return the load in ONE hand for a logged weight (kg).

    Hevy logs the weight of a single implement, so the logged weight already IS
    the per-hand load — this is the identity. Kept as the single choke point that
    every e1RM / ceiling / prescription path routes through, so if a future data
    source ever logs a combined weight, the conversion lands here and nowhere
    else. ``name`` is retained for that forward-compatibility.
    """
    return logged_kg


def load_unit_label(name: str) -> str:
    """``'each hand'`` for per-hand lifts, ``''`` for bilateral single-implement lifts."""
    return "each hand" if is_per_hand(name) else ""
