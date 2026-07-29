from __future__ import annotations

import datetime as _dt

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

# The narrow, EVIDENCE-BASED inverse of the per-hand default: exercises Rob
# enters as the COMBINED weight of both dumbbells, verified case-by-case against
# his own numbers. These halve to per-hand. Everything else is per-hand as logged
# (Hevy's default). Confirmed 2026-07-12: Romanian Deadlift (Dumbbell) 150 = 75
# each hand (his progression reads 15→20→30→45→75/hand; 150 lb dumbbells don't
# exist). Match is exact (lower-cased) so "Single Leg Romanian Deadlift (Dumbbell)"
# — logged per-hand with one bell — is NOT caught.
_LOGGED_AS_COMBINED = frozenset(
    {
        "romanian deadlift (dumbbell)",
    }
)

COMBINED_LOGGING_ENDED = _dt.date(2026, 7, 23)
"""The date Rob switched from logging RDL as a two-dumbbell TOTAL to per-hand.

A single exercise name carried two conventions, and nothing recorded the switch,
so the halving rule kept firing after it stopped being true. The engine read a
logged 75 as 37.5/hand and a logged 70 as 35 — against a genuine 75/hand through
June — and reported a **-50% e1RM regression** that is not a strength loss at
all. That false regression sets `deload_required` directly once the 9-day
post-deload cooldown lapses (`metrics.py`), i.e. it was on course to drop a
brand-new accumulation block straight back into deload.

Evidence for the boundary, from the full logged history:

    2026-05-29   90, 60   -> combined (45 / 30 per hand)
    2026-06-11   150      -> MUST be combined; 150/hand exceeds the confirmed
    2026-06-14   150         105 lb one-hand max, so per-hand is impossible
    2026-07-23   75       -> per-hand
    2026-07-26   70       -> per-hand (the plan that day read "70 lb EACH HAND")

Read as combined throughout, the series runs 45 -> 75 -> 37.5, a 50% collapse
with no corresponding change in programming. Read with the switch applied it
runs 45 -> 75 -> 75 -> 70 — flat, which is what a deload week should look like.
Only the second reading is coherent.

A VALUE-based rule (halve anything implying more than the per-hand max) was
considered and rejected: it fixes June but silently breaks May, where a logged
90 is a combined 45/hand and sits well under the max.
"""

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


def _was_combined(logged_on: _dt.date | None) -> bool:
    """Whether a set logged on this date used the two-dumbbell-total convention.

    ``None`` means the caller has no date, and resolves to the CURRENT convention
    (per-hand, no halving). That default is chosen for its failure mode, not its
    convenience: mis-reading an old combined row as per-hand yields a value above
    the 105 lb one-hand maximum, which `exceeds_per_hand_max` catches loudly,
    whereas mis-reading a new per-hand row as combined halves it silently and
    manufactures the phantom regression this whole rule exists to stop. Prefer a
    visible wrong number over an invisible one.
    """
    return logged_on is not None and logged_on < COMBINED_LOGGING_ENDED


def per_hand_kg(name: str, logged_kg: float, logged_on: _dt.date | None = None) -> float:
    """Return the load in ONE hand for a logged weight (kg).

    Hevy logs the weight of a single implement, so the logged weight already IS
    the per-hand load — the identity — EXCEPT for the verified handful in
    :data:`_LOGGED_AS_COMBINED` that Rob enters as a two-dumbbell total, which
    halve. This is the single choke point every e1RM / ceiling / prescription
    path routes through.
    """
    if name.strip().lower() in _LOGGED_AS_COMBINED and _was_combined(logged_on):
        return logged_kg / 2.0
    return logged_kg


def per_hand_sql(
    column: str = "weight_kg",
    exercise_col: str = "exercise",
    date_col: str | None = None,
) -> str:
    """SQL expression form of :func:`per_hand_kg` — the identity except for the
    verified :data:`_LOGGED_AS_COMBINED` handful, which halve.

    Every progression/trend query that aggregates in SQL (rather than reading
    rows back into Python and calling :func:`per_hand_kg`) routes through this
    so the same single choke point governs both paths — a query that skips it
    silently mixes per-hand and combined-total units into one e1RM/tonnage series.
    """
    names = ", ".join(f"'{n}'" for n in sorted(_LOGGED_AS_COMBINED))
    # Pass `date_col` wherever the query has a date. Without it the expression
    # resolves to the CURRENT (per-hand) convention, matching `_was_combined`'s
    # no-date default — see that helper for why the failure modes are asymmetric.
    when = f"lower(trim({exercise_col})) IN ({names})"
    if date_col:
        when += f" AND {date_col} < DATE '{COMBINED_LOGGING_ENDED.isoformat()}'"
    else:
        when = "FALSE AND " + when
    return f"CASE WHEN {when} THEN {column} / 2.0 ELSE {column} END"


