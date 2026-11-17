# Goals — harness-independent agent memory

Branch `rfc/harness-memory`. Source: *RFC: Harness-independent agent memory*
(2026-11-15). This file is the working contract for that branch: what the RFC
asks for, how each piece maps onto claimbase as it exists, what is decided, and
what "done" means. Status is updated in place; measurements go in
[findings.md](../findings.md), not here.

The RFC is treated as **claimbase's next phase, on its Postgres store** — not a
new system. The gold set, the eval harness, the standing-aware ranking and the
query log are the assets; a restart would throw them away.

---

## 0. What the repo said before any code was written (2026-11-16)

Checked, not assumed. These change what "phase 1" has to deliver.

| RFC statement | State found |
|---|---|
| "There were no usage statistics" | Every MCP call has been logged with its full response since 2026-08-21 (`logs/mcp-queries.jsonl`). The log held no claim ids, so it could not answer *which* claims were used. |
| "claimbase is at Phase 0" | Phase 0's stated gate did not pass (findings 2026-08-09); the store went live for the hermes fleet anyway on 2026-08-21. |
| "Extraction produced weak claims" | The 2026-08-21 reviewer eval measured the opposite bottleneck: on-target claims existed and lost the ranking. Three true supply gaps in ~42 queries. |
| (unstated) | **The store has been down since late August.** `claimbase-db` exited two months ago; the query log holds 75 calls, 73 of them from one day. Nothing has asked it a question since 2026-08-26. The nightly compile never ran: no cron daemon is active. |
| (unstated) | **It was attached to profiles, not to the work.** The hermes profiles told to ask did ask (224 calls), then stopped being run in August. The default profile is wired but never told: 0 calls in 192 sessions since. Claude Code, used daily, is not wired. |

The last two rows are the ones that matter. The RFC's phase 1 is "done when one
harness uses it daily" — that is the gate. An agent told to ask, asks; one that
is merely able to, does not; and the work moved to where nothing was asking.
Everything below is ordered to make attaching memory cheap (one call at session start, one
hook at session end, project resolved from the working directory) and to make
its absence visible (measures that read zero when nobody asks). Details:
findings.md, 2026-11-16.

---

## 1. Goals (from the RFC), and where each one lands

| # | Goal | Lands as | Status |
|---|---|---|---|
| G1 | Any MCP harness can use the store with no memory logic of its own | `brief` + `recall` + `submit_session`; the harness contract is three calls | built |
| G2 | Every claim traces to its episodes | already true (`claims.event_id`, span); `inspect` exposes it | built |
| G3 | Facts change without manual cleanup; a refutation merges at once | memory PRs (`memory_prs`, `prs.py`) | built |
| G4 | No step waits for a person; people get an exception report | `claimbase report`; contested claims are served with a label, never held | built |
| G5 | Usage is measured from the first day | query log carries claim ids + session + project; `usage sync` → `retrieval_log`, `exposures`; six measures | built |
| G6 | Projects never conflate | project ≡ `corpus`, on every row since 001; MCP takes `project`; cross-project PRs refused | built |
| G7 | Inspectable and correctable by hand | `inspect`, `pr open`, `pr revert`, `brief`, `report` on the CLI | built |
| G8 | One machine, local models, no hosted dependency | unchanged; the writer's judge is a local model behind `llm.py` | built; Bonsai sandbox exercised, real-session judge unvalidated |
| G9 | The design admits a shared scope without a rewrite | not started — see §5 | open |

Non-goals carry over unchanged: not a replacement for docs/linters/config, no
secrets, no fine-tuning, not multi-tenant.

---

## 2. Decisions taken on this branch

Each closes an RFC open question or one of its two "tensions". Owner can
overturn any of them; they are written down so that overturning is a diff.

1. **Project is `corpus`.** No new column. A project is declared in
   `corpora/<name>.toml`; a working directory resolves to a project only through
   the repo paths declared there (`projects.py`). An unknown directory resolves
   to *no project*, never to a guess.
2. **User scope is the `self` corpus** (the name `harnesses/hermes.toml` already
   reserves). `brief` returns project + `self`. Scope stays one concept for now;
   *visibility* (private/shared) is a second field to add with G9, not a value
   of this one.
