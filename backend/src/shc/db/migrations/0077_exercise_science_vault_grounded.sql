-- Deepen exercise_science for the starved muscles, grounded in vault notes.
--
-- WHY THIS EXISTS
-- `_select_grounded` asks for 4 movements per muscle. After dropping candidates
-- with no logged history and no alias resolution, 7 of 17 muscles had <= 4 usable
-- candidates for those 4 slots — lower_back had ONE. Selection was not selecting;
-- it returned the whole shelf, which is what Rob saw as "the same exercises over
-- and over" (Face Pull 34 of 73 plans). Rotation, fixed in f0e9196, needs a pool
-- deeper than the slot count before it can actuate.
--
-- CITATION SCHEME — deliberately different from rows 0057-0064
-- Those rows cite bare author-year strings and 87 of 113 (77%) name a source that
-- appears NOWHERE in the vault (Campos 2020, Yagiz 2022, Rodriguez-Ridao 2020...),
-- while the planner's own rule is "cite only real filenames from the VAULT
-- CATALOG." Unverifiable citations in an evidence-graded table are worse than no
-- citation: they launder recall as evidence. Every row below cites a vault
-- FILENAME, so any claim here is checkable with `ls`/`grep` against
-- ~/Vault/savage_vault/wiki. Where the vault grounds a PRINCIPLE and the
-- exercise-level assignment follows from movement mechanics rather than a study,
-- the rationale says so in plain words rather than implying a citation covers it.
-- citation_url uses a vault:// URI pointing at the note, satisfying the same
-- "every curated row is traceable to a source" contract that
-- test_all_targeted_muscles_are_grounded enforces — resolvable offline, and
-- unlike the consensus.app links on older rows it cannot rot or point at a paper
-- that does not say what the row claims.
--
-- SCOPE — only movements Rob demonstrably trains
-- Every exercise below appears in his own workout_sets. The previous rows added
-- Nordic Curl, Chin-Up, Hack Squat, Dip (Chest) and 19 others he has never logged
-- once — 40% of the menu was unusable, which is what made the pools so shallow in
-- the first place. Adding aspirational movements deepens the table and not the
-- menu.
--
-- STILL OPEN after this migration: traps, adductors, forearms remain at 4 usable
-- candidates. The vault has no note that grounds their regional structure (0 hits
-- for "hip adduction" and "wrist curl"), so curating them would mean inventing
-- exactly the kind of citation this migration exists to stop. They need a vault
-- ingest first — see DECISIONS.md.

