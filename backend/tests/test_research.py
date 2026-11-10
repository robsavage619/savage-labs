from __future__ import annotations

import math
import random
from datetime import date, timedelta

import pytest

from shc import research

TODAY = date(2026, 6, 30)


def _seed(conn, effect_pct: float, days: int = 360, seed: int = 3) -> None:
    """Strain on day d moves day d+1's HRV by `effect_pct` when strain is high."""
    rng = random.Random(seed)
    start = TODAY - timedelta(days=days)
    high_prev = False
    for i in range(days + 1):
        d = start + timedelta(days=i)
        high = rng.random() < 0.5
        strain = rng.uniform(14, 18) if high else rng.uniform(4, 9)
        ln = math.log(100) + rng.gauss(0, 0.18) + (effect_pct / 100 if high_prev else 0.0)
        conn.execute(
            "INSERT INTO recovery (id, source, date, score, hrv, rhr, content_hash) VALUES (?, 'whoop', ?, 60, ?, 50, ?)",
            [f"r{i}", d, math.exp(ln), f"h{i}"],
        )
        conn.execute(
            "INSERT INTO daily_cycle (id, date, strain, content_hash) VALUES (?, ?, ?, ?)",
            [f"c{i}", d, strain, f"k{i}"],
        )
        high_prev = high


SPEC = {
    "exposure": {"feature": "strain", "a": {"max": 10}, "b": {"min": 14}},
    "outcome": "lnhrv_dev_pct",
    "lag": 1,
    "unit": "day",
    "expected_sign": "-",
    "min_effect": 3,
}


def test_recovers_a_planted_effect_inside_its_range(conn) -> None:
    _seed(conn, effect_pct=-10)
    res = research.estimate(conn, SPEC, today=TODAY)
    assert res["ci_low"] <= -10 <= res["ci_high"]
    assert res["verdict"] == "supported"
    assert res["power"]["needed_per_arm"] > 0


def test_null_effect_is_not_supported(conn) -> None:
    _seed(conn, effect_pct=0)
    res = research.estimate(conn, SPEC, today=TODAY)
    assert res["ci_low"] < 0 < res["ci_high"]
    assert res["verdict"] in ("inconclusive", "ruled_out")


def test_belief_posterior_sits_between_prior_and_data_and_narrows(conn) -> None:
    _seed(conn, effect_pct=-10)
    bid = research.add_belief(
        conn,
        "Hard days lower tomorrow's HRV",
        "lnhrv_dev_pct",
        -3.0,
        5.0,
        "test prior",
        None,
        "test",
    )
    research.register(
        conn, "strain-hrv", "Does a hard day lower tomorrow's HRV?", SPEC, bid, "test"
    )
    res = research.run(conn, "strain-hrv")
    b = next(x for x in research.beliefs(conn) if x["id"] == bid)
    assert min(-3.0, res["effect"]) <= b["post_mean"] <= max(-3.0, res["effect"])
    assert b["post_sd"] < 5.0
    # Re-running must not count the same days twice.
    research.run(conn, "strain-hrv")
    again = next(x for x in research.beliefs(conn) if x["id"] == bid)
    assert again["post_sd"] == pytest.approx(b["post_sd"], rel=0.05)


def test_specs_are_immutable_and_validated(conn) -> None:
    _seed(conn, effect_pct=0, days=60)
    research.register(conn, "s1", "q", SPEC, None, "test")
    with pytest.raises(research.SpecError):
        research.register(conn, "s1", "q", SPEC, None, "test")
    bad = SPEC | {"exposure": {"feature": "strain", "a": {"max": 12}, "b": {"min": 10}}}
    with pytest.raises(research.SpecError, match="overlap"):
        research.validate_spec(conn, bad)
    with pytest.raises(research.SpecError, match="unknown feature"):
        research.validate_spec(conn, SPEC | {"outcome": "made_up"})


