-- Migration 0045: backfill secondary muscles for dynamically-seeded exercises
-- (panel review M14).
--
-- The dynamic Hevy-template seed (0038/0041) set secondary_muscles=[], so
-- auto-mapped compounds earned zero indirect volume credit. Hevy templates DO
-- carry secondary_muscle_groups (JSON-as-text) — parse, normalize to the
-- canonical anatomical vocabulary, and backfill any map row still empty.

-- ── 1. Backfill normalized secondaries from the Hevy template ─────────────────
UPDATE exercise_muscle_map AS emm
SET secondary_muscles = (
    SELECT list_distinct(list_transform(
        from_json(t.secondary_muscle_groups, '["VARCHAR"]'),
        x -> CASE lower(x)
            WHEN 'upper_back' THEN 'mid_back'
            WHEN 'quadriceps' THEN 'quads'
            WHEN 'abdominals' THEN 'abs'
            WHEN 'abductors'  THEN 'glutes'
            WHEN 'shoulders'  THEN 'side_delts'
            WHEN 'back'       THEN 'lats'
            WHEN 'brachialis' THEN 'biceps'
            ELSE lower(x)
        END
    ))
    FROM hevy_exercise_templates t
    WHERE t.title = emm.exercise_name
    LIMIT 1
)
WHERE len(emm.secondary_muscles) = 0
  AND EXISTS (
      SELECT 1 FROM hevy_exercise_templates t
      WHERE t.title = emm.exercise_name
        AND t.secondary_muscle_groups IS NOT NULL
        AND t.secondary_muscle_groups NOT IN ('[]', '')
  );

-- ── 2. Never credit the primary muscle as its own secondary ───────────────────
UPDATE exercise_muscle_map
SET secondary_muscles = list_filter(secondary_muscles, x -> x != primary_muscle)
WHERE list_contains(secondary_muscles, primary_muscle);
