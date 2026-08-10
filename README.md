# claimbase

*Notes are a build artifact, not a source of truth.*

A compiled knowledge substrate. The source of truth is an append-only capture log;
a background compiler extracts atomic claims, tracks supersession, and emits a
bitemporal claim graph that agents query over MCP. Nobody gardens.

The design is in [DESIGN.md](DESIGN.md). What follows is what is actually built, and
what the measurements say — including where they say it does not work.

## Status: Phase 0, and honest about it

Compiled over the [guru](https://github.com/4-R-C-4-N-4/guru),
[guru-web](https://github.com/4-R-C-4-N-4/guru-web) and
[rellm](https://github.com/4-R-C-4-N-4/rellm) repos — 3,287 events, 11,667 claims,
14,360 edges, from six adapters.

Against two baselines on nine gold questions:

| | ripgrep | chunk-RAG | claims |
|---|---|---|---|
| nDCG@10 | 0.229 | 0.500 | **0.679** |
| mislead-rate | 0.500 | 0.333 | **0.000** |

`mislead-rate` is the fraction of questions where a *superseded* record outranks
every correct one. It is the number this project exists to move; nDCG mostly measures
whether the thing was findable at all.

**These rest on nine questions and ranking weights adjusted against them.** That is
fitting to noise as much as to signal. The two claims that survive scrutiny are
categorical rather than marginal: the mislead-rate does not depend on weight
magnitudes, and some answers are unreachable by search at any quality — see below.

An answer-level bench (same model, same turn budget, `recall` versus ripgrep + file
reads, blind judging) ran three times: claimbase 3/4/3 correct, ripgrep 1/1/1. The
gap is robust; differences between successive ranking versions are not measurable at
that sample size, which is why tuning stopped.

## What it does that search cannot

**Knows what stopped being true.** A practice ends, eight documents go on describing
it, and similarity gives the crowd the win. Ranking accounts for provenance,
currency and whether a claim superseded others, so one correct claim can outrank
eight stale ones — it wins with a *lower* cosine than the documents it beats.

**Answers what was never written down.** The sharpest failure in a real corpus is
not contradiction, it is silence: a practice abandoned with no record of the
abandonment. No compiler recovers that. `assert` captures it, and the answer becomes
reachable — in testing, ripgrep replied *"the evidence does not contain any
information regarding..."* to a question claimbase answered correctly.

**Reads tables.** A benchmark report is numbers, which carry almost no semantic
signal; both baselines score 0.000 on metric questions. Compiled to claims, they
become retrievable.

## Design notes worth the detour

- **[The adapter seam](PLAN.md#2-the-adapter-seam)** — six adapters were written and
  `core/` was never touched. An abstraction with one implementation is not one.
- **Trust tiers** — adapters *declare* who authored a claim; core enforces what that
  permits. Agent-written prose cannot become a `fact`. Claims that outrun their trust
  are demoted rather than dropped, keeping the evidence and withholding the authority.
- **capability vs practice** — a tool that still works but is no longer used has not
  been falsified. Conflating the two cost the same test score three times through
  three different rules before the label at the source was found to be wrong.
- **[findings.md](findings.md)** — the running log, including every measurement that
  came out badly and several instruments that turned out to measure nothing.

## Running it

```bash
docker compose up -d                              # postgres + pgvector on 5433
docker compose exec -T db psql -U claimbase -d claimbase -f /migrations/001_init.sql
python -m claimbase import                        # compile a corpus
python -m claimbase embed                         # vectors (needs ollama)
python -m claimbase supersede && python -m claimbase resolve
python -m claimbase recall "is auto-promote still the promotion path?"
```

Extraction needs a local model server; everything else needs Postgres and Ollama.
Corpora are declared in [`corpora/*.toml`](corpora/) — named, and never derived from
the working directory.

For agent access see **[MCP.md](MCP.md)**. Read-only by default; writes are opt-in,
because a false claim written to the graph misleads every later session.

## Licence

MIT
