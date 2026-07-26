from __future__ import annotations

"""Coverage audit for the curated-name → logged-name alias bridge.

The plateau-triggered exercise rotation in :mod:`shc.training.autoregulation`
can only read a swap signal for a curated ``exercise_science`` movement if that
movement's e1RM history is findable under the name Rob actually logs it as. The
``exercise_alias`` table (migration 0067) bridges the two vocabularies, but it is
hand-maintained and silently reopens every time a curation migration adds a name
or Hevy introduces a naming variant. A curated name with no exact match and no
alias reads as "never trained", so its stall is invisible and it never rotates.

This module surfaces that gap: every curated name with zero logged presence,
paired with the safest candidate logged names to alias it to. Candidates are
guarded two ways so a human confirm pass is quick and low-risk:

  * **Muscle veto** — a logged name that maps to a KNOWN different primary muscle
    is rejected outright (kills the "Rear Delt Fly → chest Dumbbell Fly" class).
  * **Equipment guard + token overlap** — the two names must not name conflicting
    equipment, and their non-equipment (movement) tokens must overlap ≥50%.

Diagnosis only: nothing here writes to ``exercise_alias``. Confirmed candidates
land via a hand-authored migration.
"""

import logging
import re

import duckdb

log = logging.getLogger(__name__)

# Equipment words that name the implement rather than the movement. Two names
# with conflicting equipment (dumbbell vs cable) are never the same exercise.
_EQUIPMENT_TOKENS = frozenset(
    {
        "dumbbell",
        "barbell",
        "cable",
        "machine",
        "band",
        "kettlebell",
        "smith",
        "ez",
        "rope",
        "bodyweight",
    }
)

_MATCH_THRESHOLD = 0.5
_MAX_CANDIDATES = 3


def _tokens(name: str) -> set[str]:
    return {t for t in re.split(r"[^a-z0-9]+", name.lower()) if t}


def _split_equipment(name: str) -> tuple[frozenset[str], frozenset[str]]:
    """Return ``(equipment_tokens, movement_tokens)`` for a name."""
    toks = _tokens(name)
    equip = frozenset(toks & _EQUIPMENT_TOKENS)
    return equip, frozenset(toks - _EQUIPMENT_TOKENS)


def _equipment_compatible(a: frozenset[str], b: frozenset[str]) -> bool:
    """Names conflict only when both name equipment and it differs.

    Hevy often omits the implement when it is unambiguous ("Concentration Curl"
    for "Concentration Curl (Dumbbell)"), so an empty side is treated as
    unspecified rather than a mismatch.
    """
    if a and b:
        return a == b
    return True


def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    if not a and not b:
        return 0.0
    return len(a & b) / len(a | b)


def alias_gap_report(conn: duckdb.DuckDBPyConnection) -> list[dict]:
    """Curated exercise names with no logged match, plus safe alias candidates.

    A curated ``exercise_science`` name is a gap when neither it nor its existing
    alias target appears among Rob's logged (non-warmup) exercise strings. For
    each gap, every muscle-compatible, equipment-compatible logged name with ≥50%
    movement-token overlap is proposed as a candidate, carrying its set count and
    last-logged date so a human can confirm at a glance. Rows sort candidates-
    first, then alphabetically. Verdict ``likely_untried_or_no_equipment`` means
    no candidate survived the guards — the name is genuinely never trained or the
    equipment is not in Rob's gym.
    """
    curated = conn.execute("SELECT DISTINCT exercise_name, muscle FROM exercise_science").fetchall()
    aliases = {
        r[0]: r[1]
        for r in conn.execute("SELECT canonical_name, logged_name FROM exercise_alias").fetchall()
    }
    logged_rows = conn.execute(
        """
        SELECT d.exercise,
               COUNT(*) AS set_count,
               MAX(d.started_at)::DATE AS last_logged,
               ANY_VALUE(m.primary_muscle) AS mapped_muscle
        FROM workout_sets_dedup d
        LEFT JOIN exercise_muscle_map m ON m.exercise_name = d.exercise
        WHERE COALESCE(d.is_warmup, FALSE) = FALSE
        GROUP BY d.exercise
        """
    ).fetchall()
    logged_names = {r[0] for r in logged_rows}
    logged = [
        {
            "name": r[0],
            "set_count": int(r[1]),
            "last_logged": r[2].isoformat() if r[2] else None,
            "muscle": r[3],
            "equip": _split_equipment(r[0])[0],
            "movement": _split_equipment(r[0])[1],
        }
        for r in logged_rows
    ]

    report: list[dict] = []
    for name, muscle in curated:
        alias_target = aliases.get(name)
        if name in logged_names or (alias_target and alias_target in logged_names):
            continue  # already resolvable → not a gap
        c_equip, c_movement = _split_equipment(name)
        cands: list[dict] = []
        for lg in logged:
            if lg["muscle"] and lg["muscle"] != muscle:
                continue  # muscle veto
            if not _equipment_compatible(c_equip, lg["equip"]):
                continue
            score = _jaccard(c_movement, lg["movement"])
            if score >= _MATCH_THRESHOLD:
                cands.append(
                    {
                        "logged_name": lg["name"],
                        "score": round(score, 2),
                        "set_count": lg["set_count"],
                        "last_logged": lg["last_logged"],
                    }
                )
        cands.sort(key=lambda c: (-c["score"], -c["set_count"], c["logged_name"]))
        report.append(
            {
                "canonical_name": name,
                "muscle": muscle,
                "candidates": cands[:_MAX_CANDIDATES],
                "verdict": "candidates_found" if cands else "likely_untried_or_no_equipment",
            }
        )
    report.sort(key=lambda r: (r["verdict"] != "candidates_found", r["canonical_name"]))
    return report


