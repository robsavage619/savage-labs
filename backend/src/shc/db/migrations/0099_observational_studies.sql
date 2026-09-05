-- Four auto-suggested studies had run 47–63 days and logged one day between
-- them. Two independent causes: the scorer had no extractor for their outcome
-- metrics (fixed in 64e3ff4), and their arms describe OBSERVABLE CONDITIONS
-- ("<6.5h sleep", "2 pickleball sessions in 3 days") while arm_for_day()
-- assigns arms by hashing the date and never looks at behaviour.
--
-- Auto-logging adherence against that hash would have filed an 8.4h night into
-- the "<6.5h sleep" arm and produced a confident null — worse than silence.
-- These are observational studies wearing a randomized trial's clothes, so
-- mark them as such and classify days by what actually happened.
--
-- `design` already existed and defaulted to 'randomized_alternating', but
-- nothing branched on it. It becomes load-bearing here.

UPDATE experiments
SET design = 'observational'
WHERE slug IN (
    'suggest-pickleball-density-hrv',
    'suggest-rest-day-spacing',
    'suggest-sleep-timing-hrv'
);

-- Sleep timing: the original contrast does not exist in this subject's life.
-- Over 63 nights: 0 under 6.0h and 2 between 6.0–6.5h, against a requirement
-- of 8 per arm. Widening the low arm to <7.0h yields 15 vs 31.
--
-- The contrast is narrower, so the effect bar must move with it: judging a
-- 7h-vs-8h comparison against the 5ms bar written for 6.5h-vs-8h would return
-- REFUTED on a real-but-smaller effect — a false negative dressed as a
-- finding. 2.5ms is half the original bar for roughly half the contrast.
UPDATE experiments
SET condition_a = '<7.0h sleep',
    hypothesis  = 'Getting >=8h sleep (vs <7h) improves next-morning HRV by >=2.5ms.',
    min_effect  = 2.5,
    notes       = COALESCE(notes || ' | ', '')
                  || 'Low arm widened 6.5h->7.0h on 2026-09-04: only 2 nights under 6.5h '
                  || 'existed in 63 days, so the original contrast was unobservable. '
                  || 'min_effect lowered 5.0->2.5 to match the narrower contrast.'
WHERE slug = 'suggest-sleep-timing-hrv';

-- Full rest: 6 full-rest days in 63, against a requirement of 10 per arm. No
-- threshold change creates rest days that were not taken, so this is retired
-- rather than left "active" and silently unanswerable. Re-register it during a
-- deload block, when the rest arm will actually populate.
UPDATE experiments
SET status = 'abandoned',
    notes  = COALESCE(notes || ' | ', '')
             || 'Abandoned 2026-09-04: only 6 full-rest days in 63 against min_per_arm=10. '
             || 'The rest arm cannot populate at the current training frequency. '
             || 'Re-register during a deload block.'
WHERE slug = 'suggest-full-rest-day-hrv';
