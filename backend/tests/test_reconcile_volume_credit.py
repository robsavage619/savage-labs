"""The volume reconcile check must credit a secondary muscle the way the engine does."""

from __future__ import annotations

from datetime import date

from shc.training.reconcile import check_volume_credit_sums


def test_secondary_sets_are_credited_one_to_one(conn, seed) -> None:
    # Leg Press carries glutes and adductors as secondaries. The engine credits them 1.0
    # a set (the vault's 1:1 synergist ratio), while exercise_muscle.credit still STORES
    # 0.5, so a check that sums the stored column reads 3 sets as 1.5 and fails.
    seed.workout(date.today(), "Leg Press (Machine)", [(120.0, 10)] * 3, rpe=8.0)
    f = check_volume_credit_sums(conn)
    assert f.ok, (f.detail, f.rows)
