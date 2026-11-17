# Findings

Running record of measured results. The Phase 0 go/no-go verdict lands here too,
including if it says the claims column lost.

## 2026-11-16 — Fair local-model rerun completed, including repetitions

Parent verified all raw trial reports, their requested/attempted counts,
terminal teaching states, task and collection checks, and empty error lists.

| Batch | No-memory task passes | Memory task passes | Memory collection passes | Execution errors |
|---|---|---|---|---|
| Expanded set, one trial | 2/9 | 9/9 | 9/9 | 0 |
| Four-scenario subset, three fresh trials | 1/12 | 12/12 | 12/12 | 0 |

The subset is report-naming, changed-rule and both opposing projects. Its
memory results were 4/4 in each fresh trial, with control 0/4, 0/4 and 1/4.
Changed-rule checks establish the old rule before correction, supersede all
established old claims and leave only the new standing rule active. Each
opposing project has its own active convention, the other convention is
present in the shared store, own-scope delivery actually occurs and no foreign
scope is delivered. The full trial also passes one-off exception, irrelevant
memory and tool-evidence trust checks. The separate changed-rule smoke passed
with and without memory; it is not pooled into either denominator above.

Full: eval/.sandbox/run-1794872065318604373-325610/results.json.
Repeated: eval/.sandbox/run-1794873563806443250-358746/results.json.
Supervisor: eval/.sandbox/durable-1794871598411867092/status.json.

The supervisor finished completed, phase3_pass=true, stopped its own model
and exited successfully. About 37.73 GiB remained free. The producer's full
and repeated batch status is fail because of control task failures, not an
execution error. All isolated configs remain local/custom with no fallback,
built-in memory disabled and equivalent confined file tools. Previous failed
and interrupted trials are retained separately, not repaired or pooled.

This establishes repeatable behavior in this small synthetic sandbox. It
does not establish statistical significance, representative real-project
improvement, or causal use of a particular delivered claim. Phase 4 retrieval
pressure and Phase 5 real-project shadow evaluation remain unrun. Post-repair
Phase 3 integration sign-off is still pending; no live rollout is justified.

## 2026-11-16 — Harness capability failures are not a memory score

The post-scope-fix reruns did not establish memory effectiveness. One full
trial ran out of disk because each isolated Hermes home provisioned its own
dependency tree. Several teaching sessions also reached the 25-tool-turn
guard while trying to rename files. Inspecting the actual recorded tool
manifest established that Bonsai was given replace-only patch, not V4A file
deletion; shell access was deliberately unavailable. Guidance in SOUL.md was
also suppressed by --ignore-rules. These are harness defects, not evidence
that Bonsai cannot retain a learned rule. Preserve those runs as invalid
comparisons rather than pooling them with valid outcomes.

Both experimental arms now receive the same narrowly confined rename_file
and delete_file tools from a dedicated stdio MCP server. No terminal or
write-memory tools were added. Exact roots and toolsets, traversal/symlink
refusal, no-overwrite behavior and real protocol-level operations are tested.
Neutral capability guidance is explicitly preloaded as a job-local skill;
hidden house rules remain absent. An independent review approved the
confinement with limits; its audit gap was fixed with flushed attempt records
and paired success/error records, including rejected calls. Audit unavailability
refuses before mutation. Relevant read-only configuration assertions were
strengthened. Full scratch gate: 284 passed, 2 skipped (live-store-dependent
test_mcp_sandbox.py excluded); whitespace check clean.

The changed-rule smoke at
eval/.sandbox/run-1794871600477356276-318443/ subsequently passed. Bonsai successfully invoked
rename_file for the first correction; trusted audit and disk readback confirm
the original filename is gone and the replacement report exists. This verifies
the formerly impossible operation; the completed memory checks and repeated
outcomes are reported above. Shared package cache and a 10-GiB disk reserve
were active throughout; all prior artifacts are preserved.

## 2026-11-16 — Expanded memory sandbox exposed scope widening

Nine scenarios, one completed trial: independent task outcomes control 2/9,
memory 9/9; combined task and collection checks memory 6/9; infrastructure
errors 0. Artifacts: `eval/.sandbox/run-1794837793542577352-153992/results.json`.
Do not summarize this as nine successful memory scenarios: report naming became
a global `self` claim, then reached both opposing-project scopes. The three
collection failures correctly expose that contamination. Changed-rule,
one-off exception and tool-forgery checks passed in this trial. Rechecking the
changelog artifacts against the expanded 48-case interpreter kept the original
control failure and memory pass.

