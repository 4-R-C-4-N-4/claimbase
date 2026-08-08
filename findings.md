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
