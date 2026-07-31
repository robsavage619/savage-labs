-- 0087: move abs onto the grow tier and lats down to maintain.
--
-- Rob's explicit training decision, 2026-07-31. Invariant 10 requires exactly
-- this: the maintenance tier is the one mechanism that deliberately holds a
-- muscle BELOW its minimum effective volume, so it is reachable only by a
-- stated human intent -- never fitted, inferred, or arrived at by omission.
-- `persist_volume_landmarks` writes mev/mav/mrv only and never touches `tier`,
-- so this stays put across landmark refits.
--
-- What prompted it: a volume audit on 2026-07-31 found abs at 0.4 credited
-- sets/wk with SEVEN of the last NINE weeks at literally zero, against an MV
-- floor of 2. It had been reported as "ok" by an analysis that averaged only
-- the weeks abs was trained -- a GROUP BY over event rows emits no row for a
-- zero week, so the zeros were silently dropped. Rob caught it from his own
-- memory of training, not from the data. lats over the same window sat at
-- 7.2/wk against an MEV of 10 -- under its floor, but trained nearly every
-- week (1 of 9 zero) and carried by rows and pulldowns regardless.
--
-- The budget arithmetic (this is a REALLOCATION, not an addition -- the whole
-- point of 0078 was that the demand list must stay satisfiable against a
-- measured delivery of ~94 credited sets/wk):
--     lats  grow -> maintain :  floor MEV 10 -> MV 2   = ~8 sets/wk freed
--     abs   maintain -> grow :  floor MV 2 -> MEV  6   = ~6 sets/wk claimed
-- Net ~2 sets/wk freed. Both emphasis muscles (biceps, glutes) are untouched
-- and remain on grow, so invariant 7 is unaffected.
--
-- Risk accepted and stated: lats is a large muscle and dropping it to MV means
-- the engine stops demanding growth volume for it. The vault records 1-2 hard
-- sets/wk maintaining hypertrophy for up to ~3 months in trained lifters, and
-- lats gets substantial secondary credit from every row and pulldown, so this
-- costs no accrued size on that horizon. Revisit at the next mesocycle.

-- All mesocycle scopes, including the '' global-default row, so a mesocycle
-- rollover cannot resurrect the old assignment.
UPDATE muscle_volume_targets
SET tier = 'grow', updated_at = now()
WHERE muscle_group = 'abs';

UPDATE muscle_volume_targets
SET tier = 'maintain', updated_at = now()
WHERE muscle_group = 'lats';
