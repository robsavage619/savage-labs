-- Fill gaps in exercise_muscle_map: exercises appearing in recent workouts that were
-- unmapped, causing the per-muscle volume panel to under-report actual training stimulus.
-- Also adds traps as an explicit tracked muscle for all trap-dominant exercises.

INSERT OR IGNORE INTO exercise_muscle_map (exercise_name, primary_muscle, secondary_muscles) VALUES
-- Cable pulls / rows
('Seated Cable Row - V Grip (Cable)', 'mid_back', ['biceps', 'traps']),
('Lat Pulldown - Close Grip (Cable)', 'lats', ['biceps']),
('Cable Row', 'mid_back', ['biceps', 'traps']),
('Seated Cable Row - Bar Grip', 'mid_back', ['biceps', 'traps']),

-- Rear delt / upper back
('Rear Delt Reverse Fly (Cable)', 'rear_delts', ['traps']),
('Face Pull', 'rear_delts', ['traps']),

-- Shoulders / press
('Standing Military Press (Barbell)', 'side_delts', ['front_delts', 'traps']),
('Overhead Triceps Extension (Cable)', 'triceps', []),

-- Hamstrings / posterior chain
('Single Leg Romanian Deadlift (Dumbbell)', 'hamstrings', ['glutes']),

-- Legs / compound
('Split Squat (Dumbbell)', 'quads', ['glutes', 'hamstrings']),
('Goblet Squat', 'quads', ['glutes']),

-- Chest / incline
('Hammerstrength Incline Chest Press', 'chest', ['front_delts', 'triceps']),
('Incline Chest Fly (Dumbbell)', 'chest', []);

-- Trap-dominant exercises — make traps visible in the volume panel
INSERT OR IGNORE INTO exercise_muscle_map (exercise_name, primary_muscle, secondary_muscles) VALUES
('Dumbbell Shrug', 'traps', []),
('Shrug (Dumbbell)', 'traps', []),
('Barbell Shrug', 'traps', []),
('Dumbbell Upright Row', 'traps', ['side_delts', 'biceps']),
('Upright Row (Barbell)', 'traps', ['side_delts']),
('Upright Row (Dumbbell)', 'traps', ['side_delts']);

-- Add traps MEV/MAV/MRV target to any active mesocycle that doesn't have it yet.
-- Traps: MEV 4, MAV 8, MRV 16 (RP norms for upper traps direct work).
INSERT OR IGNORE INTO muscle_volume_targets (muscle_group, mev_sets, mav_sets, mrv_sets, mesocycle_id)
SELECT 'traps', 4, 8, 16, id FROM mesocycles WHERE status = 'active';
