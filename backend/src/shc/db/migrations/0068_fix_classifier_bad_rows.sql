-- Fix misclassified exercise_muscle rows caused by keyword-ordering bugs
-- in exercise_classifier.py (commit fix(engine): classifier keyword order).
--
-- Bug 1: "hammer" substring matched Hammerstrength brand → all credited biceps.
-- Bug 2: "fly" matched before "reverse fly" check → rear-delt flyes credited chest.
-- Bug 3: "chest"/"incline" matched before back check → chest-supported row credited chest.

DELETE FROM exercise_muscle
WHERE exercise_name IN (
    'Hammerstrength Chest Press',
    'Hammerstrength Decline Chest Press',
    'Hammerstrength High Row',
    'Hammerstrength Iso Row',
    'Hammerstrength Shrug',
    'Chest Supported Incline Row (Dumbbell)',
    'Dumbbell Reverse Fly',
    'Mini Loop Band Reverse Fly',
    'Rear Delt Reverse Fly (Machine)'
);

-- Hammerstrength chest machines
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit) VALUES
    ('Hammerstrength Chest Press',         'chest',       'primary',   1.0),
    ('Hammerstrength Chest Press',         'front_delts', 'secondary', 0.5),
    ('Hammerstrength Chest Press',         'triceps',     'secondary', 0.3),
    ('Hammerstrength Decline Chest Press', 'chest',       'primary',   1.0),
    ('Hammerstrength Decline Chest Press', 'front_delts', 'secondary', 0.5),
    ('Hammerstrength Decline Chest Press', 'triceps',     'secondary', 0.3)
ON CONFLICT DO NOTHING;

-- Hammerstrength back machines
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit) VALUES
    ('Hammerstrength High Row', 'lats',     'primary',   1.0),
    ('Hammerstrength High Row', 'mid_back', 'secondary', 0.5),
    ('Hammerstrength High Row', 'biceps',   'secondary', 0.3),
    ('Hammerstrength Iso Row',  'lats',     'primary',   1.0),
    ('Hammerstrength Iso Row',  'mid_back', 'secondary', 0.5),
    ('Hammerstrength Iso Row',  'biceps',   'secondary', 0.3)
ON CONFLICT DO NOTHING;

-- Hammerstrength shrug
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit) VALUES
    ('Hammerstrength Shrug', 'traps', 'primary', 1.0)
ON CONFLICT DO NOTHING;

-- Chest-supported incline row (back movement, not chest)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit) VALUES
    ('Chest Supported Incline Row (Dumbbell)', 'lats',     'primary',   1.0),
    ('Chest Supported Incline Row (Dumbbell)', 'mid_back', 'secondary', 0.5),
    ('Chest Supported Incline Row (Dumbbell)', 'biceps',   'secondary', 0.3)
ON CONFLICT DO NOTHING;

-- Rear-delt reverse flies (rear_delts, not chest)
INSERT INTO exercise_muscle (exercise_name, muscle, role, credit) VALUES
    ('Dumbbell Reverse Fly',          'rear_delts', 'primary',   1.0),
    ('Dumbbell Reverse Fly',          'traps',      'secondary', 0.5),
    ('Mini Loop Band Reverse Fly',    'rear_delts', 'primary',   1.0),
    ('Mini Loop Band Reverse Fly',    'traps',      'secondary', 0.5),
    ('Rear Delt Reverse Fly (Machine)', 'rear_delts', 'primary', 1.0),
    ('Rear Delt Reverse Fly (Machine)', 'traps',    'secondary', 0.5)
ON CONFLICT DO NOTHING;
