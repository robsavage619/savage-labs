from __future__ import annotations

import json
import math
import random
from datetime import date, timedelta

import pytest

from shc import research

TODAY = date(2026, 6, 30)


def _seed(conn, effect_pct: float, days: int = 360, seed: int = 3, end: date = TODAY) -> None:
    """Strain on day d moves day d+1's HRV by `effect_pct` when strain is high."""
    rng = random.Random(seed)
    start = end - timedelta(days=days)
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


def _seed_blocks(conn, seed: int, block: int = 21, days: int = 360, end: date = TODAY) -> None:
    """Regimes of `block` days shift HRV; strain also runs in blocks. No true effect.

    Strain is logged every third day, like sessions, so no two rows are
    calendar-consecutive and a lag-1 daily autocorrelation has nothing to read.
    """
    rng = random.Random(seed)
    start = end - timedelta(days=days)
    regime, high = 0.0, False
    for i in range(days + 1):
        d = start + timedelta(days=i)
        if i % block == 0:
            regime = rng.gauss(0, 0.12)
        if i % (block + 7) == 0:
            high = rng.random() < 0.5
        strain = rng.uniform(14, 18) if high else rng.uniform(4, 9)
        hrv = math.exp(math.log(100) + regime + rng.gauss(0, 0.05))
        conn.execute(
            "INSERT INTO recovery (id, source, date, score, hrv, rhr, content_hash) VALUES (?, 'whoop', ?, 60, ?, 50, ?)",
            [f"r{i}", d, hrv, f"h{i}"],
        )
        if i % 3 == 0:
            conn.execute(
                "INSERT INTO daily_cycle (id, date, strain, content_hash) VALUES (?, ?, ?, ?)",
                [f"c{i}", d, strain, f"k{i}"],
            )


def test_blocked_errors_and_blocked_arms_do_not_fake_an_effect(conn) -> None:
    _seed_blocks(conn, seed=62)
    res = research.estimate(conn, SPEC, today=TODAY)
    assert res["ci_low"] < 0 < res["ci_high"]
    assert res["verdict"] not in ("supported", "direction")
    assert res["design_effect"] > 1.5