-- ── calves ────────────────────────────────────────────────────────────────────
-- Region split is architectural, not preferential: muscle-architecture-strength
-- records soleus as force-optimised (short fascicles, high pennation) and
-- gastrocnemius as velocity-optimised (long fascicles, low pennation), citing
-- zatsiorsky-2021-ch3-athlete-specific-strength. The knee angle selects which:
-- a bent knee slackens the biarticular gastrocnemius and shifts load to the
-- soleus; a straight knee loads the gastrocnemius. That mechanical consequence is
-- standard biomechanics, not a claim the vault makes for these specific machines.
-- Rep bands follow fiber-type-hypertrophic-potential: soleus is >80% Type I, with
-- explicit "implications for rep range optimization per muscle" — hence the
-- higher band on the seated (soleus) variants.
INSERT INTO exercise_muscle
  (exercise_name, muscle, region, length_bias, rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
VALUES
 ('Seated Machine Calf Press', 'calves', 'soleus', 'lengthened', 12, 25, 'high',
  'Bent knee slackens the biarticular gastrocnemius and concentrates load on the soleus. Soleus is >80% Type I, so it earns the higher rep band. Rob''s logged soleus movement (131 sets).',
  'fiber-type-hypertrophic-potential.md', 'vault://wiki/fiber-type-hypertrophic-potential.md'),
 ('Calf Press (Machine)', 'calves', 'gastrocnemius', 'lengthened', 10, 20, 'high',
  'Straight-knee press loads the gastrocnemius through a long fascicle excursion; the deep bottom position is the lengthened stimulus. 168 logged sets.',
  'muscle-architecture-strength.md', 'vault://wiki/muscle-architecture-strength.md'),
 ('Standing Calf Raise (Machine)', 'calves', 'gastrocnemius', 'lengthened', 10, 20, 'high',
  'Straight-knee standing variant — gastrocnemius emphasis, free-loaded so the stretch position is under tension throughout.',
  'muscle-architecture-strength.md', 'vault://wiki/muscle-architecture-strength.md'),
 ('Smith Machine Calf Raise', 'calves', 'gastrocnemius', 'lengthened', 10, 20, 'moderate',
  'Straight-knee gastrocnemius work; the fixed bar path removes the balance demand but also the free-weight stabiliser stimulus, hence moderate rather than high SFR.',
  'muscle-architecture-strength.md', 'vault://wiki/muscle-architecture-strength.md')
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = EXCLUDED.region, length_bias = EXCLUDED.length_bias,
    rep_low = EXCLUDED.rep_low, rep_high = EXCLUDED.rep_high,
    sfr_tier = EXCLUDED.sfr_tier, rationale = EXCLUDED.rationale,
    citation = EXCLUDED.citation, citation_url = EXCLUDED.citation_url;

-- ── lower_back ────────────────────────────────────────────────────────────────
-- Had exactly ONE usable candidate. helms-2018-qsg-program-building maps the hip
-- hinge pattern (deadlift, good morning, back extension) to erectors as a primary
-- mover, which is what licenses these rows. SFR tiering is grounded in
-- israetel-2020-ch3-fatigue-management: axial fatigue "behaves like Systemic
-- because the spinal erectors are involved in nearly all loaded movements; affects
-- ALL subsequent compound training". A heavily axially-loaded deadlift is
-- therefore a poor stimulus-to-fatigue vehicle for direct erector hypertrophy even
-- though it trains them hard — SFR is stimulus per unit fatigue, and the fatigue
-- here is charged against the whole session. Unloaded//supported extensions carry
-- the direct work; injury-prevention-lumbar (LBPS = 44-50% of strength-training
-- injuries) is why none of these are pushed to failure-range low reps.
INSERT INTO exercise_muscle
  (exercise_name, muscle, region, length_bias, rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
VALUES
 ('Seated Back Extension', 'lower_back', 'erector_spinae', 'lengthened', 10, 20, 'high',
  'Direct erector work with the spine supported and no axial column load, so the stimulus is not charged against every later compound. Rob''s most-logged direct erector movement (136 sets).',
  'israetel-2020-ch3-fatigue-management.md', 'vault://wiki/israetel-2020-ch3-fatigue-management.md'),
 ('Trap Bar Deadlift', 'lower_back', 'erector_spinae', 'mid', 5, 10, 'moderate',
  'Neutral handles and a more upright torso shorten the moment arm on the spine versus a straight bar, lowering axial cost for the same erector work. 88 logged sets.',
  'israetel-2020-ch3-fatigue-management.md', 'vault://wiki/israetel-2020-ch3-fatigue-management.md'),
 ('Smith Machine Stiff-Legged Deadlift', 'lower_back', 'erector_spinae', 'lengthened', 8, 12, 'moderate',
  'Loaded hinge holding the erectors isometrically at length. Rob''s highest-volume hinge (318 sets). Moderate SFR: real axial cost, but the fixed path removes the balance tax.',
  'helms-2018-qsg-program-building.md', 'vault://wiki/helms-2018-qsg-program-building.md')
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = EXCLUDED.region, length_bias = EXCLUDED.length_bias,
    rep_low = EXCLUDED.rep_low, rep_high = EXCLUDED.rep_high,
    sfr_tier = EXCLUDED.sfr_tier, rationale = EXCLUDED.rationale,
    citation = EXCLUDED.citation, citation_url = EXCLUDED.citation_url;

-- ── abs ───────────────────────────────────────────────────────────────────────
-- injury-prevention-lumbar prescribes developing the corset across ALL abdominal
-- layers by name — "rectus abdominis + obliques + internal abdominis + deep
-- epaxials" — which is the grounding for treating obliques as a region that must
-- be covered rather than incidental. Rob logs 296 sets of Cable Oblique Twist and
-- the table carried no oblique row that resolves to it.
INSERT INTO exercise_muscle
  (exercise_name, muscle, region, length_bias, rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
VALUES
 ('Cable Oblique Twist', 'abs', 'obliques', 'mid', 12, 20, 'high',
  'Loaded rotation — the oblique layer of the corset, which the lumbar-injury note names explicitly and which crunch patterns do not train. 296 logged sets.',
  'injury-prevention-lumbar.md', 'vault://wiki/injury-prevention-lumbar.md'),
 ('Ab Crunch Machine', 'abs', 'rectus_abdominis', 'mid', 10, 20, 'high',
  'Loaded, progressively overloadable spinal flexion for the rectus. 744 logged sets — Rob''s actual staple, previously absent from the evidence table.',
  'injury-prevention-lumbar.md', 'vault://wiki/injury-prevention-lumbar.md'),
 ('Standing Cable Crunch', 'abs', 'rectus_abdominis', 'lengthened', 10, 20, 'high',
  'Cable resistance holds tension at the top of the stretch where bodyweight crunches unload entirely.',
  'injury-prevention-lumbar.md', 'vault://wiki/injury-prevention-lumbar.md'),
 ('Plank', 'abs', 'rectus_abdominis', 'mid', 30, 60, 'moderate',
  'Anti-extension isometric bracing — the intra-abdominal-pressure mechanism the lumbar note credits with reducing disc pressure up to 40%. Reps are SECONDS held, not repetitions.',
  'injury-prevention-lumbar.md', 'vault://wiki/injury-prevention-lumbar.md')
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = EXCLUDED.region, length_bias = EXCLUDED.length_bias,
    rep_low = EXCLUDED.rep_low, rep_high = EXCLUDED.rep_high,
    sfr_tier = EXCLUDED.sfr_tier, rationale = EXCLUDED.rationale,
    citation = EXCLUDED.citation, citation_url = EXCLUDED.citation_url;

-- ── hamstrings ────────────────────────────────────────────────────────────────
-- israetel-2020-ch1-specificity is explicit and directly on point: "Hip-hinge
-- movements and leg curls use the hamstrings across different actions (hip
-- extension vs knee flexion); using both regularly reaches all fibers; using only
-- one misses one biomechanical function." Both regions already exist in the
-- vocabulary; what was missing were movements Rob actually performs to fill them.
INSERT INTO exercise_muscle
  (exercise_name, muscle, region, length_bias, rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
VALUES
 ('Dumbbell Stiff Legged Deadlift', 'hamstrings', 'hip_extension', 'lengthened', 8, 15, 'high',
  'Hip-extension function under a long-length load. Israetel: training only knee flexion misses one of the two biomechanical functions entirely.',
  'israetel-2020-ch1-specificity.md', 'vault://wiki/israetel-2020-ch1-specificity.md'),
 ('Seated Leg Curl', 'hamstrings', 'knee_flexion', 'lengthened', 10, 20, 'high',
  'Knee-flexion function with the hip flexed, which holds the hamstrings at a longer length than the prone variant. The other half of the Israetel pairing.',
  'israetel-2020-ch1-specificity.md', 'vault://wiki/israetel-2020-ch1-specificity.md')
ON CONFLICT (exercise_name, muscle) DO UPDATE SET
    region = EXCLUDED.region, length_bias = EXCLUDED.length_bias,
    rep_low = EXCLUDED.rep_low, rep_high = EXCLUDED.rep_high,
    sfr_tier = EXCLUDED.sfr_tier, rationale = EXCLUDED.rationale,
    citation = EXCLUDED.citation, citation_url = EXCLUDED.citation_url;
