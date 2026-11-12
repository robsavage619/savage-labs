-- A merged place stays as an alias so later stays near it resolve to the target
-- instead of founding the duplicate again. Hidden places drop out of the card only.
ALTER TABLE places ADD COLUMN IF NOT EXISTS hidden BOOLEAN DEFAULT FALSE;
ALTER TABLE places ADD COLUMN IF NOT EXISTS merged_into INTEGER;

-- Dated markers (illness, travel, a tournament, a medication start) that the
-- trend charts draw, so a dip can be read against what happened.
CREATE SEQUENCE IF NOT EXISTS events_id_seq START 1;
CREATE TABLE IF NOT EXISTS events (
    id    INTEGER PRIMARY KEY DEFAULT nextval('events_id_seq'),
    day   DATE NOT NULL,
    label VARCHAR NOT NULL
);