EPLEY_REP_CAP = 12
"""Epley overestimates above ~10-12 reps, so reps feeding it are capped here."""

MAX_RIR_CREDIT = 3
"""Most reps-in-reserve an RPE log may add back before the set stops being a
usable 1RM anchor. An RPE 6 set has ~4 RIR, but extrapolating four reps past
what was actually performed is estimation, not measurement — and this number
feeds a SAFETY ceiling, so it is deliberately clamped short of the full scale."""


def effective_reps_sql(reps_col: str = "reps", rpe_col: str = "rpe") -> str:
    """SQL for RIR-adjusted reps — what the set WOULD have reached at failure.

    Epley assumes the input set was taken to failure. Rob's are not: his best
    logged sets sit at RPE 7-8, i.e. 2-3 reps in reserve. Feeding those raw
    understates e1RM, and because the day's load ceiling is a percentage OF that
    e1RM, the understatement compounds — a MODERATE day's 90% cap was landing at
    roughly 64% of what he had just lifted at RPE 8 (Leg Extension: did 200x10
    @RPE 8 on 2026-07-23, prescribed 175x10 three days later at the same target
    RPE). The plan claimed an effort the load could not deliver.

    ``effective_reps = LEAST(reps + clamp(10 - rpe, 0, MAX_RIR_CREDIT), 12)``

    Three deliberate guards, all one-directional:

    * **A missing RPE adds nothing.** ~87% of logged history predates RPE
      logging; NULL coalesces to 0 credit, so those sets score exactly as they
      did before. Under no circumstance is an RIR assumed.
    * **RIR credit is capped at 3** (:data:`MAX_RIR_CREDIT`), so a very easy set
      cannot extrapolate far past what was performed.
    * **The 12-rep Epley cap applies to the ADJUSTED value**, not before it.
      Capping first would let a 12-rep RPE-7 set score as 15 effective reps,
      deep into the range where Epley's overestimate is the known failure mode.
      Net effect is bounded at roughly +5%.

    This raises a SAFETY ceiling, which is why every guard errs downward: the
    ceiling exists to stop a "deload" being a max attempt.
    """
    # The NULL check is an explicit CASE, NOT COALESCE around LEAST/GREATEST:
    # DuckDB's LEAST/GREATEST IGNORE null arguments rather than propagating
    # them, so `LEAST(10 - NULL, 3)` returns 3, not NULL. Wrapping that in
    # COALESCE therefore never fires, and every RPE-less set — ~87% of logged
    # history — would silently receive the FULL 3-rep credit and inflate the
    # load ceiling it feeds. Caught by
    # `test_missing_rpe_scores_exactly_as_before`; do not "simplify" this back.
    rir = (
        f"CASE WHEN {rpe_col} IS NULL THEN 0 "
        f"ELSE GREATEST(LEAST(10 - {rpe_col}, {MAX_RIR_CREDIT}), 0) END"
    )
    return f"LEAST({reps_col} + ({rir}), {EPLEY_REP_CAP})"


def load_unit_label(name: str) -> str:
    """``'each hand'`` for per-hand lifts, ``''`` for bilateral single-implement lifts."""
    return "each hand" if is_per_hand(name) else ""


MAX_PER_HAND_LB = 105.0
"""Rob's confirmed maximum load in ONE hand (2026-07-18).

A hard physical bound, not a training target: no per-hand lift can legitimately
exceed it, so a set that does is a mis-entry. Deliberately NOT applied to
bilateral lifts, where the logged number is a whole-implement load — Standing
Calf Raise at 495 lb is real.
"""

_LB_PER_KG = 2.20462


def exceeds_per_hand_max(
    name: str, logged_kg: float | None, logged_on: _dt.date | None = None
) -> bool:
    """True when a logged set implies an impossible load in one hand.

    Routes through :func:`per_hand_kg` rather than testing the raw logged weight,
    so the lifts Rob enters as a two-dumbbell total are halved before the bound
    is applied. Comparing the raw value instead is what made migration 0071
    quarantine six legitimate 150 lb (= 75 lb/hand) Romanian Deadlift sets.

    Pass ``logged_on``: the combined-vs-per-hand convention changed on
    :data:`COMBINED_LOGGING_ENDED`, and without a date a pre-switch 150 lb
    (= 75/hand) set reads as 150 in one hand and gets quarantined — re-creating
    migration 0071's exact mistake through a different door.
    """
    if logged_kg is None or not is_per_hand(name):
        return False
    return per_hand_kg(name, logged_kg, logged_on) * _LB_PER_KG > MAX_PER_HAND_LB
