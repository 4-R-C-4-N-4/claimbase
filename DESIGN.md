# CLAIMBASE — A Compiled Personal Knowledge Substrate

*Working title. Alternatives: `ledger`, `stratum`, `sediment`. The name should signal "append-only geology," not "note-taking app."*

**One-line thesis:** Notes are a build artifact, not a source of truth. The source of truth is an append-only capture log; a background compiler extracts atomic claims, resolves entities, tracks supersession, and emits both a queryable temporal graph (for agents) and browsable views (for humans). Nobody gardens.

---

## 1. Design Principles

1. **Append-only capture.** The human never edits knowledge; they only add observations. All correction happens by assertion ("actually, X"), never mutation. This makes capture zero-friction and gives you perfect provenance for free.
2. **Claims, not documents.** The atomic unit is an assertion with a subject, content, timestamps, confidence, and provenance — not a page.
3. **Bitemporal by default.** Every claim carries *valid time* (when it was/is true in the world) and *transaction time* (when the system learned it). This is the single feature that kills the stale-notes problem, and no PKM tool has it.
4. **Supersession over deletion.** New claims mark old ones superseded. History is queryable ("what did I believe about the foundation design in March?").
5. **Contradiction is a first-class event.** When the compiler can't determine supersession order, it surfaces a conflict for human review. Silent coexistence of contradictory facts is a bug, not a feature.
6. **Gradual schema.** Structure is optional, incremental, and useful exactly where declared — the TypeScript model applied to knowledge. Schema-on-read is the default; schema-on-write is an opt-in per user or subdomain. Emergent types go through a review gate (open-vocabulary proposal → clustering → human approval → backfill; the guru concept-generation loop, generalized). Declared types skip the gate — the declaration *is* the gate. In no case does schema gain authority it hasn't earned: it never constrains extraction or rejects claims (§4.7).
7. **Fat pipeline, thin runtime.** Heavy inference happens in the background compiler. Query time is cheap graph traversal + vector lookup. Agents get fast, deterministic reads.
8. **Sovereign.** Local-first, git-native, plain-text capture, Postgres graph, local models for the inner loop. No cloud dependency in the core path.
9. **Views are compiled.** The "wiki" is a build output — regenerable, disposable, never hand-edited. Human browsing is a rendering concern, not a storage concern.

---

## 2. System Architecture

```
┌─────────────────────────────────────────────────────────────┐
│ CAPTURE LAYER (append-only, git-native)                     │
│  inbox/*.md, *.jsonl — notes, voice transcripts, chat logs, │
│  clipped web content, agent session transcripts             │
└──────────────────────────┬──────────────────────────────────┘
                           │ commit hook / watcher
┌──────────────────────────▼──────────────────────────────────┐
│ COMPILER (Python, batch + incremental)                      │
│  1. Segmentation & source normalization                     │
│  2. Claim extraction        (fine-tuned 7B, local)          │
│  3. Entity resolution       (embeddings + LLM adjudication) │
│  4. Temporal annotation     (valid-time inference)          │
│  5. Supersession / conflict detection                       │
│  6. Schema emergence        (tag proposal → cluster → gate) │
│  7. Index build             (pgvector + graph edges)        │
└──────────────────────────┬──────────────────────────────────┘
                           │
┌──────────────────────────▼──────────────────────────────────┐
│ STORE (Postgres, single node)                               │
│  events (raw capture, immutable)                            │
│  claims (bitemporal, provenance-linked)                     │
│  entities, entity_aliases                                   │
│  edges (typed relations between claims/entities)            │
│  conflicts (open contradictions awaiting review)            │
│  schema_types (emergent, versioned)                         │
└───────┬──────────────────────────────┬──────────────────────┘
        │                              │
┌───────▼───────────────┐   ┌──────────▼─────────────────────┐
│ QUERY API (thin)      │   │ VIEW COMPILER                  │
│  MCP server + HTTP    │   │  entity pages, timelines,      │
│  for agents/LLMs      │   │  digests → static md/HTML      │
└───────────────────────┘   └────────────────────────────────┘
```

---

## 3. Data Model

### 3.1 `events` — raw capture (immutable)

