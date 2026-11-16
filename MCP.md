# Using claimbase from a Claude session

The MCP server exposes the claim graph over stdio. Add to your Claude Code MCP config:

```json
{
  "mcpServers": {
    "claimbase": {
      "command": "/home/ivy/Work/claimbase/.venv/bin/python",
      "args": ["-m", "claimbase.mcp_server"],
      "env": { "PYTHONPATH": "/home/ivy/Work/claimbase/src",
               "CLAIMBASE_CLIENT": "claude" }
    }
  }
}
```

Requires the database up (`docker compose up -d`) and Ollama running for query
embedding. Nothing else — the model server is only needed for extraction.

## Using claimbase from hermes

Hermes has a native MCP client, but **each profile loads its own config**
(`HERMES_HOME` points at the profile dir), so the server must be declared under
`mcp_servers:` in every `~/.hermes/profiles/<name>/config.yaml` — a block in the
root `~/.hermes/config.yaml` only reaches un-profiled sessions. As of 2026-08-21
all five guru profiles (reviewer, driver, corpus-quality, explorer, guru-dev)
carry the block, each with `CLAIMBASE_CLIENT: hermes-<profile>` so the query log
keeps per-agent question distributions separable. Tools appear as
`mcp_claimbase_recall`, `mcp_claimbase_timeline`, `mcp_claimbase_conflicts`,
`mcp_claimbase_stats` after a gateway restart. The same write posture applies:
`assert_claim` stays unregistered unless a profile's config block passes
`CLAIMBASE_MCP_WRITE: "1"`.

## Blast radius

Read-only by default, and the read is enforced by the database rather than by the
code: the server connects as `claimbase_ro`, a role with `SELECT` and nothing else,
`default_transaction_read_only`, and a 10-second statement timeout. A bug in a query
cannot damage or hang the store.

`feedback` and `submit_session` look like writes and are not database writes:
one leaves a line in the query log, the other a file in the spool
(`CLAIMBASE_SPOOL`, default `spool/`). The writer — a CLI job on the write role
— is the only thing that turns either into rows, so the read-only guarantee
above did not grow an exception.

`assert_claim` and `open_pr` are **not registered** unless `CLAIMBASE_MCP_WRITE=1`. Absent, not
merely hidden: calling it by name returns `Unknown tool`, so an instruction that
names the tool directly still fails. Writes persist, which makes them categorically
worse than a wrong answer — a false claim misleads every later session — so they are
opt-in.

```json
"env": {
  "PYTHONPATH": "/home/ivy/Work/claimbase/src",
  "CLAIMBASE_MCP_WRITE": "1"          // only if you want agents writing claims
}
```

### What this does not fix

`recall` returns corpus text into the session, and that text came from docs, tickets,
commits, PRs and memory. If any of it contains instruction-shaped language, it lands
in a model's context. **Sandboxing cannot remove this — it is what retrieval is.**
Results are labelled as untrusted data so a model treats imperatives inside them as
content to report rather than direction to follow, which helps and does not
guarantee.

Worth keeping in proportion: this is the same exposure as reading those files
directly, which Claude already does. The server indexes material it can already
reach — it grants no new access. The genuinely new capability was writing, and that
is off unless you turn it on.

The combination is what to avoid: injected text persuading an agent to assert
something false converts a transient prompt injection into a permanent corpus fact.
Keeping writes off breaks that chain, which is why the default is what it is.

## The harness contract

A harness needs three calls and no memory logic of its own:

1. **`brief`** once, at session start.
2. **`recall`** exposed to the model, for everything else.
3. **`submit_session`** at session end — or, where the harness has no
   session-end hook, the wrapper: `claimbase submit-session`.

The agent never decides what to remember. A separate writer
(`claimbase writer run`, a batch job that can wait for the GPU) reads the
submitted transcript and collects only from the moments that mattered. See
[GOALS.md](GOALS.md).

### Claude Code

MCP entry as above, plus `CLAIMBASE_PROJECT` if sessions do not start inside a
declared repo. For session end, a `SessionEnd` hook in `~/.claude/settings.json`
— Claude Code passes the transcript path, session id and working directory on
stdin, which is exactly what `--hook` reads:

