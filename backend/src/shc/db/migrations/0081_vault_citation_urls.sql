-- 0081: point a vault-note citation at the vault note.
--
-- 0080 re-grounded 80 rows from an unverifiable paper onto a real vault note but
-- left `citation_url` untouched, so those rows ended up naming a vault note
-- while linking to the consensus.app page for the paper that was just replaced.
-- A citation whose link goes somewhere other than its source is worse than one
-- with no link at all: it looks verified and leads to the wrong evidence.
--
-- Vault notes are local, so the correct target is an obsidian:// URI. That is a
-- working link on Rob's machine and an obviously-local one anywhere else, which
-- is the honest signal — this evidence lives in his vault, not on the web.
--
-- Scoped to rows whose citation IS a vault filename. UNGROUNDED rows keep their
-- original paper URL: the citation string already says the claim is unverified,
-- and the URL records which paper was claimed.

UPDATE exercise_muscle
SET citation_url = 'obsidian://open?vault=savage_vault&file='
                   || replace(replace(citation, '.md', ''), ' ', '%20')
WHERE citation LIKE '%.md'
  AND citation NOT LIKE 'UNGROUNDED%';
