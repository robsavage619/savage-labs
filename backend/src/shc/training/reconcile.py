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
            ({per_hand_sql("weight_kg", "exercise", "started_at::DATE")}) * 2.20462
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


LAB_STRENGTH_FEATURE = "custom:session_e1rm_vs28d"


def _main_select_at(sql: str) -> int | None:
    """Index of the top-level SELECT that follows a WITH chain, or None."""
    import re

    depth, i, quoted = 0, 0, False
    while i < len(sql):
        ch = sql[i]
        if quoted:
            quoted = ch != "'"
        elif ch == "'":
            quoted = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        elif (
            depth == 0
            and i > 0
            and re.match(r"(?i)\bSELECT\b", sql[i:])
            and not sql[i - 1].isalnum()
        ):
            return i
        i += 1
    return None


def check_lab_strength_outcome_matches_engine_e1rm(
    conn: duckdb.DuckDBPyConnection, today: date | None = None, days: int = 120
) -> Finding:
    """The lab's stored strength outcome must use the engine's e1RM (audit F12).

    ``custom:session_e1rm_vs28d`` is SQL stored in ``research_custom_features``,
    a hand re-implementation of RIR-adjusted Epley with per-hand halving that no
    repo test can execute. This runs the stored text against this DB and compares
    it with a recompute from raw ``workout_sets_dedup`` rows built on the engine's
    own expressions (``effective_reps_sql``, ``per_hand_sql``), with the 28-day
    baseline, 35% artifact cap and 2-lift minimum done in Python. Two layers: the
    stored SQL's inner per-lift-day best e1RM (its ``d`` CTE), when separable, and
    its final daily series. Nothing from the research module is imported.

    Args:
        conn: Any DB carrying ``research_custom_features`` and workout rows.
        today: Last day of the comparison window; defaults to today.
        days: Window length in days.

    Returns:
        A Finding; a missing or unapproved feature is a FAIL, never a pass.
    """
    from datetime import timedelta

    from shc.training.load_mechanics import effective_reps_sql, per_hand_sql

    name = "lab strength outcome vs engine e1RM"
    row = conn.execute(
        "SELECT sql, status FROM research_custom_features WHERE name = ?", [LAB_STRENGTH_FEATURE]
    ).fetchone()
    if not row:
        return Finding(name, False, f"{LAB_STRENGTH_FEATURE} missing from research_custom_features")
    stored, status = row
    if status != "approved":
        return Finding(name, False, f"{LAB_STRENGTH_FEATURE} is {status!r}, not approved")

    end = today or date.today()
    start = end - timedelta(days=days)
    tol_kg, tol_pct = 0.01, 0.01

    raw = conn.execute(
        f"""
        SELECT ws.canon_exercise, ws.day_d,
               MAX(({per_hand_sql("ws.weight_kg", "ws.exercise", "ws.day_d")})
                   * (1 + {effective_reps_sql("ws.reps", "ws.rpe")} / 30.0))
        FROM workout_sets_dedup ws
        WHERE ws.source = 'hevy' AND ws.weight_kg > 0 AND ws.reps > 0
          AND NOT COALESCE(ws.is_warmup, FALSE)
          AND ws.day_d BETWEEN ? AND ?
        GROUP BY 1, 2
        """,
        [start - timedelta(days=28), end],
    ).fetchall()
    best: dict[tuple[str, date], float] = {(ex, d): float(e) for ex, d, e in raw}
    by_lift: dict[str, list[tuple[date, float]]] = {}
    for (ex, d), e in best.items():
        by_lift.setdefault(ex, []).append((d, e))

    per_day: dict[date, list[float]] = {}
    for series in by_lift.values():
        for d, e in series:
            if d < start:
                continue
            prior = [v for pd, v in series if d - timedelta(days=28) <= pd < d]
            if not prior:
                continue
            ratio = e / (sum(prior) / len(prior)) - 1
            if abs(ratio) <= 0.35:
                per_day.setdefault(d, []).append(100 * ratio)
    expected = {d: sum(v) / len(v) for d, v in per_day.items() if len(v) >= 2}

    lift_bad: list[str] = []
    day_bad: list[str] = []
    layers: list[str] = []
    cut = _main_select_at(stored)
    inner: list[tuple] | None = None
    if cut is not None:
        try:
            inner = conn.execute(stored[:cut] + "SELECT ex, day, e FROM d").fetchall()
        except duckdb.Error:
            inner = None
    if inner is None:
        layers.append("final series only (inner e1RM not separable)")
    else:
        layers.append("per-lift-day e1RM + final series")
        lab_best = {(ex, d): float(e) for ex, d, e in inner if start <= d <= end}
        want = {k: v for k, v in best.items() if k[1] >= start}
        for k in sorted(set(lab_best) | set(want), key=lambda k: (k[1], k[0])):
            a, b = lab_best.get(k), want.get(k)
            if a is None or b is None or abs(a - b) > tol_kg:
                a_s = "absent" if a is None else f"{a:.2f}kg"
                b_s = "absent" if b is None else f"{b:.2f}kg"
                lift_bad.append(f"{k[1]} {k[0]}: lab e1RM {a_s}, engine {b_s}")

    lab_series = {
        d: float(v)
        for d, v in conn.execute(
            f"SELECT * FROM ({stored}) WHERE day BETWEEN ? AND ?", [start, end]
        ).fetchall()
        if v is not None
    }
    for d in sorted(set(lab_series) | set(expected)):
        a, b = lab_series.get(d), expected.get(d)
        if a is None or b is None or abs(a - b) > tol_pct:
            a_s = "absent" if a is None else f"{a:+.2f}%"
            b_s = "absent" if b is None else f"{b:+.2f}%"
            day_bad.append(f"{d} session value: lab {a_s}, engine {b_s}")

    detail = (
        f"{len(day_bad)} session day(s) and {len(lift_bad)} lift-day(s) disagree over "
        f"{days}d to {end} ({layers[0]}; {len(expected)} expected session days)"
    )
    ok = not day_bad and not lift_bad
    return Finding(name, ok, detail, day_bad[:4] + lift_bad[:4])


ALL_CHECKS = (
    check_prescription_against_recent_reality,
    check_e1rm_paths_agree,
    check_volume_credit_sums,
    check_every_muscle_has_landmarks,
    check_citations_resolve,
    check_no_contradictory_length_bias,
    check_lab_strength_outcome_matches_engine_e1rm,
)


def run_all(conn: duckdb.DuckDBPyConnection) -> list[Finding]:
    out: list[Finding] = []
    for fn in ALL_CHECKS:
        try:
            out.append(fn(conn))
        except Exception as exc:  # noqa: BLE001 — a broken check must not hide the others
            out.append(Finding(fn.__name__, False, f"check itself errored: {exc}"))
    return out
