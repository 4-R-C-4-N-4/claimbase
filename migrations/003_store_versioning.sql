-- 003 — make a scoreboard traceable to the store that produced it.
--
-- Two scoreboards were compared across a re-extraction and read as a regression.
-- They were not comparable: the teacher runs at TEMP=0.2 with no fixed seed, so
-- every extraction writes different claims from the same events (7,525 one run,
-- 8,007 the next). Nothing recorded which run produced which claim, so there was no
-- way to tell a code change from a re-roll of the corpus.
--
-- `extractor_runs` has existed since 001 and was never written to.

ALTER TABLE extractor_runs ADD COLUMN IF NOT EXISTS temperature real;
ALTER TABLE extractor_runs ADD COLUMN IF NOT EXISTS seed bigint;
ALTER TABLE extractor_runs ADD COLUMN IF NOT EXISTS prompt_sha text;
ALTER TABLE extractor_runs ADD COLUMN IF NOT EXISTS n_events integer DEFAULT 0;
ALTER TABLE extractor_runs ADD COLUMN IF NOT EXISTS n_claims integer DEFAULT 0;

ALTER TABLE claims ADD COLUMN IF NOT EXISTS run_id uuid REFERENCES extractor_runs(id);
CREATE INDEX IF NOT EXISTS claims_run_idx ON claims (run_id);

-- A store snapshot: what the graph looked like when a scoreboard was taken. Cheap
-- to compute, and it turns "the numbers moved" into "the numbers moved AND here is
-- what differed underneath".
CREATE OR REPLACE VIEW store_fingerprint AS
SELECT
  corpus,
  count(*) FILTER (WHERE meta ? 'extractor_version')            AS extracted_claims,
  count(*) FILTER (WHERE NOT (meta ? 'extractor_version'))      AS structured_claims,
  count(*) FILTER (WHERE status = 'superseded')                 AS superseded,
  count(DISTINCT run_id)                                        AS extractor_runs,
  md5(string_agg(md5(content), '' ORDER BY id::text))           AS claims_digest
FROM claims GROUP BY corpus;
