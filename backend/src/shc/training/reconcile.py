from __future__ import annotations

"""Reconcile what the engine SAYS against what the raw rows SHOW.

Why this module exists
----------------------
On 2026-07-26 a single session found roughly a dozen calculation defects. The
719-test suite was green throughout and caught **none** of them. They were found
by a human comparing engine output to reality — most consequentially by noticing
that the plan card rendered ``Leg Extension 175lb x10 @ "RPE 8"`` directly beside
``200x10 @RPE 8`` logged three days earlier.

That is not a gap in test coverage; it is a gap in test *kind*. Unit tests assert
that a function does what its author believed. They cannot flag a function whose
belief was wrong, and every defect that day was of that second kind: e1RM scoring
submaximal sets as maximal, load capped as a fraction of 1RM when it should have
capped effort, tonnage standing in for fatigue, a keyword matching inside an
unrelated word, a prompt still teaching a rule the validator had abandoned.

The common shape is a number that is internally consistent and externally wrong.
The only thing that catches that is comparing it against an independent
observation, so these checks deliberately recompute from the rawest available
rows rather than reusing the engine's own helpers — a check that imports the
function it is checking proves nothing.

Read the output as a prompt to investigate, not a pass/fail gate. A FAIL is a
claim that two things which must agree do not.
"""

import logging
from dataclasses import dataclass, field
from datetime import date

import duckdb

log = logging.getLogger(__name__)


@dataclass
class Finding:
    check: str
    ok: bool
    detail: str
    rows: list[str] = field(default_factory=list)


def _e1rm_from_raw(conn: duckdb.DuckDBPyConnection, exercise: str, days: int = 90) -> float | None:
    """Best RIR-adjusted Epley e1RM in lb, computed WITHOUT the engine's helpers.

    Deliberately re-derived here in plain SQL. Calling ``e1rm_by_exercise``
    would make this check a tautology.
    """
    from shc.training.load_mechanics import per_hand_sql

    row = conn.execute(
        f"""
        SELECT MAX(
            ({per_hand_sql("weight_kg", "exercise")}) * 2.20462
            * (1 + LEAST(reps + CASE WHEN rpe IS NULL THEN 0
                                     ELSE GREATEST(LEAST(10 - rpe, 3), 0) END, 12) / 30.0)
        )
        FROM workout_sets_dedup
        WHERE exercise = ? AND source = 'hevy' AND is_warmup = FALSE
          AND weight_kg > 0 AND reps > 0
          AND started_at::DATE >= CURRENT_DATE - ?
        """,
        [exercise, days],
    ).fetchone()
    return float(row[0]) if row and row[0] else None


def check_prescription_against_recent_reality(
    conn: duckdb.DuckDBPyConnection, plan_date: date | None = None
) -> Finding:
    """Does today's plan prescribe less than Rob recently did at the SAME effort?

    THE check. A prescription materially lighter than a set already completed at
    the same RPE is the signature of a broken load basis, and it is what three
    separate defects produced this week (raw-rep e1RM, a fraction-of-1RM cap, and
    a prompt teaching the retired rule) — each invisible to the suite.

    Compares only against sets at an RPE within 0.5 of the prescribed target, so
    it is like-for-like: heavier-at-higher-effort is not a finding.
    """
    d = (plan_date or date.today()).isoformat()
    row = conn.execute("SELECT plan_json FROM workout_plans WHERE date = ?", [d]).fetchone()
    if not row:
        return Finding("prescription vs recent reality", True, f"no plan stored for {d}")

    import json

    plan = json.loads(row[0])
    bad: list[str] = []
    for block in plan.get("blocks", []):
        for ex in block.get("exercises", []):
            name, w, rpe_t = ex.get("name"), ex.get("weight_lbs"), ex.get("rpe_target")
            if not name or not w or rpe_t is None:
                continue
            prior = conn.execute(
                """
                SELECT MAX(weight_kg * 2.20462)
                FROM workout_sets_dedup
                WHERE exercise = ? AND source = 'hevy' AND is_warmup = FALSE
                  AND rpe IS NOT NULL AND ABS(rpe - ?) <= 0.5
                  AND started_at::DATE >= CURRENT_DATE - 28
                """,
                [name, float(rpe_t)],
            ).fetchone()
            if prior and prior[0] and float(w) < float(prior[0]) * 0.95:
                bad.append(
                    f"{name}: prescribing {w}lb @RPE {rpe_t}, but {prior[0]:.0f}lb "
                    f"was logged at that RPE within 28d"
                )
    return Finding(
        "prescription vs recent reality",
        not bad,
        f"{len(bad)} lift(s) prescribed >5% under a recent same-RPE set",
        bad,
    )


