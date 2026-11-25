"""First daily experiment candidates (WP 2.6): sized by the gate, registrable as queued."""

from __future__ import annotations

import random
from datetime import date, timedelta

import pytest

from shc import daily_candidates, lab_queue, selflab
from shc.api.routers.experiments import PreregisterIn


def _nights(conn, *, days: int, sd: float, seed: int = 1) -> None:
    rng = random.Random(seed)
    for k in range(1, days + 1):
        d = (date.today() - timedelta(days=k)).isoformat()
        conn.execute(
            "INSERT INTO sleep (id, source, night_date, content_hash, sws_min, "
            "sleep_efficiency_pct, is_nap) VALUES (?, 'whoop', ?, ?, ?, ?, FALSE)",
            [f"s{k}", d, f"s{k}", 80 + rng.gauss(0, sd * 4), 90 + rng.gauss(0, sd)],
        )
        conn.execute(
            "INSERT INTO recovery (id, source, date, rhr, content_hash) "
            "VALUES (?, 'whoop', ?, ?, ?)",
            [f"r{k}", d, round(55 + rng.gauss(0, sd)), f"r{k}"],
        )


def test_payloads_fit_the_registration_route_and_queue() -> None:
    assert len({c.slug for c in daily_candidates.CANDIDATES}) == 3
    for c in daily_candidates.CANDIDATES:
        body = PreregisterIn(**c.payload())
        assert body.queued is True
        assert body.outcome_metric in selflab.SUPPORTED_OUTCOME_METRICS
        assert lab_queue.lane_of("randomized_alternating") == "daily"


def test_quiet_history_sizes_and_registers_every_candidate(conn) -> None:
    _nights(conn, days=170, sd=1.0)
    rows = daily_candidates.size_candidates(conn)
    assert all(r["passes"] for r in rows)
    assert all(r["weeks_to_verdict"] * 7 <= selflab.MAX_DAYS_TO_ANSWER + 7 for r in rows)
    for c in daily_candidates.CANDIDATES:
        body = PreregisterIn(**c.payload()).model_dump()
        for k in ("queued",):
            body.pop(k)
        selflab.preregister(conn, queued=True, **body)
    statuses = {s for (s,) in conn.execute("SELECT status FROM experiments").fetchall()}
    assert statuses == {"approved"}


def test_noisy_history_is_refused_not_sized_optimistically(conn) -> None:
    _nights(conn, days=170, sd=12.0)
    rows = daily_candidates.size_candidates(conn)
    assert not any(r["passes"] for r in rows)
    c = daily_candidates.CANDIDATES[0]
    body = PreregisterIn(**c.payload()).model_dump()
    body.pop("queued")
    with pytest.raises(ValueError, match="limit is 120 days"):
        selflab.preregister(conn, queued=True, **body)


def test_too_little_history_has_no_gate(conn) -> None:
    rows = daily_candidates.size_candidates(conn)
    assert all(r["gate"] is None and not r["passes"] for r in rows)
