-- #31 — Orphan tables (zero readers as of 2026-06). Decision: KEEP-and-document,
-- not DROP. The DB was live-locked at audit time so row counts could not be
-- confirmed; per the conservative directive we do not drop tables that may hold
-- data worth keeping. Each is a real intended input, not schema debt — they are
-- marked intentionally-unwired here with a TODO for the wiring that closes them.
--
-- COMMENT ON persists the rationale into the catalog so the next audit sees the
-- decision inline (SELECT comment FROM duckdb_tables()).

COMMENT ON TABLE immunizations IS
    'INTENTIONALLY UNWIRED (#31). Clinical input: immunization records parsed from '
    'health source docs. TODO: wire ingest/clinical_profile to populate, and a '
    'reader to surface in the health profile. Do not drop — clinical history.';

COMMENT ON TABLE athlete_profile IS
    'INTENTIONALLY UNWIRED (#31). Key/value coaching state (goals, constraints). '
    'TODO: wire the workout/context builder to read it instead of memory files. '
    'Do not drop — intended profile store.';

COMMENT ON TABLE programmes IS
    'INTENTIONALLY UNWIRED (#31). Periodization programme container (DUP/block/'
    'conjugate). TODO: wire plan generation to persist + read the active programme. '
    'Do not drop — intended training-plan input.';

COMMENT ON TABLE llm_calls IS
    'INTENTIONALLY UNWIRED (#31). Unfinished observability: per-call token/cost/'
    'latency log. AI is chat-driven (no backend Anthropic SDK), so nothing writes '
    'here yet. TODO: log routed Copy-prompt->CC->POST cycles, or drop if the '
    'no-backend-LLM design makes it permanently moot.';

COMMENT ON TABLE source_docs IS
    'INTENTIONALLY UNWIRED (#31). Provenance for parsed clinical/source documents; '
    'immunizations.source_doc_id FKs to it. TODO: wire the doc ingest to register '
    'rows. Do not drop — referenced by immunizations FK.';

-- NOTE: session_set_logs was deliberately dropped in 0018 (Hevy-only set
-- logging; autoreg/VBT derive from workout_sets_dedup post-sync). It is NOT an
-- orphan table to document here — it intentionally does not exist.
