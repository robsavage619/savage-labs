-- Exclude non-training WHOOP autodetections and double-counted strength from load.
--
-- Two bugs fed v_session_load → composite_load → acute load → ACWR → the rest gate:
--
-- 1. WHOOP auto-detects low-effort stillness as 'yoga'/'meditation' (and
--    'cross country skiing'). These aren't real training sessions; the cardio
--    panel and modality breakdown already exclude them, but the load view did
--    not — inflating ACWR and tripping the >1.5 rest gate on phantom strain.
--    (Yoga is in fact the single largest strain contributor in recent weeks.)
--
-- 2. Strength sessions are tracked in Hevy and added to composite_load as
--    hevy tonnes. When WHOOP ALSO autodetects the same lift as a
--    'powerlifting'/'weightlifting' workout, its strain was summed on top —
--    double-counting that session. Strength load belongs to the Hevy arm only,
--    so strength kinds are excluded from the WHOOP strain arm here.
--
-- NOTE: percent_recorded is stored as a FRACTION (0–1), not a percentage.
-- The straps-off threshold is therefore 0.5 (50% recorded), not 50. Migration
-- 0021's `>= 50` excluded every session and never took effect; this supersedes it.

CREATE OR REPLACE VIEW v_session_load AS
SELECT
    started_at::DATE AS date,
    COALESCE(SUM(w.strain), 0) AS whoop_strain,
    COUNT(DISTINCT w.id) AS sessions
FROM workouts w
WHERE COALESCE(w.percent_recorded, 1.0) >= 0.5
  AND COALESCE(w.kind, '') NOT IN (
      'yoga', 'meditation', 'cross country skiing',
      'powerlifting', 'weightlifting'
  )
GROUP BY started_at::DATE;

INSERT INTO schema_version (version) VALUES (33) ON CONFLICT DO NOTHING;
