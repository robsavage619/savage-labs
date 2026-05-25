-- Progress-photo body tracking. Raw images live on disk (settings.uploads_dir);
-- this stores metadata, capture-quality flags, and deterministic measurements.
-- See shc/vision/METHODOLOGY.md — every threshold is literature-grounded.

CREATE TABLE IF NOT EXISTS progress_photos (
    id            VARCHAR PRIMARY KEY,
    photo_date    DATE NOT NULL,
    angle         VARCHAR NOT NULL,          -- 'front' | 'side'
    file_path     VARCHAR NOT NULL,          -- relative to settings.uploads_dir
    -- capture-quality gate results (quality_gate.py)
    quality_pass  BOOLEAN NOT NULL,
    quality_flags VARCHAR,                   -- JSON array of failed-check names
    pose_conf     DOUBLE,                    -- min landmark visibility used
    scale_px      DOUBLE,                    -- shoulder->ankle reference length (px)
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (photo_date, angle)
);

CREATE TABLE IF NOT EXISTS photo_measurements (
    photo_id    VARCHAR NOT NULL REFERENCES progress_photos(id),
    metric      VARCHAR NOT NULL,            -- 'waist_width' | 'shoulder_width' | 'hip_width'
                                             -- | 'waist_to_shoulder' | 'waist_to_hip' | 'silhouette_area'
    value_px    DOUBLE,                      -- raw pixel measurement (NULL for pure ratios)
    value_norm  DOUBLE NOT NULL,             -- scale-normalized (dimensionless)
    PRIMARY KEY (photo_id, metric)
);

INSERT INTO schema_version (version) VALUES (29) ON CONFLICT DO NOTHING;