The writer routed every judge-labeled `preference` into `self`, even when the
human correction explicitly said “this project.” Four deterministic regression
cases failed before a conservative evidence-based scope guard was added.
Personal preferences can still be global, but automatic widening now requires
first-person user evidence without explicit project-local qualifiers in the
source or distilled claim. This English-language guard is not a general proof
of semantic scope correctness. Ambiguous wording is kept local. Independent
Codex review approved the mitigation. Full scratch test gate: 266 passed,
2 skipped (live-store-dependent test file excluded), diff whitespace check clean.
The opposite-project checker now requires actual own-scope delivery as well as
absence of foreign delivery. A clean full run and three repeated subset trials
are in progress; no post-fix model result is established yet.


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

---

## 2026-08-08 — Teacher bake-off: the extractor works, the scoreboard does not

GPU authorised. 27B launched via `run-qwen.sh` (thinking) and then `llm qwen3.5`
with `--chat-template-kwargs {"enable_thinking":false}` for no-think, per the memory
note — helper scripts untouched.

### Mode timing, finally measured on a structured-output task

| mode | secs/passage |
|---|---|
| thinking | 189 |
| no-think (v1 prompt) | 16.4 |
| no-think (v2 prompt) | 6.9 |

~11-27x, wider than the 6x measured on tagging. Quality between modes is still
unmeasured — the run below is no-think only, and that limitation stands.

### Prompt v1 -> v2

v1 produced 13.25 claims/passage with **85% labelled `fact`**, including 14 facts
from a passage the user had marked `hypothesis` — Risk §10.1 exactly. v2 narrowed
`fact` and capped extraction at 5: claims/passage fell to 4.34 and latency to 6.9s.

But the kind collapse only **moved**: everything became `observation`, the new
stated default. The 27B is anchoring on whatever the prompt names as default rather
than discriminating. That is worth knowing before any fine-tune is designed around
kind labels.

### The free scoreboard does not work, and the mapping was mine

Scored 38 stratified labelled passages: contains 0.658, dominant 0.289, with
`decision` the worst at 0.333. Reading the disagreements showed **the model was
right and the mapping was wrong**. Two passages labelled `decision` by my mapping:

> "All 4 subtasks complete: snapshot documentLayer + dossierCapsules... Essay
> generation pending a valid OpenRouter key."
> "Added BlogHomeButton client component ... renders it as persistent chrome on both
> blog index and post routes."

Those are reports of work done — observations. `resolution -> decision` was my
invention: a resolution *closes* a ticket, but a resolution *note* is a work report.

Correcting it makes the metric useless in the other direction: ~85% of the labelled
population becomes `observation`, which is also the extractor's default, so
agreement would be high and measure nothing. And `hypothesis` — the distinction that
decides whether "should homology ship?" is answered correctly — has **one** labelled
example in the entire corpus.

**So the free second scoreboard, which PLAN §P0.5 promised and which I argued for
again one turn earlier as the reason to scrap hand-grading, cannot measure kind
classification on this corpus.** The ticket vocabulary and the claim-kind vocabulary
are not the same ontology, and assuming they were was a third instance of building a
measurement without checking what it measures.

What survives: extraction is mechanically sound — 0 errors, 0 parse failures, 4.3
claims/passage, ~7s each. Kind accuracy is unmeasured, and honestly so.

---

## 2026-08-09 — PHASE 0 VERDICT: does not pass, and the gate was mis-specified

Teacher run complete: 1,406 prose events, **6,253 claims, 0 failures, 0 parse
errors**, 2 h 23 m at 6.1 s/event on the 3090 alone. Store now holds 11,666 claims
(4,141 structured + 7,525 extracted), all embedded.

| | rg | chunk-RAG | claims |
|---|---|---|---|
| nDCG@10 | 0.291 | **0.667** | 0.554 |
| mislead-rate | 0.333 | **0.333** | **0.333** |

Prose extraction moved claims from 0.225 to 0.554 — a large gain, and still a loss.

### Against the stated gate (PLAN §1)

1. beat `rg` — **pass** (0.554 vs 0.291)
2. beat chunk-RAG — **FAIL** (0.554 vs 0.667)
3. core names no source vocabulary — **pass** (zero commits touched `core/` across
   six adapters)

**Phase 0 does not pass.** Per the plan, that means stop and rethink rather than
proceed to Phase 1.

### But the gate could not have been passed, and that is the finding

    status: active = 11666      valid_to set = 35
    superseded_by = 0           conflicts = 0

**Nothing is superseded. There are no conflicts.** `claim_search` filters
`status='active'`, which excludes nothing, so the retrieval under test was *atomised
claims versus chunks* — with the entire validity layer absent.

That layer is Phase 2 by the plan's own sequencing. So Phase 0 was built to test the
design's central thesis using only the half of the machinery that does not contain
it. The thesis is *"atomic claims **with provenance and validity** beat chunks with
similarity"*; what was measured is *"atomic claims beat chunks"*, and that is a
different and much weaker claim — one there was never good reason to believe.

