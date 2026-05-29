-- WHOOP auto-detects mindfulness/breathing as "yoga" (sport_id 45) and
-- occasionally "meditation". These are not athletic sessions and pollute the
-- cardio mix, ACWR calculations, and health story narrative.
-- Future syncs will also skip them via _EXCLUDED_KINDS in whoop.py.

DELETE FROM cardio_sessions
WHERE modality IN ('yoga', 'meditation', 'mindfulness');
