-- Migration 0066: unify exercise_muscle_map + exercise_science into ONE table.
--
-- The two tables were a split-brain: exercise_muscle_map drove volume crediting
-- (primary/secondary), exercise_science drove head/length/SFR selection — keyed
-- the same way but able to disagree about which muscles a movement trains (the
-- wrist-curl-is-biceps bug, the 0065 crediting gaps). This collapses them into a
-- single canonical `exercise_muscle` row per (exercise, muscle) carrying BOTH the
-- crediting (role + credit) AND the anatomy (region + length_bias + SFR + rep
-- range + citation). One row → the two can never diverge again.
--
-- Expand-contract: the old table NAMES are recreated as VIEWS over exercise_muscle
-- reproducing their exact old shapes, so every existing reader keeps working
-- unchanged (verified: weekly_muscle_volume / weekly_region_volume / evidence_menu
-- / _planned_sets_by_muscle all byte-identical before/after). The one runtime
-- writer (backfill_exercise_map) and the affected tests now write exercise_muscle
-- directly. Runs last so 0060/0064/0065's inserts+updates are captured.

CREATE TABLE IF NOT EXISTS exercise_muscle (
    exercise_name TEXT    NOT NULL,
    muscle        TEXT    NOT NULL,
    role          TEXT    NOT NULL DEFAULT 'primary',  -- 'primary' | 'secondary'
    credit        DOUBLE  NOT NULL DEFAULT 1.0,        -- 1.0 primary / 0.5 / 0.3 (arm)
    region        TEXT,          -- muscle head (brachialis, long_head, …); NULL if uncurated
    length_bias   TEXT,          -- lengthened | mid | shortened
    rep_low       INTEGER,
    rep_high      INTEGER,
    sfr_tier      TEXT,          -- high | moderate | low
    rationale     TEXT,
    citation      TEXT,          -- NULL ⇔ not science-curated
    citation_url  TEXT,
    PRIMARY KEY (exercise_name, muscle)
);

-- Spine = the map. Primary rows (full credit), LEFT JOIN the science attrs.
INSERT INTO exercise_muscle
SELECT m.exercise_name, m.primary_muscle, 'primary', 1.0,
       s.region, s.length_bias, s.rep_low, s.rep_high, s.sfr_tier, s.rationale,
       s.citation, s.citation_url
FROM exercise_muscle_map m
LEFT JOIN exercise_science s
       ON s.exercise_name = m.exercise_name AND s.muscle = m.primary_muscle
ON CONFLICT DO NOTHING;

-- Secondary rows (one per unnested secondary), credited at the standard synergist
-- rate — arm flexors/extensors 0.3, else 0.5 — matching volume.py, LEFT JOIN science.
INSERT INTO exercise_muscle
SELECT m.exercise_name, u.sec, 'secondary',
       CASE WHEN u.sec IN ('biceps', 'triceps', 'forearms') THEN 0.3 ELSE 0.5 END,
       s.region, s.length_bias, s.rep_low, s.rep_high, s.sfr_tier, s.rationale,
       s.citation, s.citation_url
FROM exercise_muscle_map m
CROSS JOIN UNNEST(m.secondary_muscles) AS u(sec)
LEFT JOIN exercise_science s
       ON s.exercise_name = m.exercise_name AND s.muscle = u.sec
ON CONFLICT DO NOTHING;

-- Contract: replace the old tables with views reproducing their exact shapes.
DROP TABLE exercise_muscle_map;
DROP TABLE exercise_science;

CREATE VIEW exercise_muscle_map AS
SELECT exercise_name,
       MAX(muscle) FILTER (WHERE role = 'primary')                        AS primary_muscle,
       COALESCE(list(muscle) FILTER (WHERE role = 'secondary'), []::VARCHAR[]) AS secondary_muscles
FROM exercise_muscle
GROUP BY exercise_name;

CREATE VIEW exercise_science AS
SELECT exercise_name, muscle, region, length_bias, rep_low, rep_high, sfr_tier,
       rationale, citation, citation_url
FROM exercise_muscle
WHERE citation IS NOT NULL;  -- a science-curated row is one with a citation
