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
