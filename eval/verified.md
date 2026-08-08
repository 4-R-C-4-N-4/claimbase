# Verified stale-answer candidates

Produced by `eval/verify.py`. Each candidate is tested against git and the run
configs; only what survives needs a human. Drops keep their reason.

## Bench comparability

| bench | models | n | comparable group |
|---|---|---|---|
| `v2-vs-v1-vs-base-serial` | base, v1, v2 | 130 | G3 |
| `v1-sanity` | v1 | 103 | G12 |
| `v2-human` | base, v1, v2 | 500 | G6 |
| `gauge-human` | base, v1, v2 | 130 | G3 |
| `gauge-human#human` | base, v1, v2 | 763 | G7 |
| `gauge-v3` | base, v1, v2, v3 | 130 | G8 |
| `gauge-v3#human` | base, v1, v2, v3 | 763 | G11 |
| `qwen3-4b` | base, guru | 293 | G2 |
| `qwen3-4b#human` | base, guru | 1990 | G1 |
| `qwen3-4b-v1-v2` | base, v1, v2 | 323 | G5 |
| `qwen3-4b-v1-v2#human` | base, v1, v2 | 2179 | G4 |
| `qwen3-4b-v3` | base, v1, v2, v3 | 181 | G10 |
| `qwen3-4b-v3#human` | base, v1, v2, v3 | 1497 | G9 |

## S3 — metric drift: 6 real, 28 cross-ruler artifacts

A metric that moves *between* comparability groups changed ruler, not value —
exactly the confusion the v2-regression autopsy calls a measurement artifact.

- **`v1` recall (teacher-graded)** [G3]: **0.596** (v2-vs-v1-vs-base-serial, May 22) → **0.509** (gauge-human, May 25)
- **`v2` recall (teacher-graded)** [G3]: **0.602** (v2-vs-v1-vs-base-serial, May 22) → **0.518** (gauge-human, May 25)
- **`v2` precision (teacher-graded)** [G3]: **0.597** (v2-vs-v1-vs-base-serial, May 22) → **0.669** (gauge-human, May 25)
- **`base` precision (teacher-graded)** [G3]: **0.328** (v2-vs-v1-vs-base-serial, May 22) → **0.398** (gauge-human, May 25)
- **`v1` precision (teacher-graded)** [G3]: **0.558** (v2-vs-v1-vs-base-serial, May 22) → **0.621** (gauge-human, May 25)
- **`v2` macro-F1 (teacher-graded)** [G3]: **0.525** (v2-vs-v1-vs-base-serial, May 22) → **0.502** (gauge-human, May 25)

*Dropped as cross-ruler (28): `base` precision (teacher-graded), `base` recall (teacher-graded), `base` F1 (teacher-graded), `v1` precision (teacher-graded), `v1` recall (teacher-graded), `v1` F1 (teacher-graded)…*

## S1 — rename / replace: 1 real of 1

### What is `src/middleware.ts` called / how is it referred to now?

- **evidence:** `src/middleware.ts` → `src/proxy.ts` — “Root cause: a leftover Clerk-quickstart ./middleware.ts at repo root coexisted with the intended src/middleware.ts pass-through. The root fi”
- **stale, retrievable today:** `guru-web:882d1657` (2026-05-10) — still present at HEAD
- **stale, retrievable today:** `guru-web:docs/admin-ui/IMPL-admin-ui.md` (2026-05-01) — still present at HEAD
- **stale, retrievable today:** `guru:docs/concept-hierarchy/guru-web-alignment.md` (2026-05-27) — still present at HEAD


## S2 — doc lineage: 2 real of 2

### [guru] What is the current design for 'docs'?

- **evidence:** v2 → v3
- **stale, retrievable today:** `guru:docs/v2.md` (2026-04-17) — still present at HEAD

### [rellm] What is the current design for 'docs/homology'?

- **evidence:** findings → proposal
- **stale, retrievable today:** `rellm:docs/homology/findings.md` (2026-08-05) — still present at HEAD


## S4 — explicit retraction: 0 real of 9

### [rellm] 80-concept-teacher-run-retro: what did this revise?  *[RETRACTION CONFIRMED — pairing needs judgment]*