Atomisation alone **should** lose. A chunk is 800 characters of context and embeds
richly; a claim is one sentence and embeds narrowly. Folding both back to source
records, the chunk wins on similarity almost by construction. Claims cannot earn
their keep through atomisation; they can only earn it through knowing what is no
longer true.

The identical 0.333 mislead-rate across all three columns is the same fact stated
directly: with no supersession, a claim graph is exactly as misleading as grep.

### The one durable win

**q005 — 0.000 for both baselines, 0.431 for claims.** The metric question neither
baseline can answer at all, because a table of numbers carries no semantic signal.
Adapter C turns bench tables into textual claims and makes them retrievable. That
gain comes from *modelling*, not from retrieval cleverness, and no amount of better
chunking reaches it.

### What this actually says

Not "the design is wrong". It says **the Phase 0 gate was the wrong experiment**: it
put the proof after the thing it was meant to justify. A corrected gate measures
mislead-rate with minimum-viable supersession implemented — which is a Phase 2
capability, so either Phase 2 moves earlier or the gate moves later. That is a
scoping decision for the user, not for me.

---

## 2026-08-09 — Supersession and capture: claims lead, on a harder question set

Built the validity layer the Phase 0 verdict said was missing. Four rules attempted,
**two were wrong and reverted**, and the reverts are the useful part.

### What worked

| rule | effect |
|---|---|
| `revision_removal` | 35 claims ended by the git commit that deleted their section |
| `near_duplicate` (cosine ≥ 0.94) | 865 restatements folded away, freeing rank for distinct claims |
| `trust_correction` (assert-scoped) | 18 stale claims ended by one captured correction |
| `conflict_candidates` (0.80–0.94) | 904 conflicts **opened, not resolved** — the band where a machine cannot tell a changed mind from a different remark |

### Two rules that were wrong

**`metric_restatement` — reverted.** Superseding an earlier bench reading with a
later one cost q005 its whole score (0.431 → 0.000). "v1 recall was 0.596 on 22 May"
does not stop being true when a later run reports 0.509; it is a dated measurement,
not a claim about current state. A later run *adds* an observation. Same shape as
capability-vs-practice (§0.9): only claims about how things **are** can be
superseded, and nobody writes those about metrics.

**`trust_correction` keyed on trust tier — reverted.** One captured correction
superseded **2,025 claims**, because bench measurements also carry `human` trust and
the rule read them as corrections. Rescoped to claims captured through `assert`: what
licenses the rule is the deliberate act of stating that something changed, not the
trust tier alone. 3,294 → 18.

### The scoreboard

| | rg | chunk-RAG | claims |
|---|---|---|---|
| nDCG@10 | 0.218 | 0.500 | **0.535** |
| mislead-rate | 0.500 | **0.333** | **0.333** |

**Claims lead on nDCG for the first time — but the comparison is not clean.** q003
and q009 only became scoreable once `assert` gave them a gold record, and they are
the hardest questions in the set, so every column fell. The earlier 0.587 vs 0.667
and this 0.535 vs 0.500 have different denominators and should not be read as a
gain of one and a loss of the other.

What is clean, because no denominator change touches it:

- **q005: 0.000 for both baselines, 1.000 for claims.** A metric question that
  embedding retrieval cannot reach at all, answered perfectly once bench tables
  became claims and duplicates stopped crowding them.
- **q009: 0.000 for both baselines, 0.387 for claims** — reachable only through the
  captured correction.

### Capture works; supersession has not yet cashed it

Mislead is still 0.333 for claims, tied with chunk-RAG, and q003/q009 remain at
1.000. The correction is in the graph and retrievable, and eight stale documents
still outrank it. Eighteen supersessions were not the eighteen that mattered.

That is the honest state: **the capture path demonstrably adds an answer that no
compiler could recover, and the supersession layer does not yet reliably promote it
over the stale record.** The 904 open conflicts are where that gets decided, and
resolving them is human work the design already budgets for.

---

## 2026-08-09 — Every conflict gets a lean; and one bad label cost the same score three times

904 open conflicts handed to a human is not a review queue, it is a refusal to
decide. `claimbase resolve` now leans on all of them, applies the confident leans,
and ranks anything weak by impact so a person starts where it matters.

    2299 conflicts resolved, 592 claims superseded, 0 requiring review
      recency_replacing        1809
      observations_accumulate   252
      trust_asymmetry           238

