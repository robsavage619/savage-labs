-- The private-iOS-API journal carries fields the CSV export does not: a stable
-- behavior_tracker_id, and magnitude answers (e.g. "1800 cal", "22") that the
-- CSV flattens away entirely. `source` distinguishes the two ingest paths so a
-- row's provenance is never ambiguous — the CSV path stops at 2025-02-15 and
-- the API path covers everything after, so a query that mixes them silently
-- would otherwise be impossible to audit.
ALTER TABLE whoop_journal ADD COLUMN IF NOT EXISTS source VARCHAR DEFAULT 'csv';
ALTER TABLE whoop_journal ADD COLUMN IF NOT EXISTS behavior_tracker_id INTEGER;
ALTER TABLE whoop_journal ADD COLUMN IF NOT EXISTS magnitude_value DOUBLE;
ALTER TABLE whoop_journal ADD COLUMN IF NOT EXISTS magnitude_label VARCHAR;

UPDATE whoop_journal SET source = 'csv' WHERE source IS NULL;

INSERT INTO schema_version (version) VALUES (93) ON CONFLICT DO NOTHING;
