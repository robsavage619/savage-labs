"""Mesocycle volume-landmark guards."""

from __future__ import annotations


# --- Undertrained-landmark floor (2026-08-08) --------------------------------


def _seed_targets(conn, muscle, pop, personal, meso_id="m1"):
    conn.execute("DELETE FROM muscle_volume_targets WHERE muscle_group = ?", [muscle])
    conn.execute(
        "INSERT INTO muscle_volume_targets "
        "(muscle_group, mev_sets, mav_sets, mrv_sets, mesocycle_id, mv_sets, tier) "
        "VALUES (?, ?, ?, ?, '', 2, 'grow')",
        [muscle, *pop],
    )
    conn.execute(
        "INSERT INTO muscle_volume_targets "
        "(muscle_group, mev_sets, mav_sets, mrv_sets, mesocycle_id, mv_sets, tier) "
        "VALUES (?, ?, ?, ?, ?, 2, 'grow')",
        [muscle, *personal, meso_id],
    )


def test_fitted_mrv_at_exactly_half_population_is_floored(conn) -> None:
    """The guard used `<`, so a fit landing EXACTLY on half slipped through.

    Live quads sat at fitted MRV 10 against a population 20: `10 < 10` is False,
    so the muscle kept a personal CEILING of 10 while its curated brief asks for
    12-18. The boundary case is the common one because the fit is percentile-based.
    """
    from shc.training.mesocycle import volume_targets

    _seed_targets(conn, "quads", pop=(8, 14, 20), personal=(8, 9, 10))
    vt = volume_targets(conn, meso_id="m1")["quads"]
    assert vt.source == "personal_floored"
    assert vt.mrv >= 20


def test_fitted_mev_below_curated_brief_is_floored(conn) -> None:
    """Two volume authorities are printed in the same planner block; the lower
    one was silently winning. Abs: brief 12-20, fitted MEV 6 -> ~6 sets/wk, which
    is one exercise a session."""
    from shc.training.mesocycle import volume_targets

    low = conn.execute(
        "SELECT weekly_sets_low FROM muscle_development WHERE muscle = 'abs'"
    ).fetchone()
    assert low and low[0] >= 12, "fixture drift: abs brief no longer asks 12+"
    _seed_targets(conn, "abs", pop=(6, 12, 20), personal=(6, 13, 20))
    vt = volume_targets(conn, meso_id="m1")["abs"]
    assert vt.source == "personal_floored"
    assert vt.mev >= low[0]


def test_healthy_fit_is_left_alone(conn) -> None:
    """The floor must not overwrite a genuine personal fit."""
    from shc.training.mesocycle import volume_targets

    _seed_targets(conn, "biceps", pop=(8, 14, 20), personal=(12, 16, 20))
    vt = volume_targets(conn, meso_id="m1")["biceps"]
    assert vt.source == "personal"
    assert (vt.mev, vt.mrv) == (12, 20)
