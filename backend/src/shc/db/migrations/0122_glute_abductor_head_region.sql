-- 0122: tag the abduction lifts that carry no head as gluteus_medius.
--
-- Hip Abduction (Machine) already reads region = gluteus_medius, which is what the
-- vault says the movement trains (schoenfeld-2021-ch8-program-design.md: glute
-- med/min respond to frontal-plane abduction only, and squats, deadlifts and hip
-- thrusts do not reach them). Its three siblings have a NULL region, so the
-- engine's direct-set counters (mesocycle.DIRECT_SET_SQL) could not tell them from
-- hip thrust and counted 41 of 49 glute-primary sets since August as glute-max
-- work. Credits, roles and citations are untouched; this writes the base table
-- `exercise_muscle`, never a view. Idempotent.

UPDATE exercise_muscle
   SET region = 'gluteus_medius'
 WHERE muscle = 'glutes'
   AND role = 'primary'
   AND region IS NULL
   AND exercise_name IN (
       'Machine Hip Abductor',
       'Machine Thigh Abductor',
       'Mini Loop Band Fire Hydrant'
   );
