"""n-of-1 self-experiment engine — end-to-end loop + verdict + governance tests."""

from __future__ import annotations

from datetime import date, timedelta

from shc import selflab


def _prereg(conn, **over):
    kw = dict(
        slug="caffeine-bench",
        hypothesis="Pre-lift caffeine raises top-set bench e1RM.",
        manipulated="pre_lift_caffeine",
        condition_a="none",
        condition_b="200mg",
        outcome_metric="top_set_e1rm:Bench Press (Barbell)",
        min_per_arm=6,
        min_effect=2.0,
    )
    kw.update(over)
    return selflab.preregister(conn, **kw)


def _log(conn, exp_id, day, arm, outcome, adhered=True):
    conn.execute(
        "INSERT INTO experiment_log (experiment_id, day, assigned_arm, adhered, outcome_value) "
        "VALUES (?, ?, ?, ?, ?)",
        [exp_id, day.isoformat(), arm, adhered, outcome],
    )


def _fill(conn, exp_id, a_vals, b_vals):
    base = date(2025, 1, 1)
    d = base
    for v in a_vals:
        _log(conn, exp_id, d, "A", v)
        d += timedelta(days=1)
    for v in b_vals:
        _log(conn, exp_id, d, "B", v)
        d += timedelta(days=1)


# ── Assignment: deterministic, balanced, fixed before outcomes ───────────────


def test_arm_assignment_is_deterministic_and_balanced() -> None:
    start = date(2025, 1, 1)
    arms = [selflab.arm_for_day("s", start, start + timedelta(days=i)) for i in range(40)]
    # Deterministic: recomputing gives the same answer.
    assert arms == [selflab.arm_for_day("s", start, start + timedelta(days=i)) for i in range(40)]
    # Balanced: block-of-two design → exactly half A, half B.
    assert arms.count("A") == arms.count("B") == 20
    # Each 2-day block has one of each (no run of same-arm from the design).
    for i in range(0, 40, 2):
        assert {arms[i], arms[i + 1]} == {"A", "B"}


# ── Verdicts ─────────────────────────────────────────────────────────────────


def test_confirmed_writes_governed_prior(conn) -> None:
    exp = _prereg(conn)
    _fill(conn, exp, [100, 101, 99, 100, 102, 98], [110, 111, 109, 112, 108, 110])
    r = selflab.score(conn, exp)
    assert r["verdict"] == "CONFIRMED", r
    assert 9 <= r["effect"] <= 11
    assert r["effect_ci_low"] > 0  # CI excludes zero
    priors = selflab.active_priors(conn)
    assert len(priors) == 1
    assert priors[0]["key"] == "pre_lift_caffeine.top_set_e1rm_pct"
    assert priors[0]["effect"] > 0  # +~10% of baseline


def test_insufficient_n_never_emits_a_prior(conn) -> None:
    exp = _prereg(conn)
    _fill(conn, exp, [100, 101, 99], [110, 111, 112])  # 3 per arm, need 6
    r = selflab.score(conn, exp)
    assert r["verdict"] == "INSUFFICIENT_N"
    assert selflab.active_priors(conn) == []


def test_noisy_overlap_is_inconclusive(conn) -> None:
    exp = _prereg(conn, min_effect=5.0)
    _fill(conn, exp, [100, 108, 92, 111, 89, 101], [103, 96, 110, 90, 112, 99])
    r = selflab.score(conn, exp)
    assert r["verdict"] == "INCONCLUSIVE", r
    assert selflab.active_priors(conn) == []


def test_tight_null_with_min_effect_is_refuted(conn) -> None:
    exp = _prereg(conn, min_effect=5.0)
    _fill(conn, exp, [100, 100, 101, 99, 100, 100], [100, 101, 99, 100, 100, 101])
    r = selflab.score(conn, exp)
    assert r["verdict"] == "REFUTED", r
    assert selflab.active_priors(conn) == []


def test_prior_is_retracted_when_a_study_stops_confirming(conn) -> None:
    exp = _prereg(conn)
    _fill(conn, exp, [100, 101, 99, 100, 102, 98], [110, 111, 109, 112, 108, 110])
    assert selflab.score(conn, exp)["verdict"] == "CONFIRMED"
    assert len(selflab.active_priors(conn)) == 1
    # New data erases the effect → re-score must retract the prior, not leave it stale.
    conn.execute("DELETE FROM experiment_log WHERE experiment_id = ?", [exp])
    _fill(conn, exp, [100, 100, 101, 99, 100, 100], [100, 101, 99, 100, 100, 101])
    r = selflab.score(conn, exp)
    assert r["verdict"] != "CONFIRMED"
    assert selflab.active_priors(conn) == [], "a non-confirmed study left an active prior"


def test_zero_variance_effect_confirms_via_permutation(conn) -> None:
    """A perfectly consistent effect (no within-arm noise) must CONFIRM. Welch's t
    is undefined here (zero variance); the permutation test is defined and correct
    — a flawless separation is the strongest evidence, not the weakest."""
    exp = _prereg(conn)
    _fill(conn, exp, [100, 100, 100, 100, 100, 100], [106, 106, 106, 106, 106, 106])
    r = selflab.score(conn, exp)
    assert r["verdict"] == "CONFIRMED", r
    assert r["p_value"] is not None and r["p_value"] < 0.05
    assert len(selflab.active_priors(conn)) == 1


def test_bootstrap_ci_is_reproducible(conn) -> None:
    exp = _prereg(conn)
    _fill(conn, exp, [100, 101, 99, 100, 102, 98], [110, 111, 109, 112, 108, 110])
    a = selflab.score(conn, exp)
    b = selflab.score(conn, exp)
    assert (a["effect_ci_low"], a["effect_ci_high"]) == (b["effect_ci_low"], b["effect_ci_high"])


# ── Integration: the outcome really comes from the live training data stream ──


def test_full_loop_pulls_outcome_from_training_data(conn, seed) -> None:
    exp = selflab.load(conn, _prereg(conn, min_per_arm=4))
    start = exp.started_on
    # For each day, seed the bench session heavier on assigned-B days, so the
    # engine's own arm assignment (not the test) determines the split.
    for i in range(16):
        day = start + timedelta(days=i)
        arm = selflab.log_day(conn, exp.id, day)  # computes + stores the arm
        # Realistic within-arm noise (real training data is never noiseless) plus
        # a real between-arm shift, so the effect is detectable, not degenerate.
        jitter = (i % 3) - 1  # -1, 0, +1
        weight = (105.0 if arm == "B" else 100.0) + jitter
        seed.workout(day, "Bench Press (Barbell)", [(weight, 5)], rpe=8.0)
    filled = selflab.refresh_outcomes(conn, exp.id)
    assert filled == 16
    r = selflab.score(conn, exp.id)
    assert r["verdict"] == "CONFIRMED", r
    assert r["effect"] > 0
