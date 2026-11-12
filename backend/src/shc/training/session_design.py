"""Session design: which day it is, what it is for, and what goes first.

The weekly engine decides the dose (sets per muscle per week). Nothing used to
decide the session: a fresh planner composed every day from scratch, so the day
type was renamed daily ("Upper-A", "Full Body", "Upper Pull + Arms") and an
isolation often opened the session ahead of the compound it should follow. This
module is the structure those plans are now validated against.

* Days rotate by sessions actually EXECUTED, not by weekday, because Rob trains
  3-4 times a week on shifting days. A missed day does not skip a template.
* The split follows his real frequency (`training-frequency-hypertrophy.md`:
  each muscle at least 2x/week; Helms' templates: 3 days Lower/Upper/Full, 4
  days Upper/Lower x2). Upper/Lower A/B hits a muscle on half of all sessions, so
  it reaches 2x/week only at 4+ sessions/week. Below that, the rotation is
  Upper-A -> Lower-A -> Full Body, which hits every muscle on 2 of 3 sessions.
* Every day in the rotation opens with a DIFFERENT anchor lift, so each region
  gets two movement emphases (e.g. incline press-led Upper-A, pulldown-led
  Upper-B or Full Body).
* An anchor keeps one rep range for the whole block (`variation-hypertrophy.md`,
  Israetel ch.5): changing reps on the same lift mid-block breaks the overload
  record. A heavy/light half-window split was tried and dropped on 2026-11-08: on
  the 8-12 windows it was a 10-vs-10 rep difference, and undulating loads do not
  beat fixed ones for growth (`periodization-hypertrophy.md`).
* Slot order: the day opens with an anchor compound for its region, and no
  compound follows an isolation that already tired one of its primary muscles.
  The lift that matters most goes first, fresh, so its numbers stay comparable.
  Order moves strength toward the lifts done first and does not change growth
  (`nunes-2020-exercise-order-strength-hypertrophy.md`), so this is a tracking
  rule, not a growth rule.
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
    "Full Body": ("full", "F"),
}
FOUR_DAY = ("Upper-A", "Lower-A", "Upper-B", "Lower-B")
THREE_DAY = ("Upper-A", "Lower-A", "Full Body")
# Upper/Lower A/B trains a muscle every other session: 2x/week needs 4 sessions/week.
FOUR_DAY_MIN_SESSIONS_28D = 16
PURPOSE = {
    "A": "the region's first movement emphasis, led by its own anchor lift",
    "B": "the region's second movement emphasis, led by a DIFFERENT anchor than the A day",
    "F": "the second weekly hit for every muscle, led by an anchor different from the "
    "Upper-A and Lower-A anchors",
}
ANCHOR_MUSCLES = {
    "upper": frozenset({"chest", "lats", "mid_back", "front_delts"}),
    "lower": frozenset({"quads", "glutes", "hamstrings"}),
}
ANCHOR_MUSCLES["full"] = ANCHOR_MUSCLES["upper"] | ANCHOR_MUSCLES["lower"]
_REGION_MUSCLES = {
    "upper": frozenset(m for m, g in MUSCLE_TO_GROUP.items() if g in ("push", "pull")),
    "lower": frozenset(m for m, g in MUSCLE_TO_GROUP.items() if g == "legs"),
}
_REGION_MUSCLES["full"] = _REGION_MUSCLES["upper"] | _REGION_MUSCLES["lower"]
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
    anchor_reps: str | None = None
    other_anchors: tuple[str, ...] = ()


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


def executed_days(conn: Any, before: date) -> list[tuple[date, str, str | None, str | None]]:
    """(date, session_day, opener, opener reps) for designed plans Rob trained, oldest first.

    A plan counts as trained only when at least half of the lifts logged that day
    are in it. A plan written after a workout (or one Rob ignored) shares a date
    with the session but not its lifts, and must not advance the rotation or lock
    an anchor. The opener is None when its lift was not logged.
    """
    rows = conn.execute(
        """
        SELECT p.date, p.plan_json FROM workout_plans p
        WHERE p.date < ? ORDER BY p.date
        """,
        [before],
    ).fetchall()
    out: list[tuple[date, str, str | None, str | None]] = []
    for d, pj in rows:
        logged = conn.execute(
            """
            SELECT DISTINCT exercise, canon_exercise FROM workout_sets_dedup
            WHERE day_d = ? AND source = 'hevy' AND NOT is_warmup
            """,
            [d],
        ).fetchall()
        if not logged:
            continue
        try:
            plan = json.loads(pj)
        except (TypeError, ValueError):
            continue
        day = plan.get("session_day")
        exs = _plan_exercises(plan)
        if day not in DAYS or not exs:
            continue
        names = {e.get("name") for e in exs}
        matched = sum(1 for ex, canon in logged if ex in names or canon in names)
        if matched * 2 < len(logged):
            continue
        first = exs[0]
        reps = first.get("reps")
        was_done = any(first.get("name") in (ex, canon) for ex, canon in logged)
        out.append(
            (d, day, first.get("name") if was_done else None, None if reps is None else str(reps))
        )
    return out


def _last_logged(conn: Any, before: date) -> tuple[date, str] | None:
    """(date, region) of the most recent logged lifting session, by majority of SETS.

    Each set counts once, as lower when most of its exercise's primaries are
    lower-body. lower_back counts as lower here (it sits in the "pull" group for
    gating) because its lifts are hinges: on 2026-11-08 a stiff-legged deadlift
    split half to upper and a 7-leg-set vs 6-arm-set day read as upper.
    """
    row = conn.execute(
        """
        WITH ex AS (
            SELECT exercise_name,
                   AVG(CASE WHEN muscle IN ('quads','hamstrings','glutes','calves',
                                            'adductors','lower_back')
                            THEN 1.0 ELSE 0.0 END) > 0.5 AS is_lower
            FROM exercise_muscle WHERE role = 'primary' GROUP BY exercise_name
        )
        SELECT SUM(CASE WHEN ex.is_lower THEN 1 ELSE 0 END), COUNT(*), MAX(s.day_d)
        FROM workout_sets_dedup s
        JOIN ex ON ex.exercise_name = s.exercise
        WHERE s.source = 'hevy' AND NOT s.is_warmup
          AND s.day_d = (SELECT MAX(day_d) FROM workout_sets_dedup
                         WHERE source = 'hevy' AND NOT is_warmup AND day_d < ?)
        """,
        [before],
    ).fetchone()
    if not row or not row[1]:
        return None
    return row[2], "lower" if row[0] * 2 > row[1] else "upper"


def _sessions_28d(conn: Any, before: date) -> int:
    row = conn.execute(
        """
        SELECT COUNT(DISTINCT day_d) FROM workout_sets_dedup
        WHERE source = 'hevy' AND NOT is_warmup
          AND day_d < ? AND day_d >= CAST(? AS DATE) - INTERVAL 28 DAY
        """,
        [before, before],
    ).fetchone()
    return int(row[0]) if row else 0


def _region_gated(region: str, gates: dict) -> bool:
    if region == "full":
        return _region_gated("upper", gates) or _region_gated("lower", gates)
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
    n28 = _sessions_28d(conn, today)
    four_day = n28 >= FOUR_DAY_MIN_SESSIONS_28D
    cycle = FOUR_DAY if four_day else THREE_DAY
    logged = _last_logged(conn, today)
    if hist:
        last_region = DAYS[hist[-1][1]][0]
        why = f"last trained day was {hist[-1][1]} ({hist[-1][0]})"
    else:
        last_region = logged[1] if logged else "lower"
        why = f"no designed day trained yet; last session read as {last_region}"
    # A region trained yesterday is not trained again today (48 h between sessions
    # for the same muscles, `training-frequency-hypertrophy.md`).
    recent = logged[1] if logged and (today - logged[0]).days <= 1 else None
    why += (
        f"; {n28} sessions in the last 28 days, so the "
        + ("4-day Upper/Lower A/B" if four_day else "3-day Upper/Lower/Full Body")
        + " split keeps every muscle at 2x/week"
    )

    if four_day:
        last_variant = {"upper": "B", "lower": "B"}
        for _, past, _, _ in hist:
            r, v = DAYS[past]
            if r in last_variant:
                last_variant[r] = v
        order = ["lower", "upper"] if last_region == "upper" else ["upper", "lower"]
        candidates = [f"{r.capitalize()}-{'B' if last_variant[r] == 'A' else 'A'}" for r in order]
    else:
        # After upper comes Lower-A, after lower Full Body, after Full Body Upper-A.
        start = {"upper": 1, "lower": 2, "full": 0}[last_region]
        candidates = [cycle[(start + i) % 3] for i in range(3)]
    open_days = [d for d in candidates if not _region_gated(DAYS[d][0], gates)]
    if not open_days:
        return None
    rested = [d for d in open_days if DAYS[d][0] not in (recent, "full")] if recent else []
    day = (rested or open_days)[0]
    if recent and day != open_days[0]:
        why += f"; {recent} body was trained yesterday, so {open_days[0]} waits"
    region, variant = DAYS[day]
    if open_days[0] != candidates[0]:
        why += f"; {candidates[0]} is gated today, so {open_days[0]} moves up"

    # The first opener trained for a day in this block is its anchor, reps included.
    first_by_day: dict[str, tuple[str, str | None]] = {}
    for d, past_day, name, reps in hist:
        if name and (meso_start is None or d >= meso_start):
            first_by_day.setdefault(past_day, (name, reps))
    anchor, anchor_reps = first_by_day.get(day, (None, None))
    others = tuple(first_by_day[d][0] for d in cycle if d != day and d in first_by_day)
    if anchor and _anchor_gated(conn, anchor, gates):
        why += f"; anchor {anchor} is gated today, pick another {region} compound"
        anchor, anchor_reps = None, None
    return SessionDay(day, region, variant, anchor, why, anchor_reps, others)


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
    region = DAYS[day][0]
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

    if overridden:
        return None
    opener = exs[0]["name"]
    if day == sched.day and opener in sched.other_anchors:
        return (
            f"{opener!r} already anchors another day in the rotation this block. {day} "
            "needs a different anchor, so each region gets two movement emphases."
        )
    if (
        sched.anchor
        and sched.anchor_reps
        and opener == sched.anchor
        and rep_bounds(exs[0].get("reps")) != rep_bounds(sched.anchor_reps)
    ):
        return (
            f"{opener!r} runs at {sched.anchor_reps!r} reps for this whole block; the plan "
            f"says {exs[0].get('reps')!r}. Keep the reps and move the load, so the overload "
            "record stays comparable."
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
    label = "full-body" if sched.region == "full" else sched.region
    reps = f" at **{sched.anchor_reps}** reps (fixed for the block)" if sched.anchor_reps else ""
    others = (
        f" It may not be {', '.join(sched.other_anchors)}, which anchor other days."
        if sched.other_anchors
        else ""
    )
    anchor_line = (
        f"- Anchor (held for this mesocycle): **{sched.anchor}**{reps}. Open with it."
        if sched.anchor
        else f"- Anchor: none locked yet. Pick a compound whose primary is one of "
        f"{region_list}; whatever opens this day, at the reps you give it, is its anchor "
        f"for the rest of the block.{others}"
    )
    return "\n".join(
        [
            "## ⚠ TODAY'S SESSION DESIGN (ENFORCED)",
            f'- Day: **{sched.day}** — set `"session_day": "{sched.day}"` in the plan. '
            f"Why this day: {sched.reason}.",
            f"- Purpose: {PURPOSE[sched.variant]}.",
            anchor_line,
            f"- Order: anchor compound → other {label} compounds → {label} "
            "isolations (stretch-biased first) → off-region top-ups, core, cardio. "
            "A compound may not follow an isolation that already hit the same muscle.",
            "- Rotation follows sessions actually trained, not weekdays: "
            "Upper-A → Lower-A → Full Body below 4 sessions/week, "
            "Upper-A → Lower-A → Upper-B → Lower-B at 4+.",
        ]
    )