def test_notebook_records_each_step(conn) -> None:
    _seed(conn, effect_pct=0, days=60)
    research.register(conn, "s2", "Short trial", SPEC, None, "analyst")
    research.run(conn, "s2", author="runner")
    kinds = [n["kind"] for n in research.notebook(conn)]
    assert kinds[:2] == ["result", "proposal"]


def test_estimate_never_sees_days_after_its_date(conn) -> None:
    _seed(conn, effect_pct=-10)
    cut = TODAY - timedelta(days=120)
    early = research.estimate(conn, SPEC, today=cut)
    full = research.estimate(conn, SPEC, today=TODAY)
    assert early["n_a"] + early["n_b"] < full["n_a"] + full["n_b"] - 100


def _setup_belief(conn, effect_pct: float) -> str:
    _seed(conn, effect_pct=effect_pct, days=420)
    bid = research.add_belief(
        conn, "Hard days lower HRV", "lnhrv_dev_pct", -3.0, 5.0, "test prior", None, "test"
    )
    research.register(conn, "strain-hrv", "q", SPEC, bid, "test")
    research.review(conn, "strain-hrv", "approve", "sized and adjusted", "methodologist")
    return bid


def test_backtest_finds_skill_in_a_real_effect_and_credits_its_belief(conn) -> None:
    bid = _setup_belief(conn, effect_pct=-15)
    bt = research.backtest(conn, today=TODAY)
    assert bt["n"] > 100
    assert bt["skill"] > 0
    assert bt["gains"][bid] > 0


def test_backtest_shows_no_skill_from_noise(conn) -> None:
    _setup_belief(conn, effect_pct=0)
    bt = research.backtest(conn, today=TODAY)
    assert bt["skill"] < 0.02


def test_live_forecast_is_logged_before_the_reading_and_scored_after(conn) -> None:
    _setup_belief(conn, effect_pct=-15)
    tomorrow = TODAY + timedelta(days=1)
    made = research.forecast_today(conn, today=tomorrow)
    assert made is not None and made["target_date"] == str(tomorrow)
    # Once the morning's reading exists, no second forecast is made and the first is scored.
    conn.execute(
        "INSERT INTO recovery (id, source, date, score, hrv, rhr, content_hash) VALUES ('rx', 'whoop', ?, 60, 90, 50, 'hx')",
        [tomorrow],
    )
    assert research.forecast_today(conn, today=tomorrow) is None
    view = research.forecast_view(conn)
    assert view["live"][-1]["actual"] is not None


def test_new_questions_wait_for_review_and_only_active_ones_run(conn) -> None:
    _seed(conn, effect_pct=0, days=60)
    out = research.register(conn, "s3", "q", SPEC, None, "analyst")
    assert out["status"] == "proposed"
    assert research.run_all(conn) == []
    queue = research.review_queue(conn)
    assert [q["slug"] for q in queue] == ["s3"]
    assert "rationale" not in queue[0]
    research.review(conn, "s3", "reject", "confounded by weekday", "methodologist")
    assert research.run_all(conn) == []
    with pytest.raises(research.SpecError):
        research.review(conn, "s3", "approve", "changed my mind", "methodologist")


def test_value_score_rewards_open_feasible_new_questions(conn) -> None:
    _seed(conn, effect_pct=-10)
    fast = {"needed_per_arm": 50, "days_to_answer": 30, "outcome_sd": 10}
    slow = {"needed_per_arm": 900, "days_to_answer": 1200, "outcome_sd": 20}
    assert (
        research.value_score(conn, SPEC, None, fast)["value"]
        > research.value_score(conn, SPEC, None, slow)["value"]
    )
    research.register(conn, "s4", "q", SPEC, None, "analyst")
    assert research.value_score(conn, SPEC, None, fast)["novelty"] == 0.0
    sibling = SPEC | {"lag": 2}
    assert research.value_score(conn, sibling, None, fast)["novelty"] == 0.5
    with pytest.raises(research.SpecError, match="identical"):
        research.register(conn, "s5", "q", SPEC, None, "analyst")


