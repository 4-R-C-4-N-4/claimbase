"""Adapter B — `docs/` trees.

Written as a genuine second pass rather than by analogy to Adapter A, because its
job is to find where the contract is secretly ticket-shaped. It contributes almost
no structured signal — titles and headings, nothing more — which is exactly what
stress-tests a seam designed around a structure-rich source.

Two things distinguish it:

**One event per revision, not per document.** A doc that changed three times is
three events (`path@sha1`, `path@sha2`, `path@sha3`), which is both more faithful to
append-only capture and what makes the next point work.

**`valid_to` comes from git, not from inference.** When a section disappears between
revisions, the commit that removed it dates the end of every claim that section
supported. DESIGN §4.4 says a guessed valid-time is a lie with a timestamp and null
is honest; here a large class of those nulls becomes recorded fact instead.
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

def _identifier_like(s: str) -> bool:
    """A code identifier or path, not a sentence containing one."""
    return (
        5 <= len(s) <= 80
        and not any(c.isspace() for c in s)
        and ("_" in s or "." in s or "/" in s)
        and s[0].isalnum()
    )


H2 = re.compile(r"^##\s+(.+)$", re.M)
BACKTICK = re.compile(r"`([^`\n]{3,60})`")
LINKED_PATH = re.compile(r"\]\(\.?/?([\w./-]+\.md)\)")
SPLIT_OVER = 4000  # chars; below this a doc is one unit

# Filename conventions with a usage history — DESIGN §7 step 3.
PREFIX = re.compile(r"^(BRD|IMPL|VOICE|CORE_RULES|BUGFIX)[-_]", re.I)


class MarkdownDocs:
    name = "markdown_docs"

    def __init__(self, repos: dict[str, Path], corpus: str = "guru") -> None:
        self.repos = repos
        self.corpus = corpus
        self.skipped: dict[str, str] = {}

    # --- git ------------------------------------------------------------------

    def _git(self, repo: str, *args: str) -> str:
        return subprocess.run(
            ["git", "-C", str(self.repos[repo]), *args], capture_output=True, text=True
        ).stdout

    def _doc_paths(self, repo: str) -> list[str]:
        root = self.repos[repo]
        paths = sorted(root.glob("docs/**/*.md")) + sorted(root.glob("*.md"))
        return [str(p.relative_to(root)) for p in paths]

    def _revisions(self, repo: str, rel: str) -> list[tuple[str, datetime, str]]:
        """Oldest first: (sha, commit date, author)."""
        out = self._git(repo, "log", "--reverse", "--format=%H%x00%cI%x00%an", "--", rel)
        revs = []
        for line in out.splitlines():
            parts = line.split("\x00")
            if len(parts) == 3:
                revs.append((parts[0], datetime.fromisoformat(parts[1]), parts[2]))
        return revs

    def _show(self, repo: str, sha: str, rel: str) -> str:
        return self._git(repo, "show", f"{sha}:{rel}")

    @staticmethod
    def _sections(text: str) -> list[tuple[str, str]]:
        """(heading, body). Short docs stay whole; long ones split at H2 so a claim
        can be dated to the section that carried it rather than the whole file."""
        if len(text) <= SPLIT_OVER:
            return [("", text)]
        marks = [(m.start(), m.group(1)) for m in H2.finditer(text)]
        if not marks:
            return [("", text)]
        out = [("", text[: marks[0][0]])]
        for i, (pos, head) in enumerate(marks):
            end = marks[i + 1][0] if i + 1 < len(marks) else len(text)
            out.append((head, text[pos:end]))
        return [(h, b) for h, b in out if b.strip()]

    # --- contract -------------------------------------------------------------

    def scan(self) -> Iterator[object]:
        for repo in self.repos:
            for rel in self._doc_paths(repo):
                revs = self._revisions(repo, rel)
                if not revs:
                    continue
                # Section keys per revision, so a section's disappearance can be
                # dated to the commit that removed it.
                per_rev = []
                for sha, ts, author in revs:
                    secs = self._sections(self._show(repo, sha, rel))
                    per_rev.append((sha, ts, author, secs))

                for i, (sha, ts, author, secs) in enumerate(per_rev):
                    later = per_rev[i + 1 :]
                    for head, body in secs:
                        # valid_to = the first later revision that no longer carries
                        # this section. Recorded, not inferred.
                        gone_at = None
                        for _, next_ts, _, next_secs in later:
                            if head not in {h for h, _ in next_secs}:
                                gone_at = next_ts
                                break
                        yield {
                            "repo": repo,
                            "rel": rel,
                            "sha": sha,
                            "ts": ts,
                            "author": author,
                            "heading": head,
                            "body": body,
                            "valid_to": gone_at,
                            "is_head": i == len(per_rev) - 1,
                        }

    def to_event(self, unit: object) -> Event | None:
        u: dict = unit  # type: ignore[assignment]
        if not u["body"].strip():
            self.skipped[f"{u['rel']}@{u['sha'][:8]}#{u['heading']}"] = "empty section"
            return None
        return Event(
            source=self.name,
            corpus=self.corpus,
            source_ref=f"{u['repo']}:{u['rel']}@{u['sha'][:12]}"
            + (f"#{u['heading']}" if u["heading"] else ""),
            content=u["body"],
            captured_at=u["ts"],
            meta={k: u[k] for k in ("repo", "rel", "heading", "author", "valid_to", "is_head")},
        )

    def structured_claims(self, event: Event) -> Iterable[Claim]:
        """Deliberately thin. A doc's substance is prose and belongs to the
        extractor; all this adapter can assert without a model is that a document
        section exists and when it stopped existing."""
        m = event.meta
        head = m.get("heading") or Path(m["rel"]).stem
        yield apply_cap(
            Claim(
                event_id=event.id,
                content=f"{m['rel']} documents “{head}”",
                kind=Kind.OBSERVATION,
                # Committer identity, not content authorship — a human committed it,
                # but the prose may well have been drafted by a model.
                trust=Trust.AGENT_GATED,
                asserted_at=event.captured_at,
                valid_from=event.captured_at,
                valid_to=m.get("valid_to"),
                confidence=0.95,
                meta={"field": "heading", "author": m.get("author")},
            )
        )

    def entity_mentions(self, event: Event) -> Iterable[Mention]:
        m = event.meta
        yield Mention(text=m["repo"], event_id=event.id, entity_type="project")
        yield Mention(text=m["rel"], event_id=event.id, entity_type="document")
        seen = set()
        for sym in BACKTICK.findall(event.content):
            sym = sym.strip()
            # Whitespace is the discriminator. Requiring only a dot or a slash let
            # whole clauses through — a backticked sentence like "guru CLI / RAG
            # retriever path. The previous 2048 was..." satisfied both and became an
            # "entity". 57% of the entity table was prose before this guard.
            if not _identifier_like(sym) or sym in seen:
                continue
            seen.add(sym)
            yield Mention(text=sym, event_id=event.id, entity_type=None)

    def edges(self, event: Event) -> Iterable[Edge]:
        m = event.meta
        src = f"doc:{m['repo']}:{m['rel']}"
        for target in set(LINKED_PATH.findall(event.content)):
            yield Edge(src=src, dst=f"doc:{m['repo']}:{target}", rel="links_to")
        # Revision chain: this section's own history is a supersession edge in
        # waiting. Phase 2 decides what to do with it; Phase 0 only records it.
        if m.get("valid_to"):
            yield Edge(src=src, dst=f"doc:{m['repo']}:{m['rel']}", rel="revised_by")

    def declared_types(self) -> Iterable[SchemaType]:
        counts: dict[str, int] = {}
        folders: dict[str, int] = {}
        for repo in self.repos:
            for rel in self._doc_paths(repo):
                stem = Path(rel).name
                if mt := PREFIX.match(stem):
                    key = mt.group(1).upper()
                    counts[key] = counts.get(key, 0) + 1
                parent = str(Path(rel).parent)
                if parent not in (".", "docs"):
                    folders[parent] = folders.get(parent, 0) + 1
        for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            yield SchemaType(kind="claim_tag", name=name, source="migrated", uses=n)
        for name, n in sorted(folders.items(), key=lambda kv: -kv[1]):
            yield SchemaType(kind="entity_type", name=name, source="migrated", uses=n)


def build(repos: dict[str, Path], corpus: str = "guru") -> MarkdownDocs:
    return MarkdownDocs(repos, corpus)


REGISTRY.register(MarkdownDocs({}))