```sql
CREATE TABLE events (
  id            uuid PRIMARY KEY,
  captured_at   timestamptz NOT NULL,        -- transaction time origin
  source_type   text NOT NULL,               -- note | voice | chat | web | agent_session
  source_ref    text NOT NULL,               -- git path@sha, URL, session id
  content       text NOT NULL,               -- raw text after normalization
  content_hash  bytea NOT NULL UNIQUE,       -- dedupe
  meta          jsonb NOT NULL DEFAULT '{}'
);
```

Events are never updated. Reprocessing is always safe because everything downstream is derived.

### 3.2 `claims` — the atomic unit

```sql
CREATE TABLE claims (
  id             uuid PRIMARY KEY,
  event_id       uuid NOT NULL REFERENCES events(id),
  span           int4range,                  -- char offsets into event content
  subject_id     uuid REFERENCES entities(id),
  predicate      text,                       -- emergent-schema relation, nullable early
  content        text NOT NULL,              -- normalized atomic assertion
  embedding      vector(768),
  -- bitemporality
  valid_from     timestamptz,                -- when true in the world (inferred, nullable)
  valid_to       timestamptz,                -- null = still valid
  asserted_at    timestamptz NOT NULL,       -- transaction time (from event)
  -- lifecycle
  status         text NOT NULL DEFAULT 'active',
                 -- active | superseded | retracted | conflicted
  superseded_by  uuid REFERENCES claims(id),
  confidence     real NOT NULL DEFAULT 0.8,  -- extractor confidence
  claim_kind     text NOT NULL               -- fact | preference | decision | plan |
                                             -- observation | hypothesis | task
);
```

**`claim_kind` matters more than it looks.** A *decision* supersedes differently than an *observation* (decisions invalidate prior decisions on the same subject; observations accumulate). A *plan* has implicit valid-time in the future. A *hypothesis* should never silently win a conflict against a *fact*. Encode this in the supersession rules (§4.5), not in prompts.

### 3.3 `entities` and aliases

```sql
CREATE TABLE entities (
  id             uuid PRIMARY KEY,
  canonical_name text NOT NULL,
  entity_type    text,                       -- emergent: project | person | place | artifact | concept
  embedding      vector(768),
  created_at     timestamptz NOT NULL
);

CREATE TABLE entity_aliases (
  entity_id  uuid REFERENCES entities(id),
  alias      text NOT NULL,
  source     text NOT NULL                   -- extracted | user_confirmed
);
```

"The cabin," "the 14×18," "the WV build" → one entity, three aliases.

### 3.4 `edges`, `conflicts`, `schema_types`

```sql
CREATE TABLE edges (
  src_id    uuid NOT NULL,                   -- claim or entity
  dst_id    uuid NOT NULL,
  rel       text NOT NULL,                   -- emergent-schema relation type
  weight    real DEFAULT 1.0,
  PRIMARY KEY (src_id, dst_id, rel)
);

CREATE TABLE conflicts (
  id          uuid PRIMARY KEY,
  claim_a     uuid NOT NULL REFERENCES claims(id),
  claim_b     uuid NOT NULL REFERENCES claims(id),
  detected_at timestamptz NOT NULL,
  kind        text NOT NULL,                 -- contradiction | ambiguous_order | scope_unclear
  resolution  text,                          -- null = open
  resolved_at timestamptz
);

CREATE TABLE schema_types (
  id          uuid PRIMARY KEY,
  kind        text NOT NULL,                 -- entity_type | predicate | claim_tag | field_spec
  name        text NOT NULL,
  source      text NOT NULL,                 -- user_declared | emergent | migrated
  status      text NOT NULL,                 -- proposed | approved | merged | rejected | superseded
  spec        jsonb,                         -- optional field spec (e.g. enum values, value type)
  merged_into uuid REFERENCES schema_types(id),
  examples    jsonb                          -- claim ids / usage stats that motivated the proposal
);
```

**Schema is itself claims.** Declaring or approving a type is an *event* in the append-only log, compiled into `schema_types` like any other derived fact. `user_declared` types are auto-approved (the human said so — that *is* the review gate). `emergent` types go through the proposal queue (§4.6). `migrated` types are approved or queued based on usage frequency in the imported corpus (§7). Because schema rows derive from events, schema is supersedable and provenance-tracked like everything else: a bad early ontology decision gets superseded, not migrated around, and "when did I start typing projects this way" is a legal query.

