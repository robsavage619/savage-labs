from __future__ import annotations

"""Subject profile aggregator — the centrepiece of the /lab route.

Composes self-learning, selflab, autoregulation, and oauth status into a single
dossier for SUBJECT 001. Pure composition: no new science, no new tables.
"""

import logging

import duckdb
from fastapi import APIRouter

from shc.db.schema import get_read_conn

log = logging.getLogger(__name__)

router = APIRouter(tags=["subject"])

# Population default ACWR rest threshold (resistance arm).
_POP_RES_ACWR_REST = 2.0


def _enrolled_on(conn: duckdb.DuckDBPyConnection) -> str | None:
    row = conn.execute(
        """
        SELECT MIN(dt) FROM (
            SELECT MIN(date)             AS dt FROM recovery
            UNION ALL
            SELECT MIN(night_date)       AS dt FROM sleep
            UNION ALL
            SELECT MIN(started_at::DATE) AS dt FROM workouts
        )
        """
    ).fetchone()
    return str(row[0]) if row and row[0] is not None else None


def _days_observed(conn: duckdb.DuckDBPyConnection, enrolled_on: str | None) -> int | None:
    if enrolled_on is None:
        return None
    row = conn.execute(
        "SELECT (CURRENT_DATE - ?::DATE)::INTEGER", [enrolled_on]
    ).fetchone()
    return int(row[0]) if row and row[0] is not None else None


def _personalization(conn: duckdb.DuckDBPyConnection) -> dict:
    from shc.training.mesocycle import active_mesocycle
    from shc.training.self_learning import read_acwr_bands, read_deload_calibration, read_sleep_bands

    state = active_mesocycle(conn)
    meso_id = state.id if state else ""

    total_row = conn.execute(
        "SELECT COUNT(DISTINCT primary_muscle) FROM exercise_muscle_map"
    ).fetchone()
    total_muscles = int(total_row[0]) if total_row else 0

    fitted_row = conn.execute(
        "SELECT COUNT(DISTINCT muscle_group) FROM muscle_volume_targets WHERE mesocycle_id = ?",
        [meso_id],
    ).fetchone()
    fitted_muscles = int(fitted_row[0]) if (fitted_row and meso_id) else 0

    acwr_bands = read_acwr_bands(conn)
    sleep_bands = read_sleep_bands(conn)
    deload_cal = read_deload_calibration(conn)
    deload_fitted = not deload_cal.get("using_population_defaults", True)

    fitted_params = (
        fitted_muscles
        + (1 if acwr_bands is not None else 0)
        + (1 if sleep_bands is not None else 0)
        + (1 if deload_fitted else 0)
    )
    total_params = total_muscles + 3  # N muscles + ACWR + sleep + deload

    return {
        "fitted_params": fitted_params,
        "total_params": total_params,
        "families": {
            "volume_landmarks": {"fitted": fitted_muscles, "total": total_muscles},
            "acwr_bands": acwr_bands is not None,
            "sleep_bands": sleep_bands is not None,
            "deload_trigger": deload_fitted,
        },
    }


def _phenotype_tags(
    conn: duckdb.DuckDBPyConnection,
    pers: dict,
    accuracy: dict,
    acwr_bands: dict | None,
) -> list[str]:
    tags: list[str] = []

    vl = pers["families"]["volume_landmarks"]
    if vl["fitted"] > 0:
        tags.append(
            f"Volume landmarks personalized for {vl['fitted']}/{vl['total']} muscles"
        )

    if acwr_bands:
        personal_rest = acwr_bands.get("RES_ACWR_REST")
        if personal_rest is not None:
            pct = round(abs(personal_rest - _POP_RES_ACWR_REST) / _POP_RES_ACWR_REST * 100)
            direction = "tighter" if personal_rest < _POP_RES_ACWR_REST else "higher"
            row = conn.execute(
                "SELECT sample_weeks FROM personal_acwr_bands "
                "WHERE arm = 'resistance' AND threshold_name = 'rest' LIMIT 1"
            ).fetchone()
            n_wk = f" ({int(row[0])} wk)" if row and row[0] else ""
            tags.append(f"Load tolerance {direction} than population by {pct}%{n_wk}")

    overall = accuracy.get("overall")
    n_scored = accuracy.get("n_scored", 0)
    if overall is not None and isinstance(n_scored, int) and n_scored >= 100:
        tags.append(
            f"Engine self-accuracy {round(overall * 100)}% over {n_scored:,} scored prescriptions"
        )

    try:
        from shc.training.self_learning import read_signal_quality_cache

        sq = read_signal_quality_cache(conn)
        undertrained = [m for m, q in sq.items() if q.get("undertrained")]
        if undertrained:
            suffix = " + more" if len(undertrained) > 3 else ""
            tags.append(f"Undertrained: {', '.join(undertrained[:3])}{suffix}")
    except Exception:
        pass

    return tags


def build_subject_profile(conn: duckdb.DuckDBPyConnection) -> dict:
    """Compose the full subject dossier from existing engine functions."""
    from shc import selflab
    from shc.training.autoregulation import muscle_science_report
    from shc.training.self_learning import (
        detect_accuracy_degradation,
        prescription_accuracy,
        read_accuracy_history,
        read_acwr_bands,
    )

    enrolled_on = _enrolled_on(conn)
    days_observed = _days_observed(conn, enrolled_on)

    oauth_rows = conn.execute(
        "SELECT source, last_sync_at, needs_reauth FROM oauth_state"
    ).fetchall()
    data_sources = [
        {"source": r[0], "last_sync_at": str(r[1]), "streaming": not r[2]}
        for r in oauth_rows
    ]

    pers = _personalization(conn)
    accuracy = prescription_accuracy(conn)
    history = read_accuracy_history(conn, weeks=26)
    degradation = detect_accuracy_degradation(conn)
    acwr_bands = read_acwr_bands(conn)

    phenotype = _phenotype_tags(conn, pers, accuracy, acwr_bands)

    exp_list = selflab.overview(conn)
    confirmed = sum(
        1 for e in exp_list if e.get("result") and e["result"]["verdict"] == "CONFIRMED"
    )
    active_priors_list = selflab.active_priors(conn)

    science = muscle_science_report(conn)
    total_muscles = len(science)
    personalized_muscles = sum(1 for m in science if m["data_coverage"]["personalized"])

    return {
        "subject_id": "001",
        "name": "Rob Savage",
        "enrolled_on": enrolled_on,
        "days_observed": days_observed,
        "data_sources": data_sources,
        "personalization": pers,
        "phenotype": phenotype,
        "experiments": {
            "registered": len(exp_list),
            "confirmed": confirmed,
            "active_priors": len(active_priors_list),
        },
        "engine_accuracy": {
            "current": accuracy.get("overall"),
            "n_scored": accuracy.get("n_scored"),
            "trend": degradation.get("delta"),
            "degrading": degradation.get("degrading"),
            "history": history,
        },
        "muscle_coverage": {
            "personalized": personalized_muscles,
            "total": total_muscles,
        },
    }


@router.get("/subject/profile")
async def get_subject_profile() -> dict:
    conn = get_read_conn()
    try:
        return build_subject_profile(conn)
    finally:
        conn.close()
