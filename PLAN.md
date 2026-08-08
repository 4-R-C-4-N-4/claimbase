# CLAIMBASE — Implementation Plan (Phase 0)

Companion to `DESIGN.md`. This document is the build plan; the design doc is the spec.
Written 2026-08-07 against measured machine state, not the doc's assumed one.

**Phase 0 domain: guru and its tagger.** The knowledge base is about the guru project generally —
its design, its decisions, its measurements, and how all three changed — drawn from three repos
(`guru`, `guru-web`, `rellm`) via **three independent adapters**: `.todo` ticket stores, `docs/`
trees, and dated benchmark run artifacts.

**Phase 0 is a proving corpus, not the architecture's center.** The `.todo` store is a
hand-rolled ticket engine specific to this machine. Nothing downstream of the adapter seam
(§2) may know it exists. Three adapters ship in Phase 0 precisely so that the seam is *tested*
rather than asserted — an abstraction with one implementation is not an abstraction, and the
three chosen differ in unit, provenance, and content shape rather than merely in file location.

---

## 0. What the environment actually says

### 0.1 — There is no Obsidian/Logseq vault

§7's reference importer has no input on this machine; 5 files in all of `~/Work` contain a
`[[wikilink]]`. That matters — "wiki-links → entity seed, years of human-labeled entity
resolution for free" is what let the design's Phase 0 ship without an entity resolver. The guru
corpus below is the substitute.

### 0.2 — Source A: the `.todo` stores (structure-rich, decision-rich)

`guru/.todo` + `guru-web/.todo`, 2026-04-15 → present. **rellm has no `.todo` store** — useful in
itself, since it means a third of the corpus is unreachable by this adapter and the domain cannot
be quietly todo-dependent.

| | |
|---|---|
| Tickets | 695 (306 guru, 392 guru-web; 1 unparseable — `guru/.todo/done/c503cdbf.json`) |
| Prose | ~475 KB of string content |
| States | done 631, open 53, blocked 7, wontfix 3, active 1 |
| Types | chore 403, feature 144, bug 99, refactor 33, debt 12, investigation 4 |
| Authorship | agent 388, human 305, test 2 |

Hand-curated fields that map onto the data model — **via the adapter, not in core**:

| Design concept | Ticket field the adapter reads |
|---|---|
| `claim_kind` | `analysis[].type` ∈ evidence(42) · conclusion(62) · hypothesis(1) · blame(1); ticket `type` |
| `confidence` | `analysis[].confidence` ∈ high(98) · medium(4) |
| trust tier | `source.type` ∈ human · agent · test; `analysis[].author` |
| entity mentions | `files[].path` (347 tickets), branch names, commit SHAs |
| edges | `relationships`: parent 423 · children 75 · depends_on 104 · related 17 · blocks 1 · linked_commits 21 |
| `decision` claims | 631 `resolution` notes with `resolved_at` |
| `asserted_at` | `created_at`, `analysis[].timestamp`, `work.started_at`, `resolution.resolved_at` |

This is design §7's "migration is the easy case" in its strongest form: the review gate was run
by hand, per ticket, over four months. These fields compile to claims with **no LLM in the loop**
and double as ground truth for scoring prose extraction.

### 0.3 — Source B: the `docs/` trees (prose-rich, design-rich, argument-rich)

80 markdown docs (35 guru + 33 guru-web + 12 rellm — `docs/**` plus repo-root files), 1.16 MB,
April→August window. *(An earlier count of 42 rellm docs was wrong: it swept vendored files under
`unsloth_compiled_cache/`. Verified by `eval/corpus.py`.)*
Architecture docs, BRDs, IMPL plans, audits, tuning experiments, retros, autopsies. This is the
"irreducibly prose" material of Risk §10.2 and the natural home of the *conceptual* vocabulary —
chunks, concepts, traditions, staged tags, dossiers, corpus sync — which the ticket corpus
references but never defines.

Three properties earn it a Phase 0 slot beyond corpus breadth:

- **Explicit supersession is already on disk.** `docs/v2.md` → `v3.md` → `v3-impl.md` in guru;
  `homology/proposal.md` → `homology/findings.md` in rellm. A design doc superseded by its
  successor is the cleanest possible test of §4.5 machinery.
