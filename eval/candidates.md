# Stale-answer question candidates

Auto-harvested review queue (`eval/harvest.py`). **Not a gold set.** Each item needs a
human to accept, cut, or rewrite into a question with a gold answer. Target ≥12 accepted
(PLAN §1).

Corpus: 788 records, 1,895,982 chars, 3,752 distinct symbols.

## S1 — rename / replace — 1 found, 1 shown

### What is `src/middleware.ts` called / how is it referred to now?

- **evidence:** `src/middleware.ts` → `src/proxy.ts` — “Root cause: a leftover Clerk-quickstart ./middleware.ts at repo root coexisted with the intended src/middleware.ts pass-through. The root fi”
- **current:** `guru-web:0f850d3c` (ticket, 2026-06-03) — Remove leftover root ./middleware.ts that shadows src/proxy.ts and gates /blog behind Cler
- **stale:** `guru:docs/concept-hierarchy/guru-web-alignment.md` (doc, 2026-05-27) — docs/concept-hierarchy/guru-web-alignment.md
- **stale:** `guru-web:docs/admin-ui/BRD-admin-ui.md` (doc, 2026-05-01) — docs/admin-ui/BRD-admin-ui.md
- **stale:** `guru-web:docs/concept-hierarchy/IMPL-concept-hierarchy.md` (doc, 2026-05-27) — docs/concept-hierarchy/IMPL-concept-hierarchy.md
- **stale:** `guru-web:docs/guru-web-build-plan.md` (doc, 2026-04-16) — docs/guru-web-build-plan.md
- **stale:** …and 2 more

## S2 — doc lineage — 2 found, 2 shown

### [guru] What is the current design for 'docs'?

- **evidence:** v2 → v3
- **current:** `guru:docs/v3.md` (doc, 2026-04-25) — docs/v3.md
- **stale:** `guru:docs/v2.md` (doc, 2026-04-17) — docs/v2.md

### [rellm] What is the current design for 'docs/homology'?

- **evidence:** findings → proposal
- **current:** `rellm:docs/homology/proposal.md` (doc, 2026-08-07) — docs/homology/proposal.md
- **stale:** `rellm:docs/homology/findings.md` (doc, 2026-08-05) — docs/homology/findings.md

## S3 — metric drift — 28 found, 15 shown

*13 lower-scoring candidates not shown.*

### What is model `base`'s recall (human-graded) on the tagging bench?

- **evidence:** **0.118** (gauge-human, May 25) → **0.118** (gauge-v3, May 26) → **0.550** (qwen3-4b, May 27) → **0.531** (qwen3-4b-v1-v2, Jun 10) → **0.560** (qwen3-4b-v3, Aug 07)
- **current:** `rellm:qwen3-4b-v3-2026-08-07T13-26-57Z#human` (run, 2026-08-07) — qwen3-4b-v3-2026-08-07T13-26-57Z (human-graded)
- **stale:** `rellm:gauge-human-2026-05-25T13-00-46Z#human` (run, 2026-05-25) — gauge-human-2026-05-25T13-00-46Z (human-graded)
- **stale:** `rellm:gauge-v3-2026-05-26T05-02-37Z#human` (run, 2026-05-26) — gauge-v3-2026-05-26T05-02-37Z (human-graded)
- **stale:** `rellm:qwen3-4b-2026-05-27T07-15-59Z#human` (run, 2026-05-27) — qwen3-4b-2026-05-27T07-15-59Z (human-graded)
- **stale:** `rellm:qwen3-4b-v1-v2-2026-06-10T00-49-04Z#human` (run, 2026-06-10) — qwen3-4b-v1-v2-2026-06-10T00-49-04Z (human-graded)

### What is model `base`'s recall (teacher-graded) on the tagging bench?

- **evidence:** **0.162** (v2-vs-v1-vs-base-serial, May 22) → **0.137** (v2-human, May 22) → **0.152** (gauge-human, May 25) → **0.152** (gauge-v3, May 26) → **0.561** (qwen3-4b, May 27) → **0.536** (qwen3-4b-v1-v2, Jun 10) → **0.515** (qwen3-4b-v3, Aug 07)
- **current:** `rellm:qwen3-4b-v3-2026-08-07T13-26-57Z#teacher` (run, 2026-08-07) — qwen3-4b-v3-2026-08-07T13-26-57Z (teacher-graded)
- **stale:** `rellm:v2-vs-v1-vs-base-serial-2026-05-22T15-31-12Z#teacher` (run, 2026-05-22) — v2-vs-v1-vs-base-serial-2026-05-22T15-31-12Z (teacher-graded)
- **stale:** `rellm:v2-human-2026-05-22T16-13-20Z#teacher` (run, 2026-05-22) — v2-human-2026-05-22T16-13-20Z (teacher-graded)
- **stale:** `rellm:gauge-human-2026-05-25T13-00-46Z#teacher` (run, 2026-05-25) — gauge-human-2026-05-25T13-00-46Z (teacher-graded)
- **stale:** `rellm:gauge-v3-2026-05-26T05-02-37Z#teacher` (run, 2026-05-26) — gauge-v3-2026-05-26T05-02-37Z (teacher-graded)
- **stale:** …and 2 more

