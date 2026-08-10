-- 002 — make re-import survive supersession.
--
-- `superseded_by` was a plain FK, so deleting a claim that had superseded others
-- raised a foreign-key violation. `import` deletes and reinserts an event's claims,
-- which meant the whole pipeline stopped being re-runnable the moment supersession
-- had been applied — contradicting the design's premise that derived tables can be
-- rebuilt from `events` at any time.
--
-- ON DELETE SET NULL keeps the referencing claim rather than cascading the delete
-- into it. A cascade would be much worse: removing one claim would silently remove
-- everything it had ever superseded.

ALTER TABLE claims DROP CONSTRAINT IF EXISTS claims_superseded_by_fkey;
ALTER TABLE claims
  ADD CONSTRAINT claims_superseded_by_fkey
  FOREIGN KEY (superseded_by) REFERENCES claims(id) ON DELETE SET NULL;
