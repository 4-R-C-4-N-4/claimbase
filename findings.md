# Findings

Running record of measured results. The Phase 0 go/no-go verdict lands here too,
including if it says the claims column lost.

---

## 2026-08-08 — Baselines established (P0.0)

Corpus: 815 records / 1.96 M chars, 3,290 chunks. Gold set: 9 seeded questions
(`eval/gold_recall.jsonl`), of which 5 stale-answer, 3 factual, 1 capability.

| | rg | chunk-RAG | claims |
|---|---|---|---|
| nDCG@10 | 0.303 | **0.667** | — (P0.5) |
| mislead-rate | 0.333 | **0.333** | — |

`mislead-rate` = fraction of questions where a known-superseded record outranks every
correct one. Ranked "fraction of top-k that is stale" was tried first and discarded: it
scored both baselines identically at 0.083 because a superseded doc at rank 9 counted the
same as one at rank 1. What matters is whether the stale record *wins*.

**Chunk-RAG beats grep on finding things and ties it on being misled.** That is the shape
the design predicts: similarity search has no notion of validity, so retrieval quality and
staleness are independent axes. Neither baseline can improve the second one.

### Three structural gaps, now measured rather than asserted

1. **Tabular sources are near-invisible to embedding retrieval.** q005 asks for a metric
   from a bench report; not one run record appears in either baseline's top 10 (nDCG 0.000
   for both). A table of numbers carries almost no semantic signal. This is the strongest
   argument yet for Adapter C — it converts those tables into ~80 explicit textual claims,
   which is the difference between unreachable and retrievable.
