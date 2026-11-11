-- Location from OwnTracks (significant-changes mode). Raw points are pruned
-- after 90 days; stays keep only a place id and times. Places are discovered by
-- clustering stays and stay unnamed until Rob names them.
CREATE TABLE IF NOT EXISTS location_points (
    tst  TIMESTAMPTZ PRIMARY KEY,
    lat  DOUBLE NOT NULL,
    lon  DOUBLE NOT NULL,
    acc  DOUBLE
);

CREATE SEQUENCE IF NOT EXISTS places_id_seq START 1;

CREATE TABLE IF NOT EXISTS places (
    id          INTEGER PRIMARY KEY DEFAULT nextval('places_id_seq'),
    lat         DOUBLE NOT NULL,
    lon         DOUBLE NOT NULL,
    name        VARCHAR,
    first_seen  TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS place_stays (
    arrived_at  TIMESTAMPTZ PRIMARY KEY,
    left_at     TIMESTAMPTZ NOT NULL,
    place_id    INTEGER NOT NULL
);
