# Using claimbase from a Claude session

The MCP server exposes the claim graph over stdio. Add to your Claude Code MCP config:

```json
{
  "mcpServers": {
    "claimbase": {
      "command": "/home/ivy/Work/claimbase/.venv/bin/python",
      "args": ["-m", "claimbase.mcp_server"],
      "env": { "PYTHONPATH": "/home/ivy/Work/claimbase/src" }
    }
  }
}
```

Requires the database up (`docker compose up -d`) and Ollama running for query
embedding. Nothing else — the model server is only needed for extraction.

## Blast radius

Read-only by default, and the read is enforced by the database rather than by the
code: the server connects as `claimbase_ro`, a role with `SELECT` and nothing else,
`default_transaction_read_only`, and a 10-second statement timeout. A bug in a query
cannot damage or hang the store.

`assert_claim` is **not registered** unless `CLAIMBASE_MCP_WRITE=1`. Absent, not
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

## Tools

| tool | what it is for |
|---|---|
| `recall(query, k, as_of, include_superseded)` | The main entry. Ranked by epistemic standing, not similarity alone. `as_of` gives time travel: *"what did I believe in June?"* |
| `timeline(subject)` | How belief about a subject changed, with each claim's status. Use when an answer may have **changed** rather than merely being unknown. |
| `conflicts()` | Contradictions the compiler could not settle. Empty is the normal state. |
| `assert_claim(text, kind)` | Capture something the corpus does not record. |
| `stats()` | What the corpus contains. |

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
