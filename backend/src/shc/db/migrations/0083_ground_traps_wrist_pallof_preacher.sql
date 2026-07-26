-- 0083: ground four evidence gaps from literature ingested into the vault, and
-- correct the preacher curl's length bias.
--
-- 0080 left 30 rows marked UNGROUNDED because the vault had nothing to support
-- them. Rather than let them stay unusable, the underlying literature was
-- searched, five papers were summarised into vault notes (see wiki/index.md,
-- 2026-07-26), and the rows those notes genuinely support are grounded here.
-- Rows the new notes do NOT support stay UNGROUNDED — that is the point of the
-- marker.
--
-- 1. PREACHER CURL LENGTH BIAS -- a real contradiction, now settled.
--    Preacher Curl (Dumbbell) claimed `shortened` ("peaks tension in the
--    shorter/flexed range") while Preacher Curl (Barbell) and (Machine) claimed
--    `lengthened` for the same movement pattern. Both cannot be right, and the
--    engine ranks candidates on length_bias, so the disagreement changed which
--    curl got selected. Zabaleta-Korta 2023 found the ONLY growth in a 9-week
--    incline-vs-preacher trial was distal, in the preacher group, and attributed
--    it to the preacher "placing the highest amount of strain in the range of
--    motion in which the arm muscles are more elongated". Kassiano 2024
--    replicated the distal-vs-proximal split in 63 subjects. The dumbbell row
--    was wrong; `lengthened` is correct.
--
--    Note the qualifier recorded in the vault note: Attarieh 2025 found NO
--    regional difference when preacher and Bayesian curls were matched for
--    resistance profile. So the bias comes from where resistance peaks in the
--    ROM, not from shoulder flexion -- which is why classifying by resistance
--    profile (lengthened) rather than shoulder position (which would argue
--    shortened, since shoulder flexion slackens the long head) is the right call.
--
-- 2. TRAPS -- previously ungroundable: "trapezius" appears once in 804 vault
--    notes. Ekstrom 2003 (JOSPT, 393 citations) tested 10 high-intensity
--    exercises and found the unilateral shrug produced peak UPPER-trapezius
--    activity, while horizontal extension with external rotation -- the
--    face-pull pattern -- produced peak MIDDLE-trapezius activity.
--
-- 3. WRIST EXTENSORS -- Shimose 2011: 8 weeks of isometric wrist-extension
--    training raised wrist-extension force AND grip force, increasing extensor
--    and decreasing flexor EMG during gripping. Grounds extension work only;
--    the wrist-FLEXOR row stays ungrounded because an extensor study does not
--    support it.
--
-- 4. PALLOF / ANTI-ROTATION -- Cinarli 2025: anti-movement core training
--    significantly improved external (p=0.023) and internal (p=0.003) oblique
--    activation vs control. The vault previously prescribed obliques through
--    rotation and lateral flexion only.
--
-- Keyed on (exercise_name, muscle) -- the row's identity. 0080 keyed on
-- citation, a column it was itself rewriting, and silently missed a drop.

-- ── 1. preacher curl: correct the contradicted length bias ──────────────────
UPDATE exercise_muscle
SET length_bias = 'lengthened',
    rationale = 'Preacher pattern loads the elbow flexors hardest at the bottom, where they '
                || 'are most elongated; that long-length strain is where the measured distal '
                || 'growth appeared. Complements — does not replace — a shoulder-extended '
                || 'curl, which grows the proximal region instead.',
    citation = 'zabaleta-korta-2023-regional-hypertrophy-muscle-length.md',
    citation_url = 'obsidian://open?vault=savage_vault&file=zabaleta-korta-2023-regional-hypertrophy-muscle-length'
WHERE exercise_name = 'Preacher Curl (Dumbbell)' AND muscle = 'biceps';

-- ── 2. traps: shrugs (upper) and face pulls (middle) ────────────────────────
UPDATE exercise_muscle
SET citation = 'ekstrom-2003-trapezius-serratus-emg.md',
    citation_url = 'obsidian://open?vault=savage_vault&file=ekstrom-2003-trapezius-serratus-emg'
WHERE muscle = 'traps'
  AND exercise_name IN ('Barbell Shrug', 'Dumbbell Shrug', 'Face Pull')
  AND citation LIKE 'UNGROUNDED%';

UPDATE exercise_muscle
SET citation = 'ekstrom-2003-trapezius-serratus-emg.md',
    citation_url = 'obsidian://open?vault=savage_vault&file=ekstrom-2003-trapezius-serratus-emg'
WHERE exercise_name = 'Face Pull' AND muscle = 'mid_back'
  AND citation LIKE 'UNGROUNDED%';

-- ── 3. wrist EXTENSORS only ─────────────────────────────────────────────────
UPDATE exercise_muscle
SET citation = 'shimose-2011-wrist-extension-grip-strength.md',
    citation_url = 'obsidian://open?vault=savage_vault&file=shimose-2011-wrist-extension-grip-strength'
WHERE muscle = 'forearms' AND region = 'wrist_extensors'
  AND citation LIKE 'UNGROUNDED%';

-- ── 4. Pallof / anti-rotation ───────────────────────────────────────────────
UPDATE exercise_muscle
SET citation = 'cinarli-2025-anti-movement-core-training.md',
    citation_url = 'obsidian://open?vault=savage_vault&file=cinarli-2025-anti-movement-core-training'
WHERE muscle = 'abs' AND region = 'obliques'
  AND exercise_name IN ('Cable Core Pallof Press', 'Pallof Press (Cable)')
  AND citation LIKE 'UNGROUNDED%';