def check_e1rm_paths_agree(conn: duckdb.DuckDBPyConnection) -> Finding:
    """The progression e1RM and the ceiling e1RM must be the same number.

    They are computed in different places (a SQL rollup and a Python pass), and
    a divergence means the engine grades progress against one value while
    prescribing off another.
    """
    from shc.ai.workout_planner import e1rm_by_exercise

    engine = e1rm_by_exercise(conn, date.today(), days=90)
    bad: list[str] = []
    for ex, kg in list(engine.items())[:200]:
        raw = _e1rm_from_raw(conn, ex)
        if raw is None:
            continue
        # ONE-DIRECTIONAL. The engine additionally trims high outliers via a
        # median/MAD filter (`_robust_max`), so engine <= raw is expected and
        # healthy — that is the fat-fingered-log guard doing its job. Only
        # engine ABOVE the raw maximum is impossible, and that is the direction
        # that would raise a load ceiling on bad data.
        if kg * 2.20462 > raw * 1.02 + 1.0:
            bad.append(f"{ex}: engine {kg * 2.20462:.1f}lb EXCEEDS raw max {raw:.1f}lb")
    return Finding("e1RM never exceeds the raw max", not bad, f"{len(bad)} mismatch(es)", bad)


def check_volume_credit_sums(conn: duckdb.DuckDBPyConnection) -> Finding:
    """Per-muscle weekly volume must equal a hand-rolled sum over the raw sets."""
    from shc.training.volume import weekly_muscle_volume
    from shc.training.mesocycle import _iso_week_start

    ws = _iso_week_start(date.today())
    engine = {m: round(v, 2) for m, v in weekly_muscle_volume(conn, ws).items()}
    raw = {
        m: round(float(v), 2)
        for m, v in conn.execute(
            """
            SELECT em.muscle, SUM(em.credit)
            FROM workout_sets_dedup ws
            JOIN exercise_muscle em ON em.exercise_name = ws.exercise
            WHERE ws.is_warmup = FALSE AND ws.weight_kg > 0 AND ws.reps BETWEEN 5 AND 30
              AND (ws.rpe IS NULL OR ws.rpe >= 6.0)
              AND ws.started_at::DATE >= ? AND ws.started_at::DATE < ? + 7
            GROUP BY em.muscle
            """,
            [ws, ws],
        ).fetchall()
    }
    bad = [
        f"{m}: engine {engine.get(m, 0)} vs raw {raw.get(m, 0)}"
        for m in set(engine) | set(raw)
        if abs(engine.get(m, 0) - raw.get(m, 0)) > 0.51
    ]
    return Finding("weekly volume vs raw credit sum", not bad, f"{len(bad)} mismatch(es)", bad)


def check_every_muscle_has_landmarks(conn: duckdb.DuckDBPyConnection) -> Finding:
    """Every targeted muscle needs a tier and an MV, or the tier silently no-ops."""
    from shc.training.mesocycle import volume_targets

    bad = [
        f"{m}: tier={vt.tier!r} mv={vt.mv} mev={vt.mev}"
        for m, vt in volume_targets(conn).items()
        if vt.tier not in ("grow", "maintain") or vt.mv is None or vt.mv > vt.mev
    ]
    return Finding("volume landmarks complete", not bad, f"{len(bad)} incomplete", bad)


