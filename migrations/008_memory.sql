-- 008 — the memory layer: usage, sessions, exposures, memory PRs.
--
-- Additive only. Nothing here rewrites or drops an existing row, so it is safe
-- on a populated store and `DROP TABLE` undoes it. See GOALS.md for what each
-- table is for and which RFC goal it serves.

-- --- claims: three nullable columns -----------------------------------------
--
-- origin     stated | observed | inferred. Distinct from trust: trust says who
--            authored the text, origin says how the system came to hold it. A
--            claim a user stated in a session is `stated` and standing at once;
--            one the writer drew from a single episode is `inferred` and starts
--            tentative.
-- level      specific | general. A general claim points at its specifics and
--            never replaces them — the answer to drift. Nothing writes
--            `general` yet (consolidation is not built).
-- merged_by  the memory PR that created this version, if one did.
--
-- status gains two values, by convention (the column has never had a CHECK):
--   tentative — one supporting episode; not served by recall
--   contested — served, labelled, and on the exception report

ALTER TABLE claims ADD COLUMN IF NOT EXISTS origin text;
ALTER TABLE claims ADD COLUMN IF NOT EXISTS level text NOT NULL DEFAULT 'specific';
ALTER TABLE claims ADD COLUMN IF NOT EXISTS merged_by uuid;

CREATE INDEX IF NOT EXISTS claims_tentative_idx
  ON claims (corpus, status) WHERE status IN ('tentative', 'contested');

-- --- sessions ----------------------------------------------------------------
--
-- One row per submitted transcript. The transcript itself becomes events
-- (source = 'session'); this row is the handle the measures join on.

