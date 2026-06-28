-- Migration 0058: exercise-science evidence layer — GLUTES (pass 2).
--
-- Follows the curated+cited standard set by 0057 (biceps). Note: the strongest
-- glute builders (deep squats, Bulgarian split squat, RDL) are mapped
-- quad/hamstring-PRIMARY in exercise_muscle_map, but they are prescribed here for
-- glute development because the literature supports them — the science layer
-- legitimately reaches across the primary-muscle mapping. Volume accounting still
-- credits them by their primary muscle; this table is about what GROWS the glute.

-- ── GLUTES development brief ─────────────────────────────────────────────────
INSERT INTO muscle_development
    (muscle, regions, length_priority, weekly_sets_low, weekly_sets_high,
     freq_per_week, rep_scheme, rationale, citation, citation_url)
VALUES (
    'glutes',
    '["gluteus_maximus","gluteus_medius"]',
    'lengthened',
    8, 16, 2,
    'Anchor on long-length hip extension (deep squat/BSS/RDL bottom) 6–12 reps; add a heavy short-length builder (hip thrust) 8–12; include a unilateral/abduction movement 10–20 for the upper glute (medius).',
    'Squat and hip thrust elicit SIMILAR gluteus maximus hypertrophy despite hip thrust''s higher EMG (Plotkin 2023); one trial favored the squat (Barbalho 2020). Full ROM / long muscle length grows the glute max more than short-length partials (Kassiano 2023). The upper glute/medius is preferentially trained by hip abduction/external rotation and unilateral work (Selkowitz 2016; DiStefano 2009).',
    'Plotkin 2023 / Kassiano 2023',
    'https://consensus.app/papers/details/7e990ce959d45b929c847edd64924a97/'
)
ON CONFLICT DO NOTHING;

-- ── GLUTES exercise science ──────────────────────────────────────────────────
INSERT INTO exercise_science
    (exercise_name, muscle, region, length_bias, rep_low, rep_high, sfr_tier, rationale, citation, citation_url)
VALUES
    ('Bulgarian Split Squat (Dumbbell)', 'glutes', 'gluteus_maximus', 'lengthened', 8, 15, 'high',
     'Deep hip flexion loads the glute max at long muscle length; unilateral stance drives high glute activation. Lead lengthened builder.',
     'McCurdy 2017 / Kassiano 2023', 'https://consensus.app/papers/details/bfc19288c31d5828a8ad56329b1bb8bc/'),
    ('Romanian Deadlift (Barbell)', 'glutes', 'gluteus_maximus', 'lengthened', 8, 12, 'high',
     'Hip-hinge loads the glutes (and hamstrings) hardest at the stretched bottom position — long-length hip-extension stimulus.',
     'Kassiano 2023', 'https://consensus.app/papers/details/d1fe6d13dc165a4f83ea5ec8c91829db/'),
    ('Step Up (Dumbbell)', 'glutes', 'gluteus_medius', 'lengthened', 10, 15, 'moderate',
     'Unilateral step-up demands frontal-plane stabilization → high gluteus medius (upper glute) plus maximus activation through a long range.',
     'DiStefano 2009', 'https://consensus.app/papers/details/767f2f8eecb359d0aaa5a46d601464d1/'),
    ('Squat (Barbell)', 'glutes', 'gluteus_maximus', 'lengthened', 6, 10, 'moderate',
     'Full-depth back squat grows the glute max comparably to (or better than) the hip thrust, with the load applied at long muscle length.',
     'Plotkin 2023 / Barbalho 2020', 'https://consensus.app/papers/details/7ef41313457f597da59b8280c9819bca/'),
    ('Hip Thrust (Barbell)', 'glutes', 'gluteus_maximus', 'shortened', 8, 12, 'high',
     'Peak tension at full hip extension (short length); highest glute EMG and very loadable — the heavy short-length complement to the stretch work.',
     'Plotkin 2023', 'https://consensus.app/papers/details/7e990ce959d45b929c847edd64924a97/'),
    ('Kickback (Cable)', 'glutes', 'gluteus_maximus', 'mid', 12, 20, 'moderate',
     'Single-joint hip extension for low-fatigue accumulation volume; constant cable tension through the range.',
     'DiStefano 2009', 'https://consensus.app/papers/details/767f2f8eecb359d0aaa5a46d601464d1/'),
    ('Glute Bridge (Barbell)', 'glutes', 'gluteus_maximus', 'shortened', 10, 15, 'moderate',
     'Floor hip-extension variant peaking at short length; a lower-skill alternative to the hip thrust for short-length volume.',
     'Plotkin 2023', 'https://consensus.app/papers/details/7e990ce959d45b929c847edd64924a97/')
ON CONFLICT DO NOTHING;
