-- A display name separate from the slug. The slug seeds a trial's arm
-- assignment and its bootstrap, so renaming it would change pre-registered
-- statistics. 'suggest-sleep-timing-hrv' classifies nights by sleep DURATION
-- (<7h vs >=8h), never by timing, so its name promised a test it doesn't run.
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS title VARCHAR;

UPDATE experiments
SET title = 'Sleep duration and HRV'
WHERE slug = 'suggest-sleep-timing-hrv';