CREATE TABLE IF NOT EXISTS sessions (
  id            text PRIMARY KEY,           -- '<harness>:<harness session id>'
  corpus        text,                       -- NULL = no project (user scope only)
  harness       text NOT NULL,
  started_at    timestamptz,
  ended_at      timestamptz,
  outcome       text,                       -- as reported by the harness, free text
  submitted_at  timestamptz NOT NULL DEFAULT now(),
  processed_at  timestamptz,                -- writer finished with it
  n_turns       integer NOT NULL DEFAULT 0,
  n_episodes    integer NOT NULL DEFAULT 0,
  n_triggers    integer NOT NULL DEFAULT 0,
  meta          jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS sessions_corpus_idx ON sessions (corpus, ended_at);

-- What each session had to go and look up. A lookup repeated across sessions
-- is a collection trigger: the store should have held the answer.
CREATE TABLE IF NOT EXISTS session_lookups (
  session_id  text NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  corpus      text,
  key         text NOT NULL,                -- normalized target: 'read:docs/x.md'
  n           integer NOT NULL DEFAULT 1,
  PRIMARY KEY (session_id, key)
);
CREATE INDEX IF NOT EXISTS session_lookups_key_idx ON session_lookups (corpus, key);

-- --- retrieval log -----------------------------------------------------------
--
-- Derived from logs/mcp-queries.jsonl by `claimbase usage sync`. The file stays
-- the source of truth: the MCP server reads through a role that cannot write,
-- and logging must not become the exception that guarantee grows. `id` is a
-- hash of the raw log line, so a re-sync inserts nothing.

CREATE TABLE IF NOT EXISTS retrieval_log (
  id          uuid PRIMARY KEY,
  ts          timestamptz NOT NULL,
  client      text,
  session     text,                         -- MCP server process, or harness session
  corpus      text,                         -- the project the call was scoped to
  tool        text NOT NULL,
  query       text,
  n_results   integer NOT NULL DEFAULT 0,
  ms          integer,
  error       text
);
CREATE INDEX IF NOT EXISTS retrieval_log_ts_idx ON retrieval_log (corpus, ts);
CREATE INDEX IF NOT EXISTS retrieval_log_session_idx ON retrieval_log (session);

-- What each call returned. No FK to claims on purpose: the log records what
-- the agent saw at the moment of asking, and must survive the claim being
-- rebuilt or removed later. `claim_corpus` is the returned claim's own project,
-- which is what makes a leak (a claim from another project, unasked)
-- countable rather than assumed absent.
CREATE TABLE IF NOT EXISTS retrieval_hits (
  log_id        uuid NOT NULL REFERENCES retrieval_log(id) ON DELETE CASCADE,
  claim_id      uuid NOT NULL,
  rank          integer NOT NULL,
  claim_corpus  text,
  PRIMARY KEY (log_id, claim_id)
);
CREATE INDEX IF NOT EXISTS retrieval_hits_claim_idx ON retrieval_hits (claim_id);

CREATE TABLE IF NOT EXISTS feedback (
  id        uuid PRIMARY KEY,               -- hash of the log line
  ts        timestamptz NOT NULL,
  claim_id  uuid,                           -- NULL for `missed` with no claim
  kind      text NOT NULL,                  -- helpful | not_helpful | missed
  session   text,
  client    text,
  corpus    text,
  note      text
);
CREATE INDEX IF NOT EXISTS feedback_claim_idx ON feedback (claim_id);

-- --- exposures ---------------------------------------------------------------
--
-- What a claim has survived. Three kinds, per the RFC:
--   used       a session acted on it after it was returned
--   predicted  an episode arrived that the claim already accounted for
--   tested     an outside observation agreed with it (verification; not built)
--
-- A claim unrefuted after 40 exposures and a claim never used are both
-- standing, and this table is what makes them visibly different.

CREATE TABLE IF NOT EXISTS exposures (
  id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  claim_id   uuid NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
  kind       text NOT NULL CHECK (kind IN ('used', 'predicted', 'tested')),
  session_id text,
  event_id   uuid REFERENCES events(id) ON DELETE SET NULL,
  turn       integer,                          -- where in the session, if known
  at         timestamptz NOT NULL DEFAULT now(),
  via        text NOT NULL DEFAULT 'writer',   -- writer | feedback | verifier
  -- One exposure per (claim, kind, session, episode): re-running the writer
  -- over the same session must not inflate the count.
  dedupe     text NOT NULL,
  UNIQUE (claim_id, kind, dedupe)
);
CREATE INDEX IF NOT EXISTS exposures_claim_idx ON exposures (claim_id, at);

-- --- memory PRs --------------------------------------------------------------
--
-- The only way a standing claim changes. Never edited after insert; undone by
-- another PR (kind = 'revert'). `lineage` is the root of the supersession
-- chain, so repeated reversals of one belief can be counted without walking
-- the chain each time.

CREATE TABLE IF NOT EXISTS memory_prs (
  id               uuid PRIMARY KEY,
  corpus           text NOT NULL,
  target_claim     uuid REFERENCES claims(id) ON DELETE SET NULL,
  amendment_claim  uuid REFERENCES claims(id) ON DELETE SET NULL,
  lineage          uuid NOT NULL,
  amendment        text NOT NULL,
  kind             text NOT NULL,           -- correction | source_mismatch | narrowing
                                            -- | revert | consolidation
  author           text NOT NULL,           -- user | agent | writer | verifier
  evidence_event   uuid REFERENCES events(id) ON DELETE SET NULL,
  evidence_trust   text NOT NULL,
  outcome          text NOT NULL,           -- merged | contested
  reverts          uuid REFERENCES memory_prs(id) ON DELETE SET NULL,
  merged_at        timestamptz NOT NULL DEFAULT now(),
  meta             jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS memory_prs_lineage_idx ON memory_prs (lineage, merged_at);
CREATE INDEX IF NOT EXISTS memory_prs_target_idx ON memory_prs (target_claim);
CREATE INDEX IF NOT EXISTS memory_prs_corpus_idx ON memory_prs (corpus, merged_at);

-- --- read role ---------------------------------------------------------------
--
-- The MCP server reads these through claimbase_ro. Guarded, because the role
-- is created by hand on a real store and may not exist on a scratch one.

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'claimbase_ro') THEN
    GRANT SELECT ON sessions, session_lookups, retrieval_log, retrieval_hits,
                    feedback, exposures, memory_prs TO claimbase_ro;
  END IF;
END $$;

-- --- triggers ----------------------------------------------------------------
--
-- An episode that is allowed to produce a claim: a correction, a failure, a
-- decision, a recall that missed, a lookup that had to be repeated. Everything
-- else stays an episode. One row per trigger episode, recording what selected
-- it (`rule`) and what the writer then did with it — which is the whole of
-- "yield per trigger": a rule whose claims are never used is a rule to drop.
--
-- `scored_at` NULL means the writer has not judged it yet. That is a normal
-- resting state, not an error: selection needs no model and runs at ingest;
-- scoring needs one and waits for the GPU.

CREATE TABLE IF NOT EXISTS triggers (
  event_id    uuid PRIMARY KEY REFERENCES events(id) ON DELETE CASCADE,
  session_id  text NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  corpus      text NOT NULL,
  type        text NOT NULL,     -- correction | decision | tool_failure
                                 -- | recall_miss | repeat_lookup
  rule        text NOT NULL,     -- which selector fired
  turn        integer NOT NULL,
  scored_at   timestamptz,
  judge       text,              -- which judge scored it
  relation    text,              -- predicted | novel | contradicting | nothing
  claim_id    uuid REFERENCES claims(id) ON DELETE SET NULL,
  pr_id       uuid REFERENCES memory_prs(id) ON DELETE SET NULL,
  meta        jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS triggers_pending_idx ON triggers (corpus) WHERE scored_at IS NULL;
CREATE INDEX IF NOT EXISTS triggers_session_idx ON triggers (session_id);

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'claimbase_ro') THEN
    GRANT SELECT ON triggers TO claimbase_ro;
  END IF;
END $$;
