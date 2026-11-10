-- Randomized trials log themselves (intention-to-treat): each day from
-- autolog_from is recorded at its assigned arm unless flagged otherwise. Existing
-- active studies start tomorrow, the first day their assignment rides in the
-- plan; back-filling months nobody was told about would count unfollowed days.
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS autolog_from DATE;
UPDATE experiments SET autolog_from = current_date + INTERVAL 1 DAY
WHERE design = 'randomized_alternating' AND status = 'active' AND autolog_from IS NULL;