### What is model `base`'s F1 (human-graded) on the tagging bench?

- **evidence:** **0.207** (gauge-human, May 25) → **0.207** (gauge-v3, May 26) → **0.609** (qwen3-4b, May 27) → **0.608** (qwen3-4b-v1-v2, Jun 10) → **0.594** (qwen3-4b-v3, Aug 07)
- **current:** `rellm:qwen3-4b-v3-2026-08-07T13-26-57Z#human` (run, 2026-08-07) — qwen3-4b-v3-2026-08-07T13-26-57Z (human-graded)
- **stale:** `rellm:gauge-human-2026-05-25T13-00-46Z#human` (run, 2026-05-25) — gauge-human-2026-05-25T13-00-46Z (human-graded)
- **stale:** `rellm:gauge-v3-2026-05-26T05-02-37Z#human` (run, 2026-05-26) — gauge-v3-2026-05-26T05-02-37Z (human-graded)
- **stale:** `rellm:qwen3-4b-2026-05-27T07-15-59Z#human` (run, 2026-05-27) — qwen3-4b-2026-05-27T07-15-59Z (human-graded)
- **stale:** `rellm:qwen3-4b-v1-v2-2026-06-10T00-49-04Z#human` (run, 2026-06-10) — qwen3-4b-v1-v2-2026-06-10T00-49-04Z (human-graded)

### What is model `v2`'s precision (teacher-graded) on the tagging bench?

- **evidence:** **0.597** (v2-vs-v1-vs-base-serial, May 22) → **0.692** (v2-human, May 22) → **0.669** (gauge-human, May 25) → **0.669** (gauge-v3, May 26) → **0.408** (qwen3-4b-v1-v2, Jun 10) → **0.390** (qwen3-4b-v3, Aug 07)
- **current:** `rellm:qwen3-4b-v3-2026-08-07T13-26-57Z#teacher` (run, 2026-08-07) — qwen3-4b-v3-2026-08-07T13-26-57Z (teacher-graded)
- **stale:** `rellm:v2-vs-v1-vs-base-serial-2026-05-22T15-31-12Z#teacher` (run, 2026-05-22) — v2-vs-v1-vs-base-serial-2026-05-22T15-31-12Z (teacher-graded)
- **stale:** `rellm:v2-human-2026-05-22T16-13-20Z#teacher` (run, 2026-05-22) — v2-human-2026-05-22T16-13-20Z (teacher-graded)
- **stale:** `rellm:gauge-human-2026-05-25T13-00-46Z#teacher` (run, 2026-05-25) — gauge-human-2026-05-25T13-00-46Z (teacher-graded)
- **stale:** `rellm:gauge-v3-2026-05-26T05-02-37Z#teacher` (run, 2026-05-26) — gauge-v3-2026-05-26T05-02-37Z (teacher-graded)
- **stale:** …and 1 more

### What is model `v1`'s precision (teacher-graded) on the tagging bench?

- **evidence:** **0.558** (v2-vs-v1-vs-base-serial, May 22) → **0.563** (v1-sanity, May 22) → **0.692** (v2-human, May 22) → **0.621** (gauge-human, May 25) → **0.621** (gauge-v3, May 26) → **0.444** (qwen3-4b-v1-v2, Jun 10) → **0.407** (qwen3-4b-v3, Aug 07)
- **current:** `rellm:qwen3-4b-v3-2026-08-07T13-26-57Z#teacher` (run, 2026-08-07) — qwen3-4b-v3-2026-08-07T13-26-57Z (teacher-graded)
- **stale:** `rellm:v2-vs-v1-vs-base-serial-2026-05-22T15-31-12Z#teacher` (run, 2026-05-22) — v2-vs-v1-vs-base-serial-2026-05-22T15-31-12Z (teacher-graded)
- **stale:** `rellm:v1-sanity-2026-05-22T16-02-51Z#teacher` (run, 2026-05-22) — v1-sanity-2026-05-22T16-02-51Z (teacher-graded)
- **stale:** `rellm:v2-human-2026-05-22T16-13-20Z#teacher` (run, 2026-05-22) — v2-human-2026-05-22T16-13-20Z (teacher-graded)
- **stale:** `rellm:gauge-human-2026-05-25T13-00-46Z#teacher` (run, 2026-05-25) — gauge-human-2026-05-25T13-00-46Z (teacher-graded)
- **stale:** …and 2 more

### What is model `base`'s F1 (teacher-graded) on the tagging bench?