Leaning rules in precedence order: trust asymmetry (a human capture beats a model's
reading of a doc — `trust.outranks()`, finally used for what it was written for),
then kind precedence (a hypothesis never displaces a fact), then recency among
replacing kinds, then coexistence for observations. Weak leans are recorded as the
proposed answer and surfaced, never silently enacted; the impact ranking is how
crowded the older claim's neighbourhood is, since a stale claim with many near
neighbours dominates retrieval and an isolated one misleads nobody.

### The lesson underneath it

q005 lost its entire score **three times, through three different rules** —
`metric_restatement`, then `trust_correction` keyed on trust tier, then
`recency_replacing`. Each time the fix was to constrain the rule. Each time it came
back through another route.

The fault was never in the rules. **Adapter C labelled bench measurements `fact`**,
and every recency rule correctly concluded that a later fact displaces an earlier
one. A measurement is a report of one occasion — the definition of `observation`,
and the reason observations accumulate rather than supersede. One wrong label at the
source, three symptomatic patches, before the cause was seen.

Relabelled at source and in the store: 140 claims, and the third rule became safe
without being weakened.

### Scoreboard

| | rg | chunk-RAG | claims |
|---|---|---|---|
| nDCG@10 | 0.229 | 0.500 | **0.535** |
| mislead-rate | 0.500 | **0.333** | **0.333** |

q005 back to 1.000 where both baselines score 0.000. Mislead still tied at 0.333,
pinned by q003 and q009 — the captured correction is retrievable and eight stale
documents still outrank it. That is the open problem, and it is now the *only* one
the conflict machinery has not addressed.

---

## 2026-08-09 — Ranking on epistemic standing: the thesis, demonstrated

| | rg | chunk-RAG | claims |
|---|---|---|---|
| nDCG@10 | 0.227 | 0.500 | **0.579** |
| mislead-rate | 0.500 | 0.333 | **0.000** |

**Claims lead on both axes, and mislead-rate is zero.** q003 and q009 — the
auto-promote pair that had been pinned at 1.000 mislead through every previous
attempt — now score 1.000 nDCG and 0.000 mislead.

### What actually fixed it

Not more supersession. `recall()` now ranks on standing rather than resemblance:

    score = cosine x (1 + 0.2 x trust) x (1 + 0.5 x currency) x (1 + 0.5 x settled)

The captured correction wins its question with a *lower* cosine than the documents it
beats — one claim against eight, outnumbered and right. Similarity alone can never
produce that ordering, which is the clearest statement of why a claim graph is not a
vector store: being outnumbered is not being wrong.

`currency` applies only to perishable kinds (practice, decision, plan, task). An
observation reports one occasion and does not lapse, so recency is not evidence about
it — the same distinction that took three rules to learn.

### Two corrections made along the way

**Trust was over-weighted.** At 0.6 it let provenance overturn large similarity gaps,
buying the stale-answer questions at the cost of ordinary lookups (0.535 → 0.459).
Trust is evidence about whether to *believe* a claim, not whether it *answers the
question*, so it was demoted to a tie-breaker at 0.2.

**The eval was measuring a copy of the system.** `baselines.py` had its own retrieval
implementation, so any ranking change had to be made twice to show up and a
divergence between them would have been invisible. It now calls the shipped
`claimbase.recall`.

### The caveat that matters

The weights were adjusted twice while watching this scoreboard. **Eight scored
questions cannot support tuned magnitudes** — that is fitting to noise as much as to
signal, and q005 and q007 were casualties of the final adjustment (1.000 → 0.000
each). The *ordering* the weights encode is defensible on its own terms; the numbers
are not validated and a larger question set is entitled to overturn them.

The honest headline is the mislead-rate, not the nDCG: 0.000 against 0.333 is
categorical rather than marginal, and it is the one result that does not depend on
weight magnitudes at all.

---

## 2026-08-09 — Answer-level bench: claimbase 3C+1P, grep 1C, and a regression I caused

nDCG asks whether the right record ranked highly. An agent asks what the answer is,
and the two come apart precisely where this project claims to be useful. So: same
model, same turn budget, same questions, two toolsets — `recall` over MCP versus
ripgrep plus file reads. Blind, order-randomised judging against the gold answers.

| | CORRECT | PARTIAL | WRONG |
|---|---|---|---|
| claimbase | **3** | 1 | 5 |
| grep | 1 | 0 | 8 |

Claimbase wins clearly and **both are bad in absolute terms**. The tally is the least
interesting output; three specific results are worth more.

### q004 — a regression the ranking work introduced

*"Why is `staged_edges.status` still pending after an auto-promote run?"* is a
**capability** question: how does the tool behave. The agent answered *"because
auto-promote was discontinued in July"* — true, irrelevant, confidently wrong as an
answer.

The currency boost that won q003 and q009 promotes the captured practice-change so
strongly that it hijacks questions which are not about currency at all. This is the
direct cost of mislead-rate 0.000, and it is the capability-vs-practice distinction
appearing for a fourth time — now at the answer layer rather than in a supersession
rule.