3. **Episodes are events** with `source = 'session'`. Same table, same
   content-hash dedupe, same immutability.
4. **`standing` is the existing `active`.** Two statuses are added: `tentative`
   (one supporting episode, not served by `recall`) and `contested` (served,
   labelled, on the exception report).
5. **Trust stays in ranking; no new use of `confidence`.** The RFC drops the
   score. Trust is provenance, not a score, and it is half of how mislead-rate
   went 0.273 → 0.000. Exposures are recorded beside it, not instead of it.
6. **The trust cap applies to PRs: an amendment takes the trust of its
   evidence.** A PR whose evidence is outranked by its target does not
   supersede it — the target becomes `contested`, the amendment is kept as
   `tentative`, and both go on the exception report. Nothing waits; nothing an
   agent merely *read* overwrites what a human said.
7. **A PR never crosses projects.** Target and amendment share a corpus.
8. **Revert is a new version, not a rollback.** Reverting PR *n* files PR *n+1*
   whose amendment restores the prior text and supersedes *n*'s amendment.
9. **The MCP server stays read-only against the database.** `feedback` and
   `submit_session` write files (the query log, the spool); the writer — a CLI
   batch job on the write role — is the only thing that turns them into rows.
   `open_pr` is a database write and sits behind `CLAIMBASE_MCP_WRITE`, exactly
   like `assert_claim`.
10. **Roles come from the harness, never from a model.** What counts as "the
    user's own turn" is read off the transcript's role tags. The evidence rule
    (only a user turn or a registered reference can back a PR) is only as good
    as that attribution, so it is not delegated to the segmenter.
11. **Claim ids are stable across re-import.** Adapter-derived claims were
    deleted and re-inserted with fresh uuids on every compile, which would have
    orphaned every exposure and PR target nightly. Ids are now derived from
    `(event, kind, content)` and unchanged rows are kept in place.
12. **Existing claims are kept.** They enter with zero exposures; dead weight
    is measured, and archiving is a later, measured decision.
13. **Bulk extraction is not switched off here.** The RFC proposes it; the
    measured finding (retrieval, not supply, was the bottleneck) argues against
    doing it blind. `yield per trigger` will say which side is right.

---

## 3. What is built on this branch

Read path (no model dependency):

- `brief(project | cwd)` — fixed-budget set of standing claims: recently
  exposed first, then human-stated practices / decisions / preferences.
- `recall(query, project, …)` — unchanged ranking; now project-scoped, returns
  claim ids and status, serves `contested` with its label.
- `inspect(claim_id)` — evidence, version chain, PRs, exposures.
- `feedback(claim_id, kind)` — `helpful | not_helpful | missed`, to the log.
- `stats(project)` — the measures and the exception report.

Write path:

- `submit_session` (MCP) / `claimbase submit-session` (wrapper for harnesses
  with no session-end hook) → redaction → spool.
- `claimbase writer run` — spool → episodes → triggers → score → act
  (exposure | tentative claim | memory PR) → promotion.
- `claimbase replay` — the same writer over archived transcripts into a
  scratch database, for testing thresholds before they touch a live store.
- `claimbase pr open | revert | list` and `open_pr` (MCP, write-gated).

Measures (`claimbase usage report`, `stats`): miss rate, dead weight, yield per
trigger, leak rate, repeat corrections, revert rate.

Schema: additive migrations `008_memory.sql`, `009_outcomes.sql`, and
`010_session_attribution.sql`. The new migrations were exercised only on scratch stores.

---

## 4. Gates — what is *not* done, and who holds it

| Gate | Holder | Why it is a gate |
|---|---|---|
| Bring `claimbase-db` back up | owner | It was stopped, not broken; restarting it also revives the nightly cron compile. |
| Apply memory migrations 008–010 to the live store | owner | Additive, but it is the live store. Back up and inspect the exact migration set first; sandbox approval is not live-migration approval. |
| First compile after merge | owner | Decision 11 re-keys every adapter-derived claim once. Compare `store_fingerprint` before and after; the gold scoreboard must not move. |
| Validate the writer's judge on real sessions | owner (GPU) | Local Bonsai passed the synthetic sandbox, not representative real-session judgement. Run the capture-only shadow evaluation/replay and audit retention against source evidence. |
| Wire one harness for daily use | owner | The actual phase-1 gate. Claude Code: MCP entry + a `SessionEnd` hook calling `claimbase submit-session`. See MCP.md. |
| Point hermes at this branch | owner | Profiles load `src/` from the main checkout; the branch lives in a separate worktree so the fleet is not running unreviewed code. |

