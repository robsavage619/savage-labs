-- A custom measurement declares the goal it measures, so the value score
-- weights it correctly: a strength outcome counts as muscle whoever proposed it.
-- Existing rows take their goal from what they measure.
ALTER TABLE research_custom_features ADD COLUMN IF NOT EXISTS goal VARCHAR;
UPDATE research_custom_features SET goal = 'muscle'
WHERE goal IS NULL AND name IN ('custom:emph_e1rm_mean_pct14', 'custom:session_e1rm_vs28d', 'custom:emph_sets_14d', 'custom:lift_days_14d');
UPDATE research_custom_features SET goal = 'recovery' WHERE goal IS NULL AND name = 'custom:sleep_onset_h';
UPDATE research_custom_features SET goal = CASE owner
    WHEN 'hypertrophy' THEN 'muscle' WHEN 'metabolic' THEN 'body'
    WHEN 'conditioning' THEN 'cardio' ELSE 'recovery' END
WHERE goal IS NULL;