- **evidence:** **0.217** (v2-vs-v1-vs-base-serial, May 22) → **0.201** (v2-human, May 22) → **0.220** (gauge-human, May 25) → **0.220** (gauge-v3, May 26) → **0.427** (qwen3-4b, May 27) → **0.389** (qwen3-4b-v1-v2, Jun 10) → **0.372** (qwen3-4b-v3, Aug 07)
- **current:** `rellm:qwen3-4b-v3-2026-08-07T13-26-57Z#teacher` (run, 2026-08-07) — qwen3-4b-v3-2026-08-07T13-26-57Z (teacher-graded)
- **stale:** `rellm:v2-vs-v1-vs-base-serial-2026-05-22T15-31-12Z#teacher` (run, 2026-05-22) — v2-vs-v1-vs-base-serial-2026-05-22T15-31-12Z (teacher-graded)
- **stale:** `rellm:v2-human-2026-05-22T16-13-20Z#teacher` (run, 2026-05-22) — v2-human-2026-05-22T16-13-20Z (teacher-graded)
- **stale:** `rellm:gauge-human-2026-05-25T13-00-46Z#teacher` (run, 2026-05-25) — gauge-human-2026-05-25T13-00-46Z (teacher-graded)
- **stale:** `rellm:gauge-v3-2026-05-26T05-02-37Z#teacher` (run, 2026-05-26) — gauge-v3-2026-05-26T05-02-37Z (teacher-graded)
- **stale:** …and 2 more

### What is model `base`'s macro-F1 (teacher-graded) on the tagging bench?

- **evidence:** **0.182** (v2-vs-v1-vs-base-serial, May 22) → **0.083** (v2-human, May 22) → **0.176** (gauge-human, May 25) → **0.176** (gauge-v3, May 26) → **0.293** (qwen3-4b, May 27) → **0.250** (qwen3-4b-v1-v2, Jun 10) → **0.264** (qwen3-4b-v3, Aug 07)
- **current:** `rellm:qwen3-4b-v3-2026-08-07T13-26-57Z#teacher` (run, 2026-08-07) — qwen3-4b-v3-2026-08-07T13-26-57Z (teacher-graded)
- **stale:** `rellm:v2-vs-v1-vs-base-serial-2026-05-22T15-31-12Z#teacher` (run, 2026-05-22) — v2-vs-v1-vs-base-serial-2026-05-22T15-31-12Z (teacher-graded)
- **stale:** `rellm:v2-human-2026-05-22T16-13-20Z#teacher` (run, 2026-05-22) — v2-human-2026-05-22T16-13-20Z (teacher-graded)
- **stale:** `rellm:gauge-human-2026-05-25T13-00-46Z#teacher` (run, 2026-05-25) — gauge-human-2026-05-25T13-00-46Z (teacher-graded)
- **stale:** `rellm:gauge-v3-2026-05-26T05-02-37Z#teacher` (run, 2026-05-26) — gauge-v3-2026-05-26T05-02-37Z (teacher-graded)
- **stale:** …and 2 more

### What is model `v2`'s macro-F1 (teacher-graded) on the tagging bench?

- **evidence:** **0.525** (v2-vs-v1-vs-base-serial, May 22) → **0.319** (v2-human, May 22) → **0.502** (gauge-human, May 25) → **0.502** (gauge-v3, May 26) → **0.318** (qwen3-4b-v1-v2, Jun 10) → **0.315** (qwen3-4b-v3, Aug 07)
- **current:** `rellm:qwen3-4b-v3-2026-08-07T13-26-57Z#teacher` (run, 2026-08-07) — qwen3-4b-v3-2026-08-07T13-26-57Z (teacher-graded)
- **stale:** `rellm:v2-vs-v1-vs-base-serial-2026-05-22T15-31-12Z#teacher` (run, 2026-05-22) — v2-vs-v1-vs-base-serial-2026-05-22T15-31-12Z (teacher-graded)
- **stale:** `rellm:v2-human-2026-05-22T16-13-20Z#teacher` (run, 2026-05-22) — v2-human-2026-05-22T16-13-20Z (teacher-graded)
- **stale:** `rellm:gauge-human-2026-05-25T13-00-46Z#teacher` (run, 2026-05-25) — gauge-human-2026-05-25T13-00-46Z (teacher-graded)
- **stale:** `rellm:gauge-v3-2026-05-26T05-02-37Z#teacher` (run, 2026-05-26) — gauge-v3-2026-05-26T05-02-37Z (teacher-graded)
- **stale:** …and 1 more

### What is model `base`'s precision (human-graded) on the tagging bench?