2. **Document lineage is unanswerable by content search.** q006 ("which doc describes the
   current architecture?") returns neither `v2.md` nor `v3.md` from either baseline. Which
   document supersedes which is metadata, not text, so no amount of chunking can answer it.
3. **A corpus with no correct record misleads unconditionally.** q003 (auto-promote) is the
   only question where *both* baselines mislead. 8+ live records assert the abandoned
   practice and none records its abandonment, so every retrieval path is wrong. No
   retriever can fix this; only capture can.

### Caveat on the metric

q005 scores mislead 0.000 for both baselines — but only because they retrieved nothing
relevant at all. A zero from total retrieval failure is not a win, and the current metric
cannot tell it apart from correctly avoiding a stale record. Worth separating before the
verdict run, or the claims column could inherit the same flattery.

### Gold set is seeded, not finished

9 questions, 2 flagged `needs_user_confirm`. Sourcing is now two-track (PLAN §0.8):
harvested (~6–8 usable stories, weak — the corpus self-corrects) and elicited (strong —
auto-promote is the worked example). The elicited track needs the user and has one entry.

---

## 2026-08-08 — The stale sweep found a live operational gap

Running `eval/elicit.py` against the guru corpus was meant to produce eval questions.
It also surfaced a real, current defect, which is worth recording as evidence that
design §6's stale sweep earns its promotion from "optional Phase 3 view" to core.

**`sync_taxonomy.py` has not been run since 2026-08-01.** `concepts/taxonomy.toml`
gained `contrition` (Julian of Norwich ingest, todo:7dc14fc3) and `dharma` + `bhakti`
(Bhagavad Gita ingest, todo:e5b69653) on that date. All three exist as `concept.*`
nodes in `data/guru.db`. **None has a row in `concept_family_membership`** — the
newest concepts that do are the 2026-07-16 batch (astral_light, magical_equilibrium,
magical_will). So three live concepts carry no domain/family placement.

Not verified: whether the script still executes correctly. Only that the memberships
are absent and it remains the designated tool.

### Two corrections to the user's own recollection, both resolved from artifacts

- *"the review python is unused… I use guru review web tool over Tailscale from other
  devices"* — confirms `review_tags.py` / `review_edges.py` as category **B**, not C.
  The practice of reviewing continues, but via a different tool entirely, and the
  Tailscale-from-other-devices reason appears nowhere in the corpus.
- *"sync_taxonomy… predates the domain family concept hierarchy"* — **inverted.** The
  design docs landed 2026-05-26 08:36; the script landed the same day at 14:12 and
  references domain/family 45 times. Its docstring cites `concept-hierarchy/design.md
  §7`. It does not predate the hierarchy; it implements it.

### A sharper staleness signal than "days quiet"

The user's instinct — *"not sure if it still works as it predates X"* — is a better
rule than elapsed time, and it is computable: **a claim asserted before a structural
change to its subject, never reasserted after it, needs revalidation.** That is a
graph query over `asserted_at` and schema-change events, not a timer. Worth building
into the stale sweep rather than ranking on age alone.

Here the rule fires correctly in the *opposite* direction: sync_taxonomy postdates the
hierarchy, so the suspicion is discharged — and the actual defect (never run since a
dependency changed) is a different rule: **an input changed after its consumer last
ran.** `taxonomy.toml` edited 2026-08-01, `sync_taxonomy.py` last exercised 2026-05-26.

### Ranking calibration: days-quiet is the wrong signal

Four verdicts in, from the user:

| rank | item | gap | asserts | verdict |
|---|---|---|---|---|
| 1 | `review_tags.py` | 72d | 13 | **B** — unused; web tool over Tailscale |
| 2 | `review_edges.py` | 72d | 10 | **B** — same |
| 3 | `sync_taxonomy.py` | 72d | 4 | **A** — right tool, just overdue a run |
| 4 | `run-qwen.sh` | 110d | 2 | **A** — still SOTA for the 27B tagger |

Precision 2/4, and **both false positives carry the longest gaps** — `run-qwen.sh` has the
largest gap on the entire list and is a confident A. Assertion count carried the true
positives; the gap term contributed noise, exactly as the header caveat predicted but
more strongly than expected. A launcher that works needs no commits, ever.

Drop days-quiet as a ranking term. The two rules worth keeping are the ones that fired
correctly above: *structural change precedes the claim, never reasserted after* and
*input changed after its consumer last ran*. Both are event comparisons, not timers.

### PRs help, but the sweep has a hard floor

Adding merged-PR descriptions as evidence of exercise moved several rows
(`run-qwen.sh` 110d → 74d, `sync_taxonomy.py` 72d → 61d, `cleanup_stale_embeddings.py`
97d → 83d) and removed none — 19 candidates before and after.

`run-qwen.sh` is still flagged and is still a confirmed **A**, which exposes the floor:
**practices that leave no artifact cannot be swept.** Launching a model server produces
no commit, no PR, no ticket — it is simply run. Same for reviewing through a web UI over
Tailscale, or reading a dashboard. These are exercised constantly and recorded nowhere,
so artifact-silence and abandonment are only weakly correlated for them.

This bounds design §6's stale sweep honestly: it can flag *candidates*, and the two event
rules make it much sharper than a timer, but for artifact-invisible practice the only
signal is asking. Which is an argument for the capture path (§5 `assert()`) rather than
for a better sweep — the sweep cannot see what was never written, and the fix is to make
writing cheap, not to infer harder.

---

## 2026-08-08 — First claims reading: structured-only loses to chunk-RAG

Five adapters built, corpus compiled, 4,141 claims embedded. The scoreboard with
the claims column filled — **structured claims only, no prose extraction yet**:

| | rg | chunk-RAG | claims (structured) |
|---|---|---|---|
| nDCG@10 | 0.303 | **0.667** | 0.225 |
| mislead-rate | 0.500 | **0.333** | 0.500 |

Claims lose on both axes. The plan called for reporting with and without
prose-extracted claims precisely so the two contributions stay separable, and the
"without" run answers a real question: **structure alone is not enough.** Had it
won, Phase 3's fine-tuning would have been unfunded; it did not, so the extraction
path is load-bearing rather than decorative.

### Why, measured rather than guessed

Average claim length by source:

| source | claims | avg chars |
|---|---|---|
| git_log | 1,503 | 56 |
| todo_store | 1,424 | 231 |
| markdown_docs | 871 | 70 |
| pull_requests | 165 | 66 |
| run_artifacts | 140 | 65 |
| agent_memory | 38 | 129 |

**2,679 of 4,141 claims (65%) average under 70 characters** — commit subjects, PR
titles, doc headings, metric rows. Meanwhile the 1.16 MB of *doc prose* that answers
most gold questions is not in the claim index at all: the docs adapter contributes
only heading claims by design, and extraction has not run. chunk-RAG reads all of
it. The comparison right now is a title index against full text, and full text wins.

### One genuine win, exactly where predicted

**q005 — "what was v1's recall on the 130-chunk gauge?" — 0.000 → 0.431.** Both
baselines score zero because a table of numbers carries no semantic signal; the
run-artifacts adapter turns those tables into textual metric claims and makes them
retrievable. That is the tabular-invisibility gap closing, and it is the one result
that could not have come from better chunking.

### A design question this raises

The 871 `"<path> documents <heading>"` claims are near-contentless and compete for
rank with substantive ones. Indexing every structural claim may be actively harmful
to retrieval even when it is correct to *store* it. Worth deciding in P0.5 whether
low-content structural claims belong in the vector index at all, or only in the
graph.

---

## 2026-08-08 — The hand-grading queue was unnecessary work

Built a 49-screen grading queue for `gold_extract`, then read it with a clear lens at
the user's prompting. Most of it has no bearing on the application. A fair sample of
what it asked to be labelled:

- `` `slug` is `UNIQUE` but nullable — only set at generation time. ``
- `` Build `queryText` from the concept label(s) + `definition` + `angle`. ``
- `` `sources/manifest.toml` enumerates every source (URL, license, format, translator). ``

**`claim_kind` earns its existence through supersession** (DESIGN §3.2: decisions
invalidate prior decisions on the same subject; a hypothesis must never beat a fact).
The label has consequences only where two claims about one subject collide over time.
None of the above collides with anything, answers a question anyone would ask, or
supersedes anything. Labelling them is pure cost.

Two mistakes:

1. **Sampled by source stratum and length** — which guarantees a representative slice
   of the corpus and guarantees nothing about whether the label matters.
2. **Built the instrument the plan named without checking it was needed.** The
   end-to-end recall scoreboard already decides Phase 0. An extraction gold set is a
   *diagnostic*, worth its cost only if it predicts that number; one drawn from
   arbitrary implementation trivia does not.

### The measurement was already free, and the plan said so

728 passages / 256 KB of ticket prose carry **human-assigned kind labels already**,
produced over four months as a side effect of the work:

| existing label | count | maps to |
|---|---|---|
| `resolution` note | 622 | decision |
| `analysis: conclusion` | 62 | fact |
| `analysis: evidence` | 42 | observation |
| `analysis: hypothesis` / `blame` | 1 / 1 | hypothesis / observation |

PLAN §P0.5 already called this the "free second scoreboard" and the queue was built
anyway. Extraction kind-agreement can be scored against these at zero grading cost.

### What is genuinely missing, and it is small

The free labels are badly skewed — **one** hypothesis in the entire corpus. So they
cannot measure fact-vs-hypothesis, which PLAN §5 calls the headline extraction metric
and which decides whether *"should homology ship?"* is answered correctly.

That gap is ~15–20 passages of rellm research prose, not 450 sentences across 49
screens. The review tool itself stays — it is Phase 2's conflict queue, which is real
work — but `gold_extract` as sampled is scrapped.
