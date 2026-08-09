"""Review queue — the human maintenance surface.

DESIGN §4.5: *"This review queue is the entire human maintenance burden of the
system. Target: < 2 minutes/day."* So it is built once, generic over item kinds,
rather than as a one-off grading script that gets thrown away and rebuilt when
conflicts arrive in Phase 2.

Three kinds are anticipated. Only the first is generated today:

  gold_extract    a segment, sentence-split, awaiting "which of these are claims?"
  conflict        two claims that disagree — pick A / pick B / both-scoped / unclear
  schema_tension  a claim that does not fit a declared spec (§4.7)

Decisions are **appended, never edited** — the same append-only discipline as the
capture log. A changed verdict is a new line that supersedes the old one, so the
grading history is queryable and a mis-click is recoverable.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

# Markdown is a line-oriented format, so it has to be cleaned line by line. A
# whole-document regex pass was tried first and merged prose across block
# boundaries — it produced "…has a thinking-model branch: short frag The fix is…"
# by gluing a code intro, a stray bullet and an unrelated sentence together.
# Blocks must be kept apart, not just stripped of their markers.

FENCE = re.compile(r"^\s*(```|~~~)")
DROP_LINE = re.compile(
    r"^\s*(?:"
    r"\||"              # table row
    r">|"               # blockquote
    r"!\[|\[!\[|"      # image / badge
    r"\s{4,}\S|"        # indented code
    r"[-=]{3,}\s*$|"    # rule / setext underline
    r"</?\w+[^>]*>"     # raw html
    r")"
)
HEADING = re.compile(r"^\s*#{1,6}\s+")
LIST_MARK = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
URL = re.compile(r"https?://\S+")

SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z`\"'(\[])")

KINDS = ("fact", "decision", "practice", "capability", "preference", "plan",
         "observation", "hypothesis", "task")


FRONTMATTER = re.compile(r"\A---\n.*?\n---\n", re.S)


def blocks(text: str) -> list[str]:
    """Prose blocks, with code, tables, headings and rules removed entirely.

    A list item is its own block: bullets are usually independent assertions, and
    joining them into a paragraph invents sentences nobody wrote.
    """
    # Frontmatter is metadata about the note, not an assertion in it. Left in, it
    # reaches the grader as "name: protected-main-... description: Main is
    # protected." — a key-value blob no one can assign a claim kind to.
    text = FRONTMATTER.sub("", text)
    out: list[str] = []
    buf: list[str] = []
    in_fence = False

    def flush() -> None:
        if buf:
            out.append(" ".join(" ".join(buf).split()))
            buf.clear()

    for raw in text.splitlines():
        if FENCE.match(raw):
            in_fence = not in_fence
            flush()
            continue
        if in_fence:
            continue
        if not raw.strip():
            flush()
            continue
        if DROP_LINE.match(raw) or HEADING.match(raw):
            flush()
            continue
        line = URL.sub("", raw)
        if LIST_MARK.match(line):
            flush()  # each bullet stands alone
            buf.append(LIST_MARK.sub("", line))
            flush()
            continue
        buf.append(line)
    flush()
    return [b for b in out if b]


def is_gradable(s: str) -> bool:
    """Does this look like something a person could call true or false?

    Strict on purpose. A fragment costs the grader a decision they cannot make,
    and a queue full of those teaches them to stop reading.
    """
    s = s.strip()
    if not (30 <= len(s) <= 400) or len(s.split()) < 6:
        return False
    if not (s[0].isalpha() or s[0] in "`\"'"):
        return False
    if not s.endswith((".", "!", "?", ")", "`", '"')):
        return False  # truncated mid-thought
    if sum(c in "|{}<>=" for c in s) > len(s) * 0.06:
        return False  # residual markup or code
    return True


def split_sentences(text: str) -> list[str]:
    """Prose sentences worth a verdict, in document order."""
    out: list[str] = []
    for block in blocks(text):
        for s in SENTENCE_END.split(block):
            s = s.strip()
            if is_gradable(s):
                out.append(s)
    return out[:25]


# --- pre-annotation ----------------------------------------------------------
#
# Nine kinds x ~9 sentences x 49 screens is too much to author from scratch, so
# the queue guesses and the grader corrects. Recognition beats recall — the same
# reason the elicitation list ranked candidates instead of asking "what have you
# stopped doing?".
#
# The guesser is deliberately RULE-BASED, not the model being scored. Pre-filling
# with the extractor would make the gold set measure agreement with itself. These
# rules are independent of it, so corrections are real signal — and the rules
# double as a baseline the extractor has to beat, exactly as rg and chunk-RAG are
# baselines for retrieval.
#
# Anchoring bias is still real: people accept a plausible wrong label more often
# than they invent one. Mitigated by recording the guess alongside the final mark,
# so accept-vs-change rate is measurable rather than assumed.

_CUES: list[tuple[str, str]] = [
    # order matters: first match wins, most specific first
    ("hypothesis", r"\b(seems?|appears?|probably|might|may |could be|suggests?|"
                   r"hypothes\w+|unclear|not sure|possibly|likely|I think|presumably|"
                   r"worth checking|needs? (?:more )?(?:investigation|confirmation))\b"),
    ("decision",   r"\b(decided|chose|chosen|opted|settled on|we will use|going with|"
                   r"switch(?:ed)? to|adopt(?:ed)?|rejected|reverted|deferred|"
                   r"agreed|resolved to|dropped in favou?r)\b"),
    ("practice",   r"\b(always|never|workflow|the process|standard practice|we (?:run|use)|"
                   r"should (?:run|use|be)|must (?:run|use|be)|do not (?:run|use)|"
                   r"goes? through|handled by)\b"),
    ("capability", r"\b(can |cannot |is able to|supports?|provides?|allows?|enables?|"
                   r"accepts?|returns?|handles?|is idempotent|by design)\b"),
    # TODO must not match the `todo/<id>` branch names and `todo:<id>` commit
    # prefixes this corpus is full of — case-insensitively that fired on almost
    # every ticket-linked sentence.
    ("task",       r"\b(TODO(?![:/])|need to|needs to be|remains? to|still to do|"
                   r"follow-?up|outstanding|left to)\b"),
    ("plan",       r"\b(will |plan to|next step|upcoming|intend|going to|scheduled|"
                   r"phase \d|once .* lands)\b"),
    ("preference", r"\b(prefer|rather than|I'd like|we want|nicer|cleaner if|ideally)\b"),
]
_MEASURED = re.compile(r"\b\d+(?:\.\d+)?\s*(?:%|ms|s\b|chunks?|rows?|tokens?|F1|"
                       r"precision|recall)|\b(?:F1|precision|recall|macro-F1)\s*[=:]")
_REPORTED = re.compile(r"\b(found|observed|noticed|turned out|shows?|showed|"
                       r"reported|logged|measured|confirmed)\b", re.I)


def guess_kind(s: str) -> str:
    """Best rule-based guess at a sentence's claim kind.

    Never returns None: an unmarkable sentence has already been filtered out by
    `is_gradable`, so the question here is only *which* kind, and `observation` is
    the honest default for prose that reports something without hedging,
    deciding, or describing a capability.
    """
    for kind, pattern in _CUES:
        if re.search(pattern, s, re.I):
            return kind
    if _MEASURED.search(s):
        return "fact"
    if _REPORTED.search(s):
        return "observation"
    return "observation"


@dataclass
class Item:
    kind: str
    payload: dict
    id: str = field(default_factory=lambda: str(uuid.uuid4()))


@dataclass
class Decision:
    item_id: str
    verdict: str
    payload: dict
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DecisionLog:
    """Append-only JSONL. The latest line for an item wins."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, d: Decision) -> None:
        with self.path.open("a") as fh:
            fh.write(json.dumps(asdict(d)) + "\n")

    def latest(self) -> dict[str, dict]:
        out: dict[str, dict] = {}
        if not self.path.exists():
            return out
        for line in self.path.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                out[d["item_id"]] = d  # later lines supersede earlier ones
        return out

    def decided_ids(self) -> set[str]:
        """Only a graded verdict removes an item from the queue.

        `skip` and `retracted` both leave it pending, which is what makes undo
        durable: retracting appends a line rather than deleting one, so the item
        comes back after a reload and the fumble stays on the record.
        """
        return {k for k, v in self.latest().items() if v["verdict"] == "graded"}

    def last_graded(self) -> str | None:
        last = None
        if not self.path.exists():
            return None
        for line in self.path.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                last = d["item_id"] if d["verdict"] == "graded" else last
        return last if last in self.decided_ids() else None


