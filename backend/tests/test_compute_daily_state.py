from __future__ import annotations

from datetime import date, timedelta

from shc.metrics import compute_daily_state


def days_ago(n: int) -> date:
    # compute_daily_state anchors to the real date.today(), so seed relative to it.
    return date.today() - timedelta(days=n)


# ── pipeline assembly ────────────────────────────────────────────────────────

def test_empty_db_returns_well_formed_state(conn) -> None:
    """The whole pipeline runs and serializes on an empty DB without crashing."""
    state = compute_daily_state(conn)
    assert isinstance(state, dict)
    for section in ("recovery", "sleep", "training_load", "checkin",
                    "readiness", "gates", "freshness"):
        assert section in state
    # No data → no readiness score, default gates (high, no deload).
    assert state["readiness"]["score"] is None
    assert state["gates"]["max_intensity"] == "high"
    assert state["gates"]["deload_required"] is False


def test_as_of_is_today(conn) -> None:
    assert compute_daily_state(conn)["as_of"] == date.today().isoformat()


# ── beta-blocker integration (med present AND taken) ─────────────────────────

def test_beta_blocker_adjusted_requires_med_and_taken(conn, seed) -> None:
    seed.med("Propranolol (Inderal) 10 mg PRN", active=True)
    seed.checkin(date.today(), propranolol_taken=True, energy_1_10=7, stress_1_10=3)
    state = compute_daily_state(conn)
    assert state["readiness"]["beta_blocker_adjusted"] is True


def test_no_beta_blocker_adjust_when_med_present_but_not_taken(conn, seed) -> None:
    """Propranolol is PRN — on record but NOT taken today must not reweight."""
    seed.med("Propranolol (Inderal) 10 mg PRN", active=True)
    seed.checkin(date.today(), propranolol_taken=False, energy_1_10=7, stress_1_10=3)
    state = compute_daily_state(conn)
    assert state["readiness"]["beta_blocker_adjusted"] is False


def test_no_beta_blocker_adjust_without_checkin(conn, seed) -> None:
    seed.med("Propranolol (Inderal) 10 mg PRN", active=True)
    state = compute_daily_state(conn)
    assert state["readiness"]["beta_blocker_adjusted"] is False


# ── deload cooldown integration ──────────────────────────────────────────────

def test_recent_deload_plan_suppresses_via_pipeline(conn, seed) -> None:
    """A real regression that would fire a deload is suppressed end-to-end when
    a deload was prescribed within the cooldown window."""
    ex = "Bench Press (Barbell)"
    # Strong then weak → genuine peak regression.
    seed.workout(days_ago(50), ex, [(90, 5), (88, 5)])
    seed.workout(days_ago(44), ex, [(90, 6), (88, 6)])
    seed.workout(days_ago(8), ex, [(70, 5), (68, 5)])
    seed.workout(days_ago(6), ex, [(70, 5), (68, 5)])
    # A deload was prescribed 3 days ago → within the 9-day cooldown.
    seed.plan(days_ago(3), deload_prescribed=True)

    state = compute_daily_state(conn)
    gates = state["gates"]
    assert gates["deload_required"] is False
    assert any("suppressed" in r for r in gates["reasons"])


def test_illness_checkin_forces_rest_via_pipeline(conn, seed) -> None:
    seed.checkin(date.today(), illness_flag=True)
    state = compute_daily_state(conn)
    assert state["gates"]["max_intensity"] == "rest"
