"""Adapter D — commit messages.

Overlooked in the first draft of the plan: an early check asked whether ticket
*files* were committed repeatedly, found they weren't, and wrote git off entirely.
That threw away ~503 KB of dated message prose across 1,684 commits — comparable in
volume to the whole ticket corpus.

Fourth adapter shape: the unit is a commit, which has no file of its own, no body
beyond the message, and a built-in edge to every path it touched. 586 of guru's
subjects carry a `todo:<id>` prefix, which links this source straight back to
Adapter A without either knowing about the other.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from ..core.contract import REGISTRY
from ..core.models import Claim, Edge, Event, Kind, Mention, SchemaType, Trust
from ..core.trust import apply_cap

TODO_REF = re.compile(r"\btodo:([0-9a-f]{6,})\b")
MECHANICAL = re.compile(
    r"^(merge (pull request|branch|remote)|bump|wip|fixup|squash|revert \"|\.\.\.)", re.I
)
SEP = "\x1e"


class GitLog:
    name = "git_log"

    def __init__(self, repos: dict[str, Path], corpus: str = "guru") -> None:
        self.repos = repos
        self.corpus = corpus
        self.skipped: dict[str, str] = {}

    def scan(self) -> Iterator[object]:
        for repo, root in self.repos.items():
            out = subprocess.run(
                ["git", "-C", str(root), "log", f"--format={SEP}%H%x00%cI%x00%an%x00%s%x00%b", "--name-only"],
                capture_output=True,
                text=True,
            ).stdout
            for block in out.split(SEP):
                if not block.strip():
                    continue
                head, _, tail = block.partition("\n")
                parts = head.split("\x00")
                if len(parts) < 4:
                    continue
                sha, iso, author, subject = parts[0], parts[1], parts[2], parts[3]
                body = parts[4] if len(parts) > 4 else ""
                paths = [ln.strip() for ln in tail.splitlines() if ln.strip()]
                yield {
                    "repo": repo,
                    "sha": sha,
                    "ts": iso,
                    "author": author,
                    "subject": subject,
                    "body": body,
                    "paths": paths,
                }

    def to_event(self, unit: object) -> Event | None:
        u: dict = unit  # type: ignore[assignment]
        subject = u["subject"].strip()
        if not subject:
            self.skipped[u["sha"][:8]] = "empty subject"
            return None
        if MECHANICAL.match(subject):
            # Merge commits and mechanical subjects carry no claim. Dropping them is
            # right; dropping them silently would hide a third of the source, so the
            # count is reported by the importer.
            self.skipped[u["sha"][:8]] = "mechanical subject"
            return None
        content = f"{subject}\n\n{u['body']}".strip()
        return Event(
            source=self.name,
            corpus=self.corpus,
            source_ref=f"{u['repo']}@{u['sha'][:12]}",
            content=content,
            captured_at=datetime.fromisoformat(u["ts"]),
            meta={k: u[k] for k in ("repo", "sha", "author", "subject", "paths")},
        )

    def structured_claims(self, event: Event) -> Iterable[Claim]:
        m = event.meta
        yield apply_cap(
            Claim(
                event_id=event.id,
                content=m["subject"],
                kind=Kind.OBSERVATION,  # a report of work done, not a proof of it
                # A human committed, but in these repos the message is frequently
                # model-drafted. The diff behind it is the corroboration.
                trust=Trust.AGENT_GATED,
                asserted_at=event.captured_at,
                valid_from=event.captured_at,
                confidence=0.85,
                corroborated=True,
                meta={"field": "subject", "sha": m["sha"], "author": m["author"]},
            )
        )

    def entity_mentions(self, event: Event) -> Iterable[Mention]:
        m = event.meta
        yield Mention(text=m["repo"], event_id=event.id, entity_type="project")
        for p in m["paths"][:40]:  # a mass rename should not flood the mention table
            yield Mention(text=p, event_id=event.id, entity_type="artifact")

    def edges(self, event: Event) -> Iterable[Edge]:
        m = event.meta
        src = f"commit:{m['sha']}"
        for tid in set(TODO_REF.findall(event.content)):
            # Closes the loop with Adapter A. Neither adapter knows the other exists;
            # they meet at the ref, which is the seam working as intended.
            yield Edge(src=src, dst=f"ticket:{m['repo']}:{tid}", rel="references_ticket")
        for p in m["paths"][:40]:
            yield Edge(src=src, dst=f"path:{m['repo']}:{p}", rel="touched")


    def declared_types(self) -> Iterable[SchemaType]:
        """Commit messages encode no convention worth promoting to a type. Stated
        explicitly rather than inherited: structural typing gives no defaults."""
        return ()


def build(repos: dict[str, Path], corpus: str = "guru") -> GitLog:
    return GitLog(repos, corpus)


REGISTRY.register(GitLog({}))