**The fix is not a smaller weight.** Currency is evidence of relevance *only when the
question is about the current state*. A question about mechanism should not receive
a currency-boosted practice claim at all. Ranking needs to condition on what is being
asked, which is a real piece of design rather than a tuning knob.

### q001 — the judge is weak

The answer reached the right conclusion and correctly identified the June reading as
a measurement artifact, then garbled a number. That is PARTIAL by the rubric; the
judge said WRONG. **The same 27B answers and judges**, and it is mediocre at both, so
these tallies carry real noise and should not be quoted as precise.

### q009 — the result grep cannot reach

*"Should the 0.85 tier be auto-promoted?"* — claimbase CORRECT, grep answered *"the
evidence does not contain any information regarding a 0.85 confidence edge tier."*
No file states the answer, so no amount of searching finds it. That is the capture
path paying off end to end, through the transport an agent actually uses.

### What this bench is worth

It escapes the tuning trap — a wrong answer is unambiguous where nDCG is not — but it
inherits a weak judge and still rests on nine questions. Its value here was
diagnostic: it found a regression that every retrieval metric scored as an
improvement.

---

## 2026-08-09 — Intent-conditioned ranking, and the limit of a 9-question bench

### The fix q004 asked for

Currency now scales by what the question is *asking*, classified without a model
(DESIGN §1.7, thin runtime):

| intent | currency | favoured kinds |
|---|---|---|
| mechanism (*why is / how does*) | 0.0 | capability, fact |
| current (*still / currently / should we*) | 1.0 | practice, decision |
| historical (*was / in May / used to*) | 0.0 | observation, fact |
| neutral | 0.8 | — |

Mechanism is tested first on purpose: *"why is X **still** pending"* contains a
currency marker and is not a currency question, which is exactly how q004 went wrong.
Neutral sits near current rather than halfway — an unmarked question about a live
project implicitly means now; at 0.5 the stale reading of q001 won.

Retrieval: **nDCG 0.679, mislead 0.000** against chunk-RAG's 0.500 / 0.333. Best on
both axes.

### The interface bug underneath it

q004 still failed after the ranking fix, and for a reason worth keeping: the agent
searched `"staged_edges.status pending after auto-promote"` — **it had stripped "why
is" and "still"**, the exact tokens intent classification reads. Intent lives in the
user's question; ranking was seeing the agent's keywords.

The tool was implicitly advertising itself as a keyword index. It now asks for the
question in full and says why, with an `intent` override available. A claim graph
wants the sentence, not the search terms — and that is an interface property no
retrieval metric would ever have surfaced.

### The bench has hit its resolution limit

Three agent runs, same 9 questions:

| run | claimbase | grep |
|---|---|---|
| 1 | 3C 1P 5W | 1C 0P 8W |
| 2 | 4C 1P 4W | 1C 1P 7W |
| 3 | 3C 3P 3W | 1C 2P 6W |

**The gap against grep is robust** — claimbase 6-of-9 not-wrong versus grep 3-of-9 on
the best run, and it never lost a run. **The differences between my own ranking
versions are not measurable here**: q005 went WRONG → CORRECT and q007 CORRECT →
WRONG between runs with no relevant change in between.

At n=9, with one 27B both answering and judging, variance swamps the effect being
tuned. Further weight adjustment against this bench would be fitting noise, and the
right response is to stop rather than to keep going and call the movement progress.

What would raise the ceiling, in order: more questions (harvested from real MCP use,
not synthesised), a judge that is not the system under test, and repeated runs per
condition. Until then the defensible claims are the two categorical ones — mislead
0.000 versus 0.333, and answers grep cannot reach at all.

---

## 2026-08-12 — Entity resolution, linking, and the ranking calibration

Extraction rebuilt (run `8f6a7e99`, 8,366 claims, 3h23m). Store: 12,778 claims,
5,138 entities, 8,254 claim-entity links.

### The calibration

| | rg | chunk-RAG | claims (before) | claims (after) |
|---|---|---|---|---|
| nDCG@10 | 0.150 | 0.278 | 0.512 | 0.452 |
| **mislead-rate** | 0.182 | 0.273 | 0.273 | **0.091** |

The entity signal cuts mislead-rate by two thirds — three misleading questions down
to one — and costs nDCG. That is the right trade for this system: nDCG asks whether
a thing was findable, mislead-rate asks whether the answer was *wrong*, and a
confidently stale answer is the failure this project exists to prevent.

Claims now mislead on **one** of eleven scored questions against chunk-RAG's three.

