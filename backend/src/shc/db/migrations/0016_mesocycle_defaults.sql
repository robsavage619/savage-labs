-- Seed global MEV/MAV/MRV volume landmarks (Israetel et al.)
-- mesocycle_id = '' (empty string, NOT NULL) = global defaults; mesocycle-
-- scoped rows (a real UUID) override these. NOT NULL, so comparing against
-- SQL NULL instead of '' would silently match nothing.

INSERT INTO muscle_volume_targets (muscle_group, mev_sets, mav_sets, mrv_sets, mesocycle_id)
VALUES
    ('push',      10, 16, 22, ''),
    ('pull',      10, 16, 22, ''),
    ('legs',      10, 16, 20, ''),
    ('core',       6, 10, 16, ''),
    ('shoulders',  8, 14, 20, ''),
    ('arms',       6, 12, 18, '')
ON CONFLICT DO NOTHING;

-- Seed the first mesocycle starting today if none exists yet.
-- This lets the system work on day 1 without a manual API call.
INSERT INTO mesocycles (started_on, planned_weeks, status, notes)
SELECT CURRENT_DATE, 5, 'active', 'Auto-seeded on first migration'
WHERE NOT EXISTS (SELECT 1 FROM mesocycles);

INSERT INTO schema_version (version) VALUES (16) ON CONFLICT DO NOTHING;
