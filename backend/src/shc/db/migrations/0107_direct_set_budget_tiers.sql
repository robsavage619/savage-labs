-- Rob's call, 2026-11-01: abs step down from a growth target to a held 4 sets, and
-- back and hamstrings rise to 3 sets per muscle. Explicit human intent (invariant 10).
UPDATE muscle_volume_targets SET tier = 'maintain', mv_sets = 4 WHERE muscle_group = 'abs';
UPDATE muscle_volume_targets SET mv_sets = 3 WHERE muscle_group IN ('lats', 'mid_back', 'hamstrings');
DELETE FROM muscle_emphasis WHERE muscle = 'abs';
