"""The Rob Model registry: what the lab knows about one person, and how sure.

Every parameter starts from a published prior cited to a vault note and carries
the value the engine currently fits from his own evidence. :func:`refresh` only
READS what the engine already fits (volume landmarks, ACWR and sleep bands,
noise floors, per-lift session noise, the belief ledger) and mirrors it into
``rob_parameters``. It never re-derives a fit and holds no personal value.

Status rule (one rule for every parameter): ``prior only`` when there is no
evidence (n = 0), ``learning`` while n is below the engine's own sample gate for
that parameter, ``established`` once n reaches it, which is the point the engine
starts acting on the value. Updating a parameter from experiment evidence is
WP 1.2 and not here.
"""

from __future__ import annotations

import logging
import re
import statistics
from dataclasses import dataclass
from typing import Any

import duckdb

from shc.ai.vault import valid_citation_filenames
from shc.training.load_mechanics import effective_reps_sql, per_hand_sql

log = logging.getLogger(__name__)

NO_PRIOR = "no published prior"
DOMAINS = ("training", "recovery", "sleep", "health")
_COLUMNS = (
    "domain",
    "label",
    "unit",
    "prior_mean",
    "prior_sd",
    "prior_source",
    "post_mean",
    "post_sd",
    "evidence_kind",
    "n_evidence",
    "consumer",
    "status",
)
_ACWR_NOTE = "acute-chronic-workload-ratio.md"
_BELIEF_MIN_RESULTS = 3
_LIFT_MIN_SESSIONS = 5
_LIFT_TOP_N = 5
_NOISE_WINDOW_DAYS = 28


@dataclass(frozen=True)
class Parameter:
    """One registry row before it is stored."""

    key: str
    domain: str
    label: str
    unit: str | None
    prior_mean: float | None
    prior_sd: float | None
    prior_source: str
    post_mean: float | None
    post_sd: float | None
    evidence_kind: str
    n_evidence: int
    consumer: str | None
    min_n: int


def status_for(n_evidence: int, min_n: int) -> str:
    """Apply the one status rule: n = 0 prior only, below the engine gate learning, else established."""
    if n_evidence <= 0:
        return "prior only"
    return "learning" if n_evidence < min_n else "established"


def validate_citation(source: str, prior_mean: float | None, prior_sd: float | None) -> None:
    """Reject a prior whose citation is not a real vault note.

    Args:
        source: A vault note filename, or ``NO_PRIOR``.
        prior_mean: The prior mean; must be None exactly when ``source`` is ``NO_PRIOR``.
        prior_sd: The prior sd, same rule.

    Raises:
        ValueError: If the citation is not in the vault, or numbers and source disagree.
    """
    if source == NO_PRIOR:
        if prior_mean is not None or prior_sd is not None:
            raise ValueError(f"'{NO_PRIOR}' must not carry a prior number")
        return
    if prior_mean is None:
        raise ValueError(f"a cited prior needs a prior_mean: {source!r}")
    allowed = valid_citation_filenames()
    if allowed and source not in allowed:
        raise ValueError(f"prior_source {source!r} is not a vault note filename")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _landmarks(conn: duckdb.DuckDBPyConnection) -> list[Parameter]:
    from shc.training.self_learning import _LANDMARK_MIN_WEEKS
    from shc.training.volume import muscle_weekly_volume_series

    rows = conn.execute(
        "SELECT muscle_group, mev_sets, mrv_sets FROM muscle_volume_targets "
        "WHERE mesocycle_id = '' ORDER BY muscle_group"
    ).fetchall()
    out: list[Parameter] = []
    for muscle, mev, mrv in rows:
        n = len(muscle_weekly_volume_series(conn, muscle, 104))
        gated = n >= _LANDMARK_MIN_WEEKS
        name = str(muscle).replace("_", " ")
        for kind, value, words in (
            ("mev", mev, "fewest weekly sets that still grow"),
            ("mrv", mrv, "most weekly sets he recovers from"),
        ):
            out.append(
                Parameter(
                    f"landmark.{muscle}.{kind}", "training", f"{name}: {words}",
                    "sets/week", None, None, NO_PRIOR,
                    float(value) if gated else None, None, "fitted", n,
                    "muscle_volume_targets", _LANDMARK_MIN_WEEKS,
                )
            )  # fmt: skip
    return out


