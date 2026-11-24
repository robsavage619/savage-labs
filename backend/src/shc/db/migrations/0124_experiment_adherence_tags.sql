-- Per-session studies read adherence from the Hevy session itself: a fixed tag in the
-- workout description or the outcome exercise's note names the arm that was followed.
-- One tag per arm, set at registration (e.g. 'nocaf' / 'caf').
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS adherence_tag_a VARCHAR;
ALTER TABLE experiments ADD COLUMN IF NOT EXISTS adherence_tag_b VARCHAR;
