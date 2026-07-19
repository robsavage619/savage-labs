from __future__ import annotations

import uuid
from datetime import date, timedelta

from shc.metrics import RecoveryMetrics, SleepMetrics, TrainingLoadMetrics, _freshness


def _iso(days_ago: int) -> str:
    return (date.today() - timedelta(days=days_ago)).isoformat()


def test_hevy_gap_present_when_stale(conn) -> None:
    load = TrainingLoadMetrics(last_session_date=_iso(5))
    f = _freshness(conn, date.today(), RecoveryMetrics(), SleepMetrics(), load)
    assert f.hevy_age_days == 5
    assert any("Hevy" in g for g in f.gaps)


def test_hevy_gap_absent_when_fresh(conn) -> None:
    load = TrainingLoadMetrics(last_session_date=_iso(1))
    f = _freshness(conn, date.today(), RecoveryMetrics(), SleepMetrics(), load)
    assert f.hevy_age_days == 1
    assert not any("Hevy" in g for g in f.gaps)


def test_cardio_gap_present_when_stale(conn) -> None:
    conn.execute(
        "INSERT INTO cardio_sessions (id, date, modality, content_hash) "
        "VALUES ($id, $d, 'run', 'h')",
        {"id": str(uuid.uuid4()), "d": _iso(6)},
    )
    f = _freshness(conn, date.today(), RecoveryMetrics(), SleepMetrics(), TrainingLoadMetrics())
    assert f.cardio_age_days == 6
    assert any("Cardio" in g for g in f.gaps)


def test_cardio_gap_absent_when_fresh(conn) -> None:
    conn.execute(
        "INSERT INTO cardio_sessions (id, date, modality, content_hash) "
        "VALUES ($id, $d, 'run', 'h')",
        {"id": str(uuid.uuid4()), "d": _iso(1)},
    )
    f = _freshness(conn, date.today(), RecoveryMetrics(), SleepMetrics(), TrainingLoadMetrics())
    assert f.cardio_age_days == 1
    assert not any("Cardio" in g for g in f.gaps)


def test_whoop_stale_flag_set_when_stale(conn) -> None:
    rec = RecoveryMetrics(score_date=_iso(4))
    f = _freshness(conn, date.today(), rec, SleepMetrics(), TrainingLoadMetrics())
    assert f.whoop_stale is True


def test_whoop_stale_flag_false_when_fresh(conn) -> None:
    rec = RecoveryMetrics(score_date=_iso(1))
    f = _freshness(conn, date.today(), rec, SleepMetrics(), TrainingLoadMetrics())
    assert f.whoop_stale is False


def test_whoop_stale_flag_false_when_no_data(conn) -> None:
    f = _freshness(conn, date.today(), RecoveryMetrics(), SleepMetrics(), TrainingLoadMetrics())
    assert f.whoop_stale is False