- **evidence:** **0.833** (gauge-human, May 25) → **0.833** (gauge-v3, May 26) → **0.682** (qwen3-4b, May 27) → **0.711** (qwen3-4b-v1-v2, Jun 10) → **0.633** (qwen3-4b-v3, Aug 07)
- **current:** `rellm:qwen3-4b-v3-2026-08-07T13-26-57Z#human` (run, 2026-08-07) — qwen3-4b-v3-2026-08-07T13-26-57Z (human-graded)
- **stale:** `rellm:gauge-human-2026-05-25T13-00-46Z#human` (run, 2026-05-25) — gauge-human-2026-05-25T13-00-46Z (human-graded)
- **stale:** `rellm:gauge-v3-2026-05-26T05-02-37Z#human` (run, 2026-05-26) — gauge-v3-2026-05-26T05-02-37Z (human-graded)
- **stale:** `rellm:qwen3-4b-2026-05-27T07-15-59Z#human` (run, 2026-05-27) — qwen3-4b-2026-05-27T07-15-59Z (human-graded)
- **stale:** `rellm:qwen3-4b-v1-v2-2026-06-10T00-49-04Z#human` (run, 2026-06-10) — qwen3-4b-v1-v2-2026-06-10T00-49-04Z (human-graded)

### What is model `v3`'s precision (teacher-graded) on the tagging bench?

- **evidence:** **0.636** (gauge-v3, May 26) → **0.439** (qwen3-4b-v3, Aug 07)
- **current:** `rellm:qwen3-4b-v3-2026-08-07T13-26-57Z#teacher` (run, 2026-08-07) — qwen3-4b-v3-2026-08-07T13-26-57Z (teacher-graded)
- **stale:** `rellm:gauge-v3-2026-05-26T05-02-37Z#teacher` (run, 2026-05-26) — gauge-v3-2026-05-26T05-02-37Z (teacher-graded)

### What is model `v3`'s macro-F1 (teacher-graded) on the tagging bench?

- **evidence:** **0.522** (gauge-v3, May 26) → **0.331** (qwen3-4b-v3, Aug 07)
- **current:** `rellm:qwen3-4b-v3-2026-08-07T13-26-57Z#teacher` (run, 2026-08-07) — qwen3-4b-v3-2026-08-07T13-26-57Z (teacher-graded)
- **stale:** `rellm:gauge-v3-2026-05-26T05-02-37Z#teacher` (run, 2026-05-26) — gauge-v3-2026-05-26T05-02-37Z (teacher-graded)

### What is model `v1`'s F1 (teacher-graded) on the tagging bench?

- **evidence:** **0.577** (v2-vs-v1-vs-base-serial, May 22) → **0.615** (v1-sanity, May 22) → **0.638** (v2-human, May 22) → **0.560** (gauge-human, May 25) → **0.560** (gauge-v3, May 26) → **0.488** (qwen3-4b-v1-v2, Jun 10) → **0.462** (qwen3-4b-v3, Aug 07)
- **current:** `rellm:qwen3-4b-v3-2026-08-07T13-26-57Z#teacher` (run, 2026-08-07) — qwen3-4b-v3-2026-08-07T13-26-57Z (teacher-graded)
- **stale:** `rellm:v2-vs-v1-vs-base-serial-2026-05-22T15-31-12Z#teacher` (run, 2026-05-22) — v2-vs-v1-vs-base-serial-2026-05-22T15-31-12Z (teacher-graded)
- **stale:** `rellm:v1-sanity-2026-05-22T16-02-51Z#teacher` (run, 2026-05-22) — v1-sanity-2026-05-22T16-02-51Z (teacher-graded)
- **stale:** `rellm:v2-human-2026-05-22T16-13-20Z#teacher` (run, 2026-05-22) — v2-human-2026-05-22T16-13-20Z (teacher-graded)
- **stale:** `rellm:gauge-human-2026-05-25T13-00-46Z#teacher` (run, 2026-05-25) — gauge-human-2026-05-25T13-00-46Z (teacher-graded)
- **stale:** …and 2 more

### What is model `v1`'s recall (teacher-graded) on the tagging bench?

- **evidence:** **0.596** (v2-vs-v1-vs-base-serial, May 22) → **0.676** (v1-sanity, May 22) → **0.591** (v2-human, May 22) → **0.509** (gauge-human, May 25) → **0.509** (gauge-v3, May 26) → **0.542** (qwen3-4b-v1-v2, Jun 10) → **0.534** (qwen3-4b-v3, Aug 07)
- **current:** `rellm:qwen3-4b-v3-2026-08-07T13-26-57Z#teacher` (run, 2026-08-07) — qwen3-4b-v3-2026-08-07T13-26-57Z (teacher-graded)
- **stale:** `rellm:v2-vs-v1-vs-base-serial-2026-05-22T15-31-12Z#teacher` (run, 2026-05-22) — v2-vs-v1-vs-base-serial-2026-05-22T15-31-12Z (teacher-graded)
- **stale:** `rellm:v1-sanity-2026-05-22T16-02-51Z#teacher` (run, 2026-05-22) — v1-sanity-2026-05-22T16-02-51Z (teacher-graded)
- **stale:** `rellm:v2-human-2026-05-22T16-13-20Z#teacher` (run, 2026-05-22) — v2-human-2026-05-22T16-13-20Z (teacher-graded)
- **stale:** `rellm:gauge-human-2026-05-25T13-00-46Z#teacher` (run, 2026-05-25) — gauge-human-2026-05-25T13-00-46Z (teacher-graded)
- **stale:** …and 2 more

