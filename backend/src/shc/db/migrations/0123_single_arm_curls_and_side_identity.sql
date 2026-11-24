-- 0123: the two single-arm curls (Left / Right) enter the catalogue, and the dedup
-- view stops collapsing the two arms into one lift.
--
-- Rows are copied from the sibling `Seated Dumbbell Curl` (role, credit, head,
-- citation), so the new names credit exactly what a dumbbell curl credits. The
-- half-weight per set lives in code (load_mechanics.set_weight), keyed on the
-- (Left)/(Right) suffix, not in a column: ALTER on a table with dependent views is
-- refused. Writes the base table `exercise_muscle`, never a view. Idempotent.

INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT n.name, s.muscle, s.role, s.credit, s.region, s.length_bias, s.rep_low,
       s.rep_high, s.sfr_tier, s.rationale, s.citation, s.citation_url
FROM exercise_muscle s
CROSS JOIN (VALUES ('Single Arm Dumbbell Curl (Left)'),
                   ('Single Arm Dumbbell Curl (Right)')) AS n(name)
WHERE s.exercise_name = 'Seated Dumbbell Curl'
ON CONFLICT DO NOTHING;

INSERT INTO exercise_muscle (exercise_name, muscle, role, credit)
SELECT name, 'biceps', 'primary', 1.0
FROM (VALUES ('Single Arm Dumbbell Curl (Left)'),
             ('Single Arm Dumbbell Curl (Right)')) AS n(name)
ON CONFLICT DO NOTHING;

-- canon_exercise strips a trailing "(...)" equipment tag, which also stripped
-- "(Left)"/"(Right)": both arms became one lift for every GROUP BY canon_exercise
-- (the lab's session e1RM, the dashboard lift rollups). A side tag is identity,
-- not equipment, so it is kept. Only that CASE differs from 0102's definition.
CREATE OR REPLACE VIEW workout_sets_dedup AS
WITH labeled AS (
    SELECT
        ws.id,
        ws.workout_id,
        ws.exercise,
        ws.set_idx,
        ws.reps,
        ws.weight_kg,
        ws.rpe,
        ws.is_warmup,
        ws.content_hash,
        w.source,
        w.started_at,
        w.started_at::DATE AS day_d,
        -- Twin-map first (legacy name -> the name Rob logs it under today),
        -- then normalize. Order matters: the map is keyed on the raw string.
        array_to_string(
            list_sort(list_transform(
                string_split_regex(
                    regexp_replace(
                        lower(trim(CASE WHEN regexp_matches(lower(trim(COALESCE(t.current_name, ws.exercise))),
                                                 '\((left|right)\)\s*$')
                                 THEN COALESCE(t.current_name, ws.exercise)
                                 ELSE regexp_replace(
                                     COALESCE(t.current_name, ws.exercise),
                                     '\s*\([^)]*\)\s*$', '') END)),
                        '[^a-z0-9 ]', ' ', 'g'),
                    '\s+'),
                tok -> CASE WHEN length(tok) > 3 AND ends_with(tok, 's')
                            THEN tok[1:length(tok) - 1] ELSE tok END)),
            ' ') AS canon_exercise
    FROM workout_sets ws
    JOIN workouts w ON w.id = ws.workout_id
    LEFT JOIN exercise_source_twin t ON t.legacy_name = ws.exercise
),
best_source AS (
    SELECT
        day_d,
        canon_exercise,
        CASE
            WHEN COUNT(*) FILTER (WHERE source = 'hevy') > 0 THEN 'hevy'
            WHEN COUNT(*) FILTER (WHERE source = 'fitbod') > 0 THEN 'fitbod'
            ELSE MIN(source)
        END AS chosen_source
    FROM labeled
    GROUP BY day_d, canon_exercise
)
SELECT l.*
FROM labeled l
JOIN best_source b
  ON b.day_d = l.day_d
 AND b.canon_exercise = l.canon_exercise
 AND b.chosen_source = l.source;
