# Gold set — your questions, with refs spelled out

Each ref is what the scoreboard treats as *the right record to return* (supports) or *a record it would be wrong to return as current* (contradicts).

Skim for refs that look wrong. A bad ref makes that question's score meaningless, which is worse than not having the question.


---

## q010 — How many traditions and texts are in the guru db locally?

**You said true:** The amount of traditions and texts must be verified in the DB and is not worth calling stable, it grows constantly.

**You said wrong:** The traditions can be read from references in PRs or documentation

**SUPPORTS your answer:**

- `guru:ee871b53`
  - ticket  guru [chore/done] QA pass: manually verify 1 text per tradition against source
  - *decision [superseded]*: QA verified 2 traditions via acquire.py: (1) gnosticism/gospel-of-thomas — 28560 chars, clean Lambdin translation text, no HTML artifacts. (2) jewish_mysticism/sefer-yetirah — 16275 chars, c
  - *task*: QA pass: manually verify 1 text per tradition against source

**CONTRADICTS it (would be a stale answer):**

- `guru:5bd45ac2`
  - ticket  guru [chore/done] Create sources/manifest.toml with all v1 sources
  - *observation [superseded]*: sources/manifest.toml contains 23 v1 sources: 2 gnostic texts from gnosis.org, 17 Corpus Hermeticum tractates from sacred-texts.com, 1 Heart Sutra from sacred-texts.com, and 2 Jewish mystici
  - *decision*: Created sources/manifest.toml with 23 v1 sources: 2 gnostic texts (gnosis.org), 17 Corpus Hermeticum tractates (sacred-texts.com), 1 Heart Sutra (sacred-texts.com), 2 Jewish mysticism texts 
