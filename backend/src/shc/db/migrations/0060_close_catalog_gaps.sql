-- Migration 0060: close the forearm + adductor catalog gaps, wired to Hevy.
--
-- 0059 flagged that forearms had no wrist movements and adductors had no
-- isolation. These are added here using the EXACT Hevy exercise-template titles
-- (verified against the synced hevy_exercise_templates library) so a set logged
-- in Hevy maps straight to the muscle map on sync, and a pushed routine
-- fuzzy-matches the template. Each new movement is also grounded in the
-- exercise-science layer with a citation. Bonus: a dedicated gluteus-medius
-- isolation (Hip Abduction machine) is added for the glute upper-shelf.

-- ── Catalog: add the movements with Hevy-exact titles ────────────────────────
INSERT INTO exercise_muscle_map (exercise_name, primary_muscle, secondary_muscles) VALUES
    ('Seated Palms Up Wrist Curl', 'forearms', []),
    ('Palms-Up Dumbbell Wrist Curl', 'forearms', []),
    ('Palms-Down Dumbbell Wrist Curl', 'forearms', []),
    ('Seated Wrist Extension (Barbell)', 'forearms', []),
    ('Wrist Roller', 'forearms', []),
    ('Reverse Curl (Dumbbell)', 'forearms', ['biceps']),
    ('Reverse Curl (Barbell)', 'forearms', ['biceps']),
    ('Hip Adduction (Machine)', 'adductors', []),
    ('Hip Abduction (Machine)', 'glutes', [])
ON CONFLICT DO NOTHING;

-- ── Forearms: real regions now trainable ─────────────────────────────────────
UPDATE muscle_development SET
    regions = '["wrist_flexors","wrist_extensors","brachioradialis"]',
    rep_scheme = '10-20 reps wrist flexion and extension with a loaded stretch at the bottom; reverse curls 10-15 for the brachioradialis',
    rationale = 'Forearm size responds to direct loading: wrist flexion, wrist extension, and pronated reverse curls each hypertrophy a different forearm region, and the wrist extensors in particular need dedicated work because pulling movements never extend the wrist. Dedicated wrist movements are now in the catalog (Hevy: Seated Palms Up Wrist Curl, Palms-Down Dumbbell Wrist Curl, Seated Wrist Extension).'
WHERE muscle = 'forearms';

INSERT INTO exercise_science VALUES
  ('Seated Palms Up Wrist Curl', 'forearms', 'wrist_flexors', 'lengthened', 12, 20, 'high', 'Direct wrist flexion loads the forearm flexors through a full range with a loaded stretch at the bottom; forearm flexion-extension training produced large forearm and elbow-flexor hypertrophy.', 'Yagiz 2022', 'https://consensus.app/papers/details/589e28c8184850f89b1c654915fc6ba2/'),
  ('Palms-Down Dumbbell Wrist Curl', 'forearms', 'wrist_extensors', 'lengthened', 12, 20, 'high', 'Palms-down (reverse) wrist curl trains the wrist extensors, which stay highly active across grip tasks and need dedicated work; direct loading drives forearm hypertrophy.', 'Yagiz 2022', 'https://consensus.app/papers/details/589e28c8184850f89b1c654915fc6ba2/'),
  ('Seated Wrist Extension (Barbell)', 'forearms', 'wrist_extensors', 'lengthened', 12, 20, 'moderate', 'Barbell wrist extension isolates the wrist extensors under load through a full range; the extensors require dedicated extension work no compound provides.', 'Yagiz 2022', 'https://consensus.app/papers/details/589e28c8184850f89b1c654915fc6ba2/'),
  ('Reverse Curl (Dumbbell)', 'forearms', 'brachioradialis', 'mid', 10, 15, 'moderate', 'Pronated-grip elbow flexion biases the brachioradialis and wrist extensors, adding the forearm-width and separation that read as definition.', 'Yagiz 2022', 'https://consensus.app/papers/details/589e28c8184850f89b1c654915fc6ba2/')
ON CONFLICT DO NOTHING;

-- ── Adductors: isolation now available ───────────────────────────────────────
UPDATE muscle_development SET
    rep_scheme = '6-12 reps deep compounds; 10-15 reps hip adduction machine isolation',
    rationale = 'Full-depth squatting drove significantly greater adductor volume than half squats, loading the adductors at long length under deep hip flexion; the Hip Adduction machine is now in the catalog to provide the direct isolation that compounds cannot.'
WHERE muscle = 'adductors';

INSERT INTO exercise_science VALUES
  ('Hip Adduction (Machine)', 'adductors', 'adductors', 'lengthened', 10, 15, 'high', 'The hip adduction machine isolates the adductors with resistance greatest near the abducted (stretched) start; machine adduction effectively recruits the hip adductors and supplies the isolation deep compounds cannot.', 'Brandt 2013', 'https://consensus.app/papers/details/31a547691cfd57179c7e7ba91aa90f92/')
ON CONFLICT DO NOTHING;

-- ── Glutes bonus: dedicated medius (upper-shelf) isolation ────────────────────
INSERT INTO exercise_science VALUES
  ('Hip Abduction (Machine)', 'glutes', 'gluteus_medius', 'shortened', 12, 20, 'moderate', 'The hip abduction machine isolates the gluteus medius (upper glute); abduction and external rotation preferentially activate the superior glute that hip-extension movements under-train.', 'Selkowitz 2016', 'https://consensus.app/papers/details/9ba1146fa8be5286a88567436537351e/')
ON CONFLICT DO NOTHING;