Phase 1 is **done** when one harness has used it daily for a week and the six
measures have a week of data. Nothing on this branch can make that true by
itself.

---

## 5. Not started (RFC phases 2, 5, 6)

- **References** — `add_reference`, snapshots as events, section anchors,
  change detection. Useful alone; next after daily use is real.
- **Idle verification** — check recipes, `verify`. Depends on references.
- **Consolidation** — general claims over specifics (`level` column exists,
  nothing writes `general`).
- **Shared scope** — attestations, cross-participant PRs. Needs decision 2's
  second field.
- **Graph expansion at recall** — held until evaluation shows misses hybrid
  search cannot reach.

## 6. Known holes

- **Scope recognition remains lexical.** The project-reference noun veto
  fixes intervening-qualifier leakage conservatively; it can retain genuinely
  global preferences locally and is not arbitrary semantic scope understanding.
  Scope and delivery-order fixes passed regressions, independent confirmation
  and fresh smoke/full/repeated execution; live rollout remains owner-gated.
- **Re-extraction resurrects amended claims.** An extractor-version bump
  rebuilds extracted claims wholesale; a PR that superseded one of them is not
  replayed. PRs need to be re-applied after extraction the way captured
  asserts already are (`rebuild_captured`).
- **Causal use remains unproven.** Reports now separate logged delivery,
  weak inferred use, explicit feedback and independent task outcomes. The
  earlier three-rule sandbox followed rules with zero lexical-use signals;
  the lexical threshold was not tuned to those examples. A passing artifact
  does not prove which claim caused it; no lexical match remains unknown.
- **Legacy attribution can remain unknown.** New attribution uses exact,
  harness-qualified session identities or structurally captured per-call
  receipts. Ambiguous, duplicate or conflicting receipts fail closed rather
  than guessing by project and time. This does not retroactively resolve
  unidentified historical traffic.
- **Correction detection is a heuristic** over user turns. It is a trigger
  selector, not a classifier; the rule that fired is recorded on each episode
  so yield per rule can be measured and bad rules dropped. Calibrated once, by
  eye, on 145 hermes sessions (findings 2026-11-16); what it misses is unknown.
- **Tool failures are pre-filtered.** One that resembles nothing in the store
  is never shown to the judge. That is the RFC's rule, and it also means a
  failure teaching something wholly new is not collected.
- **Thresholds are unmeasured.** Every constant at the top of `writer.py` was
  chosen by argument.
- **Revert rate undercounts.** A wrong merge nobody notices looks like a safe
  one. The measure is a floor.

## 7. Hermes sandbox gate (2026-11-16)

**Executed:** local Ternary-Bonsai-2-27B as agent and judge, 65,536-token
context on the 3090. Expanded set: **2/9 task checks without memory, 9/9
with memory**, with **9/9 collection checks**. Three fresh four-scenario
subset trials: **3/12 without memory, 12/12 with memory and collection**.
Zero execution errors. The separate changed-rule smoke also passed and is
not pooled into those denominators. Hermes's built-in memory was disabled.

The real runs exposed and corrected scope widening, unavailable filesystem
operations, suppressed capability guidance, dependency-cache disk growth and
chat-lifetime coupling. Both arms now receive identical confined rename/delete
tools; no shell or memory-writing tools were added. Failed/contaminated runs
remain separate. See the [sandbox notes](evaluation/hermes-bonsai-sandbox-2026-11-16.md)
and [post-review portable evidence](../eval/evidence/2026-11-16-hermes-bonsai-post-review.json).
These fresh results cover behavioral commit cdd0b94; initial pre-review evidence
remains separately preserved, not pooled or overwritten.

This verifies **synthetic sandbox execution**, not any owner gate in §4 or
causal use of a particular claim. Next: PR review/owner merge, retrieval
pressure, then capture-only real-project shadow evaluation. The judge still
needs representative real-session validation and daily use still needs a week
of evidence. No live store or normal Hermes profile was changed.
