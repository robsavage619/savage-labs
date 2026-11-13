-- One row per surface per day: which screens actually get opened, so unused
-- ones can be deleted on evidence rather than opinion.
CREATE TABLE IF NOT EXISTS page_views (
    day  DATE NOT NULL,
    path VARCHAR NOT NULL,
    n    INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (day, path)
);