Entity matching is lexical against the alias table, deliberately. Embeddings put
`retriever.ts` and `retriever.py` almost on top of each other, which is why q013
failed; lexical identity is the signal similarity discards, and the alias table is
what lets it survive path variation.

### Three bugs the rebuild exposed, all mine

**`TRUNCATE entities CASCADE` destroyed the claims table.** TRUNCATE follows every
foreign key regardless of its ON DELETE action, and `claims.subject_id` references
entities. 8,012 extracted claims — a second three-hour GPU run — lost to what was
meant to be a rebuild of a derived lookup table. `subject_id` is now ON DELETE SET
NULL, the reset path uses DELETE, and every destructive command takes a verified
snapshot first.

**Capture was not rebuildable.** `assert` events survived, but no adapter produces
their claims, so nothing regenerated them — and the one answer a compiler can never
recover was also the one it could not restore. That single missing claim accounted
for the entire apparent regression: mislead 0.636 with it gone, 0.273 with it back.
Captured facts now rebuild from their events like everything else.

**A test was writing to the live store.** The MCP sandbox probe called
`assert_claim` with writes enabled against the real database and left the rows
behind; three copies were sitting in the corpus. Now marked and purged by a fixture.

### What is still wrong

q016 fell from 0.901 to 0.000 and q014 from 0.315 to 0.000 — the entity boost
promotes claims that name a file over claims that answer the question, when the
question happens to name a file. That is the same shape as the currency regression
(over-weighting one signal until it hijacks unrelated questions), and it says the
entity boost should be conditioned on intent too, not applied flat.

q013 remains 0.000 for claims and 0.387 for rg despite being the question entity
resolution was built for. The entities are correctly separated now; what is missing
is a claim that states which one production uses, and the corpus does not contain
one. Resolution made the distinction *representable*, not *answerable*.

## 2026-08-21 — The reviewer eval, and the ranking's turn to be wrong

The first sustained live traffic: the hermes reviewer (local Qwen3.8) ran ~42
mechanism-phrased queries over the whole guru workbook through the MCP server,
every one logged with its full response. Grading them against the store settled
the standing attribution question: **the compiler is mostly fine; retrieval was
the bottleneck.** Nearly every miss had active, *embedded*, on-target claims
that lost the top-5 — the corpus-toml rule (missed under two phrasings, cosine
ranks 1–2 for the query), node-15 publish, node-01/04, `--respect-reviewed`.
Only three true supply gaps surfaced: the AGENTS.md GPU rule (extraction drop,
now `assert:gpu-release`), node-08's mechanism (5 thin claims vs node-03's 24+),
and the drift-remedy sentence.

What the traffic exposed, and what shipped for it (commit `recall:` this date):

- **Phrase sensitivity** — vector-only candidates missed distinctive-phrase
  matches → lexical OR-of-lexemes leg over a new tsvector index (migration 007),
  fused into one pool.
- **Doc-naming queries** — "what does docs/ingest/03-acquire.md say", "workbook
  node 3": content claims don't repeat their own path → provenance candidate leg
  + W_REF, with node-number → filename translation.
- **Scaffold crowding** — "documents §X" claims took 7 of 8 slots on a
  failure-modes query → penalized (0.45×), not excluded.
- **Cross-revision near-dups** — same fact from adjacent SHAs both active,
  twice in one top-5 → token-Jaccard collapse at result time.
- **Boosts as vetoes** — a linked cos-0.69 claim buried an unlinked cos-0.83
  one; the q016/q014 note above called this shape early → W_ENTITY 0.8→0.55
  plus a cosine-leader guarantee: the two most similar claims always make the
  cut, standing orders everything above them.
- **timeline was ILIKE-only** — "edge review node 14" returned empty against a
  corpus full of node-14 history → semantic fallback, `matched_by` in the
  response.

Scoreboard: original 16 questions nDCG 0.407 → 0.43 with mislead 0.273 →
**0.000**; the gold set grew to 27 with 11 regression questions taken straight
from the reviewer log (q017–q027), and the expanded set lands at 0.488 / 0.000.
The query log did exactly what it was built for: real questions from a real
agent turned into the regression set the harvest could not supply.

### What is still wrong

q023 (chunk-id as citation) stays 0.000 — genuine vocabulary mismatch between
question and claim, the class no lexical trick fixes; it wants either a better
embedding or a captured claim that says it in answer-shaped words. Claims from
banner-retired docs stay active and unmarked (retirement leaves no git deletion
for valid_to to key on). Node-08 remains thin in the store; that is extraction
depth, not ranking, and a targeted re-extract of the readability-gate doc is the
fix. And the recall weights have now been adjusted while watching this larger
scoreboard — 27 questions is better than eight, but the docstring's honesty
clause still applies.


---

## 2026-11-16 — Twelve weeks of silence, and what trigger selection found

