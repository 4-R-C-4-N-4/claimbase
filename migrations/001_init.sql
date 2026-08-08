-- 001_init.sql — Phase 0 schema.
--
-- Every column Phase 2 and Phase 3 will need exists here, unpopulated. Adding a
-- bitemporal column to a table with a million derived rows is a migration; adding
-- the logic that fills a column that already exists is a Tuesday. Derived tables
-- can be rebuilt from `events` at any time, so the cost of carrying them early is
-- close to zero.

CREATE EXTENSION IF NOT EXISTS vector;

-- Raw capture. Never updated. Everything downstream is derived from this.
CREATE TABLE events (
  id            uuid PRIMARY KEY,
  corpus        text NOT NULL,
  source        text NOT NULL,            -- adapter name: provenance, not dispatch
  source_ref    text NOT NULL,            -- path@sha | repo#pr | run dir | memory scope
  captured_at   timestamptz,              -- NULL is legal and honest (DESIGN §4.4)
  content       text NOT NULL,
  content_hash  bytea NOT NULL,
  meta          jsonb NOT NULL DEFAULT '{}',
  UNIQUE (corpus, content_hash)           -- dedupe is per-corpus, not global
);
CREATE INDEX events_source_idx ON events (corpus, source);
CREATE INDEX events_captured_idx ON events (captured_at);

CREATE TABLE entities (
  id             uuid PRIMARY KEY,
  corpus         text NOT NULL,
  canonical_name text NOT NULL,
  entity_type    text,
  embedding      vector(768),
  created_at     timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX entities_name_idx ON entities (corpus, canonical_name);

CREATE TABLE entity_aliases (
  entity_id  uuid NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
  alias      text NOT NULL,
  source     text NOT NULL,               -- extracted | user_confirmed | migrated
  PRIMARY KEY (entity_id, alias)
);

CREATE TABLE claims (
  id             uuid PRIMARY KEY,
  corpus         text NOT NULL,
  event_id       uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  span           int4range,
  subject_id     uuid REFERENCES entities(id),
  subject_text   text,                    -- unresolved mention until Phase 1
  predicate      text,
  content        text NOT NULL,
  embedding      vector(768),

  -- bitemporality. valid_to is what makes "superseded and kept" work: a practice
  -- that ended keeps its row and gains an end date, and a practice that resumes is
  -- a NEW row with a later valid_from. The gap between them is the answer to
  -- "when did I stop doing this?", so dormancy needs no status of its own.
  valid_from     timestamptz,
  valid_to       timestamptz,
  asserted_at    timestamptz,

  status         text NOT NULL DEFAULT 'active',
  superseded_by  uuid REFERENCES claims(id),
  confidence     real NOT NULL DEFAULT 0.8,
  claim_kind     text NOT NULL,

  -- Declared by the adapter, enforced by core. `corroborated` records that
  -- something outside the author's own prose backs the claim — a linked commit, a
  -- merged PR — which lifts an agent claim a tier.
  trust          text NOT NULL DEFAULT 'unknown',
  corroborated   boolean NOT NULL DEFAULT false,

  meta           jsonb NOT NULL DEFAULT '{}'
);
CREATE INDEX claims_subject_idx ON claims (corpus, subject_id);
CREATE INDEX claims_active_idx ON claims (corpus, status) WHERE status = 'active';
CREATE INDEX claims_kind_idx ON claims (corpus, claim_kind);
CREATE INDEX claims_valid_idx ON claims (valid_from, valid_to);
CREATE INDEX claims_event_idx ON claims (event_id);

-- Sub-threshold extractions land here, never in claims. Precision over recall:
-- a missed claim costs a retrieval, a hallucinated one poisons the graph.
CREATE TABLE claims_review (
  id           uuid PRIMARY KEY,
  corpus       text NOT NULL,
  event_id     uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  content      text NOT NULL,
  claim_kind   text,
  confidence   real,
  reason       text NOT NULL,             -- below_threshold | trust_capped | parse_failed
  meta         jsonb NOT NULL DEFAULT '{}'
);

CREATE TABLE edges (
  corpus    text NOT NULL,
  src_id    uuid NOT NULL,
  dst_id    uuid NOT NULL,
  rel       text NOT NULL,                -- free text; canonicalised by schema emergence
  weight    real NOT NULL DEFAULT 1.0,
  meta      jsonb NOT NULL DEFAULT '{}',
  PRIMARY KEY (corpus, src_id, dst_id, rel)
);
CREATE INDEX edges_dst_idx ON edges (corpus, dst_id);

CREATE TABLE conflicts (
  id          uuid PRIMARY KEY,
  corpus      text NOT NULL,
  claim_a     uuid NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
  claim_b     uuid REFERENCES claims(id) ON DELETE CASCADE,  -- NULL for schema tensions
  detected_at timestamptz NOT NULL DEFAULT now(),
  kind        text NOT NULL,              -- contradiction | ambiguous_order
                                          -- | scope_unclear | schema_tension | stale_suspect
  resolution  text,
  resolved_at timestamptz
);
CREATE INDEX conflicts_open_idx ON conflicts (corpus) WHERE resolution IS NULL;

CREATE TABLE schema_types (
  id          uuid PRIMARY KEY,
  corpus      text NOT NULL,
  kind        text NOT NULL,              -- entity_type | predicate | claim_tag | field_spec
  name        text NOT NULL,
  source      text NOT NULL,              -- user_declared | emergent | migrated
  status      text NOT NULL,              -- proposed | approved | merged | rejected | superseded
  uses        integer NOT NULL DEFAULT 0, -- frequency is accumulated review (DESIGN §7)
  spec        jsonb,
  merged_into uuid REFERENCES schema_types(id),
  examples    jsonb NOT NULL DEFAULT '[]'
);
CREATE UNIQUE INDEX schema_types_name_idx ON schema_types (corpus, kind, name);

-- Which extractor produced what, so a model upgrade can reprocess selectively
-- instead of rebuilding everything.
CREATE TABLE extractor_runs (
  id          uuid PRIMARY KEY,
  corpus      text NOT NULL,
  version     text NOT NULL,
  model       text NOT NULL,
  started_at  timestamptz NOT NULL DEFAULT now(),
  finished_at timestamptz,
  meta        jsonb NOT NULL DEFAULT '{}'
);