- **Retracted beliefs, dated, with corrections attached.** rellm's
  `qwen-3-4b-v2-regression-autopsy.md` (2026-08-05) explicitly retracts a prior reading:
  *"the 'base beats the fine-tunes' reading of the June bench is a measurement artifact."*
  Human-authored ground truth about what superseded what, for free.
- **A declared schema with usage history.** `BRD-` / `IMPL-` filename prefixes and the
  `docs/<topic>/` folder taxonomy are conventions with a frequency record — design §7 step 3's
  test case, arriving free.

### 0.4 — Source C: rellm benchmark run artifacts (measurement-rich)

`rellm/runs/bench/<name>-<ISO-timestamp>/`, 16 run directories, 2026-05-13 → 2026-08-07, of which
**8 carry a `report.txt`** (per-model precision / recall / F1 / MAE / macro-F1 tables). The other
8 hold only `cells.csv` / `runs.csv` — metrics recoverable by aggregation, deliberately deferred;
Phase 0 reads `report.txt` and nothing else. Two directories (`grammar-test`, `smoke-human`) have
no parseable timestamp in the name at all, which is a useful forcing function: the adapter must
handle a **null** `captured_at` rather than inventing one (design §4.4 — a guessed valid-time is
a lie with a timestamp).

This is the third source *shape*, and the one that matters most for §2: its unit is a directory
not a file, its timestamp comes from the **path**, not git (rellm has only 20 commits total), and
its content is tabular rather than prose. It exercises exactly the contract properties that the
other two adapters leave untested.

It also supplies the purest bitemporal claims in the corpus. *"v2 F1 = 0.443 on the 181-run
bench"* is a measurement with an exactly-known assertion date; the same metric restated by a
later run is supersession with **no inference required** — the ground truth is the timestamp.

### 0.45 — Source D: git history (overlooked in the first draft of this plan)

An early check asked whether ticket *files* were committed repeatedly, found they weren't, and
wrote git off. That was the wrong question, and it cost two things:

**D1 — Commit messages are a source.** 1,684 commits across the three repos (755 guru, 909
guru-web, 20 rellm) carrying **~503 KB of message prose** — comparable in volume to the entire
ticket corpus, and previously ingested at zero. 586 of guru's are `todo:`-prefixed and link
directly to ticket ids; the rest are dense dated claims in their own right
(*"corpus: mandaean body cleanups drained by review apply (37 chunks, wrap-normalization +
token_count)"*). Unit = a commit; provenance = the SHA; trust tier = the committer; entity
mentions = the changed paths. It is a fourth adapter shape: no file of its own, no body text
beyond the message, and a built-in edge to every path it touched.

**D2 — Diffs supply exact `valid_to`, which is otherwise the hardest field in the model.**
36 markdown files have multi-commit revision chains. `git log -S<symbol> -- <path>` reports the
commit where a claim's supporting text *disappeared* — so a claim extracted from revision N gets
`valid_to` = the timestamp of revision N+1 that removed it. Design §4.4 says a guessed valid-time
is a lie with a timestamp and null is honest; git converts a large class of those nulls into
**recorded fact**. This is the single biggest temporal win available in this corpus and the first
draft of the plan missed it entirely.

Consequence for Adapter B (§3): a doc is not one event. Each revision is its own event
(`path@sha1`, `path@sha2`, …), which is both more faithful to append-only capture and what makes
D2 work. It also resolves the harvester's ⚠ same-day ordering problem — commit order is total,
even when dates tie.

Worked example, the case the harvester got right for the wrong reason: `docs/web-review/edges.md`
has two commits 20 minutes apart, `9f2a7995 16:05` then `be523169 16:25 "flip to Option B (full
rename)"`. Grep over the working tree can only say "no stale record survives." Git says the stale
window was twenty minutes wide and names the commit that closed it.

### 0.5 — Why all three together, and not any alone

Docs are **declarative state**, tickets are **change events**, runs are **measurements**. The
interesting failures are cross-source:

- A doc describes `staged_tag_id`; an April ticket renamed it to `target_id`. Nothing reconciles
  them, and chunk-RAG returns the doc.
- The June bench *measured* base > fine-tunes; the August autopsy *reinterprets* that measurement
  as an artifact. Measurement superseded by re-interpretation is a genuinely different relation
  than doc-supersedes-doc, and needs both C and B present to exist at all.
- `homology/proposal.md` argues the method bet; `findings.md` records the gate not passing.
  "Should homology scoring go into guru?" is a live question whose naive answer is wrong.

These are the sharpest eval questions available (§3), and each exists only because more than one
source is present.

