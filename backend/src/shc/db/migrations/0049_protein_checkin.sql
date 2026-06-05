-- Migration 0049: add protein tracking to daily check-in.
-- Used to gate volume-increase prescriptions: if protein has been consistently
-- below target, the stimulus can't be converted and adding sets is counterproductive.
ALTER TABLE daily_checkin ADD COLUMN IF NOT EXISTS protein_grams INTEGER;
