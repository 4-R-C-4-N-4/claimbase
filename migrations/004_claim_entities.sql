-- 004 — link claims to the entities they mention.
--
-- Entity resolution produced a clean table that nothing reads: `claims.subject_id`
-- is null everywhere and `recall` never consults entities, so folding 13 surface
-- forms of retriever.ts into one identity changed no answer. The link table is what
-- turns resolution into retrieval.
--
-- A claim mentions several things, so this is many-to-many rather than the single
-- `subject_id` the original schema anticipated. That column stays for the eventual
-- resolved subject; this is about every entity a claim touches.

CREATE TABLE IF NOT EXISTS claim_entities (
  claim_id  uuid NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
  entity_id uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  -- How the mention was matched, so a bad linker can be audited rather than
  -- silently degrading rank.
  via       text NOT NULL DEFAULT 'alias',
  PRIMARY KEY (claim_id, entity_id)
);
CREATE INDEX IF NOT EXISTS claim_entities_entity_idx ON claim_entities (entity_id);