def test_cumulative_features_are_daily_totals_from_one_source(conn) -> None:
    day = date(2026, 6, 1)
    rows = [
        ("apple", "apple:a1", 9, 3000.0),
        ("apple", "apple:a2", 15, 4500.0),
        # A daily summary from a second source must not be added on top.
        ("hae", "hae:d1", 23, 7400.0),
    ]
    for src, ext, hour, v in rows:
        conn.execute(
            "INSERT INTO measurements (source, metric, ts, value_num, external_id, content_hash) "
            "VALUES (?, 'step_count', ?, ?, ?, ?)",
            [src, f"{day} {hour:02d}:00:00+00", v, ext, ext],
        )
    assert research.series(conn, "steps")[day] == 7500.0


def test_malformed_adjust_is_a_spec_error_not_a_crash(conn) -> None:
    for bad in ([{"feature": "strain", "lag": 1}], "strain", [3]):
        with pytest.raises(research.SpecError, match="adjust"):
            research.validate_spec(conn, SPEC | {"adjust": bad})


def test_weekend_feature_marks_saturday_and_sunday(conn) -> None:
    _seed(conn, effect_pct=0, days=14)
    s = research.series(conn, "weekend")
    sat = next(d for d in s if d.weekday() == 5)
    assert s[sat] == 1.0 and s[sat + timedelta(days=2)] == 0.0
    research.validate_spec(conn, SPEC | {"adjust": ["weekend"]})


def test_preview_is_the_sum_of_its_named_terms(conn) -> None:
    _setup_belief(conn, effect_pct=-15)
    p = research.forecast_preview(conn, today=TODAY)
    assert p["terms"] and p["target_date"] == str(TODAY + timedelta(days=1))
    assert p["predicted"] == pytest.approx(sum(t["contribution"] for t in p["terms"]))


def test_explainer_fields_are_served(conn) -> None:
    _setup_belief(conn, effect_pct=-15)
    research.run(conn, "strain-hrv")
    h = next(x for x in research.hypotheses(conn) if x["slug"] == "strain-hrv")
    r = h["result"]
    assert r["mean_a"] is not None and r["mean_b"] is not None
    # Raw arm means agree in sign with the planted effect.
    assert r["mean_b"] < r["mean_a"]
    assert h["value_parts"] is not None and h["value_parts"]["value"] == h["value_score"]
    t = research.forecast_preview(conn, today=TODAY)["terms"][0]
    assert t["exposure"] is not None and t["arm_b"] == SPEC["exposure"]["b"]


def test_randomized_trials_log_themselves_from_autolog_date(conn) -> None:
    from shc import selflab

    start = date(2026, 5, 1)
    exp_id = selflab.preregister(
        conn,
        slug="auto-trial",
        hypothesis="X raises Y.",
        manipulated="x",
        condition_a="no x",
        condition_b="x",
        outcome_metric="hrv_next_morning",
        min_effect=3.0,
        started_on=start,
    )
    # A flagged day must survive the automatic pass.
    selflab.log_day(conn, exp_id, start + timedelta(days=2), adhered=False)
    added = selflab.autolog_randomized(conn, exp_id, today=start + timedelta(days=10))
    rows = conn.execute(
        "SELECT day, adhered FROM experiment_log WHERE experiment_id = ? ORDER BY day", [exp_id]
    ).fetchall()
    assert added == 9 and len(rows) == 10
    assert dict(rows)[start + timedelta(days=2)] is False
    a = selflab.todays_assignments(conn, start)
    assert a and a[0]["arm"] == selflab.arm_for_day("auto-trial", start, start)


# ── Goal outcomes ───────────────────────────────────────────────────────────


def _map(conn, exercise: str, muscle: str, role: str = "primary") -> None:
    conn.execute(
        "INSERT INTO exercise_muscle (exercise_name, muscle, role, credit) VALUES (?, ?, ?, ?)",
        [exercise, muscle, role, 1.0 if role == "primary" else 0.5],
    )


