-- One-off cleanup: NULL out respiratory_rate values that are physiologically
-- impossible for adult sleep (8–30 bpm is the plausible range).
--
-- Legacy data was contaminated when the misnamed `sleep.rhr` column held a
-- mix of respiratory_rate and resting_heart_rate values across schema
-- changes. Migration 0020 backfilled all of those into respiratory_rate;
-- this migration removes the ones that are clearly wrong so the next WHOOP
-- sync (with bumped content_hash) can repopulate them from the API.

UPDATE sleep
SET respiratory_rate = NULL
WHERE respiratory_rate IS NOT NULL
  AND (respiratory_rate < 8 OR respiratory_rate > 30);

INSERT INTO schema_version (version) VALUES (22) ON CONFLICT DO NOTHING;
