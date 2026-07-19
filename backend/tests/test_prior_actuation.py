"""Deterministic actuation of CONFIRMED n-of-1 priors into the volume decision.

Covers the loop selflab.py -> autoregulation.weekly_prescription: a
preregistered actuation target, once CONFIRMED, must change a concrete
prescribed number — and stop changing it the moment the prior is retracted.
"""

from __future__ import annotations

from datetime import date, timedelta

from shc import selflab
from shc.training.autoregulation import weekly_prescription


def _prereg_with_actuation(conn, **over):
    kw = dict(
        slug="caffeine-chest",
        hypothesis="Pre-lift caffeine raises chest e1RM.",
        manipulated="pre_lift_caffeine",
        condition_a="none",
        condition_b="200mg",
        outcome_metric="top_set_e1rm:Bench Press (Barbell)",
        min_per_arm=6,
        min_effect=2.0,
        actuation_target_kind="volume_target",
        actuation_target_key="chest",
        actuation_direction="+",
        actuation_magnitude_pct=10.0,
        actuation_cap_pct=10.0,
    )
    kw.update(over)
    return selflab.preregister(conn, **kw)


def _fill(conn, exp_id, a_vals, b_vals):
    base = date(2025, 1, 1)
    d = base
    for v in a_vals:
        conn.execute(
            "INSERT INTO experiment_log (experiment_id, day, assigned_arm, adhered, outcome_value) "
            "VALUES (?, ?, 'A', TRUE, ?)",
            [exp_id, d.isoformat(), v],
        )
        d += timedelta(days=1)
    for v in b_vals:
        conn.execute(
            "INSERT INTO experiment_log (experiment_id, day, assigned_arm, adhered, outcome_value) "
            "VALUES (?, ?, 'B', TRUE, ?)",
            [exp_id, d.isoformat(), v],
        )
        d += timedelta(days=1)


def test_preregister_validates_actuation_fields(conn) -> None:
    import pytest

    with pytest.raises(ValueError, match="all-or-nothing"):
        _prereg_with_actuation(conn, actuation_target_kind=None)
    with pytest.raises(ValueError, match="target_kind"):
        _prereg_with_actuation(conn, actuation_target_kind="not_a_real_kind")
    with pytest.raises(ValueError, match="direction"):
        _prereg_with_actuation(conn, actuation_direction="up")
    with pytest.raises(ValueError, match="magnitude_pct"):
        _prereg_with_actuation(conn, actuation_magnitude_pct=0.0)
    with pytest.raises(ValueError, match="must not exceed"):
        _prereg_with_actuation(conn, actuation_magnitude_pct=20.0, actuation_cap_pct=10.0)


def test_confirmed_prior_changes_a_concrete_prescribed_number(conn, seed) -> None:
    """The whole loop: preregister with an actuation target, confirm it with a
    strong effect, and verify weekly_prescription's chest target actually
    moved — not just that a prior row exists."""
    today = date.today()
    seed.workout(today, "Bench Press (Barbell)", [(100.0, 8)] * 3)

    baseline_rx = weekly_prescription(conn)
    chest_before = next(m for m in baseline_rx.muscles if m.muscle == "chest")

    exp_id = _prereg_with_actuation(conn)
    _fill(conn, exp_id, [100, 101, 99, 100, 102, 98], [110, 111, 109, 112, 108, 110])
    result = selflab.score(conn, exp_id)
    assert result["verdict"] == "CONFIRMED", result

    actuated = selflab.read_active_volume_target_actuations(conn)
    assert actuated.get("chest") == 1.10

    rx = weekly_prescription(conn)
    chest_after = next(m for m in rx.muscles if m.muscle == "chest")

    from shc.training.mesocycle import volume_targets

    vt = volume_targets(conn, "")["chest"]
    expected = max(vt.mev, min(vt.mrv, round(chest_before.target_sets * 1.10)))

    assert "confirmed prior" in chest_after.reason
    assert chest_after.target_sets == expected
    assert expected != chest_before.target_sets, (
        "fixture didn't actually exercise the actuation — pre/post targets are equal"
    )


