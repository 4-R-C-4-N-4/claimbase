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

### How many traditions and texts are in the guru db locally?
TRUE: The amount of traditions and texts must be verified in the DB and is not worth calling stable, it grows constantly.
WRONG: The traditions can be read from references in PRs or documentation

### Once a review on a tag or edge has been made with the guru review tool, is the change applied?
TRUE: No. The apply gate is the final step in the loop and must be completed by a human.
WRONG: The reviewed tags and edges are live. Once reviewed the agent can apply them.

### Which database does the guru export seed?
TRUE: First, the export seeds the local postgres docker environment. This is staging. After testing with guru-web, the same export is promoted to production by a human.
WRONG: The guru export is sent directly to production.

### Are tags safe to add with no extra context if proposed from the tagging process?
TRUE: Tags can be accepted in review or added to the taxonomy beforehand, but must be assigned a family and domain, or else they are orphaned from the tag concept hierarchy.
WRONG: Tags are static and do not change. Tags are not related to one another.

### When an agent is reviewing a chunk for tag or edge reviews with the guru-review tool, is it required for the agent to read the entire chunks present, or can they bulk submit if the reviews are trending a certain direction?
TRUE: The review agent should never submit reviews without reading each chunk provided and the reasoning from the local model.
WRONG: The review tool allows for bulk calls so it is best to quickly review rather than optimize quality.
 
### When adding a new text, the first step is to chunk the content.
TRUE: The first step should always be manifest work, including source verifiation and license public domain.
WRONG: Yes, a text can quickly be chunked without consideration of strata like author notes or footnotes or html artifacts.

### Does the guru-web app allow users to reference the chunk source material on the site? Are the references hyperlinks?
TRUE: Yes, each text is browsable chunk by chunk and the references after each query link to the chunk that was sent to the backend model.
WRONG: The guru-web app is only a RAG system for comparative religion.
