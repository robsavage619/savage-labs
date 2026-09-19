-- Migration 0101: make every muscle_development head a region some curated lift can credit.
--
-- The per-muscle menu lists each head from muscle_development.regions and fills its
-- count from weekly_region_volume, which credits exercise_science.region. Three head
-- lists named regions no curated row carries, so those heads read 0 every week and
-- permanently tagged themselves "←lead" — steering selection toward a head nothing
-- on the menu can train:
--
--   quads       vastus_lateralis/medialis/intermedius  -> curated rows say 'vastii'
--   hamstrings  biceps_femoris/semitendinosus          -> curated rows are by function
--                                                         (hip_extension/knee_flexion)
--   traps       lower_traps                            -> no curated row; Face Pull,
--                                                         the only lower-trap mover,
--                                                         is tagged mid_traps
--
-- biceps is left alone: its 'biceps_brachii' rows are deliberately head-neutral curls,
-- and the menu already appends a trained region missing from the head list.

UPDATE muscle_development SET regions = '["rectus_femoris","vastii"]' WHERE muscle = 'quads';
UPDATE muscle_development SET regions = '["hip_extension","knee_flexion"]' WHERE muscle = 'hamstrings';
UPDATE muscle_development SET regions = '["upper_traps","mid_traps"]' WHERE muscle = 'traps';
