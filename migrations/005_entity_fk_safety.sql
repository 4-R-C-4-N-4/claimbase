-- 005 — stop entity churn from reaching claims.
--
-- `TRUNCATE entities CASCADE` truncated `claims`, because TRUNCATE CASCADE follows
-- every foreign key regardless of its ON DELETE action, and claims.subject_id
-- references entities. That destroyed 8,012 extracted claims — three hours of GPU —
-- for what was meant to be a rebuild of a derived lookup table.
--
-- Entities are cheap and rebuilt often; claims are expensive. The dependency now
-- points the safe way: dropping an entity nulls a reference instead of removing the
-- claim that held it.

ALTER TABLE claims DROP CONSTRAINT IF EXISTS claims_subject_id_fkey;
ALTER TABLE claims
  ADD CONSTRAINT claims_subject_id_fkey
  FOREIGN KEY (subject_id) REFERENCES entities(id) ON DELETE SET NULL;