---

## 4. The Compiler

Runs on git commit hook (incremental) + nightly full pass (consistency sweep). All stages are idempotent and re-runnable — derived tables can be rebuilt from `events` at any time. Version every model/prompt used per claim so you can selectively reprocess after model upgrades (`meta.extractor_version`).

### 4.1 Segmentation & normalization
Split capture into paragraphs/utterances. Normalize timestamps (file mtime, frontmatter dates, in-text date expressions). Voice transcripts get speaker/segment structure. Dedupe by content hash.

### 4.2 Claim extraction
Fine-tuned local 7B (Qwen2.5-class, QLoRA — the rellm tagger playbook applies directly). Input: segment + local context. Output: JSON list of atomic claims, each with `claim_kind`, candidate subject mentions, confidence, and any explicit temporal expressions.

**Training data bootstrap:** run a large teacher (frontier API or local 27B) over an initial corpus slice, human-grade a sample, distill. Same teacher→student pattern that took the tagger from F1 0.281 → 0.638; claim extraction is a comparable structured-output task.

**Precision over recall.** A missed claim costs a bad retrieval later. A hallucinated claim poisons the graph. Threshold aggressively; low-confidence extractions go to a review queue, not the graph.

### 4.3 Entity resolution
Two-stage: (1) embedding similarity of mention against `entities` + `entity_aliases` (pgvector, cheap); (2) for matches in the ambiguous band (~0.75–0.92 cosine), LLM adjudication with both contexts. Above the band → auto-link; below → new entity. Ambiguous merges that the adjudicator flags go to human review. **Never auto-merge entities** — a wrong merge is the most expensive error in the system (splitting is manual archaeology). Merges are human-gated; auto-linking mentions to existing entities is fine.

### 4.4 Temporal annotation
Infer `valid_from`/`valid_to` from explicit dates, tense, and `claim_kind` defaults (observation: valid_from = asserted_at; plan: future; decision: valid_from = asserted_at, open-ended). Leave null when genuinely unknown — a null valid-time is honest; a guessed one is a lie with a timestamp.

### 4.5 Supersession & conflict detection
For each new claim: retrieve active claims on the same `(subject, predicate-ish)` neighborhood (graph + vector). Then apply rules:

| new \ old | fact | decision | plan | preference | hypothesis |
|---|---|---|---|---|---|
| **fact** | contradiction check → supersede or conflict | supersedes if it reports the decision changed | closes plan if it reports outcome | coexist | supersedes |
| **decision** | coexist | supersedes prior decision on same subject | supersedes plan | coexist | supersedes |
| **hypothesis** | never supersedes | never supersedes | coexist | coexist | coexist |

Contradiction check is an LLM call (cheap, local): "do these two assertions conflict, and if so which is more current given timestamps?" If order is ambiguous → open a `conflicts` row. Conflicts surface in the daily digest; resolution is one keystroke (pick A / pick B / both-true-scoped / needs-more-info).

**This review queue is the entire human maintenance burden of the system.** Target: < 2 minutes/day. If it grows beyond that, the extractor thresholds are wrong — fix the model, don't recruit the human.

### 4.6 Schema emergence
Weekly batch: cluster unlabeled predicates/entity-types (HDBSCAN over embeddings — the Hermes domain-clustering code is reusable here), propose canonical names via LLM, present as a review batch ("approve 7 proposed types?"). Approved types trigger backfill over historical claims. Rejected clusters stay as raw text — no forced taxonomy.

### 4.7 Gradual schema (declared structure)

Users can declare structure at any time — "projects have a `status`," "cabin.foundation is one of {pier-beam, slab, rubble-trench}" — via a declaration event in the capture log, compiled to an approved `schema_types` row with `source: user_declared` (and an optional `spec`). Declared types take effect immediately in their region: extraction prompts include them as *candidate* labels for matching subjects, views group by them, and `recall` can filter on them.

Two invariants keep declared schema from becoming the janitorial trap with extra steps:

1. **Schema never rejects claims.** It is a lens, not a validator. A claim that doesn't fit a declared spec ("thinking about helical piers" vs. a declared foundation enum) lands in the graph anyway and the mismatch surfaces as a *tension* item in the daily digest — "claim doesn't fit declared schema: extend the enum, or reclassify as hypothesis?" — never as a capture-time error. The moment schema can block writes, capture friction returns and the human is maintaining an ontology *and* fighting it. (This is the Notion/Tana failure mode; zero-friction capture is non-negotiable.)
2. **Declared schema biases extraction; it does not constrain it.** The extractor may propose labels outside the declared set. Out-of-schema extractions are evidence the schema is incomplete, and feed the tension queue — the corpus gets a vote.

Tension items are a third row type in `conflicts` (`kind: schema_tension`), resolved through the same one-keystroke digest flow as contradictions. Resolutions (extend spec / reclassify claim / supersede the schema type) are themselves events — so schema evolves through the same append-only, provenance-tracked funnel as everything else, and every resolution is a labeled training example for the extractor.

---

## 5. Query Layer (agent-facing)

Ship as an **MCP server** first — that makes every Claude/agent session a consumer on day one, and dogfooding pressure lands where it should.

Core operations:

```
recall(query, as_of?, subject?, kinds?, include_superseded?)
  → ranked claims with provenance, validity intervals, confidence
  -- hybrid: vector top-k → graph expansion (1-hop entity neighborhood)
  → temporal filter → supersession filter (active-only unless asked)

entity(name_or_alias)
  → resolved entity + active claims grouped by predicate + timeline

timeline(subject, from?, to?)
  → claims ordered by valid_from; shows supersession chains

conflicts(open_only=true)
  → pending contradictions (agents can propose resolutions, human confirms)

assert(text, source_ref)
  → capture path for agents: writes an event, returns provisional claim ids
  -- agents WRITE through the same funnel as humans; no privileged writes
```

**Key retrieval property:** answers come with epistemic metadata. An agent asking "what's the cabin foundation?" gets *"pier-and-beam (decision, asserted 2026-03-10, active, source: notes/cabin-design.md@a3f2)"* — not two contradictory paragraphs and a shrug. `as_of` gives you time-travel queries for free from bitemporality.

---

## 6. View Compiler (human-facing)

Static generation, guru-style thin runtime. Zero interactivity needed for v1 — output markdown into a `views/` directory and let any editor/Obsidian render it (interop instead of competition: Obsidian becomes a *viewer* of compiled output, and existing vaults are just another capture source).

- **Entity pages** — active claims grouped by predicate, timeline, superseded history collapsed but present
- **Daily digest** — new claims, resolved/open conflicts, schema proposals (this is your review inbox)
- **Decision log** — all `decision` claims, chronological, per-project
- **Stale sweep** — claims with old `asserted_at`, no recent corroboration, on active entities ("is this still true?" prompts, optional)

---

## 7. Importers & Migration

Migration is the *easy* case for schema, because the user already ran the review gate — by hand, over years. Existing conventions aren't schema proposals; they're schema with a usage history attached. The importer's job is to make a migrated vault arrive substantially **typed and entity-resolved**, not as a flat text dump that has to rediscover its own structure.

**Pipeline (Obsidian/Logseq vault as the reference importer):**

1. **Files → events.** One event per note (or per dated section for daily notes), `source_type: note`, `source_ref: path@import-sha`. Frontmatter dates and file history inform `captured_at`.
2. **Wiki-links → entity seed.** Every `[[link]]` target becomes an entity; link text variants become `user_confirmed` aliases. This is years of human-labeled entity-resolution data for free — it also bootstraps the §4.3 adjudicator's training set.
3. **Conventions → schema events, frequency-weighted.** Frontmatter keys, consistent tags, folder taxonomies, Tana supertags → `schema_types` with `source: migrated`. A key used consistently across 200 notes fast-tracks to `approved`; one used 3 times enters the proposal queue like any emergent cluster. Thresholds are per-corpus knobs, but the principle is fixed: *usage frequency is accumulated review*.
4. **Frontmatter values → structured claims.** `status: active` on a project note compiles directly to a claim with the migrated predicate — high-confidence, no LLM in the loop.
5. **Body prose → normal extraction** (§4.2), with the migrated schema available as candidate labels per §4.7.

