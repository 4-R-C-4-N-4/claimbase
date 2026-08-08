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

# Sentence-ish split. Deliberately crude: over-splitting costs a click, while
# under-splitting hides a claim inside a blob the grader cannot mark separately.
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z`\"'*\[(])|\n\s*[-*]\s+|\n{2,}")

KINDS = ("fact", "decision", "practice", "capability", "preference", "plan",
         "observation", "hypothesis", "task")


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
        return {k for k, v in self.latest().items() if v["verdict"] != "skip"}


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in SENTENCE.split(text) if p and p.strip()]
    return [p for p in parts if len(p) > 15][:40]


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
        "todo_store": (200, 0.30),
        "markdown_docs": (400, 0.30),
        "git_log": (120, 0.10),
        "pull_requests": (300, 0.15),
        "agent_memory": (150, 0.15),
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
                if len(sents) < 2:
                    continue
                items.append(
                    Item(
                        kind="gold_extract",
                        payload={
                            "event_id": str(eid),
                            "source": src,
                            "source_ref": ref,
                            "sentences": sents,
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
                        "graded_at": d["at"],
                    }
                )
                + "\n"
            )
            n += 1
    return n