### 0.6 — Two measured corrections

**Git is not a mutation log.** `git log -p -- .todo/` looked like a free append-only event
stream. It isn't: most tickets are committed exactly once (deepest is 11; the rest 1–2). Ticket
state history is not recoverable from git. The temporal substrate is in-file timestamps; commits
supply `source_ref` and first-seen dates only. Docs revise more, but still modestly (113 commits
over guru/guru-web docs; rellm has 20 commits total, so its adapters must not depend on git at
all — path-derived timestamps carry it).

**Intra-ticket time is thin.** Median ticket lives 47 minutes create→update; p90 is 19.5 h; 63
of 695 live past a day. Only 22 tickets carry more than one `analysis` entry, median span between
them 0 h. So **supersession here is cross-ticket and cross-source, not intra-record** — Phase 2's
rules get aimed there from the start.

### 0.7 — Infrastructure

Local Postgres 18.3 is installed, not running, no pgvector; guru runs `pgvector/pgvector:pg17`
in Docker. Use Docker for parity, port 5433 so both can be up. `nomic-embed-text:v1.5` already
pulled in Ollama (768-dim, matches the schema). `guru/scripts/llm.py` already is the provider
abstraction the design specs — vendor it verbatim as `claimbase/llm.py` with a provenance header,
treat guru as upstream. Use the existing `llm <name>` swap and `scripts/run-*.sh` for the
teacher; don't reimplement model launching.

---

## 1. Phase 0 objective, restated as a falsifiable test

Phase 0 passes only if, on a held-out question set over the guru corpus:

1. `claimbase recall` beats `rg` over the source trees, **and**
2. beats a plain chunk-RAG baseline over the same material (chunk, embed, retrieve — what a naive
   agent does today), **and**
3. does so with a measured hallucination rate below a stated threshold, **and**
4. **no core module imports or names anything source-specific** (§2.3).

Point 2 is the substantive one — beating grep proves nothing. Point 4 is the agnosticism gate and
is pass/fail, not a score.

**The sharpest question class** is *stale-answer avoidance*: questions whose correct answer
changed during the April→August window. Chunk-RAG answers these confidently and wrongly. Target
≥12, harvested from (a) tickets sharing a `files[].path` across time, (b) doc↔ticket
contradictions, (c) design-doc lineages (`v2`→`v3`, `proposal`→`findings`), (d) metrics restated
across bench runs, (e) beliefs a later doc explicitly retracts.

Candidates are harvested by `eval/harvest.py` into `eval/candidates.md` — a review queue, not a
gold set; each needs a human to accept, cut, or rewrite it.

**Corrected 2026-08-07.** An earlier draft of this section listed three seeds as "verified to
exist." Running the harvester falsified two of them. Recorded here because the *way* they failed
is a standing lesson about this corpus:

| Claimed seed | Verdict |
|---|---|
| *How does the review app store staged tag targets?* (`staged_tag_id` → `target_id`) | **Dead.** Only 3 files mention `staged_tag_id` and all 3 also mention `target_id` — the docs were revised alongside the rename. No stale record survives, so chunk-RAG answers it correctly. Staleness was inferred from the rename ticket existing, which is not the same thing. |
| *Does the base model beat the fine-tunes?* | **Alive, but not where claimed.** The June `report.txt` shows base F1 0.389 vs v1 **0.488** — base loses there too. The retracted claim lives in the **human-graded** table (`report_human.txt`, base 0.594 > v1 0.537 > v3 0.589), restated in `qwen-3-4b-guru-card.md` (May 27) and disowned as a "shotgun over-emission artifact" by the autopsy (Aug 5). |
| *Should homology scoring be wired into guru?* | **Alive.** `proposal.md` argues the bet; `findings.md` (2026-08-05) records the gate not passing. |

Two general lessons, both now encoded in the harvester:

1. **A rename is not a stale answer.** Supersession only produces a bad retrieval when something
   stale *survives*. A well-maintained corpus self-corrects, and this one often does. S1 therefore
   requires a surviving record that mentions the old name and not the new one.
2. **Ground truth has variants.** `report.txt` (teacher-labelled) and `report_human.txt`
   (human-graded) disagree about which model wins, and the disagreement is the whole point. They
   are loaded as separate records with the variant in the metric name; collapsing them would have
   erased the corpus's single best stale-answer pair.

---

## 2. The adapter seam