Written while starting the memory-layer branch ([GOALS.md](docs/GOALS.md)). Two things were
measured before any of it was built; neither is a scoreboard.

### Nobody has asked the store anything since August

`claimbase-db` exited two months ago and was never restarted. The query log
holds 75 calls in total: 73 on 2026-08-21 (the reviewer eval above) and 2 on
2026-08-26. The nightly compile has not run either: the crontab entry is
there, no cron daemon is active on this machine, and `logs/cron-compile.log`
was never created.

Why the silence, checked against the harnesses' own records rather than
guessed:

| harness | wired | told to ask | claimbase calls, ever | sessions since 2026-08-26 |
|---|---|---|---|---|
| hermes `reviewer` | yes | yes — SOUL.md: "ask the compiled memory first" | 224 tool messages | 0 (last 2026-08-21) |
| hermes `guru-dev` | yes | yes, same section | 4 | 3, all on 2026-08-26 |
| hermes `driver` | yes | no | 0 | 0 (last 2026-08-20) |
| hermes default profile | yes (root `config.yaml`) | no | **0** | **192** |
| Claude Code | no | — | 0 | daily |

Two things are visible, and they are separate.

**Wired and told to ask, an agent asks.** The reviewer did, 224 times. **Wired
and not told, it never does**: the default profile has had the tool available
for 192 sessions since August and has not called it once. (Of the 21 recent
default sessions that record their tool list, none lists a claimbase tool;
whether the server fails to load there was not checked, so "available" may be
generous.) Retrieval quality cannot matter to a caller that does not call.

**And the callers that did ask stopped running.** The work moved to the
default profile and to Claude Code; the store's absence went unnoticed because
nothing still in use depended on it. Memory was attached to five profiles
instead of to the work — the RFC's own motivation, demonstrated on its
predecessor.

That shapes the branch. `brief` is one call at session start that asks nothing
of the agent's judgment, so an unprompted agent still gets memory; projects
resolve from the working directory, so wiring is per harness and not per
profile; and `usage report` opens with an activity line that reads zero when
zero is the truth.

One gap in the log itself: responses carried no claim ids, so it could say what
was asked and never which claims were used. Fixed going forward; the 75
historical lines are matched to claims by exact text where the claim still
exists.

### Selection, run over 145 real hermes sessions (no model)

`sessions.segment` over the 145 most recent hermes sessions with at least two
user messages — 50,698 turns. Three passes:

| pass | user-role turns | corrections | decisions | tool failures |
|---|---|---|---|---|
| first rules | 1,460 | 105 | 65 | 191 |
| harness notices removed | 1,054 | 36 | 31 | 191 |
| two rules tightened | 1,054 | 30 | 17 | 191 |

**406 of 1,460 "user" turns were not the user** (28%). Hermes writes bracketed
notices into the user role — `[ASYNC DELEGATION BATCH COMPLETE …]`,
`[CONTEXT COMPACTION — REFERENCE ONLY]`, `[System: …]` — and a subagent's report
is dense with "don't" and "instead". They accounted for 69 of the first 105
corrections. This matters past selection noise: a user turn is the one kind of
evidence allowed to back a PR that merges against a human claim, so text the
harness put in that role would have carried human authority. Role attribution
is now structural *and* filtered, and the filter is a test.

**Tool failures outnumber every user trigger four to one**, and read as
transient (a build error, a missing path). Judging each would spend most of the
model budget on the lowest-value trigger. A failure is now judged only when it
is similar to something the store holds — the RFC's own wording, "implicates a
claim the agent acted on" — and otherwise recorded as an episode and left.
The threshold (cosine 0.6) is a guess.

**The remaining triggers are sparse: 47 across 145 sessions.** One in three
sessions has a correction or a decision at all. Need-driven collection will be
slow to fill a store, by design; whether it fills it with better claims than
extraction did is the question `yield per trigger` exists to answer, and it
cannot be answered until sessions are submitted and a judge has run.

### Not measured

- **The judge.** Its prompt has run only against a scripted stand-in. Durable
  rate per rule, and whether its claims are self-contained, are unknown.
- **Every threshold in `writer.py`** — duplicate 0.92, promote 0.86, failure
  0.6, use-overlap 0.5. Chosen by argument. `claimbase replay` is the
  instrument for tuning them.
- **Correction recall.** The selector's precision was read by eye from samples;
  what it misses was not looked at.
- **Stable claim ids against the real corpus.** The import path now keeps
  unchanged claims in place (GOALS decision 11). Tested on a scratch database,
  not on the 11.6k-claim store, which was down.

---

## 2026-11-16 — Hermes + Bonsai: a correction survived a fresh session

