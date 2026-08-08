"""Adapter F — pull request descriptions.

Found by asking the user to mark elicitation rows and being told: *"their PRs likely
have the most relevant info, I would just be checking those."* A derivable answer
belongs in the corpus, not in someone's afternoon.

174 PRs across guru and guru-web, ~329 KB. rellm has none.

A PR description is an **outcome summary written at merge time** — the same claim
density as a ticket resolution note, with a merge date and a diff behind it. It
overlaps neither commits (too terse) nor tickets (written before the fact).

`mergedAt` is the capture time, and an unmerged PR is deliberately skipped: a
proposal is not a record of work done.
"""

from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from ..core.contract import REGISTRY
from ..core.models import Claim, Edge, Event, Kind, Mention, Trust
from ..core.trust import apply_cap

TODO_REF = re.compile(r"\btodo/([0-9a-f]{6,})\b|\btodo:([0-9a-f]{6,})\b")
FIELDS = "number,title,body,createdAt,mergedAt,state,headRefName"


class PullRequests:
    name = "pull_requests"

    def __init__(self, repos: dict[str, Path], corpus: str = "guru", cache: Path | None = None):
        self.repos = repos
        self.corpus = corpus
        self.cache = cache
        self.skipped: dict[str, str] = {}

    def _fetch(self, repo: str) -> list[dict]:
        """`gh` is a network call, so results are cached. An offline run degrades to
        contributing nothing rather than failing the whole import."""
        if self.cache:
            f = self.cache / f"prs-{repo}.json"
            if f.exists():
                return json.loads(f.read_text())
        out = subprocess.run(
            ["gh", "pr", "list", "--state", "all", "--limit", "500", "--json", FIELDS],
            cwd=self.repos[repo],
            capture_output=True,
            text=True,
        )
        data = json.loads(out.stdout) if out.stdout.strip() else []
        if self.cache:
            self.cache.mkdir(parents=True, exist_ok=True)
            (self.cache / f"prs-{repo}.json").write_text(json.dumps(data))
        return data

    def scan(self) -> Iterator[object]:
        for repo in self.repos:
            for pr in self._fetch(repo):
                yield {"repo": repo, "pr": pr}

    def to_event(self, unit: object) -> Event | None:
        u: dict = unit  # type: ignore[assignment]
        pr, repo = u["pr"], u["repo"]
        if not pr.get("mergedAt"):
            self.skipped[f"{repo}#{pr.get('number')}"] = "not merged"
            return None
        content = f"{pr.get('title', '')}\n\n{pr.get('body') or ''}".strip()
        if not content:
            self.skipped[f"{repo}#{pr.get('number')}"] = "empty"
            return None
        return Event(
            source=self.name,
            corpus=self.corpus,
            source_ref=f"{repo}#{pr['number']}",
            content=content,
            captured_at=datetime.fromisoformat(pr["mergedAt"].replace("Z", "+00:00")),
            meta={
                "repo": repo,
                "number": pr["number"],
                "title": pr.get("title", ""),
                "branch": pr.get("headRefName", ""),
            },
        )

    def structured_claims(self, event: Event) -> Iterable[Claim]:
        m = event.meta
        yield apply_cap(
            Claim(
                event_id=event.id,
                content=m["title"],
                kind=Kind.DECISION,  # merging is a decision, and the merge date proves it
                trust=Trust.AGENT_GATED,
                asserted_at=event.captured_at,
                valid_from=event.captured_at,
                confidence=0.9,
                corroborated=True,  # a merged diff stands behind it
                meta={"field": "title", "pr": m["number"]},
            )
        )

    def entity_mentions(self, event: Event) -> Iterable[Mention]:
        yield Mention(text=event.meta["repo"], event_id=event.id, entity_type="project")
        if b := event.meta.get("branch"):
            yield Mention(text=b, event_id=event.id, entity_type="branch")

    def edges(self, event: Event) -> Iterable[Edge]:
        m = event.meta
        src = f"pr:{m['repo']}#{m['number']}"
        refs = {a or b for a, b in TODO_REF.findall(event.content + " " + m.get("branch", ""))}
        for tid in refs - {""}:
            yield Edge(src=src, dst=f"ticket:{m['repo']}:{tid}", rel="references_ticket")


def build(repos: dict[str, Path], corpus: str = "guru", cache: Path | None = None) -> PullRequests:
    return PullRequests(repos, corpus, cache)


REGISTRY.register(PullRequests({}))