def test_per_muscle_features_validate_and_measure(conn, seed) -> None:
    _map(conn, "Synthetic Curl", "biceps")
    _map(conn, "Synthetic Row", "lats")
    _map(conn, "Synthetic Row", "biceps", "secondary")
    _map(conn, "Synthetic Raise", "calves")  # mapped, never trained
    end = TODAY
    # Prior fortnight at 20 kg, this fortnight at 21 kg: same reps, +5% e1RM.
    for k in (20, 17):
        seed.workout(end - timedelta(days=k), "Synthetic Curl", [(20.0, 10)] * 3, rpe=None)
    for k in (6, 2):
        seed.workout(end - timedelta(days=k), "Synthetic Curl", [(21.0, 10)] * 3, rpe=None)
    seed.workout(end - timedelta(days=2), "Synthetic Row", [(40.0, 10)] * 2, rpe=None)
    seed.workout(end - timedelta(days=2), "Synthetic Curl", [(10.0, 10)], rpe=None, is_warmup=True)

    sets = research.series(conn, "sets:biceps")
    # Secondary credit counts at 1.0, the warm-up doesn't count at all.
    assert sets[end - timedelta(days=2)] == 5.0
    assert research.series(conn, "sets:lats")[end - timedelta(days=2)] == 2.0
    pct = research.series(conn, "e1rm_pct14:biceps")
    assert pct[end] == pytest.approx(5.0, abs=0.01)

    assert research.known_feature(conn, "e1rm_pct14:biceps")
    assert not research.known_feature(conn, "sets:not_a_muscle")
    assert not research.known_feature(conn, "sets:")
    research.validate_spec(
        conn,
        SPEC
        | {
            "exposure": SPEC["exposure"] | {"feature": "sets:biceps"},
            "outcome": "e1rm_pct14:biceps",
        },
    )
    names = {f["name"]: f for f in research.dictionary(conn)}
    assert names["e1rm_pct14:biceps"]["unit"] == "%" and names["sets:biceps"]["timing"] == "day"
    assert names["sets:biceps"]["goal"] == "muscle"
    assert "sets:calves" not in names


def test_value_score_weights_outcomes_by_goal(conn) -> None:
    fast = {"needed_per_arm": 50, "days_to_answer": 30, "outcome_sd": 10}
    hrv = research.value_score(conn, SPEC, None, fast)
    muscle = research.value_score(conn, SPEC | {"outcome": "e1rm_pct14:biceps"}, None, fast)
    body = research.value_score(conn, SPEC | {"outcome": "body_mass_7d"}, None, fast)
    other = research.value_score(conn, SPEC | {"outcome": "steps"}, None, fast)
    assert (hrv["goal"], hrv["goal_weight"]) == ("recovery", 0.6)
    assert (muscle["goal"], muscle["goal_weight"]) == ("muscle", 1.0)
    assert body["goal_weight"] == 0.85 and other["goal_weight"] == 0.5
    assert muscle["value"] > body["value"] > hrv["value"] > other["value"]
    assert muscle["value"] / hrv["value"] == pytest.approx(1 / 0.6, rel=0.01)


def test_beliefs_carry_their_outcome_unit_and_a_symmetric_scale(conn) -> None:
    research.add_belief(conn, "Mass holds", "body_mass_7d", 0.0, 0.5, "test prior", None, "t")
    research.add_belief(conn, "Curls help", "e1rm_pct14:biceps", 2.0, 3.0, "test prior", None, "t")
    research.add_belief(conn, "HRV dips", "lnhrv_dev_pct", -3.0, 5.0, "test prior", None, "t")
    research.add_belief(conn, "Override", "steps", 100.0, 50.0, "test prior", None, "t", unit="k")
    by = {b["claim"]: b for b in research.beliefs(conn)}
    assert by["Mass holds"]["unit"] == "lb"
    assert by["Curls help"]["unit"] == "%"
    assert by["Override"]["unit"] == "k"
    assert by["HRV dips"]["scale"] == 15
    for b in by.values():
        assert b["scale"] >= abs(b["prior_mean"]) + 2 * b["prior_sd"]