### What is model `v2`'s F1 (teacher-graded) on the tagging bench?

- **evidence:** **0.599** (v2-vs-v1-vs-base-serial, May 22) → **0.601** (v2-human, May 22) → **0.584** (gauge-human, May 25) → **0.584** (gauge-v3, May 26) → **0.458** (qwen3-4b-v1-v2, Jun 10) → **0.443** (qwen3-4b-v3, Aug 07)
- **current:** `rellm:qwen3-4b-v3-2026-08-07T13-26-57Z#teacher` (run, 2026-08-07) — qwen3-4b-v3-2026-08-07T13-26-57Z (teacher-graded)
- **stale:** `rellm:v2-vs-v1-vs-base-serial-2026-05-22T15-31-12Z#teacher` (run, 2026-05-22) — v2-vs-v1-vs-base-serial-2026-05-22T15-31-12Z (teacher-graded)
- **stale:** `rellm:v2-human-2026-05-22T16-13-20Z#teacher` (run, 2026-05-22) — v2-human-2026-05-22T16-13-20Z (teacher-graded)
- **stale:** `rellm:gauge-human-2026-05-25T13-00-46Z#teacher` (run, 2026-05-25) — gauge-human-2026-05-25T13-00-46Z (teacher-graded)
- **stale:** `rellm:gauge-v3-2026-05-26T05-02-37Z#teacher` (run, 2026-05-26) — gauge-v3-2026-05-26T05-02-37Z (teacher-graded)
- **stale:** …and 1 more

### What is model `v1`'s recall (human-graded) on the tagging bench?

- **evidence:** **0.356** (gauge-human, May 25) → **0.356** (gauge-v3, May 26) → **0.514** (qwen3-4b-v1-v2, Jun 10) → **0.499** (qwen3-4b-v3, Aug 07)
- **current:** `rellm:qwen3-4b-v3-2026-08-07T13-26-57Z#human` (run, 2026-08-07) — qwen3-4b-v3-2026-08-07T13-26-57Z (human-graded)
- **stale:** `rellm:gauge-human-2026-05-25T13-00-46Z#human` (run, 2026-05-25) — gauge-human-2026-05-25T13-00-46Z (human-graded)
- **stale:** `rellm:gauge-v3-2026-05-26T05-02-37Z#human` (run, 2026-05-26) — gauge-v3-2026-05-26T05-02-37Z (human-graded)
- **stale:** `rellm:qwen3-4b-v1-v2-2026-06-10T00-49-04Z#human` (run, 2026-06-10) — qwen3-4b-v1-v2-2026-06-10T00-49-04Z (human-graded)

## S4 — explicit retraction — 8 found, 8 shown

### [rellm] 80-concept-teacher-run-retro: what did this revise?