def test_independent_noise_keeps_a_real_effect_supported(conn) -> None:
    _seed(conn, effect_pct=-10)
    res = research.estimate(conn, SPEC, today=TODAY)
    assert res["verdict"] == "supported"
    assert res["design_effect"] < 2.0


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
        conn,
        "strain-hrv",
        "Does a hard day lower tomorrow's HRV?",
        # Sized so the planned look fits in the seeded history.
        SPEC | {"min_effect": 5},
        bid,
        "test",
    )
    # Registered before the data arrived, so the days count; otherwise the result
    # is retrospective and (correctly) leaves the prior alone.
    conn.execute(
        "UPDATE research_hypotheses SET created_at = ? WHERE slug = 'strain-hrv'",
        [TODAY - timedelta(days=400)],
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
    fast = {"needed_per_arm": 50, "days_to_confirm": 30, "outcome_sd": 10}
    slow = {"needed_per_arm": 900, "days_to_confirm": 1200, "outcome_sd": 20}
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
    fast = {"needed_per_arm": 50, "days_to_confirm": 30, "outcome_sd": 10}
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


def test_forecaster_refuses_to_score_without_beliefs(conn) -> None:
    _seed(conn, effect_pct=0, days=75)
    none = research.backtest(conn, today=TODAY)
    assert none["skill"] is None and "No active belief" in none["reason"]
    research.store_backtest(conn, none)
    assert research.forecast_view(conn)["backtest"]["reason"]
    with pytest.raises(research.SpecError, match="forecast target"):
        research.backtest(conn, today=TODAY, metric="made_up")


def test_retired_questions_stop_running_but_keep_their_evidence(conn) -> None:
    bid = _setup_belief(conn, effect_pct=-15)
    research.run(conn, "strain-hrv")
    before = next(b for b in research.beliefs(conn) if b["id"] == bid)
    research.retire(conn, "strain-hrv", "hurts the forecast in the backtest", "methodologist")
    assert research.run_all(conn) == []
    after = next(b for b in research.beliefs(conn) if b["id"] == bid)
    assert after["post_mean"] == before["post_mean"]
    assert research.notebook(conn, 1)[0]["kind"] == "retirement"
    with pytest.raises(research.SpecError):
        research.retire(conn, "strain-hrv", "already retired, try again", "methodologist")


def test_misses_follow_the_requested_target(conn) -> None:
    _setup_belief(conn, effect_pct=-15)
    research.store_backtest(conn, research.backtest(conn, today=TODAY))
    assert research.misses(conn)["metric"] == research.FORECAST_METRIC
    with pytest.raises(research.SpecError):
        research.misses(conn, "not_a_target")


def test_more_sessions_do_not_read_as_more_strength(conn, seed) -> None:
    # One session last fortnight; five this fortnight scattered around the same
    # load. Taking the window's MAX would read +5% from sheer opportunity.
    _map(conn, "Synthetic Curl", "biceps")
    end = TODAY
    seed.workout(end - timedelta(days=20), "Synthetic Curl", [(20.0, 10)], rpe=None)
    for k, w in zip((12, 10, 7, 4, 1), (19.0, 19.5, 20.0, 20.5, 21.0), strict=True):
        seed.workout(end - timedelta(days=k), "Synthetic Curl", [(w, 10)], rpe=None)
    pct = research.series(conn, "e1rm_pct14:biceps")
    assert pct[end] == pytest.approx(0.0, abs=0.01)


def _status(conn, slug: str) -> str:
    return conn.execute("SELECT status FROM research_hypotheses WHERE slug = ?", [slug]).fetchone()[
        0
    ]


def test_a_revision_registers_the_reviewers_design_as_active(conn) -> None:
    # The limit is judged on days still to come, so the feed has to be live.
    _seed(conn, effect_pct=-10, end=date.today())
    research.register(conn, "s6", "q", SPEC, None, "hypertrophy")
    # A design that cannot answer in time is refused before anything is written.
    with pytest.raises(research.SpecError, match="limit is 120"):
        research.review(
            conn, "s6", "revise", "adjust for drift", "methodologist", SPEC | {"lag": 2}
        )
    assert _status(conn, "s6") == "proposed"
    fixed = SPEC | {"min_effect": 12, "adjust": ["time_years"], "start_date": "2025-09-01"}
    out = research.review(conn, "s6", "revise", "adjust for drift", "methodologist", fixed)
    assert out["revised_as"] == "s6-r1"
    assert (_status(conn, "s6"), _status(conn, "s6-r1")) == ("rejected", "active")
    new = next(h for h in research.hypotheses(conn) if h["slug"] == "s6-r1")
    assert new["author"] == "hypertrophy" and new["spec"] == fixed


def test_start_date_and_trend_restrict_and_adjust(conn) -> None:
    _seed(conn, effect_pct=-10)
    full = research.estimate(conn, SPEC, today=TODAY)
    late = research.estimate(conn, SPEC | {"start_date": "2026-01-01"}, today=TODAY)
    assert 0 < late["n_a"] + late["n_b"] < full["n_a"] + full["n_b"]
    s = research.series(conn, "time_years")
    assert s[date(2025, 1, 1)] == pytest.approx(1.0, abs=0.01)
    with pytest.raises(research.SpecError, match="start_date"):
        research.validate_spec(conn, SPEC | {"start_date": "last spring"})


def test_live_questions_that_cannot_answer_retire_themselves(conn) -> None:
    _setup_belief(conn, effect_pct=0)
    # Answerable and fed: left alone. Unanswered with years to go: retired.
    done = research.estimate(conn, SPEC | {"min_effect": 10}, today=TODAY)
    assert research._dead_reason(conn, SPEC, done, today=TODAY) is None
    tiny = SPEC | {"min_effect": 0.2}
    stuck = research.estimate(conn, tiny, today=TODAY)
    assert stuck["verdict"] == "inconclusive"
    assert "current pace" in research._dead_reason(conn, tiny, stuck, today=TODAY)
    # The seeded feed stopped on TODAY, months before the real date run_all uses.
    out = research.run_all(conn)
    assert "no data since" in out[0]["retired"]
    assert _status(conn, "strain-hrv") == "retired"
    assert research.run_all(conn) == []


def test_retrospective_questions_that_cannot_confirm_in_time_retire(conn) -> None:
    _seed(conn, effect_pct=-10)
    limit = research._RETIRE_AFTER_DAYS

    def retro(days: int | None) -> dict:
        return {"verdict": "retrospective", "power": {"days_to_confirm": days}}

    assert "3319 more days" in research._dead_reason(conn, SPEC, retro(3319), today=TODAY)
    assert "cannot confirm" in research._dead_reason(conn, SPEC, retro(None), today=TODAY)
    assert research._dead_reason(conn, SPEC, retro(limit), today=TODAY) is None
    assert research._dead_reason(conn, SPEC, retro(30), today=TODAY) is None


def _decided(conn, slug: str, verdict: str, status: str = "active") -> None:
    conn.execute(
        "INSERT INTO research_hypotheses (id, slug, question, spec, spec_hash, author, status) "
        "VALUES (?, ?, ?, ?, ?, 'test', ?)",
        [f"h-{slug}", slug, f"Does {slug} hold?", json.dumps(SPEC), slug, status],
    )
    conn.execute(
        "INSERT INTO research_results (id, hypothesis_id, effect, ci_low, ci_high, verdict) "
        "VALUES (?, ?, -6.0, -9.0, -3.0, ?)",
        [f"r-{slug}", f"h-{slug}", verdict],
    )


def _challenge(conn, slug: str, verdict: str, severity: str, body: str = "tested") -> None:
    research.note(conn, "devils-advocate", "review", f"{severity}: {slug} at {verdict}", body)


def test_only_decisive_challenged_results_reach_the_planner(conn) -> None:
    assert research.lab_results_section(conn) == ""
    _decided(conn, "kept", "supported", status="retired")
    _challenge(conn, "kept", "supported", "qualified")
    _decided(conn, "against-ok", "against")
    _decided(conn, "retro", "retrospective")
    _challenge(conn, "retro", "retrospective", "stands")
    _decided(conn, "unchallenged", "supported")
    _decided(conn, "doubted", "direction")
    _challenge(conn, "doubted", "direction", "doubtful")
    _decided(conn, "dry", "supported")
    _challenge(conn, "dry", "supported", "stands", body="DRY RUN. nothing tested")
    _decided(conn, "proposed", "supported", status="proposed")
    _challenge(conn, "proposed", "supported", "stands")
    assert [g["slug"] for g in research.governed_results(conn)] == ["kept", "against-ok"]
    text = research.lab_results_section(conn)
    assert text.startswith("## LAB RESULTS (pre-registered, challenged)")
    assert "not over it" in text
    assert "Does kept hold? → supported: -6.00" in text and "95% CI -9.00 to -3.00" in text
    assert "challenge: qualified" in text
    for slug in ("retro", "unchallenged", "doubted", "dry", "proposed"):
        assert f"Does {slug} hold?" not in text


def test_an_untested_belief_ranks_the_same_whatever_prior_its_proposer_wrote(conn) -> None:
    fast = {"needed_per_arm": 50, "days_to_confirm": 30, "outcome_sd": 10}
    ids = [
        research.add_belief(conn, f"c{sd}", "lnhrv_dev_pct", 0.0, sd, "test prior", "d", "t")
        for sd in (1.0, 50.0)
    ]
    narrow, wide = (research.value_score(conn, SPEC, b, fast) for b in ids)
    assert narrow["value"] == wide["value"] and narrow["uncertainty"] == 3.0
    small = research.value_score(conn, SPEC | {"min_effect": 0.5}, ids[0], fast)
    assert small["uncertainty"] == narrow["uncertainty"]


def test_review_queue_rescores_power_on_current_data(conn) -> None:
    _seed(conn, effect_pct=0, days=60)
    research.register(conn, "s7", "q", SPEC, None, "analyst")
    conn.execute("UPDATE research_hypotheses SET power = '{\"days_to_answer\": 1}'")
    item = research.review_queue(conn)[0]
    assert item["power_at_proposal"] == {"days_to_answer": 1}
    assert item["power"] == research.estimate(conn, SPEC).get("power")


def test_a_hairline_skill_is_called_a_tie(conn) -> None:
    rng = random.Random(1)
    noise = [(rng.gauss(0, 20), rng.gauss(0, 1)) for _ in range(200)]
    assert research._skill_call(noise) == "tie"
    assert research._skill_call([(a, 0.8 * a) for a, _ in noise]) == "better"
    assert research._skill_call([(a, -a) for a, _ in noise]) == "worse"
    assert research._skill_call(noise[:5]) is None


def _vo2(conn, source: str, metric: str, day: date, value: float) -> None:
    conn.execute(
        "INSERT INTO measurements (source, metric, ts, value_num, unit, external_id, content_hash) "
        "VALUES (?, ?, ?, ?, 'mL/kg/min', ?, ?)",
        [source, metric, f"{day} 12:00:00", value, f"{metric}:{day}", f"h{day}{metric}"],
    )


def test_vo2_reads_one_estimator_at_a_time_whoop_first(conn) -> None:
    _vo2(conn, "apple_health", "vo2_max", date(2026, 3, 3), 38.2)
    assert research.series(conn, "vo2_max") == {date(2026, 3, 3): 38.2}
    # Once WHOOP has rows the series is WHOOP's alone: no step from changing source.
    _vo2(conn, "whoop_private", "vo2_max_whoop", date(2026, 3, 3), 39.0)
    _vo2(conn, "whoop_private", "vo2_max_whoop", date(2026, 3, 10), 38.0)
    assert research.series(conn, "vo2_max") == {date(2026, 3, 3): 39.0, date(2026, 3, 10): 38.0}


def test_supported_needs_the_range_to_clear_the_size_the_question_asks(conn) -> None:
    _seed(conn, effect_pct=-10)
    # Real and in the predicted direction, but the range reaches below 10.
    assert research.estimate(conn, SPEC | {"min_effect": 10}, today=TODAY)["verdict"] == "direction"
    # Real, yet the whole range sits short of 30: an effect that size is ruled out.
    assert research.estimate(conn, SPEC | {"min_effect": 30}, today=TODAY)["verdict"] == "ruled_out"
    assert (
        research.estimate(conn, SPEC | {"expected_sign": "+"}, today=TODAY)["verdict"] == "against"
    )


def test_days_seen_before_registration_cannot_confirm_a_question(conn) -> None:
    _seed(conn, effect_pct=-15)
    # min_effect 5 plans a look (about 160 per arm) the seeded history can reach.
    spec = SPEC | {"min_effect": 5}
    research.register(conn, "seen", "Does a hard day lower tomorrow's HRV?", spec, None, "test")
    # Every seeded day predates the registration: the effect is there, the proof is not.
    res = research.run(conn, "seen")
    assert res["verdict"] == "retrospective"
    assert res["effect"] < 0
    assert "since it was registered" in res["summary"]
    # Registered before the data arrived: the same days now count.
    conn.execute(
        "UPDATE research_hypotheses SET created_at = ? WHERE slug = 'seen'",
        [TODAY - timedelta(days=400)],
    )
    assert research.run(conn, "seen")["verdict"] == "supported"


def test_time_to_confirm_counts_only_days_after_registration(conn) -> None:
    _seed(conn, effect_pct=-10)
    spec = SPEC | {"min_effect": 10}
    # A draft has no days of its own yet, however much history sits behind it.
    draft = research.estimate(conn, spec, today=TODAY)["power"]
    assert draft["days_to_answer"] == 0
    assert draft["days_to_confirm"] > 0
    old = research.estimate(conn, spec, today=TODAY, registered=TODAY - timedelta(days=400))
    assert old["power"]["days_to_confirm"] == 0


def test_a_retrospective_result_says_how_long_the_wait_is(conn) -> None:
    _seed(conn, effect_pct=-10, end=date.today())
    research.register(conn, "wait", "Does a hard day lower tomorrow's HRV?", SPEC, None, "test")
    res = research.run(conn, "wait")
    assert res["verdict"] == "retrospective"
    assert f"about {res['power']['days_to_confirm']} more days" in res["summary"]


def test_a_retrospective_result_does_not_move_a_belief(conn) -> None:
    _seed(conn, effect_pct=-10)
    bid = research.add_belief(
        conn, "Hard days lower tomorrow's HRV", "lnhrv_dev_pct", -3.0, 5.0, "prior", None, "test"
    )
    research.register(conn, "seen", "q", SPEC, bid, "test")
    assert research.run(conn, "seen")["verdict"] == "retrospective"
    b = next(x for x in research.beliefs(conn) if x["id"] == bid)
    assert b["post_mean"] == pytest.approx(-3.0) and b["post_sd"] == pytest.approx(5.0)


def _ar_series(phi: float, n: int = 200) -> list[dict]:
    rng = random.Random(4)
    y, prev = [], 0.0
    for _ in range(n):
        prev = phi * prev + rng.gauss(0, 10)
        y.append(prev)
    return [{"actual": y[i], "predicted": 0.0, "persist": 0.25 * y[i - 1]} for i in range(1, n)]


def test_skill_is_also_scored_against_shrunk_persistence() -> None:
    # A forecast that always says zero ties the zero baseline exactly, but loses to
    # persistence when the series carries over from day to day.
    rows = _ar_series(0.5)
    best = research._best_baseline(rows)
    assert best["baseline"] == "persistence"
    assert best["skill_best"] < 0
    # Series stored before persistence was kept report nothing rather than a guess.
    assert research._best_baseline([{"actual": 1, "predicted": 0}])["skill_best"] is None


def test_persistence_coefficient_is_fitted_only_before_the_origin() -> None:
    origin = date(2026, 3, 1)
    actual = {origin - timedelta(days=i): (i % 2) * 2.0 - 1.0 for i in range(120)}
    before = research._persistence_coef(actual, origin, 1)
    actual |= {origin + timedelta(days=i): 50.0 for i in range(1, 60)}
    assert research._persistence_coef(actual, origin, 1) == before == 0.0


def test_backtest_keeps_the_zero_baseline_fields_and_adds_persistence(conn) -> None:
    _setup_belief(conn, effect_pct=-15)
    bt = research.backtest(conn, today=TODAY)
    for k in ("skill", "rmse_lab", "rmse_base", "skill_best", "baseline", "rmse_persist"):
        assert k in bt
    assert bt["skill_best"] <= bt["skill"] + 1e-9
    research.store_backtest(conn, bt)
    view = research.forecast_view(conn)["backtest"]
    assert view["skill_best"] == pytest.approx(bt["skill_best"])
    assert view["call"] is not None and "call_best" in view


def test_a_tie_is_not_reported_as_beliefs_improving_the_forecast(conn) -> None:
    rng = random.Random(2)
    series = [
        {"date": str(i), "actual": rng.gauss(0, 20), "predicted": rng.gauss(0, 0.5), "persist": 0.0}
        for i in range(120)
    ]
    bt = {
        "metric": research.FORECAST_METRIC,
        "skill": 0.007,
        "n": 120,
        "rmse_lab": 1.0,
        "rmse_base": 1.0,
        "gains": {},
        "series": series,
    }
    bt |= research._best_baseline(series)
    assert bt["call_best"] == "tie"
    research.store_backtest(conn, bt)
    titles = [n["title"] for n in research.notebook(conn)]
    assert any("a tie" in t for t in titles)
    assert not any("beliefs improve the forecast" in str(n) for n in research.notebook(conn))


def test_brief_says_how_small_an_effect_120_days_can_detect(conn) -> None:
    _seed(conn, effect_pct=0)
    det = research.detectable_in_120d(conn, today=TODAY)
    h = det["lnhrv_dev_pct"]
    assert h["reason"] is None and h["units_per_arm"] == 60
    # The reported effect is exactly the point where the lab's own sizing formula says n is enough.
    n, sd, de = h["units_per_arm"], h["outcome_sd"], h["design_effect"]
    assert research._needed_per_arm(sd, h["detectable_effect"] * 1.02, de) <= n
    assert research._needed_per_arm(sd, h["detectable_effect"] * 0.95, de) > n
    assert h["detectable_at_80pct_adherence"] > h["detectable_effect"]
    # No number is guessed where none can be computed.
    assert det["strength_emphasis_pct14"]["detectable_effect"] is None
    assert "readings" in det["strength_emphasis_pct14"]["reason"]
    assert det["top_set_e1rm"]["detectable_effect"] is None and det["top_set_e1rm"]["reason"]
    assert "detectable_in_120d" in research.brief(conn)["rules"]


def _fake_estimator(a: list[float], b: list[float], visible: list[int]):
    """A stand-in for `estimate` over in-memory arms, honouring `z` and `cap_per_arm`."""

    def fake(conn, spec, today=None, registered=None, z=1.96, cap_per_arm=None):
        n = visible[0] if cap_per_arm is None else min(visible[0], cap_per_arm)
        xa, xb = a[:n], b[:n]
        eff = sum(xb) / n - sum(xa) / n
        va = sum((v - sum(xa) / n) ** 2 for v in xa) / (n - 1)
        vb = sum((v - sum(xb) / n) ** 2 for v in xb) / (n - 1)
        se = math.sqrt((va + vb) / n)
        lo, hi = eff - z * se, eff + z * se
        verdict = "direction" if lo > 0 else "against" if hi < 0 else "inconclusive"
        return {
            "n_a": n,
            "n_b": n,
            "verdict": verdict,
            "effect": eff,
            "ci_low": lo,
            "ci_high": hi,
            "unit": "day",
            "summary": "x → " + verdict,
        }

    return fake


def test_nightly_peeking_at_a_null_effect_stays_near_the_nominal_error(monkeypatch) -> None:
    """A question re-tested every night for 120 days per arm, true effect zero.

    The all-days verdict is taken as favourable every night (the worst case: a
    lead selected because it looked good). Looking at the new days nightly with
    a fixed 1.96 reaches "direction" in about one run in six; two planned looks
    keep it near the nominal 2.5%.
    """
    rng = random.Random(7)
    visible = [0]
    false_calls, runs = 0, 400
    power = {"needed_per_arm": 100, "days_to_confirm": 1, "days_to_next_look": 1}
    for _ in range(runs):
        a = [rng.gauss(0, 1) for _ in range(120)]
        b = [rng.gauss(0, 1) for _ in range(120)]
        monkeypatch.setattr(research, "estimate", _fake_estimator(a, b, visible))
        hit = False
        for n in range(10, 121):
            visible[0] = n
            res = {
                "verdict": "direction",
                "unit": "day",
                "summary": "x → direction",
                "power": power,
            }
            out = research._confirm_on_new_days(None, {"unit": "day"}, res, date(2026, 1, 1))
            hit = hit or out["verdict"] in research._FAVOURABLE
        false_calls += hit
    assert false_calls / runs < 0.06


def test_hypotheses_report_power_on_current_data_not_the_proposal_copy(conn) -> None:
    _seed(conn, effect_pct=-10)
    research.register(conn, "p", "q", SPEC, None, "test")
    conn.execute(
        "UPDATE research_hypotheses SET power = '{\"needed_per_arm\": 1}', status = 'active' WHERE slug = 'p'"
    )
    h = next(x for x in research.hypotheses(conn) if x["slug"] == "p")
    assert h["power_at_proposal"] == {"needed_per_arm": 1}
    assert h["power"]["needed_per_arm"] > 1 and not h["power_stale"]
    assert "min_effect" in h["power"]["needed_for"]


def test_hypotheses_read_the_last_run_power_without_rescoring(conn, monkeypatch) -> None:
    _seed(conn, effect_pct=-10)
    research.register(conn, "p", "q", SPEC, None, "test")
    conn.execute("UPDATE research_hypotheses SET status = 'active' WHERE slug = 'p'")
    research.run(conn, "p")

    def _no_rescore(*_a, **_k):
        raise AssertionError("hypotheses() rescored a question that already has a run")

    monkeypatch.setattr(research, "estimate", _no_rescore)
    h = next(x for x in research.hypotheses(conn) if x["slug"] == "p")
    assert h["power"]["needed_per_arm"] > 1 and not h["power_stale"]
