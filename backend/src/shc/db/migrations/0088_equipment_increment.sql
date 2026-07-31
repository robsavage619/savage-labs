-- 0088: declared equipment increments — the one thing no amount of data mining
-- can supply.
--
-- `training/loadable.py` infers each lift's loadable notches from logged history,
-- which is right for well-sampled lifts and silent on thin ones. It deliberately
-- refuses to argue a weight is absent under `_MIN_SETS_TO_PROVE_A_GAP` (10) sets,
-- because a missing value proves nothing on a lift trained a handful of times --
-- that guard is what stops it inventing a gap (`Crunch (Machine)`, 9 sets across
-- 3 notches, was being cut 70 -> 60 on no evidence at all).
--
-- The cost of that correct caution is that the case which STARTED this work goes
-- unfixed. Hip Thrust (Machine) has 9 logged sets across exactly two weights,
-- 230 and 270, so the inferred grid may not rule anything out and a prescribed
-- 235 passes through untouched -- the precise complaint Rob raised.
--
-- This table is the escape hatch: a human-declared fact outranks an inference.
-- Rob confirmed 2026-07-31 that the hip thrust machine is PLATE-LOADED and his
-- smallest plates are 10s. Plates load in symmetric PAIRS, so the true step is
-- 20 lb, not 10 -- and the observed 230 -> 270 gap being exactly 40 (two pairs)
-- corroborates it. The lattice is therefore 230 + 20k: 230, 250, 270, ...
-- A prescribed 235 is genuinely unloadable and belongs at 230.
--
-- anchor_lb fixes the lattice PHASE, which increment alone cannot. An empty
-- carriage weighs something unknown, so "multiples of 20" is wrong; what is
-- known is that 230 is achievable and the step is 20. Any logged value works as
-- an anchor.
--
-- Deliberately NOT auto-populated. Inferring "plate-loaded, 10s" from a
-- histogram is exactly the guessing this table exists to override.

CREATE TABLE IF NOT EXISTS equipment_increment (
    exercise_name TEXT PRIMARY KEY,
    increment_lb  DOUBLE NOT NULL,
    anchor_lb     DOUBLE NOT NULL,
    note          TEXT,
    updated_at    TIMESTAMPTZ DEFAULT now()
);

INSERT INTO equipment_increment (exercise_name, increment_lb, anchor_lb, note)
VALUES (
    'Hip Thrust (Machine)', 20.0, 230.0,
    'Plate-loaded; smallest plates are 10s and they load in pairs, so the step '
    || 'is 2 x 10 = 20 lb. Confirmed by Rob 2026-07-31. The logged 230/270 pair '
    || 'differs by exactly two steps, which corroborates it.'
)
ON CONFLICT (exercise_name) DO UPDATE SET
    increment_lb = excluded.increment_lb,
    anchor_lb    = excluded.anchor_lb,
    note         = excluded.note,
    updated_at   = now();
