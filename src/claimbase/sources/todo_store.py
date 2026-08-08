"""Adapter A — hand-rolled `.todo` ticket stores.

The richest Phase 0 source and the one most likely to bend the seam, because it
supplies almost every field the model has. Everything ticket-shaped stays inside
this module: `analysis[].type`, `source.type`, `relationships` keys, the `.todo`
layout. Core never sees any of it.

695 tickets across guru and guru-web. rellm has no store — the corpus definition
says so rather than this adapter discovering it and silently contributing nothing.
"""

from __future__ import annotations

import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from ..core.contract import REGISTRY
from ..core.models import Claim, Edge, Event, Kind, Mention, SchemaType, Trust
from ..core.trust import apply_cap

# The ticket vocabulary, translated at the boundary. These maps are the entire
# reason core can stay ignorant of this source.
_KIND_FROM_ANALYSIS = {
    "evidence": Kind.OBSERVATION,
    "conclusion": Kind.FACT,
    "hypothesis": Kind.HYPOTHESIS,
    "blame": Kind.OBSERVATION,
}
_TRUST_FROM_SOURCE = {
    "human": Trust.HUMAN,
    "agent": Trust.AGENT,
    "test": Trust.UNKNOWN,
}
_CONFIDENCE = {"high": 0.9, "medium": 0.6, "low": 0.3}


