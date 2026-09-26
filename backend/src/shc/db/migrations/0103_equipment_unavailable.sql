-- 0103: exercises Rob's gym cannot run, declared by Rob, enforced by the engine.
--
-- The Hevy catalog says what Rob can LOG, not what his gym has. Seated Back
-- Extension is in the catalog, has 2021 history, and was the #2 lower_back
-- menu pick, so the daily plans for 2026-09-24, 25 and 26 all prescribed it on
-- a machine that does not exist. A memory note did not stop the repeats; this
-- table does. `autoregulation.unavailable_exercises()` reads it, the menus,
-- rotation swaps and RE-ENTRY TARGETS drop these names, and validate_plan #25
-- rejects any plan that names one.
--
-- Same shape as 0088's equipment_increment: a human-declared fact that no
-- amount of data mining can supply, keyed on the exact exercise string.
--
-- 'Kickback (Cable)' is the curated exercise_science name for the same
-- standing cable glute kickback, so it goes too; triceps cable kickbacks use a
-- handle, not the missing ankle attachment, and are unaffected.

CREATE TABLE IF NOT EXISTS equipment_unavailable (
    exercise_name TEXT PRIMARY KEY,
    note          TEXT,
    confirmed_on  DATE NOT NULL,
    updated_at    TIMESTAMPTZ DEFAULT now()
);

INSERT INTO equipment_unavailable (exercise_name, note, confirmed_on)
VALUES
    ('Seated Back Extension',
     'No seated back extension machine at Rob''s gym.', DATE '2026-09-16'),
    ('Glute Kickback (Machine)',
     'No glute kickback machine at Rob''s gym.', DATE '2026-07-15'),
    ('Standing Cable Glute Kickbacks',
     'No ankle attachment for the cable stack.', DATE '2026-07-15'),
    ('Kickback (Cable)',
     'Curated name for Standing Cable Glute Kickbacks; no ankle attachment.',
     DATE '2026-07-15')
ON CONFLICT (exercise_name) DO UPDATE SET
    note         = excluded.note,
    confirmed_on = excluded.confirmed_on,
    updated_at   = now();
