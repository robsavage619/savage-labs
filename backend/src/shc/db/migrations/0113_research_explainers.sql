-- Fields the Lab's explainers read: each result's raw outcome mean per arm, and
-- the parts of a question's value score as computed at registration.
ALTER TABLE research_results ADD COLUMN IF NOT EXISTS mean_a DOUBLE;
ALTER TABLE research_results ADD COLUMN IF NOT EXISTS mean_b DOUBLE;
ALTER TABLE research_hypotheses ADD COLUMN IF NOT EXISTS value_parts VARCHAR;
