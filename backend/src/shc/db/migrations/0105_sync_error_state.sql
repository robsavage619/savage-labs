-- A failing sync used to surface only in the log; the app kept reading as healthy.
ALTER TABLE oauth_state ADD COLUMN IF NOT EXISTS last_error VARCHAR;
ALTER TABLE oauth_state ADD COLUMN IF NOT EXISTS last_error_at TIMESTAMPTZ;