- **evidence:** - 3089 chunks tagged, **0 errors**, 31 batches of 100 with steady ~4.5h/batch cadence. - ~161s/chunk on average — no degradation across the 138-hour run. - 11,473 tags proposed by the model. - DB outcome: 6665 inserted + 3806 superseded + 1002 skipped_reviewed = 11473 (matches log proposals exactly;
- **current:** `rellm:docs/80-concept-teacher-run-retro.md` (doc, 2026-05-15) — docs/80-concept-teacher-run-retro.md
- **also:** 11,473 proposed = 6665 inserted + 3806 superseded + 1002 skipped_reviewed. The supersede-pending policy did exactly what it should: 3806 prior pending tags were replaced, 1002 already-reviewed chunks 
- **also:** - The 27B teacher held a stable inference rate for nearly six days straight on local hardware. That's the real headline. - The `supersede_pending` semantics worked correctly under a real workload — 38

### [guru-web] CORE_RULES-draft: what did this revise?

- **evidence:** > Note: the tradition list at the top was moved into CORE_RULES from > the voice overlays during ticket 3 (see > [VOICE-woowoo-draft.md](./VOICE-woowoo-draft.md) → "Tradition list > moved to CORE_RULES"). It's the retrieval catalog, invariant > across voices, so duplicating it per overlay was wrong.
- **current:** `guru-web:docs/chat-voice/CORE_RULES-draft.md` (doc, 2026-05-14) — docs/chat-voice/CORE_RULES-draft.md

### [guru-web] retriever-hitlist: what did this revise?

- **evidence:** The original ordering put Bug 1 first as "a one-line SELECT fix." That was wrong — see the Bug 1 verification: `chunks` has no `tier` column, so Bug 1 is a scoring redesign, not a one-liner, and it cannot be done in isolation from Bug 2. Revised order:
- **current:** `guru-web:docs/retriever-hitlist.md` (doc, 2026-05-25) — docs/retriever-hitlist.md

### [rellm] edge-review-pass: what did this revise?

- **evidence:** Headline accept rate: ~96.5% — Mistral's 0.85 tier was strongly over-flagged at first glance, but turned out to be well-calibrated for the bulk of tradition pairs. The surface_only flips concentrated in a handful of pathological clusters rather than being evenly noisy.
- **current:** `rellm:docs/edges/edge-review-pass.md` (doc, 2026-08-07) — docs/edges/edge-review-pass.md

### [rellm] findings: what did this revise?

- **evidence:** Status: **method gate not passed** — the geometry does not beat the cheap baseline out of sample. Per the proposal's own decision point, the homology scoring layer should not be wired into guru on current evidence. The gold set, the extraction infrastructure, and the secondary uses all survive.
- **current:** `rellm:docs/homology/findings.md` (doc, 2026-08-05) — docs/homology/findings.md

### [rellm] proposal: what did this revise?

- **evidence:** Resolution: the gold verdict is an ordinal 0–4 depth-of-correspondence rating (anchors in `data/homology/gold/README.md`), plus "rejected" for unusable test cases. Consequences for the eval design (supersedes the binary-separation framing in the Evaluation section above):
- **current:** `rellm:docs/homology/proposal.md` (doc, 2026-08-07) — docs/homology/proposal.md

### [rellm] qwen-3-4b-guru-card: what did this revise?

- **evidence:** **vs human-graded labels:** base 0.594 F1 (inflated — a "shotgun" over-emission artifact, base emits 36.3 tags/chunk vs v3's 14.2, landing extra hits on ungraded cells for free), v1 0.537, v2 0.577, **v3 0.589** — v3 wins among the models with comparable emission counts. v1's worst blind spot, `anim
- **current:** `rellm:docs/qwen-3-4b-guru-card.md` (doc, 2026-05-27) — docs/qwen-3-4b-guru-card.md

### [rellm] qwen-3-4b-v2-regression-autopsy: what did this revise?

- **evidence:** ## 1. The bench blind spot (base does NOT beat the fine-tunes)
- **current:** `rellm:docs/qwen-3-4b-v2-regression-autopsy.md` (doc, 2026-08-05) — docs/qwen-3-4b-v2-regression-autopsy.md

## S5 — contested symbol — 95 found, 15 shown

*80 lower-scoring candidates not shown.*

### What is the current state of `staged_tags`?

- **evidence:** 59 records over 114d across doc+ticket; 37 state change or retraction
- **current:** `guru:56d6d337` (ticket, 2026-08-07) — Duplicate pending tags on chunks reviewed by two different model batches
- **stale:** `guru:README.md` (doc, 2026-04-15) — README.md
- **stale:** `guru:docs/guru-implementation.md` (doc, 2026-04-15) — docs/guru-implementation.md
- **stale:** `guru:4b5863bc` (ticket, 2026-04-15) — Write guru.db schema (nodes, edges, staged_tags, staged_edges, staged_concepts)
- **stale:** `guru:ebba37dd` (ticket, 2026-04-15) — Build tag_concepts.py (LLM-assisted tagging with structured scoring prompt)
- **stale:** …and 54 more

### What is the current state of `chunk_id`?

- **evidence:** 37 records over 98d across doc+ticket; 29 state change or retraction
- **current:** `guru-web:7b60b6fb` (ticket, 2026-07-23) — Ask-about-this-passage: chunk page button that opens chat pre-scoped to the text/passage
- **stale:** `guru:docs/guru-architecture.md` (doc, 2026-04-15) — docs/guru-architecture.md
- **stale:** `guru:docs/guru-implementation.md` (doc, 2026-04-15) — docs/guru-implementation.md
- **stale:** `guru:4b5863bc` (ticket, 2026-04-15) — Write guru.db schema (nodes, edges, staged_tags, staged_edges, staged_concepts)
- **stale:** `guru:0d2b85a6` (ticket, 2026-04-15) — Build backfill_concepts.py (sync concept tags from guru.db to vector metadata)
- **stale:** …and 32 more

### What is the current state of `embed_corpus`?

- **evidence:** 50 records over 108d across doc+ticket; 25 state change or retraction
- **current:** `guru:eaa8f17c` (ticket, 2026-08-02) — embed_corpus for both texts (ollama nomic-embed-text)
- **stale:** `guru:README.md` (doc, 2026-04-15) — README.md
- **stale:** `guru:docs/guru-implementation.md` (doc, 2026-04-15) — docs/guru-implementation.md
- **stale:** `guru:0be14787` (ticket, 2026-04-15) — Guru: RAG-powered comparative esoteric text agent
- **stale:** `guru:34eb456c` (ticket, 2026-04-15) — Build propose_edges.py (cross-tradition pair classification)
- **stale:** …and 45 more

### What is the current state of `tag_concepts`?

- **evidence:** 43 records over 108d across doc+ticket; 22 state change or retraction
- **current:** `guru:630d252c` (ticket, 2026-08-01) — tag_concepts.py 27B no-think — stage Julian tags; queue-only via /guru-review-tags
- **stale:** `guru:README.md` (doc, 2026-04-15) — README.md
- **stale:** `guru:docs/guru-implementation.md` (doc, 2026-04-15) — docs/guru-implementation.md
- **stale:** `guru:0be14787` (ticket, 2026-04-15) — Guru: RAG-powered comparative esoteric text agent
- **stale:** `guru:4b5863bc` (ticket, 2026-04-15) — Write guru.db schema (nodes, edges, staged_tags, staged_edges, staged_concepts)
- **stale:** …and 38 more

### What is the current state of `chunk_embeddings`?

- **evidence:** 34 records over 114d across doc+ticket; 21 state change or retraction
- **current:** `rellm:docs/homology/proposal.md` (doc, 2026-08-07) — docs/homology/proposal.md
- **stale:** `guru:README.md` (doc, 2026-04-15) — README.md
- **stale:** `guru:1237b4fe` (ticket, 2026-04-17) — Phase 1: Add chunk_embeddings table and backfill from ChromaDB
- **stale:** `guru:602f39de` (ticket, 2026-04-17) — Write scripts/migrate_to_sqlite_embeddings.py: creates chunk_embeddings, iterate
- **stale:** `guru:3940b852` (ticket, 2026-04-17) — Run migrate_to_sqlite_embeddings.py locally once; confirm reconciliation counts 
- **stale:** …and 29 more

### What is the current state of `staged_edges`?

- **evidence:** 35 records over 107d across doc+ticket; 20 state change or retraction
- **current:** `guru:a2d04102` (ticket, 2026-08-01) — propose_edges.py targeted at Gita — stage cross-tradition edges; queue-only, review via /g
- **stale:** `guru:README.md` (doc, 2026-04-15) — README.md
- **stale:** `guru:docs/guru-implementation.md` (doc, 2026-04-15) — docs/guru-implementation.md
- **stale:** `guru:4b5863bc` (ticket, 2026-04-15) — Write guru.db schema (nodes, edges, staged_tags, staged_edges, staged_concepts)
- **stale:** `guru:34eb456c` (ticket, 2026-04-15) — Build propose_edges.py (cross-tradition pair classification)
- **stale:** …and 30 more

### What is the current state of `created_at`?

- **evidence:** 26 records over 87d across doc+ticket; 20 state change or retraction
- **current:** `guru-web:e13dd999` (ticket, 2026-07-12) — Fork endpoint: POST /api/shares/[slug]/fork copies snapshot into new session, zeroed accou
- **stale:** `guru:4b5863bc` (ticket, 2026-04-15) — Write guru.db schema (nodes, edges, staged_tags, staged_edges, staged_concepts)
- **stale:** `guru-web:docs/guru-web-build-plan.md` (doc, 2026-04-16) — docs/guru-web-build-plan.md
- **stale:** `guru:docs/v3.md` (doc, 2026-04-25) — docs/v3.md
- **stale:** `guru:docs/web-review/design.md` (doc, 2026-04-25) — docs/web-review/design.md
- **stale:** …and 21 more

### What is the current state of `review_tags`?

- **evidence:** 30 records over 80d across doc+ticket; 18 state change or retraction
- **current:** `guru:docs/summary/implementation-guru.md` (doc, 2026-07-04) — docs/summary/implementation-guru.md
- **stale:** `guru:README.md` (doc, 2026-04-15) — README.md
- **stale:** `guru:docs/guru-implementation.md` (doc, 2026-04-15) — docs/guru-implementation.md
- **stale:** `guru:0be14787` (ticket, 2026-04-15) — Guru: RAG-powered comparative esoteric text agent
- **stale:** `guru:083a1785` (ticket, 2026-04-15) — Build review_tags.py (CLI review tool for staged tags)
- **stale:** …and 25 more

### What is the current state of `text_id`?

- **evidence:** 38 records over 99d across doc+ticket; 18 state change or retraction
- **current:** `guru-web:83607715` (ticket, 2026-07-24) — Snapshot: attach deduped work-dossier capsules (label, summary, context, resolved themes) 
- **stale:** `guru:docs/guru-architecture.md` (doc, 2026-04-15) — docs/guru-architecture.md
- **stale:** `guru:docs/guru-implementation.md` (doc, 2026-04-15) — docs/guru-implementation.md
- **stale:** `guru:0be14787` (ticket, 2026-04-15) — Guru: RAG-powered comparative esoteric text agent
- **stale:** `guru:2effac9d` (ticket, 2026-04-15) — Build generic_html.py downloader (BeautifulSoup extraction)
- **stale:** …and 33 more

### What is the current state of `text_name`?

- **evidence:** 25 records over 87d across doc+ticket; 15 state change or retraction
- **current:** `guru-web:5f35c4a7` (ticket, 2026-07-12) — Migration 015: session_shares table + sessions.scope_override + sessions.forked_from_share
- **stale:** `guru:docs/guru-architecture.md` (doc, 2026-04-15) — docs/guru-architecture.md
- **stale:** `guru:docs/guru-implementation.md` (doc, 2026-04-15) — docs/guru-implementation.md
- **stale:** `guru:ca06050b` (ticket, 2026-04-15) — Define chunking config schema (chunking/*.toml)
- **stale:** `guru:3cd86aee` (ticket, 2026-04-15) — Write chunking configs for all v1 texts (one per text)
- **stale:** …and 20 more

### What is the current state of `jewish_mysticism`?

- **evidence:** 33 records over 107d across doc+ticket; 14 state change or retraction
- **current:** `guru:docs/corpus-expansion/hit-literature-2026-08.md` (doc, 2026-08-01) — docs/corpus-expansion/hit-literature-2026-08.md
- **stale:** `guru:README.md` (doc, 2026-04-15) — README.md
- **stale:** `guru:ee871b53` (ticket, 2026-04-15) — QA pass: manually verify 1 text per tradition against source
- **stale:** `guru:1b131d1c` (ticket, 2026-04-15) — Write corpus/traditions.toml registry from chunking configs
- **stale:** `guru:af75fb01` (ticket, 2026-04-15) — QA pass: verify chunk boundaries for 2-3 texts per tradition
- **stale:** …and 28 more

### What is the current state of `cost_usd`?

- **evidence:** 20 records over 72d across doc+ticket; 14 state change or retraction
- **current:** `guru-web:e13dd999` (ticket, 2026-07-12) — Fork endpoint: POST /api/shares/[slug]/fork copies snapshot into new session, zeroed accou
- **stale:** `guru-web:0d91fca3` (ticket, 2026-04-30) — feat: cost tracking + dual-axis (queries + USD) budget enforcement
- **stale:** `guru-web:938740cb` (ticket, 2026-04-30) — schema migration: cost_usd + cached_input_tokens on queries; create model_pricin
- **stale:** `guru-web:92ebb9fd` (ticket, 2026-04-30) — src/lib/cost.ts: computeCost(modelId, inputTokens, outputTokens, cachedTokens, a
- **stale:** `guru-web:7c8fdae7` (ticket, 2026-04-30) — wire into /api/query (persist cost_usd + cached_input_tokens) + /api/quota (retu
- **stale:** …and 15 more

### What is the current state of `propose_edges`?

- **evidence:** 32 records over 108d across doc+ticket; 13 state change or retraction
- **current:** `guru:32f96b6b` (ticket, 2026-08-02) — propose_edges on mistral with --text filter per text (NOT --tradition); staged only
- **stale:** `guru:README.md` (doc, 2026-04-15) — README.md
- **stale:** `guru:docs/guru-implementation.md` (doc, 2026-04-15) — docs/guru-implementation.md
- **stale:** `guru:0be14787` (ticket, 2026-04-15) — Guru: RAG-powered comparative esoteric text agent
- **stale:** `guru:4b5863bc` (ticket, 2026-04-15) — Write guru.db schema (nodes, edges, staged_tags, staged_edges, staged_concepts)
- **stale:** …and 27 more

### What is the current state of `concept_id`?

- **evidence:** 17 records over 54d across doc+ticket; 13 state change or retraction
- **current:** `guru-web:docs/review-2026-06-09/02-semantic-concept-matching.md` (doc, 2026-06-09) — docs/review-2026-06-09/02-semantic-concept-matching.md
- **stale:** `guru:docs/guru-implementation.md` (doc, 2026-04-15) — docs/guru-implementation.md
- **stale:** `guru:4b5863bc` (ticket, 2026-04-15) — Write guru.db schema (nodes, edges, staged_tags, staged_edges, staged_concepts)
- **stale:** `guru:0d2b85a6` (ticket, 2026-04-15) — Build backfill_concepts.py (sync concept tags from guru.db to vector metadata)
- **stale:** `guru:docs/web-review/design.md` (doc, 2026-04-25) — docs/web-review/design.md
- **stale:** …and 12 more

### What is the current state of `source_id`?

- **evidence:** 16 records over 49d across doc+ticket; 13 state change or retraction
- **current:** `guru:79801268` (ticket, 2026-06-03) — SBE Zoroastrian re-acquire — apply 5a794b5e patch to legacy chunks (RISKY — needs coordina
- **stale:** `guru:4b5863bc` (ticket, 2026-04-15) — Write guru.db schema (nodes, edges, staged_tags, staged_edges, staged_concepts)
- **stale:** `guru:1237b4fe` (ticket, 2026-04-17) — Phase 1: Add chunk_embeddings table and backfill from ChromaDB
- **stale:** `guru:9ec1dcee` (ticket, 2026-04-25) — Make chunk_ids and corpus directory names internally consistent (root cause: chu
- **stale:** `guru:docs/web-review/design.md` (doc, 2026-04-25) — docs/web-review/design.md
- **stale:** …and 11 more