def sample_segments(limit: int = 60, seed: int = 7) -> list[Item]:
    """Stratified sample of prose segments to grade.

    Stratification is not decoration: the corpus is dominated by one project, and
    rellm's research prose is the material most likely to be mis-typed as `fact`
    (hedged, conditional, self-superseding), so it is deliberately over-sampled.
    """
    import random

    from ..core.store import connect

    rng = random.Random(seed)
    strata = {
        # source, min length, share of the sample
        "todo_store": (300, 0.30),
        "markdown_docs": (600, 0.40),
        "pull_requests": (400, 0.15),
        "agent_memory": (200, 0.15),
        # git_log dropped: a commit subject is one line and usually a single
        # obvious observation. Grading it teaches the extractor nothing and costs
        # the grader attention that doc prose deserves.
    }
    items: list[Item] = []
    with connect() as conn, conn.cursor() as cur:
        for source, (min_len, share) in strata.items():
            n = max(1, round(limit * share))
            cur.execute(
                """
                SELECT id, source, source_ref, content, meta
                FROM events
                WHERE corpus = %s AND source = %s AND length(content) >= %s
                ORDER BY md5(id::text || %s)
                LIMIT %s
                """,
                ("guru", source, min_len, str(seed), n * 3),
            )
            rows = cur.fetchall()
            rng.shuffle(rows)
            for eid, src, ref, content, meta in rows[:n]:
                # rellm prose is over-weighted inside the docs stratum for the
                # hedging reason above.
                sents = split_sentences(content)
                if len(sents) < 3:
                    continue  # too thin to be worth a screen
                items.append(
                    Item(
                        kind="gold_extract",
                        payload={
                            "event_id": str(eid),
                            "source": src,
                            "source_ref": ref,
                            "sentences": sents,
                            # Pre-filled guesses. The grader corrects rather than
                            # authors; both the guess and the final answer are kept.
                            "guesses": {str(i): guess_kind(s) for i, s in enumerate(sents)},
                            "repo": (meta or {}).get("repo", ""),
                        },
                    )
                )
    rng.shuffle(items)
    return items[:limit]


def to_gold_jsonl(log: DecisionLog, items: dict[str, Item], out: Path) -> int:
    """Compile graded decisions into the gold set the extractor is scored against."""
    n = 0
    with out.open("w") as fh:
        for item_id, d in log.latest().items():
            if d["verdict"] != "graded" or item_id not in items:
                continue
            it = items[item_id]
            fh.write(
                json.dumps(
                    {
                        "event_id": it.payload["event_id"],
                        "source": it.payload["source"],
                        "source_ref": it.payload["source_ref"],
                        "sentences": it.payload["sentences"],
                        # marks: {sentence_index: claim_kind}; unmarked = not a claim,
                        # which is as important as the positives.
                        "marks": d["payload"].get("marks", {}),
                        # Kept so the rule-based pre-annotator can be scored against
                        # the human, and so anchoring can be measured rather than
                        # assumed away.
                        "guesses": it.payload.get("guesses", {}),
                        "graded_at": d["at"],
                    }
                )
                + "\n"
            )
            n += 1
    return n
