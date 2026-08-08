-- 0090: give the soleus a loggable home.
--
-- Fallout from 0089, caught by the per-head coverage check. The only curated
-- soleus movement was 'Seated Machine Calf Press', which turns out to be a
-- Fitbod-era string (131 sets, last logged 2025-02-28, source 'fitbod') and so
-- sits outside the Hevy vocabulary. Once 0089 started filtering unloggable
-- movements out of the menu, calves silently dropped from 2 heads to 1 — the
-- soleus became unprogrammable rather than merely mis-named.
--
-- 'Seated Calf Raise' is a real Hevy template. The pairing is made on MECHANICS,
-- not on name similarity: a seated calf movement flexes the knee, which slackens
-- the gastrocnemius and puts the soleus under load. That is the entire reason
-- the row is tagged soleus, and it is the same knee-angle distinction 0089
-- deliberately refused to blur when it declined to pair seated with standing
-- calf raises by string match.
--
-- The Fitbod row keeps its region and role so historical sets still credit the
-- soleus; only the citation moves, which is what governs menu eligibility.
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Seated Calf Raise', muscle, role, credit, region, length_bias, rep_low, rep_high,
       sfr_tier, rationale, citation, citation_url
  FROM exercise_muscle
 WHERE exercise_name = 'Seated Machine Calf Press' AND muscle = 'calves'
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = COALESCE(exercise_muscle.region, EXCLUDED.region),
    length_bias = COALESCE(exercise_muscle.length_bias, EXCLUDED.length_bias),
    rep_low = COALESCE(exercise_muscle.rep_low, EXCLUDED.rep_low),
    rep_high = COALESCE(exercise_muscle.rep_high, EXCLUDED.rep_high),
    sfr_tier = COALESCE(exercise_muscle.sfr_tier, EXCLUDED.sfr_tier),
    rationale = COALESCE(exercise_muscle.rationale, EXCLUDED.rationale),
    citation = COALESCE(exercise_muscle.citation, EXCLUDED.citation),
    citation_url = COALESCE(exercise_muscle.citation_url, EXCLUDED.citation_url);

UPDATE exercise_muscle SET citation = NULL, citation_url = NULL
 WHERE exercise_name = 'Seated Machine Calf Press';

-- Re-point the redirect 0089 inverted, so sets logged under either legacy string
-- still credit the surviving science.
DELETE FROM exercise_alias
 WHERE canonical_name IN ('Seated Machine Calf Press', 'Seated Calf Raise');
INSERT INTO exercise_alias (canonical_name, logged_name)
VALUES ('Seated Calf Raise', 'Seated Machine Calf Press')
ON CONFLICT (canonical_name) DO UPDATE SET logged_name = EXCLUDED.logged_name;