def check_citations_resolve(conn: duckdb.DuckDBPyConnection, vault: str | None = None) -> Finding:
    """A `.md` citation must name a note that exists on disk."""
    import pathlib

    root = pathlib.Path(vault or (pathlib.Path.home() / "Vault/savage_vault/wiki"))
    if not root.is_dir():
        return Finding("citations resolve", True, "vault not present on this machine")
    cited = {
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT citation FROM exercise_science WHERE citation LIKE '%.md'"
        ).fetchall()
    }
    bad = sorted(c for c in cited if not (root / c).is_file())
    return Finding("citations resolve", not bad, f"{len(bad)} dangling", bad)


def check_no_contradictory_length_bias(conn: duckdb.DuckDBPyConnection) -> Finding:
    """Variants of one movement must not disagree about where they load the muscle.

    `length_bias` is a ranking key in `_select_grounded`, so a disagreement makes
    selection depend on which variant the menu happened to surface. Preacher Curl
    carried both `shortened` and `lengthened` across three rows.
    """
    # Implement differences are legitimate and must NOT be flagged: a dumbbell
    # bench press really does load a longer muscle length than a barbell that
    # stops at the chest. The bug shape is a PHANTOM duplicate — two rows for one
    # movement, disagreeing, where one name has no logged history at all (as with
    # `Leg Extension` / `Leg Extension (Machine)`, 0 sets vs 557).
    rows = conn.execute(
        """
        WITH sci AS (
            SELECT exercise_name, muscle, length_bias,
                   regexp_replace(exercise_name, ' \\(.*\\)$', '') AS base
            FROM exercise_science WHERE length_bias IS NOT NULL
        ), logged AS (
            SELECT exercise, COUNT(*) n FROM workout_sets_dedup GROUP BY 1
        )
        SELECT a.exercise_name, b.exercise_name, a.muscle,
               a.length_bias, b.length_bias,
               COALESCE(la.n, 0), COALESCE(lb.n, 0)
        FROM sci a JOIN sci b
          ON a.base = b.base AND a.muscle = b.muscle
         AND a.exercise_name < b.exercise_name
         AND a.length_bias <> b.length_bias
        LEFT JOIN logged la ON la.exercise = a.exercise_name
        LEFT JOIN logged lb ON lb.exercise = b.exercise_name
        -- Only flag ALIAS pairs: one name bare, the other parenthesised
        -- ("Leg Extension" vs "Leg Extension (Machine)"). Two DIFFERENT
        -- implements are a real variant, not a duplicate — a dumbbell press
        -- travels past where a bar stops at the chest, so Overhead Press
        -- (Barbell) legitimately reads `mid` while (Dumbbell) reads
        -- `lengthened`. Flagging those would train the reader to ignore this
        -- check, which is worse than not having it.
        WHERE (a.exercise_name = a.base OR b.exercise_name = b.base)
          AND (COALESCE(la.n, 0) = 0 OR COALESCE(lb.n, 0) = 0)
        """
    ).fetchall()
    bad = [
        f"{an!r}({ab}, {an_n} sets) vs {bn!r}({bb}, {bn_n} sets) on {m} — phantom duplicate"
        for an, bn, m, ab, bb, an_n, bn_n in rows
    ]
    return Finding("length_bias consistent across variants", not bad, f"{len(bad)} split", bad)


ALL_CHECKS = (
    check_prescription_against_recent_reality,
    check_e1rm_paths_agree,
    check_volume_credit_sums,
    check_every_muscle_has_landmarks,
    check_citations_resolve,
    check_no_contradictory_length_bias,
)


def run_all(conn: duckdb.DuckDBPyConnection) -> list[Finding]:
    out: list[Finding] = []
    for fn in ALL_CHECKS:
        try:
            out.append(fn(conn))
        except Exception as exc:  # noqa: BLE001 — a broken check must not hide the others
            out.append(Finding(fn.__name__, False, f"check itself errored: {exc}"))
    return out
