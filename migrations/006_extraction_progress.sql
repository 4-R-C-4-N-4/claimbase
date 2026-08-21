-- Events the extractor has READ, independent of whether any claim survived.
--
-- Without this, "processed, nothing extracted" is indistinguishable from "never
-- read": the pending check looked for surviving claims, so an event that
-- legitimately yields no claims was re-extracted on every run (and its
-- below-threshold rows re-inserted into claims_review). This is guru's
-- tagging_progress lesson (guru docs/ingest/10-tag-concepts.md): progress and
-- output are different facts and must be recorded separately.
--
-- Keyed per extractor version so a version bump re-reads everything — that is
-- the deliberate full-reprocess path, not an accident.
--
-- The other half of the guru lesson also applies: a row here is written only
-- when the response parsed to a well-formed array. An unparseable response or a
-- transport error leaves no row, so the event is retried next run rather than
-- silently recorded as "read, empty".

CREATE TABLE extraction_progress (
  event_id   uuid NOT NULL REFERENCES events(id) ON DELETE CASCADE,
  version    text NOT NULL,
  run_id     uuid,
  n_claims   int NOT NULL DEFAULT 0,
  at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (event_id, version)
);

-- Backfill: every event that already carries claims from a version was read by
-- it. The historical empty-yield tail has no claims and stays unmarked — it is
-- re-read exactly once more, then recorded.
INSERT INTO extraction_progress (event_id, version, n_claims)
SELECT event_id, meta->>'extractor_version', count(*)
FROM claims
WHERE meta->>'extractor_version' IS NOT NULL
GROUP BY 1, 2
ON CONFLICT DO NOTHING;