def _plant_strength(monkeypatch, conn, effect: float, seed: int = 5) -> None:
    """A strength outcome that rises `effect` points a week after a hard day."""
    rng = random.Random(seed)
    strain = research.series(conn, "strain")
    out = {
        d + timedelta(days=7): (effect if s >= 14 else 0.0) + rng.gauss(0, 1.0)
        for d, s in strain.items()
    }
    monkeypatch.setitem(research._DERIVED, research.STRENGTH_METRIC, lambda _c: out)


STRENGTH_SPEC = SPEC | {
    "outcome": research.STRENGTH_METRIC,
    "lag": 7,
    "expected_sign": "+",
    "min_effect": 1,
}


def _strength_belief(conn, slug: str = "strain-strength", spec: dict = STRENGTH_SPEC) -> str:
    bid = research.add_belief(
        conn,
        "Hard days build strength",
        research.STRENGTH_METRIC,
        1.0,
        3.0,
        "test prior",
        None,
        "t",
    )
    research.register(conn, slug, "q", spec, bid, "test")
    research.review(conn, slug, "approve", "sized and adjusted", "methodologist")
    return bid


def test_forecaster_predicts_a_second_target_weekly(conn, monkeypatch) -> None:
    _seed(conn, effect_pct=0, days=420)
    _plant_strength(monkeypatch, conn, effect=4.0)
    bid = _strength_belief(conn)
    # A lag shorter than the week-ahead horizon can't be known when the bet is made.
    _strength_belief(conn, "too-short", STRENGTH_SPEC | {"lag": 3})
    bt = research.backtest(conn, today=TODAY, metric=research.STRENGTH_METRIC)
    assert bt["reason"] is None and bt["n"] >= 12
    # Scored once a week, not daily.
    assert bt["n"] <= 6 * 5
    assert bt["skill"] > 0.3
    assert set(bt["gains"]) == {bid} and bt["gains"][bid] > 0
    research.store_backtest(conn, bt)
    view = research.forecast_view(conn, metric=research.STRENGTH_METRIC)
    assert view["backtest"]["skill"] == pytest.approx(bt["skill"])
    assert view["target"]["horizon_days"] == 7
    assert {t["metric"] for t in view["targets"]} == set(research.FORECAST_TARGETS)
    # The HRV view is untouched by the strength run.
    assert research.forecast_view(conn)["backtest"] is None
    p = research.forecast_preview(conn, today=TODAY, metric=research.STRENGTH_METRIC)
    assert p["target_date"] == str(TODAY + timedelta(days=7))
    made = research.forecast_today(conn, today=TODAY, metric=research.STRENGTH_METRIC)
    assert made is not None and made["target_date"] == str(TODAY + timedelta(days=7))


def test_forecaster_refuses_to_score_without_beliefs_or_history(conn, monkeypatch) -> None:
    _seed(conn, effect_pct=0, days=75)
    _plant_strength(monkeypatch, conn, effect=4.0)
    none = research.backtest(conn, today=TODAY, metric=research.STRENGTH_METRIC)
    assert none["skill"] is None and "No active belief" in none["reason"]
    _strength_belief(conn)
    thin = research.backtest(conn, today=TODAY, metric=research.STRENGTH_METRIC)
    assert thin["skill"] is None and thin["n"] < 12 and "need 12" in thin["reason"]
    assert all(g is None for g in thin["gains"].values())
    research.store_backtest(conn, thin)
    assert research.forecast_view(conn, metric=research.STRENGTH_METRIC)["backtest"]["reason"]
    with pytest.raises(research.SpecError, match="forecast target"):
        research.backtest(conn, today=TODAY, metric="made_up")