Design §7's closing line — *"every importer is just an adapter that emits events + optional
schema/alias events; nothing downstream knows imports exist"* — is the load-bearing constraint of
this build, so it gets a contract and a test rather than good intentions.

### 2.1 The contract

```python
class Source(Protocol):
    name: str                                    # "todo_store", "markdown_docs"
    def scan(self)                  -> Iterator[Unit]        # discover raw units
    def to_event(self, unit)        -> Event                 # canonical text + provenance
    def structured_claims(self, ev) -> Iterator[Claim]       # optional, no LLM
    def entity_mentions(self, ev)   -> Iterator[Mention]
    def edges(self, ev)             -> Iterator[Edge]
    def declared_types(self)        -> Iterator[SchemaType]  # source: migrated
```

Everything downstream — extraction, embedding, supersession, recall, views — consumes only
`events` / `claims` / `entities` / `edges` / `schema_types`. An adapter that needs a new core
field is a signal to generalize the field, not to special-case the adapter.

### 2.2 What must not leak

| Source-specific thing | Generalized as |
|---|---|
| `analysis[].type` ∈ evidence/conclusion/… | adapter maps to core `claim_kind`; core never sees the ticket vocabulary |
| `source.type: agent \| human` | adapter declares a **trust tier** per claim; core enforces the kind cap (a low-trust author cannot produce `fact`/`decision`) |
| `relationships` key names | emitted as free text in `edges.rel`; canonicalization is schema emergence's job (§4.6), not the adapter's |
| ticket `type`, `BRD-`/`IMPL-` prefixes | `schema_types` rows with `source: migrated` — identical treatment for both adapters |
| `.todo/` layout, frontmatter keys | confined to `scan()` / `to_event()` |

The trust-tier generalization is the important one. "Agent-authored prose may not become `fact`"
is a *general* rule about authorship provenance that any adapter can supply — a session
transcript adapter computes it from turn role, a doc adapter from git author. Only the
*computation* is source-specific.

### 2.3 Conformance test (ships in P0.1, gates P0.5)

- An adapter conformance suite each source must pass: idempotent re-import, stable
  `content_hash`, no null provenance, declared trust tier on every claim.
- A structural test asserting no module under `claimbase/core/` imports from
  `claimbase/sources/`, and that source-specific identifiers appear nowhere in core.
- The real acceptance test is Phase 1's: **adding the session-transcript adapter must require
  zero changes to core.** If it doesn't, the seam failed and Phase 0's pass was partly illusory.

---

## 3. Build order — eval harness first

Per Risk §10.1, the first milestone builds nothing that extracts anything.

### P0.0 — Eval harness and gold sets *(build first)*

- `eval/gold_extract.jsonl` — 40–60 hand-graded prose segments, stratified across both adapters
  (ticket `description` / `analysis[].content` / `resolution.note`, and doc body prose), both
  repos, both authorship tiers, all six ticket types. Structured fields are *not* graded — they
  compile deterministically and serve as ground truth instead. **Over-sample rellm research
  prose** — it is the material most likely to be mis-typed as `fact` (§5).
- `eval/gold_recall.jsonl` — 25–35 questions with gold source spans, ≥12 of them stale-answer
  questions per §1. Harvest candidates by grouping tickets and docs on shared file paths and
  symbols, then reading the timelines; `staged_tag_id → target_id` is the worked example.
- `claimbase eval extract` → precision / recall / hallucination-rate. Match is fuzzy: embedding
  cosine ≥ τ **and** exact `claim_kind`. Hallucination = claim unsupported by its span.
- `claimbase eval recall` → nDCG@10, answer-supported-rate, **stale-answer rate**, against `rg`
  and chunk-RAG. Both baselines implemented **in this milestone**, before extraction exists.

*Exit:* the scoreboard prints with the claims column empty. Everything after this fills it.

### P0.1 — Skeleton, store, seam