def _acwr(conn: duckdb.DuckDBPyConnection) -> list[Parameter]:
    from shc.metrics import (
        _ACWR_TIGHTEN_MIN_WEEKS,
        COND_ACWR_FORBID_LEGS,
        COND_ACWR_HOLD_LEGS,
        _acwr_band_sample_weeks,
        personalized_cond_thresholds,
    )

    n = _acwr_band_sample_weeks(conn)[1]
    hold, forbid = personalized_cond_thresholds(conn)
    out: list[Parameter] = []
    for key, label, prior, live in (
        ("cond_acwr_hold_legs", "Court load at which leg training is cut back",
         COND_ACWR_HOLD_LEGS, hold),
        ("cond_acwr_forbid_legs", "Court load at which leg training is blocked",
         COND_ACWR_FORBID_LEGS, forbid),
    ):  # fmt: skip
        out.append(
            Parameter(
                key, "training", label, "ratio of this week to the last 3",
                float(prior), None, _ACWR_NOTE,
                float(live) if n > 0 else None, None, "fitted", n,
                "metrics.personalized_cond_thresholds", _ACWR_TIGHTEN_MIN_WEEKS,
            )
        )  # fmt: skip
    return out


def _sleep(conn: duckdb.DuckDBPyConnection) -> list[Parameter]:
    from shc.training.self_learning import _SLEEP_MIN_NIGHTS, read_sleep_bands

    bands = read_sleep_bands(conn) or {}
    row = conn.execute("SELECT MAX(sample_nights) FROM personal_sleep_bands").fetchone()
    n = int(row[0]) if row and row[0] is not None else 0
    out: list[Parameter] = []
    for key, band, label, unit in (
        ("sleep_disturbance_p80", "DISTURBANCE_P80",
         "Nightly disturbances that count as a restless night", "disturbances/night"),
        ("sleep_cycle_p20", "CYCLE_P20",
         "Sleep cycles below which a night counts as short", "cycles/night"),
    ):  # fmt: skip
        out.append(
            Parameter(
                key, "sleep", label, unit, None, None, NO_PRIOR,
                bands.get(band), None, "fitted", n,
                "metrics sleep-architecture gate", _SLEEP_MIN_NIGHTS,
            )
        )  # fmt: skip
    return out


def _noise_floors(conn: duckdb.DuckDBPyConnection) -> list[Parameter]:
    from shc.stats.noise_floor import swc

    out: list[Parameter] = []
    for column, key, label, unit in (
        ("hrv", "noise_hrv", "Smallest HRV change that is more than his normal swing", "ms"),
        ("rhr", "noise_rhr", "Smallest resting-heart-rate change that is more than his normal swing", "bpm"),
    ):  # fmt: skip
        vals = [
            float(r[0])
            for r in conn.execute(
                f"""
                SELECT AVG({column}) FROM recovery
                WHERE {column} IS NOT NULL
                  AND date >= CURRENT_DATE - INTERVAL '{_NOISE_WINDOW_DAYS} DAYS'
                GROUP BY date ORDER BY date
                """
            ).fetchall()
        ]
        out.append(
            Parameter(
                key, "recovery", label, unit, None, None, NO_PRIOR,
                swc(vals), None, "observed", len(vals), "stats.noise_floor", 7,
            )
        )  # fmt: skip
    return out


def _lift_noise(conn: duckdb.DuckDBPyConnection) -> list[Parameter]:
    per_hand = per_hand_sql("weight_kg", "exercise")
    eff = effective_reps_sql("reps", "rpe")
    rows = conn.execute(
        f"""
        SELECT exercise, day_d, MAX(({per_hand}) * (1 + ({eff}) / 30.0)) AS e1rm
        FROM workout_sets_dedup
        WHERE NOT COALESCE(is_warmup, FALSE) AND weight_kg > 0 AND reps > 0
          AND day_d >= CURRENT_DATE - INTERVAL '180 DAYS'
        GROUP BY exercise, day_d ORDER BY exercise, day_d
        """
    ).fetchall()
    series: dict[str, list[float]] = {}
    for exercise, _day, e1rm in rows:
        if e1rm and e1rm > 0:
            series.setdefault(str(exercise), []).append(float(e1rm))
    ranked = sorted(series.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:_LIFT_TOP_N]
    out: list[Parameter] = []
    for exercise, vals in ranked:
        if len(vals) < _LIFT_MIN_SESSIONS:
            continue
        # Successive-session log ratios remove the slow trend; /sqrt(2) turns a
        # difference's spread back into one session's spread.
        diffs = [100.0 * (vals[i + 1] / vals[i] - 1.0) for i in range(len(vals) - 1)]
        noise = statistics.stdev(diffs) / (2**0.5)
        out.append(
            Parameter(
                f"lift_noise.{_slug(exercise)}", "training",
                f"{exercise}: session-to-session swing in estimated max",
                "% of e1RM", None, None, NO_PRIOR, noise, None, "observed",
                len(vals), "stats.noise_floor", _LIFT_MIN_SESSIONS,
            )
        )  # fmt: skip
    return out