def curation_gap_report(conn: duckdb.DuckDBPyConnection, min_sets: int = 10) -> list[dict]:
    """Movements Rob trains hard that no ``exercise_science`` row can see.

    :func:`alias_gap_report` walks curated→logged: a curated name whose history is
    unfindable. This walks logged→curated, which is where the damage was actually
    hiding. A movement with real volume and no science row is invisible to
    :func:`shc.training.autoregulation.evidence_menu` — it can never be selected,
    never credits a region, and never competes for a slot, no matter how central it
    is to how Rob actually trains. Dumbbell Upright Row sat at **1,541 logged sets**
    while the traps menu recommended movements he had never performed once, and
    nothing in the system said so; it took him raising "the engine keeps picking the
    same exercises" five times for anyone to look.

    That silence is the bug this closes. The starved pools it surfaces are the
    upstream cause of the repetition — selection cannot rotate through movements it
    cannot see, so a shallow catalog and a stable-by-design selector compound into
    the same four exercises forever.

    Returns one row per unseen movement, heaviest first::

        {exercise, sets, last_done, muscle, verdict}

    ``verdict`` separates the two fixes, which are not interchangeable:

    * ``mapped_uncurated`` — the movement has an ``exercise_muscle`` row (so it
      credits volume) but no citation, so it is invisible to selection. Fix is a
      curation migration adding region/length_bias/rep band/SFR.
    * ``unmapped`` — no ``exercise_muscle`` row at all. It credits nothing
      anywhere; fix is the classifier or the muscle map first, curation second.

    Diagnosis only — writes nothing. ``min_sets`` filters one-off experiments;
    the default of 10 is deliberately low, because a movement can matter long
    before it accumulates volume.
    """
    curated = {r[0] for r in conn.execute("SELECT exercise_name FROM exercise_science").fetchall()}
    # A logged name is "seen" if it is curated itself or an alias target of a
    # curated name — the same bridge the plateau signal reads through.
    # Column is `canonical_name` (migration 0067) — NOT wrapped in a try/except,
    # deliberately. A swallowed schema error here would silently report every
    # aliased movement as an uncovered gap, which is the exact failure mode this
    # report exists to expose. Fail loud instead.
    aliases = conn.execute("SELECT canonical_name, logged_name FROM exercise_alias").fetchall()
    seen = set(curated) | {logged for canonical, logged in aliases if canonical in curated}

    rows = conn.execute(
        """
        SELECT ws.exercise,
               COUNT(*)                       AS sets,
               MAX(w.started_at)::DATE::VARCHAR AS last_done,
               ANY_VALUE(em.muscle)           AS muscle
        FROM workout_sets ws
        JOIN workouts w ON w.id = ws.workout_id
        LEFT JOIN exercise_muscle em
               ON em.exercise_name = ws.exercise AND em.role = 'primary'
        WHERE COALESCE(ws.is_warmup, FALSE) = FALSE
        GROUP BY ws.exercise
        HAVING COUNT(*) >= ?
        ORDER BY sets DESC
        """,
        [min_sets],
    ).fetchall()

    return [
        {
            "exercise": ex,
            "sets": int(sets),
            "last_done": last_done,
            "muscle": muscle,
            "verdict": "mapped_uncurated" if muscle else "unmapped",
        }
        for ex, sets, last_done, muscle in rows
        if ex not in seen
    ]
