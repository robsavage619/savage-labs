-- #30 — Persist the brightness / left-right luminance asymmetry the vision
-- pipeline computes (vision/pipeline.py:_brightness_asymmetry) instead of
-- discarding it after the quality-gate check.
--
-- PhotoAnalysis.brightness_asymmetry already carries the value; it was only used
-- to raise the 'uneven_lighting' advisory and then thrown away. Storing it lets a
-- later trend reason about capture-lighting consistency over time (a high or
-- rising asymmetry trend flags that the 'visible detail' critique section is
-- riding on lighting, not real change).
--
-- NOTE (handoff): the INSERT in api/routers/progress_photos.py:upload_photo must
-- be extended to write analysis.brightness_asymmetry into this column. That file
-- is owned elsewhere; the column is added here so the writer has a target.

ALTER TABLE progress_photos
    ADD COLUMN IF NOT EXISTS brightness_asymmetry DOUBLE;
