-- Full-text index over claim content: the lexical candidate leg for recall.
--
-- Why (2026-08-21 reviewer eval, ~42 logged queries): vector-only candidate
-- selection is phrase-sensitive. Queries sharing distinctive vocabulary with an
-- on-target claim ("chunker config", "boilerplate-survey", "--respect-reviewed")
-- repeatedly failed to surface claims that were active AND embedded — the miss
-- was candidate selection / ranking, not supply. A lexical leg retrieves by the
-- distinctive phrase directly and is fused with the vector candidates in
-- recall(); see W_LEXICAL there.
--
-- STORED generated column so the read-only role (claimbase_ro) needs no new
-- grants and the MCP query path stays SELECT-only.

ALTER TABLE claims
  ADD COLUMN IF NOT EXISTS content_tsv tsvector
  GENERATED ALWAYS AS (to_tsvector('english', content)) STORED;

CREATE INDEX IF NOT EXISTS idx_claims_content_tsv
  ON claims USING GIN (content_tsv);