- **evidence:** - 3089 chunks tagged, **0 errors**, 31 batches of 100 with steady ~4.5h/batch cadence. - ~161s/chunk on average — no degradation across the 138-hour run. - 11,473 tags proposed by the model. - DB outcome: 6665 inserted + 3806 superseded + 1002 skipped_reviewed = 11473 (matches log proposals exactly;

### [guru] 10-tag-concepts: what did this revise?  *[RETRACTION CONFIRMED — pairing needs judgment]*

- **evidence:** **`--resume` and `--supersede-pending` interacting badly on a re-run.** Read what they do before re-tagging a text that already has pending rows; the defaults are not always what a re-run wants.

### [guru-web] CORE_RULES-draft: what did this revise?  *[RETRACTION CONFIRMED — pairing needs judgment]*

- **evidence:** > Note: the tradition list at the top was moved into CORE_RULES from > the voice overlays during ticket 3 (see > [VOICE-woowoo-draft.md](./VOICE-woowoo-draft.md) → "Tradition list > moved to CORE_RULES"). It's the retrieval catalog, invariant > across voices, so duplicating it per overlay was wrong.

### [guru-web] retriever-hitlist: what did this revise?  *[RETRACTION CONFIRMED — pairing needs judgment]*

- **evidence:** The original ordering put Bug 1 first as "a one-line SELECT fix." That was wrong — see the Bug 1 verification: `chunks` has no `tier` column, so Bug 1 is a scoring redesign, not a one-liner, and it cannot be done in isolation from Bug 2. Revised order:
- *lexical guess, unreliable:* `guru:docs/v2.md` (2026-04-17) — 4 shared identifiers — still present at HEAD
- *lexical guess, unreliable:* `guru:docs/guru-architecture.md` (2026-04-15) — 3 shared identifiers — still present at HEAD

### [rellm] edge-review-pass: what did this revise?  *[RETRACTION CONFIRMED — pairing needs judgment]*

- **evidence:** Headline accept rate: ~96.5% — Mistral's 0.85 tier was strongly over-flagged at first glance, but turned out to be well-calibrated for the bulk of tradition pairs. The surface_only flips concentrated in a handful of pathological clusters rather than being evenly noisy.

### [rellm] findings: what did this revise?  *[RETRACTION CONFIRMED — pairing needs judgment]*

- **evidence:** Status: **method gate not passed** — the geometry does not beat the cheap baseline out of sample. Per the proposal's own decision point, the homology scoring layer should not be wired into guru on current evidence. The gold set, the extraction infrastructure, and the secondary uses all survive.

### [rellm] proposal: what did this revise?  *[RETRACTION CONFIRMED — pairing needs judgment]*

- **evidence:** Resolution: the gold verdict is an ordinal 0–4 depth-of-correspondence rating (anchors in `data/homology/gold/README.md`), plus "rejected" for unusable test cases. Consequences for the eval design (supersedes the binary-separation framing in the Evaluation section above):

### [rellm] qwen-3-4b-guru-card: what did this revise?  *[RETRACTION CONFIRMED — pairing needs judgment]*

- **evidence:** **vs human-graded labels:** base 0.594 F1 (inflated — a "shotgun" over-emission artifact, base emits 36.3 tags/chunk vs v3's 14.2, landing extra hits on ungraded cells for free), v1 0.537, v2 0.577, **v3 0.589** — v3 wins among the models with comparable emission counts. v1's worst blind spot, `anim
- *lexical guess, unreliable:* `rellm:MODEL_CARD.md` (2026-05-18) — 10 shared identifiers — still present at HEAD

### [rellm] qwen-3-4b-v2-regression-autopsy: what did this revise?  *[RETRACTION CONFIRMED — pairing needs judgment]*

- **evidence:** ## 1. The bench blind spot (base does NOT beat the fine-tunes)
- *lexical guess, unreliable:* `guru:docs/concept-hierarchy/design.md` (2026-05-26) — 15 shared identifiers — still present at HEAD
- *lexical guess, unreliable:* `guru:docs/corpus-expansion-candidates.md` (2026-05-28) — 7 shared identifiers — still present at HEAD