```json
"hooks": { "SessionEnd": [ { "hooks": [ { "type": "command",
  "command": "PYTHONPATH=/home/ivy/Work/claimbase/src /home/ivy/Work/claimbase/.venv/bin/python -m claimbase.cli submit-session --hook" } ] } ] }
```

The project is resolved from the session's working directory through the repo
paths `corpora/*.toml` declare; an undeclared repo is its own project, named
after its directory; outside any repo is the user scope, `self`.

### Hermes

Sessions are SQLite rows, not files: `claimbase submit-session --harness hermes
--session-id <id>`. Whether hermes exposes a session-end hook to call it from
is unchecked.

## Tools

| tool | what it is for |
|---|---|
| `brief(project, cwd, budget_tokens)` | Session start. A fixed-budget set of standing claims for the project and the user scope: recently relied on first, then human-stated practices, decisions and preferences. |
| `inspect(claim_id)` | One claim, everything known: source passage, what it replaced and what replaced it, PRs, how often returned / used. Accepts a unique id prefix. |
| `feedback(kind, claim_id, note)` | `helpful`, `not_helpful` or `missed`. Writes nothing to the database — the query-log line is the record. |
| `submit_session(outcome, transcript_path \| messages, …)` | Session end. Redacts and queues the transcript for the writer. A path is honoured only under a known harness session directory. |
| `open_pr(claim_id, amendment, evidence, kind)` | **Write-gated.** A memory PR: applied at once. Enters at agent trust — it replaces a claim of equal standing and *contests* one a person stated. |
| `recall(query, k, as_of, include_superseded, project)` | The main entry. Ranked by epistemic standing, not similarity alone. `as_of` gives time travel: *"what did I believe in June?"* Scoped to one project; each result carries its claim `id`. |
| `timeline(subject)` | How belief about a subject changed, with each claim's status. Use when an answer may have **changed** rather than merely being unknown. Matches the subject as a literal substring first (verbatim phrases work best); falls back to semantic similarity when nothing matches, and `matched_by` in the response says which happened. |
| `conflicts()` | Contradictions the compiler could not settle. Empty is the normal state. |
| `assert_claim(text, kind)` | Capture something the corpus does not record. |
| `stats(project)` | What the store holds, the six usage measures, and the exception report. |

Every tool that reads takes `project`; without it the server answers for
`CLAIMBASE_PROJECT` (default `guru`). Results never mix projects.

## Query log

Every tool call — arguments, latency, and the full response the agent saw (or
the error) — is appended to `logs/mcp-queries.jsonl`. This is testing data:
real agent queries are the gold-set source that harvesting could not supply,
and a miss is only gradeable later because the log keeps what was returned at
the moment of asking, not a pointer into a graph that has since moved.

- Each line carries the claim `id`s returned, the `project` asked about, and a
  `session` id (one per server process, or `CLAIMBASE_SESSION`). That is what
  makes "which claims get used" answerable; lines from before 2026-11-16 have
  none of the three and are matched to claims by text where possible.
- `claimbase usage sync` loads new lines into tables; `claimbase usage report`
  and `claimbase report` read them.
- `CLAIMBASE_QUERY_LOG` overrides the path; set empty to disable (tests do).
- `CLAIMBASE_CLIENT` names the harness per config entry (`hermes`, `claude`),
  so per-client question distributions stay separable.
- It is a file, not a table, so the read-only DB role keeps its guarantee.
- Logging failures go to stderr and never fail the call.

## Two properties worth knowing when reading results

**Answers carry their standing.** Every hit reports kind, trust, assertion date, and
how many claims it superseded. *"practice · human · 2026-08-09 · supersedes 18"* is a
different answer from the same sentence with *"observation · agent · 2026-04-26"*
attached, and the ranking already accounts for the difference.

**An agent's `assert_claim` is not privileged.** It enters at `agent` trust and is
capped: asking for `kind="fact"` yields an `observation`, because a model's say-so is
not evidence. Corroboration or a human capture is what lifts a claim's standing. This
is the same cap every importer lives under — agents write through the same funnel as
everything else.
