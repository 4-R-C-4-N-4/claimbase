-- Independent checker results; no claim-use attribution is implied.
CREATE TABLE IF NOT EXISTS usage_outcomes (
    session_id text NOT NULL REFERENCES sessions(id),
    corpus text NOT NULL,
    run_id text NOT NULL,
    checker text NOT NULL,
    passed boolean NOT NULL,
    evidence jsonb NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (run_id, checker, session_id)
);
-- The composite FK also serializes scope-changing updates with outcome writes.
CREATE UNIQUE INDEX IF NOT EXISTS sessions_id_corpus_key ON sessions (id, corpus);
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'usage_outcomes_session_scope_fkey'
                   AND conrelid = 'usage_outcomes'::regclass) THEN
        ALTER TABLE usage_outcomes ADD CONSTRAINT usage_outcomes_session_scope_fkey
            FOREIGN KEY (session_id, corpus) REFERENCES sessions (id, corpus);
    END IF;
END $$;
DO $$ BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'claimbase_ro') THEN
        GRANT SELECT ON usage_outcomes TO claimbase_ro;
    END IF;
END $$;
