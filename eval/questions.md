# Questions

Write questions here in your own words. Don't look anything up, don't find file
paths, don't worry about phrasing — I resolve all of that into `gold_recall.jsonl`.

## Format

    ### <the question, as you'd actually ask it>
    TRUE: <what's actually the case — a sentence is plenty>
    WRONG: <what it would be wrong to tell you — the valuable line>
    UNSURE: <optional; anything you're not certain of>

`WRONG` is the one that matters. **mislead-rate** — did the system hand back a
superseded answer as if it were current — is the metric this project exists to move,
and it only needs to know what's stale. A question can have a debatable best answer
and a completely unambiguous wrong one.

`TRUE` can be rough or partial. Where it's genuinely subjective, say so in `UNSURE`
and that question gets scored on mislead only, marked as such rather than quietly
counted as if it were objective.

Good questions are ones where **the answer changed**, or where the docs would
mislead someone who trusted them. Boring lookups are fine too, but they mostly
measure whether something was findable at all.

---

### (example — delete or keep, whichever)
TRUE: Tag and edge review happens in the guru-review web app, over Tailscale from
whatever device is to hand.
WRONG: That review runs through `scripts/review_tags.py` or `scripts/review_edges.py`.
Those scripts are unused; if they still work it's a coincidence.
UNSURE:

---
