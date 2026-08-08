-- 0091: give rear and side delts enough movements to rotate at all.
--
-- The menu shows 4 candidates per muscle. After 0089 both delt heads had exactly
-- 4 distinct MOVEMENTS curated, so the coverage pass took one and the fill pass
-- took the rest: the same four every week, forever. No plateau or tenure trigger
-- could act, because there was never an alternative to swap to. This is distinct
-- from the naming gap 0089 fixed — neither muscle had a single name-blocked
-- option. They were simply under-curated.
--
-- Method is migration 0064's: COPY the science from an already-vetted,
-- mechanically-equivalent curated row. No citation is invented, and where a
-- source row is flagged UNGROUNDED that flag travels with it rather than being
-- laundered into a grounded-looking claim.
--
-- Upsert, not UPDATE: these target rows are created by `backfill_exercise_map`
-- from Rob's logs, so a bare UPDATE silently no-ops on any database that has not
-- ingested them (every test fixture). role/credit are set explicitly on insert
-- and deliberately NOT touched on conflict — the live mapping already credits
-- Dumbbell Upright Row's side-delt contribution as a secondary, and copying the
-- source's `primary` over it would inflate side-delt volume retroactively.
--
-- Menu eligibility only: every target already carries a crediting row live, so
-- no set is newly credited and no landmark fit moves. Each also has real Hevy
-- history, which is the evidence the equipment exists (catalog presence is not).

-- Machine reverse fly is the supported version of the cable reverse fly — same
-- transverse-abduction mechanic, same mid position. 13 logged sets.
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Rear Delt Reverse Fly (Machine)', muscle, 'primary', 1.0, region, length_bias, rep_low, rep_high,
       sfr_tier, rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Rear Delt Reverse Fly (Cable)' AND muscle = 'rear_delts'
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = EXCLUDED.region, length_bias = EXCLUDED.length_bias,
    rep_low = EXCLUDED.rep_low, rep_high = EXCLUDED.rep_high,
    sfr_tier = EXCLUDED.sfr_tier, rationale = EXCLUDED.rationale,
    citation = EXCLUDED.citation, citation_url = EXCLUDED.citation_url;

-- A seated dumbbell rear delt raise IS a dumbbell reverse fly performed seated;
-- the torso angle preserves the lengthened start the source row is cited for.
-- 109 logged sets.
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Seated Dumbbell Rear Delt Raise', muscle, 'primary', 1.0, region, length_bias, rep_low, rep_high,
       sfr_tier, rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Rear Delt Reverse Fly (Dumbbell)' AND muscle = 'rear_delts'
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = EXCLUDED.region, length_bias = EXCLUDED.length_bias,
    rep_low = EXCLUDED.rep_low, rep_high = EXCLUDED.rep_high,
    sfr_tier = EXCLUDED.sfr_tier, rationale = EXCLUDED.rationale,
    citation = EXCLUDED.citation, citation_url = EXCLUDED.citation_url;

-- Machine lateral raise is the guided dumbbell lateral raise — same shortened-
-- position abduction. 126 logged sets.
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Lateral Raise (Machine)', muscle, 'primary', 1.0, region, length_bias, rep_low, rep_high,
       sfr_tier, rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Lateral Raise (Dumbbell)' AND muscle = 'side_delts'
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = EXCLUDED.region, length_bias = EXCLUDED.length_bias,
    rep_low = EXCLUDED.rep_low, rep_high = EXCLUDED.rep_high,
    sfr_tier = EXCLUDED.sfr_tier, rationale = EXCLUDED.rationale,
    citation = EXCLUDED.citation, citation_url = EXCLUDED.citation_url;

-- Dumbbell upright row mirrors the barbell upright row already curated here.
-- NOTE the source carries 'UNGROUNDED: Andersen 2008' and that label is copied
-- verbatim — this option's citation is not vault-verified and the menu keeps
-- saying so. Its PRIMARY muscle is traps, hence role=secondary/0.5 here, exactly
-- how the live mapping already credits it.
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit, region, length_bias,
                             rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
SELECT 'Dumbbell Upright Row', muscle, 'secondary', 0.5, region, length_bias, rep_low, rep_high,
       sfr_tier, rationale, citation, citation_url
  FROM exercise_muscle WHERE exercise_name = 'Upright Row (Barbell)' AND muscle = 'side_delts'
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = EXCLUDED.region, length_bias = EXCLUDED.length_bias,
    rep_low = EXCLUDED.rep_low, rep_high = EXCLUDED.rep_high,
    sfr_tier = EXCLUDED.sfr_tier, rationale = EXCLUDED.rationale,
    citation = EXCLUDED.citation, citation_url = EXCLUDED.citation_url;

-- Retire the Fitbod-era twin. 'Dumbbell Lateral Raise' (438 lifetime sets, last
-- 2026-02-17, source fitbod) and 'Lateral Raise (Dumbbell)' (source hevy, still
-- current) are one movement. The Fitbod string is ALSO a Hevy template, so it
-- survives the vocabulary filter and competed for the slot — and won it on
-- lifetime volume, surfacing a dead name tagged "stale" while hiding a lift Rob
-- had done three days earlier. Its crediting row stays; only eligibility goes.
UPDATE exercise_muscle SET citation = NULL, citation_url = NULL
 WHERE exercise_name = 'Dumbbell Lateral Raise';
DELETE FROM exercise_alias WHERE canonical_name = 'Dumbbell Lateral Raise';

-- Deliberately NO alias back to the retired twin here, unlike 0089's inversions.
-- An alias redirects the plateau/recency lookup from the curated name to the
-- string Rob logs it under, and it only helps while the curated name has no
-- history of its own. 'Lateral Raise (Dumbbell)' has history — it is what he
-- logs NOW (2026-08-05) — so a redirect would read the dead twin's February date
-- and report a lift done three days ago as "stale: not trained in >6wk".
-- The same misdirection already existed on Bulgarian Split Squat (Dumbbell);
-- `_progress_info` now prefers whichever name was trained most recently, so a
-- row like that degrades to a no-op rather than corrupting selection.
DELETE FROM exercise_alias
 WHERE canonical_name = 'Bulgarian Split Squat (Dumbbell)'
   AND logged_name = 'Bulgarian Split Squat';
