-- Migration 0025: exercise_muscle_map + tournament_events
-- exercise_muscle_map: maps Hevy exercise names to muscle groups for per-muscle volume tracking
-- tournament_events: tracks pickleball tournament results and DUPR rating changes

CREATE TABLE IF NOT EXISTS exercise_muscle_map (
    exercise_name VARCHAR PRIMARY KEY,
    primary_muscle VARCHAR NOT NULL,
    secondary_muscles VARCHAR[] DEFAULT []
);

-- Seed from canonical RP/Hevy exercise list (top exercises by muscle group)
INSERT OR IGNORE INTO exercise_muscle_map (exercise_name, primary_muscle, secondary_muscles) VALUES
-- Chest
('Bench Press (Barbell)', 'chest', ['front_delts', 'triceps']),
('Bench Press (Dumbbell)', 'chest', ['front_delts', 'triceps']),
('Incline Bench Press (Barbell)', 'chest', ['front_delts', 'triceps']),
('Incline Bench Press (Dumbbell)', 'chest', ['front_delts', 'triceps']),
('Decline Bench Press (Barbell)', 'chest', ['triceps']),
('Chest Fly (Dumbbell)', 'chest', []),
('Chest Fly (Cable)', 'chest', []),
('Cable Crossover', 'chest', []),
('Push-Up', 'chest', ['front_delts', 'triceps']),
('Dip (Chest)', 'chest', ['triceps']),

-- Back
('Deadlift (Barbell)', 'back', ['glutes', 'hamstrings', 'traps']),
('Romanian Deadlift (Barbell)', 'hamstrings', ['glutes', 'back']),
('Romanian Deadlift (Dumbbell)', 'hamstrings', ['glutes', 'back']),
('Pull-Up', 'back', ['biceps']),
('Chin-Up', 'back', ['biceps']),
('Lat Pulldown (Cable)', 'back', ['biceps']),
('Seated Cable Row', 'back', ['biceps', 'rear_delts']),
('Bent Over Row (Barbell)', 'back', ['biceps', 'rear_delts']),
('Bent Over Row (Dumbbell)', 'back', ['biceps', 'rear_delts']),
('T-Bar Row', 'back', ['biceps']),
('Single Arm Row (Dumbbell)', 'back', ['biceps']),
('Face Pull (Cable)', 'rear_delts', ['traps']),

-- Shoulders
('Overhead Press (Barbell)', 'front_delts', ['triceps', 'traps']),
('Overhead Press (Dumbbell)', 'front_delts', ['triceps', 'traps']),
('Arnold Press (Dumbbell)', 'front_delts', ['side_delts', 'triceps']),
('Lateral Raise (Dumbbell)', 'side_delts', []),
('Lateral Raise (Cable)', 'side_delts', []),
('Front Raise (Dumbbell)', 'front_delts', []),
('Rear Delt Fly (Dumbbell)', 'rear_delts', []),
('Rear Delt Fly (Cable)', 'rear_delts', []),
('Upright Row (Barbell)', 'side_delts', ['traps']),
('Shrug (Barbell)', 'traps', []),
('Shrug (Dumbbell)', 'traps', []),

-- Biceps
('Bicep Curl (Barbell)', 'biceps', []),
('Bicep Curl (Dumbbell)', 'biceps', []),
('Hammer Curl (Dumbbell)', 'biceps', ['brachialis']),
('Preacher Curl (Barbell)', 'biceps', []),
('Preacher Curl (Dumbbell)', 'biceps', []),
('Concentration Curl (Dumbbell)', 'biceps', []),
('Cable Curl', 'biceps', []),
('Incline Curl (Dumbbell)', 'biceps', []),

-- Triceps
('Tricep Pushdown (Cable)', 'triceps', []),
('Skull Crusher (Barbell)', 'triceps', []),
('Skull Crusher (Dumbbell)', 'triceps', []),
('Close Grip Bench Press (Barbell)', 'triceps', ['chest']),
('Overhead Tricep Extension (Dumbbell)', 'triceps', []),
('Overhead Tricep Extension (Cable)', 'triceps', []),
('Dip (Tricep)', 'triceps', []),
('Tricep Kickback (Dumbbell)', 'triceps', []),

-- Quads
('Squat (Barbell)', 'quads', ['glutes', 'hamstrings']),
('Front Squat (Barbell)', 'quads', ['glutes']),
('Hack Squat (Machine)', 'quads', ['glutes']),
('Leg Press (Machine)', 'quads', ['glutes', 'hamstrings']),
('Leg Extension (Machine)', 'quads', []),
('Bulgarian Split Squat (Dumbbell)', 'quads', ['glutes']),
('Bulgarian Split Squat (Barbell)', 'quads', ['glutes']),
('Lunge (Dumbbell)', 'quads', ['glutes', 'hamstrings']),
('Lunge (Barbell)', 'quads', ['glutes', 'hamstrings']),
('Step Up (Dumbbell)', 'quads', ['glutes']),
('Goblet Squat (Dumbbell)', 'quads', ['glutes']),

-- Hamstrings
('Leg Curl (Machine)', 'hamstrings', []),
('Nordic Curl', 'hamstrings', []),
('Good Morning (Barbell)', 'hamstrings', ['back']),

-- Glutes
('Hip Thrust (Barbell)', 'glutes', ['hamstrings']),
('Hip Thrust (Dumbbell)', 'glutes', ['hamstrings']),
('Glute Bridge (Barbell)', 'glutes', ['hamstrings']),
('Kickback (Cable)', 'glutes', []),

-- Calves
('Calf Raise (Machine)', 'calves', []),
('Standing Calf Raise (Dumbbell)', 'calves', []),
('Seated Calf Raise (Machine)', 'calves', []),

-- Core
('Plank', 'core', []),
('Ab Rollout', 'core', []),
('Hanging Leg Raise', 'core', []),
('Cable Crunch', 'core', []),
('Pallof Press (Cable)', 'core', []),
('Dead Bug', 'core', []);

-- tournament_events: DUPR/UTPR tracking with training context
CREATE TABLE IF NOT EXISTS tournament_events (
    id VARCHAR PRIMARY KEY DEFAULT gen_random_uuid()::VARCHAR,
    event_date DATE NOT NULL,
    event_name VARCHAR NOT NULL,
    location VARCHAR,
    format VARCHAR DEFAULT 'doubles',   -- 'doubles' | 'singles' | 'mixed'
    dupr_before DOUBLE,
    dupr_after DOUBLE,
    utpr_before DOUBLE,
    utpr_after DOUBLE,
    result_notes VARCHAR,
    notes VARCHAR,
    created_at TIMESTAMPTZ DEFAULT now()
);