def test_retracted_prior_no_longer_actuates(conn, seed) -> None:
    """A study that stops CONFIRMING must stop moving the target — score()
    already retracts the prior row (active=FALSE); confirm the actuation
    read path (and therefore weekly_prescription) honors that."""
    today = date.today()
    seed.workout(today, "Bench Press (Barbell)", [(100.0, 8)] * 3)

    exp_id = _prereg_with_actuation(conn)
    _fill(conn, exp_id, [100, 101, 99, 100, 102, 98], [110, 111, 109, 112, 108, 110])
    assert selflab.score(conn, exp_id)["verdict"] == "CONFIRMED"
    assert selflab.read_active_volume_target_actuations(conn).get("chest") == 1.10

    # Re-log a null/noisy result and re-score: the study stops confirming.
    conn.execute("DELETE FROM experiment_log WHERE experiment_id = ?", [exp_id])
    _fill(conn, exp_id, [100, 108, 92, 111, 89, 101], [103, 96, 110, 90, 112, 99])
    result = selflab.score(conn, exp_id)
    assert result["verdict"] != "CONFIRMED", result

    actuated = selflab.read_active_volume_target_actuations(conn)
    assert "chest" not in actuated

    rx = weekly_prescription(conn)
    chest = next(m for m in rx.muscles if m.muscle == "chest")
    assert "confirmed prior" not in chest.reason


def test_actuation_never_breaches_mrv(conn, seed) -> None:
    """An actuated target must never exceed the muscle's MRV, no matter how
    large the confirmed magnitude — the cap_pct bound is enforced at
    preregistration, but weekly_prescription's own MRV clamp is the backstop."""
    today = date.today()
    # Push chest's current volume near its population MRV so a +10% nudge
    # would overshoot without the clamp.
    for wk in range(1):
        seed.workout(
            today - timedelta(weeks=wk),
            "Bench Press (Barbell)",
            [(100.0, 8)] * 10,  # a large session, well up the volume range
        )

    exp_id = _prereg_with_actuation(conn)
    _fill(conn, exp_id, [100, 101, 99, 100, 102, 98], [110, 111, 109, 112, 108, 110])
    assert selflab.score(conn, exp_id)["verdict"] == "CONFIRMED"

    rx = weekly_prescription(conn)
    chest = next(m for m in rx.muscles if m.muscle == "chest")

    from shc.training.mesocycle import volume_targets

    vt = volume_targets(conn, "")
    mrv = vt["chest"].mrv if "chest" in vt else None
    assert mrv is not None, "fixture must have a chest MRV to make this check meaningful"
    assert chest.target_sets <= mrv


def test_actuation_never_breaches_mev(conn, seed) -> None:
    """Symmetric check for the MEV floor with a negative-direction actuation."""
    today = date.today()
    seed.workout(today, "Bench Press (Barbell)", [(100.0, 8)] * 3)

    exp_id = _prereg_with_actuation(
        conn, slug="stress-chest", actuation_direction="-", actuation_magnitude_pct=50.0,
        actuation_cap_pct=50.0,
    )
    _fill(conn, exp_id, [100, 101, 99, 100, 102, 98], [90, 89, 91, 88, 92, 90])
    result = selflab.score(conn, exp_id)
    assert result["verdict"] == "CONFIRMED", result

    from shc.training.mesocycle import volume_targets

    vt = volume_targets(conn, "")
    mev = vt["chest"].mev if "chest" in vt else None
    assert mev is not None, "fixture must have a chest MEV to make this check meaningful"

    rx = weekly_prescription(conn)
    chest = next(m for m in rx.muscles if m.muscle == "chest")
    assert chest.target_sets >= mev