- `guru-web:b22586bc`
  - ticket  guru-web [feature/done] Build golden retrieval test set: fixture pinned to v3 snapshot with corpus_version + precision/r
  - *decision*: Corpus-pinned golden gate (corpus_version 27): 14 asserted queries — tradition-anchored (distinctive term -> certain tradition: taoism/jewish_mysticism/neoplatonism/hermeticism/egyptian/gnos
  - *observation*: The corpus-pinned golden gate for corpus_version 27 contains 14 asserted queries covering tradition-anchored terms and hierarchy/breadth constraints.
- `guru:af75fb01`
  - ticket  guru [chore/done] QA pass: verify chunk boundaries for 2-3 texts per tradition
  - *decision*: QA pass on 2 traditions: (1) gnosticism/gospel-of-thomas: 114 logion chunks, min=9 max=300 avg=56 tokens. Logion 77 'split a piece of wood' verified correct. (2) jewish_mysticism/sefer-yetir
  - *observation*: The gnosticism/gospel-of-thomas text contains 114 logion chunks with token counts ranging from 9 to 300 and an average of 56 tokens.


---

## q011 — Once a review on a tag or edge has been made with the guru review tool, is the change applied?

**You said true:** No. The apply gate is the final step in the loop and must be completed by a human.

**You said wrong:** The reviewed tags and edges are live. Once reviewed the agent can apply them.

**SUPPORTS your answer:**

- `assert:autopromote-retired`
  - CAPTURED autopromote-retired  (you told me this directly)
  - *practice*: Auto-promote is no longer used for guru staged edges or tags at any confidence tier. As of 2026-07-14 every tier goes through the guru-review queue-only flow with the user keeping the apply 
- `guru:f84089c0`
  - ticket  guru [chore/done] /guru-review-edges queue-only over all staged edges touching both texts (user keeps apply gate)
  - *task*: /guru-review-edges queue-only over all staged edges touching both texts (user keeps apply gate)
- `guru:docs/ingest/11-tag-review.md`
  - doc     guru/docs/ingest/11-tag-review.md
  - *observation*: The review web app's HTTP API is driven by the guru-review-tags skill.
  - *practice*: Only the user applies decisions in the tag-review process.

**CONTRADICTS it (would be a stale answer):**

- `guru:b60b9a0e`
  - ticket  guru [chore/done] Build review_edges.py (CLI review tool for staged edges)
  - *observation*: The script `scripts/review_edges.py` is an interactive CLI tool for human review of `staged_edges` from Pass C.
  - *task*: Build review_edges.py (CLI review tool for staged edges)
- `guru:docs/ingest/14-edge-review.md`
  - doc     guru/docs/ingest/14-edge-review.md
  - *fact*: Per-text scoping for edge review is available only through the review web app.
  - *fact [superseded]*: The CLI tool scripts/review_edges.py scopes reviews by tradition pair, edge type, and confidence rather than by text.
- `guru:a8a1e876`
  - ticket  guru [refactor/done] C1: review_edges.py — drop [p] (accept-at-proposed) per editorial-overlay rule. Any human Accept
  - *task*: C1: review_edges.py — drop [p] (accept-at-proposed) per editorial-overlay rule. Any human Accept = verified
  - *observation*: Help text, prompt, and unknown-key message were updated in review_edges.py.


---

## q012 — Which database does the guru export seed?

**You said true:** First, the export seeds the local postgres docker environment. This is staging. After testing with guru-web, the same export is promoted to production by a human.

**You said wrong:** The guru export is sent directly to production.

**SUPPORTS your answer:**

- `guru:eb9d20d6`
  - ticket  guru [chore/done] Populate concept_aliases — first pass (33 transliteration/foreign-term concepts)
  - *capability*: export.py carries concept_aliases to the guru-web PostgreSQL database.
  - *decision*: 33 concepts / 50 aliases populated in concepts/taxonomy.toml [concept_aliases]; loaded to guru.db (50 rows, 0 dangling, 0 non-lowercase). Curated against the word-boundary-regex matcher per 
- `guru:d4b196da`
  - ticket  guru [chore/done] Close-out gated on user apply: re-promote themes, smoke test, export.py, docker postgres load
  - *task*: Close-out gated on user apply: re-promote themes, smoke test, export.py, docker postgres load
- `guru:b44966d0`
  - ticket  guru [feature/done] staged_cleanups queue: model-proposed rewrites for hard-wrapped prose behind the apply gate
  - *decision*: Full pipeline shipped: staged_cleanups schema+migration (v3_008), propose_cleanups.py (local model, mechanical words_preserved contract), guru-review /cleanups deck (BEFORE/AFTER cards, appa
  - *observation*: The full staged_cleanups pipeline is shipped with schema v3_008, propose_cleanups.py, a guru-review deck on port 7314, and apply_cleanups.py with staleness/drift/ratio guards.

**CONTRADICTS it (would be a stale answer):**

- `guru:docs/summary/document-knowledge-data-structures.md`
  - doc     guru/docs/summary/document-knowledge-data-structures.md
  - *observation*: SCHEMA_VERSION is set to 4 in scripts/export.py and EXPECTED_SCHEMA_VERSION is set to '4' in guru-web/src/lib/boot.ts:48.
  - *fact [superseded]*: CI hash checks pass only if both the guru-web repo and the data repo are updated simultaneously.
- `guru-web:9dedc4cb`
  - ticket  guru-web [chore/blocked] Load full corpus via guru-corpus.sql.gz into production Postgres
  - *task*: Load full corpus via guru-corpus.sql.gz into production Postgres


---

## q013 — Where does guru's production retrieval actually run?

**You said true:** The real retrieval query is in guru-web, which talks to the postgres db. This is what runs on production.

**You said wrong:** The search cli in guru reflects the retrieval algorithm in guru-web.

**Classed `abstain`** — nothing in the corpus takes a position either way, so the correct behaviour is to decline rather than answer. Not scored on nDCG.

**SUPPORTS your answer:**

- *(none found)*

**CONTRADICTS it (would be a stale answer):**

- *(none found)*


---

## q014 — When an agent is reviewing a chunk for tag or edge reviews with the guru-review tool, is it required for the agent to read the entire chunks present, or can they bulk submit if the reviews are trending a certain direction?

**You said true:** The review agent should never submit reviews without reading each chunk provided and the reasoning from the local model.

**You said wrong:** The review tool allows for bulk calls so it is best to quickly review rather than optimize quality.

**SUPPORTS your answer:**

- `guru:AGENTS.md`
  - doc     guru/AGENTS.md
  - *practice*: Files in `corpus/*.toml` are generated and should not be reviewed directly; instead, review the chunker configuration.
  - *practice*: Accept and reject decisions at nodes 11 and 14 must be based on reading the chunk body rather than sampling or extrapolating across a batch.

**CONTRADICTS it (would be a stale answer):**

- *(none found)*


---

## q015 — When adding a new text, the first step is to chunk the content.

**You said true:** The first step should always be manifest work, including source verifiation and license public domain.

**You said wrong:** Yes, a text can quickly be chunked without consideration of strata like author notes or footnotes or html artifacts.

**SUPPORTS your answer:**

- `guru:docs/ingest/02-manifest-entry.md`
  - doc     guru/docs/ingest/02-manifest-entry.md
  - *decision*: If a work has multi-page pagination, it must be handled by creating one entry per page or adding multi-page support to the host's downloader to avoid ingesting fragments.
  - *fact*: Source IDs serve as the citation namespace and must be globally unique across all traditions, not just unique per tradition.
- `guru:7dc14fc3`
  - ticket  guru [feature/done] Ingest Julian of Norwich, Revelations of Divine Love (Warrack) into christian_mysticism — full p
  - *observation*: The ingestion of Julian of Norwich resulted in 127 chunks, 1409 tags reviewed (720 accepted including the new concept contrition), and 332 edges reviewed (83 accepted, 15 CONTRASTS including
  - *decision*: Julian of Norwich, Revelations of Divine Love (Warrack) fully ingested: 127 chunks, 1409 tags reviewed (720 accepted incl. new concept contrition), 332 edges reviewed (83 accepts, 15 CONTRAS
- `guru:5bd45ac2`
  - ticket  guru [chore/done] Create sources/manifest.toml with all v1 sources
  - *observation*: The Corpus Hermeticum entries use the html_multi format because the index page links to individual tractates.
  - *observation*: The file sources/manifest.toml was created to track all v1 corpus sources with their download URLs, license status, and extraction instructions.

**CONTRADICTS it (would be a stale answer):**

- `guru#22`
  - PR      guru#22 Junk-text cleanup C1: strip sacred-texts nav prefix (981 chunks → 0)
  - *practice*: The process to add a new text involves adding a manifest entry, acquiring and chunking the text, bootstrapping graph nodes, tagging concepts, reviewing edges, and embedding the chunks.
  - *hypothesis*: Re-chunking may require re-tagging of promoted EXPRESSES tags for the three texts where chunk boundaries shifted.
- `guru:2957d758`
  - ticket  guru [chore/done] Strip whole-page apparatus from page-as-chunk SBE texts (Plotinus, Zhuangzi)
  - *fact*: Dropping any chunk in a page-as-chunk text requires re-ingesting the entire text because chunk.py renumbers chunks sequentially, changing all downstream IDs.
  - *decision*: Both page-as-chunk SBE texts cleaned. Plotinus (79e876b): drop 76 front-matter+divider pages, 828->752, curation preserved via body remap. Zhuangzi (this commit): scope to Inner Chapters I-V
- `guru:11cf1630`
  - ticket  guru [chore/done] Manifest stanza + chunking config for julian-revelations (Gutenberg #52958, generic_html, chapte
  - *observation*: The chunking configuration for julian-revelations uses regex-section-split on chapter headers and pre-strips Gutenberg header boilerplate, Grace Warrack's introduction, and glossary/notes ta
  - *task*: Manifest stanza + chunking config for julian-revelations (Gutenberg #52958, generic_html, chapter-split)


---

## q016 — Does the guru-web app allow users to reference the chunk source material on the site? Are the references hyperlinks?

**You said true:** Yes, each text is browsable chunk by chunk and the references after each query link to the chunk that was sent to the backend model.

**You said wrong:** The guru-web app is only a RAG system for comparative religion.

**SUPPORTS your answer:**

- `guru:d7885c88`
  - ticket  guru [chore/done] Smoke test: guru query cites Gita chunks; record chunk/tag/edge counts in ticket
  - *task*: Smoke test: guru query cites Gita chunks; record chunk/tag/edge counts in ticket
  - *observation*: Smoke test PASS 2026-08-01: 'guru query' on non-attachment retrieves hinduism.bhagavad-gita-chapter-03 chunks (sim 0.647) in a cross-tradition set (Tao Te Ching, Plotinus, Diamond Sutra, Lév
- `guru-web:6adfbb6b`
  - ticket  guru-web [feature/done] Source material browser: public /read library (traditions→texts→chunk viewer with tags, parallel
  - *task*: Source material browser: public /read library (traditions→texts→chunk viewer with tags, parallels, summaries) + citation deep-links from chat/blog/share
  - *decision*: Shipped in PR #106: public /read library (traditions→texts→chunk viewer with tags/parallels/summaries), concept constellation pages, citation deep-links across chat/blog/share, sitemap+robot
- `guru-web#106`
  - PR      guru-web#106 Source material browser: public /read library + citation deep-links
  - *fact [superseded]*: The guru-web repository is a TypeScript and Next.js front-end for the Guru esoteric research platform.
  - *fact [superseded]*: The guru-web repository is a TypeScript and Next.js front-end for the Guru esoteric research platform.

**CONTRADICTS it (would be a stale answer):**

- *(none found)*

