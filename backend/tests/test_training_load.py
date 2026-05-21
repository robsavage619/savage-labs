from __future__ import annotations

from datetime import date, timedelta

from shc.metrics import _training_load


def ago(today: date, n: int) -> date:
    return today - timedelta(days=n)


def test_empty_defaults(conn, today: date) -> None:
    m = _training_load(conn, today)
    assert m.acwr is None
    assert m.days_since_legs == 99
    assert m.days_since_push == 99
    assert m.days_since_pull == 99
    assert m.push_pull_ratio_28d is None


def test_acwr_high_when_recent_load_spikes(conn, seed, today: date) -> None:
    # composite_load = hevy_volume_kg / 5000 (no WHOOP strain seeded).
    seed.workout(ago(today, 25), "Bench Press (Barbell)", [(50, 10)])     # vol 500
    seed.workout(ago(today, 2), "Bench Press (Barbell)", [(200, 50)])     # vol 10000
    m = _training_load(conn, today)
    assert m.acwr is not None
    assert m.acwr > 1.5  # acute window carries the spike


def test_acwr_low_when_no_recent_load(conn, seed, today: date) -> None:
    seed.workout(ago(today, 25), "Bench Press (Barbell)", [(200, 50)])    # only old
    m = _training_load(conn, today)
    assert m.acwr is not None
    assert m.acwr < 0.8


def test_days_since_muscle_groups(conn, seed, today: date) -> None:
    seed.workout(ago(today, 1), "Bench Press (Barbell)", [(80, 8)])   # push
    seed.workout(ago(today, 5), "Bent Over Row (Barbell)", [(80, 8)])  # pull
    m = _training_load(conn, today)
    assert m.days_since_push == 1
    assert m.days_since_pull == 5
    assert m.days_since_legs == 99  # never trained


def test_push_pull_ratio(conn, seed, today: date) -> None:
    seed.workout(ago(today, 3), "Bench Press (Barbell)",
                 [(80, 8), (80, 8), (80, 8), (80, 8)])  # 4 push sets
    seed.workout(ago(today, 4), "Bent Over Row (Barbell)",
                 [(80, 8), (80, 8)])                     # 2 pull sets
    m = _training_load(conn, today)
    assert m.push_sets_28d == 4
    assert m.pull_sets_28d == 2
    assert m.push_pull_ratio_28d == 2.0


def test_pickleball_counts_as_legs_stimulus(conn, seed, today: date) -> None:
    """CLAUDE.md invariant: pickleball is a legs stimulus for rest tracking."""
    seed.cardio(ago(today, 2), "pickleball", 90)
    m = _training_load(conn, today)
    assert m.days_since_legs == 2
    assert m.pickleball_min_28d == 90


def test_lift_legs_more_recent_than_pickleball_wins(conn, seed, today: date) -> None:
    seed.cardio(ago(today, 6), "pickleball", 90)
    seed.workout(ago(today, 1), "Goblet Squat", [(40, 10)])  # legs lift yesterday
    m = _training_load(conn, today)
    assert m.days_since_legs == 1