def _parse_ts(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _author_trust(author: str | None, fallback: Trust) -> Trust:
    """An analysis entry names its own author, which may differ from the ticket's."""
    if not author:
        return fallback
    return Trust.HUMAN if "agent" not in author.lower() else Trust.AGENT


class TodoStore:
    name = "todo_store"

    def __init__(self, repos: dict[str, Path], corpus: str = "guru") -> None:
        self.repos = repos  # repo name -> path, supplied by the corpus definition
        self.corpus = corpus
        # Keyed by path: to_event is called more than once per unit (the
        # conformance suite re-scans to check idempotence), and a list would
        # report one bad ticket as two.
        self.skipped: dict[str, str] = {}
        self._sha_cache: dict[str, dict[str, str]] = {}

    # --- provenance ----------------------------------------------------------

    def _last_shas(self, repo: str) -> dict[str, str]:
        """path -> sha of the last commit touching it. One git call per repo; 695
        individual `git log -1` calls would dominate the import."""
        if repo in self._sha_cache:
            return self._sha_cache[repo]
        out = subprocess.run(
            ["git", "-C", str(self.repos[repo]), "log", "--format=@%H", "--name-only"],
            capture_output=True,
            text=True,
        ).stdout
        shas: dict[str, str] = {}
        cur = ""
        for line in out.splitlines():
            if line.startswith("@"):
                cur = line[1:]
            elif line.strip():
                shas.setdefault(line.strip(), cur)  # first seen == most recent
        self._sha_cache[repo] = shas
        return shas

    # --- contract ------------------------------------------------------------

    def scan(self) -> Iterator[object]:
        for repo, root in self.repos.items():
            for p in sorted(root.glob(".todo/*/*.json")):
                if p.name == "config.json":
                    continue
                yield (repo, p)

    def to_event(self, unit: object) -> Event | None:
        repo, path = unit  # type: ignore[misc]
        try:
            d = json.loads(path.read_text())
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            # One ticket in guru has an invalid escape. Skipping is correct; skipping
            # silently is not — the count surfaces in the import report.
            self.skipped[str(path)] = str(e)
            return None

        rel = str(path.relative_to(self.repos[repo]))
        sha = self._last_shas(repo).get(rel, "")
        return Event(
            source=self.name,
            corpus=self.corpus,
            source_ref=f"{repo}:{rel}@{sha[:12]}" if sha else f"{repo}:{rel}",
            content=self._render(d),
            captured_at=_parse_ts(d.get("created_at")),
            meta={
                "repo": repo,
                "ticket_id": d.get("id"),
                "ticket_type": d.get("type"),
                "state": d.get("state"),
                "raw": d,
            },
        )

    @staticmethod
    def _render(d: dict) -> str:
        """Canonical text with a fixed field order.

        Order is load-bearing: content_hash is the dedupe key, so an unstable
        rendering makes every re-import insert duplicates. The conformance suite
        checks this directly.
        """
        parts = [f"[{d.get('type')}/{d.get('state')}] {d.get('summary', '')}"]
        if d.get("description"):
            parts.append(str(d["description"]))
        for a in d.get("analysis") or []:
            parts.append(
                f"({a.get('type')}, {a.get('confidence')}, {a.get('author')}) "
                f"{a.get('content', '')}"
            )
        res = d.get("resolution") or {}
        if res.get("note"):
            parts.append(f"(resolution) {res['note']}")
        for f in d.get("files") or []:
            if f.get("note"):
                parts.append(f"({f.get('path')}) {f['note']}")
        return "\n\n".join(parts)

    def structured_claims(self, event: Event) -> Iterable[Claim]:
        d = event.meta["raw"]
        base_trust = _TRUST_FROM_SOURCE.get((d.get("source") or {}).get("type"), Trust.UNKNOWN)
        res = d.get("resolution") or {}
        # A linked commit is evidence outside the author's own prose.
        corroborated = bool(res.get("commit"))

        if d.get("summary"):
            yield apply_cap(
                Claim(
                    event_id=event.id,
                    content=d["summary"],
                    kind=Kind.TASK,
                    trust=base_trust,
                    asserted_at=event.captured_at,
                    confidence=0.95,
                    corroborated=corroborated,
                    meta={"field": "summary"},
                )
            )

        if res.get("note"):
            resolved = _parse_ts(res.get("resolved_at"))
            yield apply_cap(
                Claim(
                    event_id=event.id,
                    content=res["note"],
                    kind=Kind.DECISION,
                    trust=base_trust,
                    asserted_at=resolved or event.captured_at,
                    valid_from=resolved,
                    confidence=0.9,
                    corroborated=corroborated,
                    meta={"field": "resolution", "commit": res.get("commit")},
                )
            )

        for a in d.get("analysis") or []:
            yield apply_cap(
                Claim(
                    event_id=event.id,
                    content=a.get("content", ""),
                    kind=_KIND_FROM_ANALYSIS.get(a.get("type"), Kind.OBSERVATION),
                    trust=_author_trust(a.get("author"), base_trust),
                    asserted_at=_parse_ts(a.get("timestamp")) or event.captured_at,
                    confidence=_CONFIDENCE.get(a.get("confidence"), 0.6),
                    corroborated=corroborated,
                    meta={"field": "analysis", "analysis_type": a.get("type")},
                )
            )

    def entity_mentions(self, event: Event) -> Iterable[Mention]:
        d = event.meta["raw"]
        repo = event.meta["repo"]
        yield Mention(text=repo, event_id=event.id, entity_type="project")
        for f in d.get("files") or []:
            if f.get("path"):
                yield Mention(text=f["path"], event_id=event.id, entity_type="artifact")
        work = d.get("work") or {}
        if work.get("branch"):
            yield Mention(text=work["branch"], event_id=event.id, entity_type="branch")

    def edges(self, event: Event) -> Iterable[Edge]:
        d = event.meta["raw"]
        src = f"ticket:{event.meta['repo']}:{d.get('id')}"
        rels = d.get("relationships") or {}
        for rel, target in rels.items():
            # Relation names pass through as free text. Canonicalising here would
            # bake this store's vocabulary into the graph; that is schema
            # emergence's job, with usage counts behind it.
            for t in target if isinstance(target, list) else [target]:
                if t:
                    yield Edge(src=src, dst=f"ticket:{event.meta['repo']}:{t}", rel=rel)
        res = d.get("resolution") or {}
        if res.get("commit"):
            yield Edge(src=src, dst=f"commit:{res['commit']}", rel="resolved_by")

    def declared_types(self) -> Iterable[SchemaType]:
        """The ticket `type` vocabulary is a declared schema with four months of
        usage history — exactly DESIGN §7 step 3's case."""
        counts: dict[str, int] = {}
        for repo, path in self.scan():  # type: ignore[misc]
            try:
                d = json.loads(path.read_text())
            except Exception:
                continue
            t = d.get("type")
            if t:
                counts[t] = counts.get(t, 0) + 1
        for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            yield SchemaType(kind="claim_tag", name=name, source="migrated", uses=n)


def build(repos: dict[str, Path], corpus: str = "guru") -> TodoStore:
    return TodoStore(repos, corpus)


REGISTRY.register(TodoStore({}))  # registration is by name; instances carry config
