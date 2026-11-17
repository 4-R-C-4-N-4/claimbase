-- Exact attribution is additive; existing ambiguous session values remain untouched.
ALTER TABLE retrieval_log ADD COLUMN IF NOT EXISTS call_id uuid;
ALTER TABLE retrieval_log ADD COLUMN IF NOT EXISTS canonical_session text;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS call_id uuid;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS canonical_session text;
CREATE INDEX IF NOT EXISTS retrieval_log_call_id_idx ON retrieval_log (call_id);
CREATE INDEX IF NOT EXISTS feedback_call_id_idx ON feedback (call_id);
CREATE INDEX IF NOT EXISTS retrieval_log_canonical_idx ON retrieval_log (corpus, canonical_session);
CREATE TABLE IF NOT EXISTS session_receipts (
    call_id uuid PRIMARY KEY,
    session_id text NOT NULL,
    corpus text NOT NULL,
    tool text NOT NULL
);
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'claimbase_ro') THEN
        GRANT SELECT ON session_receipts TO claimbase_ro;
    END IF;
END $$;

ALTER TABLE session_receipts ADD COLUMN IF NOT EXISTS conflicted boolean NOT NULL DEFAULT false;
ALTER TABLE retrieval_log ADD COLUMN IF NOT EXISTS declared_session text;
ALTER TABLE feedback ADD COLUMN IF NOT EXISTS declared_session text;
-- Track inference that depends on a logged delivery so revocation can retract it.
ALTER TABLE exposures ADD COLUMN IF NOT EXISTS source_log uuid
    REFERENCES retrieval_log(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS exposures_source_log_idx ON exposures (source_log);
-- Preserve explicit identities written by the initial Phase2 implementation.
UPDATE retrieval_log SET declared_session = canonical_session
 WHERE declared_session IS NULL AND canonical_session IS NOT NULL;
UPDATE feedback SET declared_session = canonical_session
 WHERE declared_session IS NULL AND canonical_session IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS sessions_id_corpus_key ON sessions (id, corpus);
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'session_receipts_scope_fkey'
                   AND conrelid = 'session_receipts'::regclass) THEN
        ALTER TABLE session_receipts ADD CONSTRAINT session_receipts_scope_fkey
            FOREIGN KEY (session_id, corpus) REFERENCES sessions (id, corpus);
    END IF;
END $$;
