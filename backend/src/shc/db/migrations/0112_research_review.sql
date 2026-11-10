-- Questions now wait for the methodologist: proposed -> active | rejected.
-- The value score is the server's fixed value-of-information ranking. The five
-- seeded questions were registered before review existed and stay active.
ALTER TABLE research_hypotheses ADD COLUMN IF NOT EXISTS value_score DOUBLE;
UPDATE research_hypotheses SET status = 'active' WHERE status IN ('registered', 'underpowered');