- `uv` project, `claimbase` package, `python -m claimbase` CLI (guru's CLI shape).
- `claimbase/core/` and `claimbase/sources/` split from the first commit, with the §2.1 contract
  and the §2.3 conformance suite present before any adapter is written.
- `docker-compose.yml` → `pgvector/pgvector:pg17`, own volume, port 5433.
- Numbered plain-SQL migrations (guru convention); Atlas deferred until a second schema consumer
  exists.
- Tables: `events`, `claims`, `entities`, `entity_aliases`, `edges`; `conflicts` and
  `schema_types` created empty-but-present. `claims` carries `valid_from` / `valid_to` /
  `status` / `superseded_by` and a `trust` tier from day one — Phase 2 adds only populating
  logic, never a backfill migration.

### P0.2 — Adapter A: `sources/todo_store.py`

- One event per ticket; `content` is a canonical text rendering with stable field ordering so
  `content_hash` dedupes across re-imports. `source_ref` = `<repo>/.todo/<state>/<id>.json@<sha>`;
  `captured_at` = ticket `created_at`.
- Structured → claims, no LLM: `summary` → claim; `resolution.note` → `decision` with
  `valid_from = resolved_at`; each `analysis[]` entry → claim with `claim_kind` and `confidence`
  mapped from its own fields and `asserted_at` from its timestamp.
- Trust tier declared per claim from `source.type` / `analysis[].author`; core enforces the cap.
- Entity mentions from `files[].path`, repo names, branches. Edges from `relationships` (641,
  free). Declared types from ticket `type` vocabulary.
- Handle the unparseable ticket explicitly — log and skip, don't crash the import.

### P0.3 — Adapter B: `sources/markdown_docs.py`

Written against the same contract, ideally by a different pass of attention than A, because its
job is to find where the contract is secretly todo-shaped.

- **One event per doc *revision*, not per doc** (§0.45 D2). `source_ref` = `path@sha`,
  `captured_at` = that commit's date. Longer docs split at H2 with heading path in `meta`.
- Claims whose supporting text is removed by a later revision get `valid_to` from that commit —
  recorded, not inferred. This is the adapter's most valuable output and it is pure bookkeeping.
- Structured → claims: title and heading-path claims only. Docs are prose — this adapter
  deliberately contributes *little* structured signal, which is exactly what stress-tests a seam
  designed around a structure-rich source.
- Trust tier from git author. Entity mentions from headings, backtick-quoted identifiers, and
  linked paths. Declared types from `BRD-`/`IMPL-` prefixes and folder taxonomy.
- Doc lineage (`v2` → `v3` → `v3-impl`, `proposal` → `findings`) emitted as edges; supersession
  *logic* stays Phase 2.

### P0.4 — Adapter C: `sources/run_artifacts.py`

The seam's real exam: a unit that is a **directory**, a timestamp from the **path**, and content
that is **tabular, not prose**. If the contract survives C without modification, it is probably
real; if C forces a core change, better to learn it now than at Phase 1.

- Unit = one `runs/bench/<name>-<ISO-timestamp>/` directory. `captured_at` parsed from the
  directory name; git is not consulted — rellm has 20 commits and they carry no signal.
- Scope tight: parse the **per-model summary and macro-F1 tables in `report.txt` only**. Not
  `cells.csv`, not `runs.csv`, not confusion matrices. That is ~80 metric claims total, entirely
  deterministic, no LLM.
- Each metric row → one claim: *"v2 F1 = 0.443 (181 runs, bench `qwen3-4b-v3`)"* with
  `claim_kind: fact`, `asserted_at` from the directory timestamp, high confidence.
- Entity mentions: model names (`base`, `v1`, `v2`, `v3`), bench names, metric names.
- Contributes **zero prose** to extraction — deliberately. An adapter with no prose at all is the
  cleanest check that the pipeline does not assume every source feeds the extractor.

### P0.4b — Adapter D: `sources/git_log.py`

Added after git was found to have been overlooked (§0.45). Small: one `git log` parse per repo,
no file-shaped unit, no LLM.

- Unit = one commit. `source_ref` = `<repo>@<sha>`; `captured_at` = commit date; trust tier from
  the committer. Subject → claim; body → prose for extraction; changed paths → entity mentions;
  `todo:<id>` prefixes → edges to ticket claims, closing the loop between A and D.
- Merge commits and mechanical subjects are dropped, and the drop count is reported — a silent
  filter here would quietly hide a third of the source.

*Exit for P0.2–4b:* `claimbase import --all` is idempotent, the conformance suite passes for all
four adapters, per-source claim / entity / edge counts are reported, and **the git log shows no
commit touching `claimbase/core/` while B and C were written**. That last one is the agnosticism
evidence, and it is free to collect.

### P0.5 — Prose extraction

- Prompt + strict JSON schema per §4.2; `meta.extractor_version` on every claim so a model bump
  can selectively reprocess.
- Teacher A: local 27B via the existing `llm` swap, **no-think** (6× faster on mechanical tasks).
  Teacher B: frontier API, over the gold set only. Pick on measured F1, not vibes — this also
  finally measures 27B no-think vs. think on a structured-output task.
- **Free second scoreboard:** run the extractor over ticket prose whose record already declares a
  type and confidence, and measure agreement with the human labels. Hundreds of labeled examples
  at zero grading cost, independent of the hand-graded set.
- Aggressive confidence threshold; sub-threshold extractions land in a `review` staging table, not
  in `claims` (precision over recall).
- Batch runner with resume-from-checkpoint; GPU work ends with `llm stop`.

### P0.6 — Embeddings, `recall`, go/no-go

- `nomic-embed-text:v1.5` via Ollama, batched, HNSW index on `claims.embedding`.
- `claimbase recall <query>` — vector top-k, 1-hop expansion along edges, rendered with
  provenance (`content` · `claim_kind` · `asserted_at` · `source_ref` · trust), plus
  `--with-context` for surrounding source text (Risk §10.2).
- Run the full scoreboard. Report **with and without prose-extracted claims** so the
  deterministic and LLM contributions stay separable — if structured claims alone beat chunk-RAG,
  that is a real result that nonetheless funds none of Phase 3.
- Verdict to `findings.md` including if the claims column loses. Phase 1 starts only on a pass.

---

## 4. Deliberate deferrals

| Deferred | Until | Why |
|---|---|---|
| Session-transcript / memory / vault adapters | Phase 1 | Each is *only a new adapter* if §2 held. Sessions are the agnosticism acceptance test. |
| Entity resolution (§4.3) | Phase 1 | Phase 0 mentions come from paths and headings. Cross-source aliasing ("the review app" ≡ `guru-review` ≡ guru-web review flow) is the first real resolver work. |
| Supersession / conflicts (§4.5) | Phase 2 | Columns exist from P0.1; aimed at cross-ticket and doc↔ticket contradiction per §0.5. |
| Schema emergence / declared schema (§4.6/4.7) | Phase 3 / Phase 2 | `schema_types` exists empty; both adapters already feed it `migrated` rows. |
| MCP server (§5) | Phase 1 | CLI `recall` suffices to run the eval, and the eval is the point. |
| Fine-tuned 7B (§4.2) | Phase 3 | Teacher output is the training set; it must accumulate first. |
| Atlas | Second schema consumer | Numbered SQL is enough for one writer. |

---

## 5. Risks specific to this build (beyond DESIGN §10)

- **The seam is still proven only on filesystem sources.** C fixes the worst of this — directory
  units, path-derived time, tabular content, no git dependence — but all three adapters still
  read a local tree with a stable path. A voice transcript or a web clipping has no path identity
  and no natural unit boundary. Mitigation: write the *contract* against those cases now
  (nullable provenance, adapter-supplied trust, adapter-chosen unit boundaries) even though no
  Phase 0 adapter exercises them, and keep Phase 1's session adapter as the real acceptance test.
- **The domain is narrow.** Three repos of one project family: already atomic, typed, timestamped,
  trust-labeled. An extractor tuned here will not transfer cleanly to prose or speech. Phase 0
  proves the *machinery*, not the *generality*; a score drop in Phase 1 is expected, not a
  regression.
- **rellm's research prose is argumentative, not declarative.** Autopsies and findings docs are
  full of hedged, conditional, and explicitly-superseded statements ("tune peak was pure selection
  noise"). An extractor that flattens these into confident `fact` claims produces exactly the
  authoritative-sounding garbage of Risk §10.1 — on the material where being wrong matters most.
  Mitigation: over-sample rellm prose in the gold set, and treat `hypothesis`-vs-`fact` confusion
  there as the headline extraction metric rather than aggregate F1.
- **Structured fields could carry the eval.** Hence the split reporting in P0.5.
- **Thin intra-record time (§0.5).** Bitemporality has less to chew on than the design assumes.
  If the stale-answer question set can't reach ~12 items, that is itself a Phase 0 finding worth
  writing down before building Phase 2.
- **Vocabulary overlap inflates scores.** guru and guru-web share terminology heavily. Stratify
  gold sets by repo and report per-repo.
- **The gold set is the bottleneck.** 40–60 graded segments plus ~30 questions is a few hours of
  careful work with no substitute. The structured fields shrink it; they don't remove it.
