"""Session design: which day it is, what it is for, and what goes first.

The weekly engine decides the dose (sets per muscle per week). Nothing used to
decide the session: a fresh planner composed every day from scratch, so the day
type was renamed daily ("Upper-A", "Full Body", "Upper Pull + Arms") and an
isolation often opened the session ahead of the compound it should follow. This
module is the structure those plans are now validated against.

* Four days rotate by sessions actually EXECUTED, not by weekday, because Rob
  trains 3-4 times a week on shifting days. Region alternates upper/lower; A/B
  alternates within a region. A missed day does not skip a template.
* A days are load days (the anchor runs in the heavy half of its evidence rep
  window), B days are volume days (light half). Both stay inside the hypertrophy
  windows `exercise_science` already enforces; the variation is the point.
* Slot order: the day opens with an anchor compound for its region, and no
  compound follows an isolation that already tired one of its primary muscles. Exercise order changes what
  the later lifts get (`exercise-order-strength.md`); the lift that matters most
  goes first, fresh.
* The anchor is held for the whole mesocycle: the first anchor executed for a day
  in a block is that day's anchor until the block ends, so overload is visible on
  the same lift week over week.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from shc.metrics import MUSCLE_TO_GROUP

log = logging.getLogger(__name__)

DAYS: dict[str, tuple[str, str]] = {
    "Upper-A": ("upper", "A"),
    "Lower-A": ("lower", "A"),
    "Upper-B": ("upper", "B"),
    "Lower-B": ("lower", "B"),
}
PURPOSE = {
    "A": (
        "LOAD day: the anchor runs in the HEAVY half of its rep window, 2-3 min rests, "
        "compounds carry the session"
    ),
    "B": (
        "VOLUME day: the anchor runs in the LIGHT half of its rep window, shorter rests, "
        "stretch-biased isolations carry the session"
    ),
}
ANCHOR_MUSCLES = {
    "upper": frozenset({"chest", "lats", "mid_back", "front_delts"}),
    "lower": frozenset({"quads", "glutes", "hamstrings"}),
}
_REGION_MUSCLES = {
    "upper": frozenset(m for m, g in MUSCLE_TO_GROUP.items() if g in ("push", "pull")),
    "lower": frozenset(m for m, g in MUSCLE_TO_GROUP.items() if g == "legs"),
}
# Same multi-joint pattern as prescriptor._COMPOUND_RE, plus pulldowns.
_COMPOUND_RE = re.compile(
    r"\b(press|squat|deadlift|row|lunge|pull[ -]?up|chin[ -]?up|dip|thrust|clean|snatch|"
    r"good morning|step[ -]?up|pulldown)(e?s)?\b"
)
_NOT_COMPOUND = ("straight arm", "pallof")
_HINGE_RE = re.compile(r"\b(deadlift|rdl|romanian|good morning|stiff[ -]legged)\b")


@dataclass
class SessionDay:
    day: str
    region: str
    variant: str
    anchor: str | None
    reason: str


def is_compound(name: str) -> bool:
    n = name.lower()
    return bool(_COMPOUND_RE.search(n)) and not any(x in n for x in _NOT_COMPOUND)


def _primary_muscles(conn: Any, name: str) -> set[str]:
    rows = conn.execute(
        "SELECT muscle FROM exercise_muscle WHERE exercise_name = ? AND role = 'primary'",
        [name],
    ).fetchall()
    return {r[0] for r in rows}


def slot_kind(conn: Any, name: str, region: str) -> str:
    """Classify an exercise for a day: 'anchor', 'compound', 'isolation' or 'other'.

    'other' is anything outside the day's region (core, cardio, off-region
    top-ups); it is unconstrained after the anchor.
    """
    prim = _primary_muscles(conn, name)
    if not prim & _REGION_MUSCLES[region]:
        return "other"
    if not is_compound(name):
        return "isolation"
    return "anchor" if prim & ANCHOR_MUSCLES[region] else "compound"


def _plan_exercises(plan: dict) -> list[dict]:
    return [ex for b in plan.get("blocks", []) for ex in b.get("exercises", [])]


def executed_days(conn: Any, before: date) -> list[tuple[date, str, str | None]]:
    """(date, session_day, first exercise) for designed plans Rob actually trained, oldest first."""
    rows = conn.execute(
        """
        SELECT p.date, p.plan_json FROM workout_plans p
        WHERE p.date < ? AND EXISTS (
            SELECT 1 FROM workout_sets_dedup s
            WHERE s.day_d = p.date AND s.source = 'hevy' AND NOT s.is_warmup)
        ORDER BY p.date
        """,
        [before],
    ).fetchall()
    out: list[tuple[date, str, str | None]] = []
    for d, pj in rows:
        try:
            plan = json.loads(pj)
        except (TypeError, ValueError):
            continue
        day = plan.get("session_day")
        if day in DAYS:
            exs = _plan_exercises(plan)
            out.append((d, day, exs[0].get("name") if exs else None))
    return out


def _last_logged_region(conn: Any, before: date) -> str | None:
    """Region of the most recent logged lifting session, by primary-muscle majority."""
    row = conn.execute(
        """
        SELECT
            SUM(CASE WHEN m.muscle IN ('quads','hamstrings','glutes','calves','adductors')
                     THEN 1 ELSE 0 END),
            COUNT(*)
        FROM workout_sets_dedup s
        JOIN exercise_muscle m ON m.exercise_name = s.exercise AND m.role = 'primary'
        WHERE s.source = 'hevy' AND NOT s.is_warmup
          AND s.day_d = (SELECT MAX(day_d) FROM workout_sets_dedup
                         WHERE source = 'hevy' AND day_d < ?)
        """,
        [before],
    ).fetchone()
    if not row or not row[1]:
        return None
    return "lower" if row[0] * 2 > row[1] else "upper"


def _region_gated(region: str, gates: dict) -> bool:
    groups = set(gates.get("forbid_muscle_groups") or [])
    muscles = set(gates.get("forbid_muscles") or [])
    if region == "lower" and "legs" in groups:
        return True
    if region == "upper" and {"push", "pull"} <= groups:
        return True
    return ANCHOR_MUSCLES[region] <= muscles


def _anchor_gated(conn: Any, anchor: str, gates: dict) -> bool:
    groups = set(gates.get("forbid_muscle_groups") or [])
    muscles = set(gates.get("forbid_muscles") or [])
    if _HINGE_RE.search(anchor.lower()) and "pull" in groups:
        return True
    prim = _primary_muscles(conn, anchor)
    return bool(prim & muscles) or any(MUSCLE_TO_GROUP.get(m) in groups for m in prim)


def scheduled_session(
    conn: Any, gates: dict, today: date, meso_start: date | None = None
) -> SessionDay | None:
    """Today's day in the rotation, or None when both regions are gated.

    Args:
        conn: DuckDB connection.
        gates: ``DailyState["gates"]``.
        today: The planning date.
        meso_start: Active mesocycle start; anchors are only held within a block.
    """
    hist = executed_days(conn, today)
    last_variant = {r: "B" for r in ("upper", "lower")}
    for _, day, _ in hist:
        region, variant = DAYS[day]
        last_variant[region] = variant
    if hist:
        last_region = DAYS[hist[-1][1]][0]
        why = f"last trained day was {hist[-1][1]} ({hist[-1][0]})"
    else:
        last_region = _last_logged_region(conn, today) or "lower"
        why = f"no designed day trained yet; last session read as {last_region}"

    order = ["lower", "upper"] if last_region == "upper" else ["upper", "lower"]
    open_regions = [r for r in order if not _region_gated(r, gates)]
    if not open_regions:
        return None
    region = open_regions[0]
    if region != order[0]:
        why += f"; {order[0]} is gated today, so {region} moves up"
    variant = "B" if last_variant[region] == "A" else "A"
    day = f"{region.capitalize()}-{variant}"

    anchor = None
    for d, past_day, first in reversed(hist):
        if meso_start and d < meso_start:
            break
        if past_day == day and first:
            anchor = first
    if anchor and _anchor_gated(conn, anchor, gates):
        why += f"; anchor {anchor} is gated today, pick another {region} compound"
        anchor = None
    return SessionDay(day, region, variant, anchor, why)


def _science_window(conn: Any, name: str) -> tuple[int, int] | None:
    row = conn.execute(
        "SELECT MIN(rep_low), MAX(rep_high) FROM exercise_science WHERE exercise_name = ?",
        [name],
    ).fetchone()
    if not row or row[0] is None or row[1] is None:
        return None
    return int(row[0]), int(row[1])


def check_session(
    conn: Any,
    plan: dict,
    sched: SessionDay,
    rep_bounds: Any,
    override_reason: str | None = None,
) -> str | None:
    """Return a rejection message if the plan breaks today's session design, else None.

    Args:
        conn: DuckDB connection.
        plan: The submitted plan.
        sched: Output of :func:`scheduled_session`.
        rep_bounds: Callable parsing a reps field to ``(low, high)`` or None.
        override_reason: A stated reason lets the day and anchor deviate;
            slot order still applies.
    """
    overridden = bool(override_reason and override_reason.strip())
    day = plan.get("session_day")
    if day not in DAYS:
        return (
            f"Plan needs session_day: today is {sched.day} ({PURPOSE[sched.variant]}). "
            f'Set "session_day": "{sched.day}".'
        )
    if day != sched.day and not overridden:
        return (
            f"session_day {day!r} is out of rotation: today is {sched.day} "
            f"({sched.reason}). Build {sched.day}, or pass override_reason to deviate."
        )
    region, variant = DAYS[day]
    exs = [e for e in _plan_exercises(plan) if e.get("name")]
    if not exs:
        return None
    kinds = [slot_kind(conn, e["name"], region) for e in exs]

    if kinds[0] != "anchor":
        return (
            f"{day} must open with an anchor compound for the {region} body "
            f"(primary {sorted(ANCHOR_MUSCLES[region])}); it opens with "
            f"{exs[0]['name']!r} ({kinds[0]}). The most important lift goes first, fresh."
        )
    # Pre-fatigue is per muscle: a fly before a row tires nothing the row needs,
    # a fly before a press does.
    tired: dict[str, str] = {}
    for e, k in zip(exs, kinds, strict=True):
        prim = _primary_muscles(conn, e["name"])
        if k in ("anchor", "compound"):
            hit = sorted(m for m in prim if m in tired)
            if hit:
                return (
                    f"{e['name']!r} comes after {tired[hit[0]]!r}, an isolation that already "
                    f"tired {hit}. Put every compound before the isolations for the same muscle."
                )
        elif k == "isolation":
            for m in prim:
                tired.setdefault(m, e["name"])

    if sched.anchor and day == sched.day and not overridden and exs[0]["name"] != sched.anchor:
        return (
            f"{day}'s anchor this mesocycle is {sched.anchor!r}; the plan opens with "
            f"{exs[0]['name']!r}. Keep the anchor for the block so overload is measured on "
            "the same lift, or pass override_reason."
        )

    window = _science_window(conn, exs[0]["name"])
    bounds = rep_bounds(exs[0].get("reps"))
    if window and bounds:
        mid = (window[0] + window[1]) / 2
        if variant == "A" and bounds[1] > mid:
            return (
                f"{day} is a load day: {exs[0]['name']!r} reps {exs[0].get('reps')!r} must "
                f"stay in the heavy half of its {window[0]}-{window[1]} window (top ≤ {mid:g})."
            )
        if variant == "B" and bounds[0] < mid:
            return (
                f"{day} is a volume day: {exs[0]['name']!r} reps {exs[0].get('reps')!r} must "
                f"stay in the light half of its {window[0]}-{window[1]} window (bottom ≥ {mid:g})."
            )
    return None


def session_context_block(conn: Any, gates: dict, today: date) -> str:
    """Markdown block that tells the planner today's day, purpose, order and anchor."""
    from shc.training.mesocycle import active_mesocycle

    meso = active_mesocycle(conn)
    sched = scheduled_session(conn, gates, today, meso.started_on if meso else None)
    if sched is None:
        return (
            "## ⚠ TODAY'S SESSION DESIGN (ENFORCED)\nBoth regions are gated: no designed "
            "lifting day today. Rest-intensity plans skip this check."
        )
    region_list = sorted(ANCHOR_MUSCLES[sched.region])
    anchor_line = (
        f"- Anchor (held for this mesocycle): **{sched.anchor}**. Open with it."
        if sched.anchor
        else f"- Anchor: none locked yet. Pick a {sched.region} compound whose primary is one "
        f"of {region_list}; whatever opens this day is its anchor for the rest of the block."
    )
    return "\n".join(
        [
            "## ⚠ TODAY'S SESSION DESIGN (ENFORCED)",
            f'- Day: **{sched.day}** — set `"session_day": "{sched.day}"` in the plan. '
            f"Why this day: {sched.reason}.",
            f"- Purpose: {PURPOSE[sched.variant]}.",
            anchor_line,
            f"- Order: anchor compound → other {sched.region} compounds → {sched.region} "
            "isolations (stretch-biased first) → off-region top-ups, core, cardio. "
            "A compound may not follow an isolation that already hit the same muscle.",
            "- Rotation follows sessions actually trained, not weekdays: upper/lower "
            "alternate, A/B alternate within each.",
        ]
    )