def _beliefs(conn: duckdb.DuckDBPyConnection) -> list[Parameter]:
    rows = conn.execute(
        "SELECT id, claim, outcome, unit, prior_mean, prior_sd, prior_source, "
        "post_mean, post_sd, n_results FROM research_beliefs ORDER BY created_at, id"
    ).fetchall()
    out: list[Parameter] = []
    for bid, claim, outcome, unit, pm, psd, src, post_m, post_s, n in rows:
        o = str(outcome).lower()
        domain = (
            "sleep" if "sleep" in o
            else "recovery" if any(t in o for t in ("hrv", "rhr", "recovery"))
            else "training"
        )  # fmt: skip
        src = re.sub(r"^\[\[|\]\]$", "", str(src).strip())
        if src and not src.endswith(".md"):
            src += ".md"
        out.append(
            Parameter(
                f"belief.{bid}", domain, str(claim), unit,
                float(pm), float(psd), src, float(post_m), float(post_s),
                "experiment", int(n), "research_beliefs", _BELIEF_MIN_RESULTS,
            )
        )  # fmt: skip
    return out


def _store(conn: duckdb.DuckDBPyConnection, p: Parameter) -> bool:
    """Validate and upsert one parameter; return True if the row changed."""
    if p.domain not in DOMAINS:
        raise ValueError(f"unknown domain {p.domain!r}")
    validate_citation(p.prior_source, p.prior_mean, p.prior_sd)
    n = max(p.n_evidence, 0)
    # No evidence, or nothing fitted yet: show the prior unchanged.
    use_prior = n == 0 or p.post_mean is None
    post_mean = p.prior_mean if use_prior else p.post_mean
    post_sd = p.prior_sd if use_prior else p.post_sd
    row: tuple[Any, ...] = (
        p.domain, p.label, p.unit, p.prior_mean, p.prior_sd, p.prior_source,
        post_mean, post_sd, p.evidence_kind, n, p.consumer, status_for(n, p.min_n),
    )  # fmt: skip
    cols = ", ".join(_COLUMNS)
    existing = conn.execute(f"SELECT {cols} FROM rob_parameters WHERE key = ?", [p.key]).fetchone()
    if existing is None:
        conn.execute(
            f"INSERT INTO rob_parameters (key, {cols}) VALUES (?, {', '.join('?' * len(row))})",
            [p.key, *row],
        )
        return True
    if tuple(existing) == row:
        return False
    sets = ", ".join(f"{c} = ?" for c in _COLUMNS)
    conn.execute(
        f"UPDATE rob_parameters SET {sets}, updated_at = now() WHERE key = ?",
        [*row, p.key],
    )
    return True


def refresh(conn: duckdb.DuckDBPyConnection) -> dict[str, Any]:
    """Seed and refresh every parameter by reading what the engine already fits.

    Args:
        conn: A write connection.

    Returns:
        ``{"written", "unchanged", "skipped"}``; ``skipped`` lists ``{key, reason}``
        for a parameter that failed validation or whose source table could not be
        read, so nothing is dropped silently.
    """
    written = unchanged = 0
    skipped: list[dict[str, str]] = []
    for collect in (_landmarks, _acwr, _sleep, _noise_floors, _lift_noise, _beliefs):
        try:
            params = collect(conn)
        except duckdb.Error as exc:
            log.warning("rob_model: %s unreadable: %s", collect.__name__, exc)
            skipped.append({"key": collect.__name__.lstrip("_"), "reason": str(exc)})
            continue
        for p in params:
            try:
                changed = _store(conn, p)
            except ValueError as exc:
                skipped.append({"key": p.key, "reason": str(exc)})
                continue
            written += changed
            unchanged += not changed
    return {"written": written, "unchanged": unchanged, "skipped": skipped}


def read_all(conn: duckdb.DuckDBPyConnection) -> dict[str, list[dict[str, Any]]]:
    """Stored parameters grouped by domain, in plain-words field names. Read-only."""
    rows = conn.execute(
        f"SELECT key, {', '.join(_COLUMNS)}, updated_at FROM rob_parameters ORDER BY domain, key"
    ).fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {d: [] for d in DOMAINS}
    for r in rows:
        key, domain, label, unit, pm, psd, src, post_m, post_s, kind, n, consumer, status, ts = r
        grouped[domain].append(
            {
                "key": key,
                "label": label,
                "unit": unit,
                "literature": {"mean": pm, "sd": psd, "source": src},
                "rob": {"mean": post_m, "sd": post_s},
                "how_sure": status,
                "evidence": {"kind": kind, "n": n},
                "changes": consumer,
                "updated_at": ts.isoformat() if ts else None,
            }
        )
    return {d: v for d, v in grouped.items() if v}