`eval/sandbox_hermes.py run`, Ternary-Bonsai-2-27B-PQ2_0, 65,536-token
context, RTX 3090 only. Completed in approximately nine minutes, exit 0.
The same local model acted as working agent and writer's judge. Three
scripted corrections; fresh project copies and fresh sessions for probes.
Hermes's own memory and user profile were disabled in both arms, ambient
project rules excluded, and file access confined to the current working copy.
Only `recall` was exposed over MCP; transcript submission was hook-owned.

| House rule | No memory | Claimbase brief |
|---|---|---|
| Reports use `reports/rpt_YYYYMMDD.md` | fail | pass |
| Overrides go in `config/local.toml`; generated defaults stay unchanged | pass | pass |
| Code changes get an Unreleased changelog entry | fail | pass |
| **Total** | **1/3** | **3/3** |

Checked the output files, not the agent's assurances. The report contained the
requested skipped-tagger explanation; the config probe set `max_retries = 5`
in local overrides while defaults retained 3; the code probe defined
`truncate` and added its changelog entry. All nine Hermes sessions finalized.
All six captured teaching/probe sessions were stamped `sandbox`; no terminal
or built-in memory tool was called. Brief logs show claim counts
`0, 0, 0, 3, 3, 3`: three empty teaching briefs, then three populated probes.
The writer produced the three intended standing practices from the actual
user corrections. No hand-authored claims or explicit helpful feedback were
inserted into this completed run.

### Integration defects the first real run exposed

Earlier attempts were discarded, not pooled with this result.

- Hermes's coding posture overrode the config's default file-only toolset.
  The runner now pins `--toolsets` explicitly and excludes ambient rules.
- A one-shot CLI left a home-scoped gateway alive; deleting/reusing its home
  caused an empty SQLite store / missing `sessions` table. Each experiment now
  has a unique directory, and session lookup tolerates pre-schema startup.
- Write-only confinement let the agent read the runner or other scenarios.
  The guard now confines reads and writes to `sessions.cwd`, including V4A
  patch paths, and fails closed.
- The finalize hook's `cwd` was the gateway checkout, not the work. Capture
  also ignored `CLAIMBASE_PROJECT`, and the Hermes reader preferred the git
  root over the actual cwd. Sessions landed in `hermes-agent`, leaving the
  intended sandbox brief empty. All three scoping mistakes are fixed; a
  regression test exercises the real SQLite-to-spool CLI path. The scored
  comparison above is a complete fresh rerun after those fixes, not repaired
  data from the rejected attempt.
- Exposing the whole MCP server let the model submit its own summary. The
  experiment now exposes only recall, so the writer sees harness transcripts.
- The launcher interpreted the agent environment's `TEMP` scratch path as a
  numeric temperature. `TEMP=1.0 LLM_GPUS=0 llm bonsai` avoids that collision.

### The usage proxy failed even though the task outcomes passed

The final report recorded **zero inferred uses**, **100% miss rate** for two
nonempty recalls, and 0% yield for correction-derived claims. These are not
measurements of this experiment's task success. Applying `attribute_uses`
directly to the archived probe transcripts reproduced the zeros: the best
single-turn overlap with each relevant rule was 2/9 distinctive words for
report naming, 4/10 for config overrides, and 4/9 for the changelog rule.
All miss the fixed 0.5 threshold, despite the verified artifacts. The report
name also instantiates a date template rather than repeating its literal
`YYYYMMDD` token. No threshold was tuned after observing this result.

Separately, `usage.measures` associates recall coverage/use by project and
elapsed time rather than requiring an exact session match. Concurrent sessions
can therefore affect the classification. Usage-derived miss/yield numbers are
not an acceptance gate until attribution is calibrated against artifact-level
outcomes and session joins are tightened. Dead weight and leak rate were both
0% in this single-project fixture; that does not validate cross-project
isolation against adversarial inputs.

### Limits and artifacts

This is one synthetic, three-case integration run, not statistical evidence of
general improvement, a real-session judge evaluation, or the daily-use gate.
The config rule was already followed in its control; the incremental wins
were report naming and changelog discipline. No owner gate was crossed: no
live-store startup, migration, compile, or normal-profile rewiring.

- Result: `eval/results-sandbox-hermes.json` (generated, gitignored).
- Run directory: `eval/.sandbox/run-1794822231257260818-87995/`.
- Full CLI transcript: that directory's `logs/hermes.log`; hook responses:
  `logs/mcp-queries.jsonl`; normalized transcripts: `spool/done/`.
- Five new regression tests pass. Broader isolated-HOME suite:
  `171 passed, 2 skipped`, excluding `tests/test_mcp_sandbox.py`, whose existing
  checks depend on the live-store setup. Skips: absent live memory scope and
  missing PR cache. `git diff --check` passes.