Other sources follow the same shape with thinner steps 2–4: chat/agent-session exports (rich in decisions and preferences, weak on declared structure), browser clippings, voice transcripts. Every importer is just an adapter that emits events + optional schema/alias events; nothing downstream knows imports exist.

---

## 8. MVP Phasing

**Phase 0 — Ingest + extract (1–2 weekends)**
Vault importer (§7, steps 1–2 minimum) + git repo watcher → events table → teacher-model claim extraction → claims with embeddings. No supersession yet; entities only as seeded by wiki-links. Deliverable: `recall(query)` over claims beats grep over your notes. *If this isn't already better than your current setup, stop and rethink.*

**Phase 1 — Entities + MCP (the "usable daily" line)**
Entity resolution, `entity()` and `assert()`, MCP server wired into your Claude sessions. Agent sessions become both consumer and capture source.

**Phase 2 — Time + truth**
Bitemporal fields, supersession rules, conflict queue, daily digest. This is the phase where the system becomes *different in kind* from every existing tool rather than just a nicer RAG.

**Phase 3 — Distill + emerge**
Fine-tune the 7B extractor on accumulated teacher outputs + your conflict-resolution decisions (every resolution is a labeled training example — the closed-loop fine-tuning skill pattern). Schema emergence batch. View compiler.

**Phase 4 — Generalize (optional, product territory)**
Multi-corpus support, packaging, the "bring your Obsidian vault" importer. Only if phases 0–3 prove daily-driver value on your own corpus first.

---

## 9. Stack

| Layer | Choice | Rationale |
|---|---|---|
| Capture | git repo, md/JSONL | sovereign, greppable, agent-writable, free sync/history |
| Compiler | Python | your pipeline muscle; batch inference tooling lives here |
| Extraction (bootstrap) | 27B local or frontier API | teacher quality |
| Extraction (steady state) | Qwen2.5-7B QLoRA on the 3090 | proven pattern, 10× cheaper, local |
| Embeddings | nomic-embed-text v1.5 via Ollama | already deployed for guru |
| Store | Postgres + pgvector | one database for graph, vectors, bitemporal queries; Atlas for schema |
| Agent API | MCP server (TypeScript or Python) | day-one integration with Claude sessions |
| Views | static md/HTML export | thin runtime, Obsidian-compatible |

Deliberately boring. The novelty budget is all spent on the data model.

## 10. Honest Risks

- **Extraction quality is the whole ballgame.** If atomic claims are wrong or mangled, everything downstream is confidently wrong — worse than the semantic soup you have now, because it *looks* authoritative. Mitigation: aggressive confidence thresholds, provenance always one click away, human-graded eval set from week one (build the benchmark harness before the pipeline, per your v3 instincts).
- **Claim decomposition loses nuance.** Some knowledge is irreducibly prose (design rationale, tradeoff discussions). Mitigation: claims always link to source spans; `recall` can return the surrounding event text. Claims are an index into prose, not a replacement for it.
- **Entity resolution errors compound.** Hence: no auto-merge, ever.
- **Compiler cost.** Nightly full sweeps over a growing corpus on one 3090. Mitigation: incremental processing as the default path; full rebuilds only on extractor version bumps. (The 128GB RAM + KTransformers route raises your local teacher ceiling if API costs annoy you.)
- **The cold-start chicken-and-egg.** Value appears only after enough corpus is compiled. Mitigation: Phase 0 targets your *existing* notes and chat exports, not future capture — you should have a queryable graph of years of material before you've changed a single habit.
- **Declared schema drifting into authority.** The tension queue only works if it stays short; if a user's declared specs generate constant mismatches, the temptation will be to "fix" it by validating at capture. Resist. The correct pressure valve is superseding the schema type, and the digest should make that the one-keystroke default when a spec accumulates repeated tensions.
- **Scope creep toward "product."** Build it as infrastructure for one user (you) with clean seams. The product question is a Phase 4 question and most likely the answer is "open-source it and let it find its people," which suits the sovereignty ethos anyway.
