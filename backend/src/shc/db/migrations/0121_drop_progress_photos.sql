-- Progress photos were removed on 2026-11-14 (docs/decisions/2026-11.md), and Rob
-- asked for the stored data to go with them. Nothing reads these tables any more.
-- photo_measurements references progress_photos, so it goes first.
DROP TABLE IF EXISTS photo_measurements;
DROP TABLE IF EXISTS progress_photos;
DROP TABLE IF EXISTS physique_critiques;
