"""Entity resolution, first pass: resolve paths against the filesystem.

11,672 entities, of which 9,307 are `artifact` — file paths in whatever surface form
the source happened to use. "retriever" alone appears as `retriever.ts`,
`src/lib/retriever.ts`, `guru-web/src/lib/retriever.ts`, and `retriever.ts:82`.
Meanwhile `guru/retriever.py` is a genuinely different implementation that must stay
separate. Question q013 fails on exactly this: grep beats the claim graph 0.387 to
0.000 because a literal string match distinguishes the two and the graph does not.

**Basename matching would be the wrong fix.** 854 basenames appear under more than
one path, and most are genuinely different files — `design.md` exists in a dozen
directories. Merging on basename is precisely the over-merge DESIGN §4.3 calls the
most expensive error in the system, since splitting afterwards is manual archaeology.

So resolution here is against the **real filesystem**: a surface form is only merged
into a canonical entity when it resolves, unambiguously, to one file that exists.
Anything ambiguous is left alone and counted. That is deterministic, checkable, and
it cannot invent an identity — the repos are the authority, not a similarity score.

Semantic aliasing ("the review app" ≡ guru-review) is a later pass and needs
adjudication; this one needs none.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .core.store import connect

# Line references arrive in more shapes than a first pass assumed: an ASCII hyphen
# range, an EN-DASH range (`retriever.ts:65–69`), and several ranges at once
# (`retriever.ts:283–304, 349–364`). Each unhandled shape leaves a duplicate entity
# for the same file, which is the exact fragmentation this pass exists to remove.
_RANGE = r"\d+(?:\s*[-–—]\s*\d+)?"
LINE_SUFFIX = re.compile(rf":\s*{_RANGE}(?:\s*,\s*{_RANGE})*\s*$")
PATHISH = re.compile(r"\.[A-Za-z0-9]{1,5}$")


@dataclass
class Index:
    """Every real file in the corpus repos, indexed for lookup by suffix.

    Built once. A surface form is matched by longest-suffix: `retriever.ts` matches
    `guru-web/src/lib/retriever.ts` only if nothing else in any repo ends the same
    way, so a bare basename shared by several files resolves to nothing rather than
    to a guess.
    """

    repos: dict[str, Path]
    by_suffix: dict[str, list[str]] = field(default_factory=dict)

    def build(self) -> "Index":
        for repo, root in self.repos.items():
            if not root.is_dir():
                continue
            for p in root.rglob("*"):
                if not p.is_file():
                    continue
                rel = p.relative_to(root).as_posix()
                if any(seg in (".git", "node_modules", ".venv", "__pycache__")
                       for seg in rel.split("/")):
                    continue
                ref = f"{repo}:{rel}"
                parts = rel.split("/")
                # index every path suffix: a.ts, lib/a.ts, src/lib/a.ts ...
                for i in range(len(parts)):
                    self.by_suffix.setdefault("/".join(parts[i:]), []).append(ref)
        return self

    def resolve(self, surface: str) -> str | None:
        """Canonical `repo:relpath`, or None when it is not unambiguous."""
        s = LINE_SUFFIX.sub("", surface.strip()).lstrip("./")
        if not s or not PATHISH.search(s):
            return None
        # A surface form may already carry its repo prefix.
        for repo in self.repos:
            for pre in (f"{repo}/", f"{repo}:"):
                if s.startswith(pre):
                    tail = s[len(pre):]
                    hits = [h for h in self.by_suffix.get(tail, []) if h.startswith(f"{repo}:")]
                    return hits[0] if len(hits) == 1 else None
        hits = self.by_suffix.get(s, [])
        return hits[0] if len(hits) == 1 else None


def run(corpus: str = "guru", repos: dict[str, Path] | None = None,
        dry_run: bool = False) -> dict:
    repos = repos or {
        "guru": Path("~/Work/guru").expanduser(),
        "guru-web": Path("~/Work/guru-web").expanduser(),
        "rellm": Path("~/Work/rellm").expanduser(),
    }
    index = Index(repos).build()

    conn = connect()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, canonical_name, entity_type FROM entities WHERE corpus = %s",
            (corpus,),
        )
        rows = cur.fetchall()

    groups: dict[str, list[tuple]] = {}
    unresolved = 0
    for eid, name, etype in rows:
        canon = index.resolve(name)
        if canon is None:
            unresolved += 1
            continue
        groups.setdefault(canon, []).append((eid, name, etype))

    merged = aliases = 0
    if not dry_run:
        with conn.cursor() as cur:
            for canon, members in groups.items():
                # Keep the member whose surface form already equals the canonical
                # path if there is one; otherwise the first. Its id survives so any
                # future reference stays valid.
                members.sort(key=lambda m: (m[1] != canon.split(":", 1)[1], m[1]))
                # Re-runnable: if a previous pass already created this canonical
                # entity, fold into it rather than renaming another row onto its
                # name — which raised a unique violation the first time this was
                # run twice.
                cur.execute(
                    "SELECT id FROM entities WHERE corpus = %s AND canonical_name = %s",
                    (corpus, canon),
                )
                existing = cur.fetchone()
                keep_id = existing[0] if existing else members[0][0]
                if not existing:
                    cur.execute(
                        "UPDATE entities SET canonical_name = %s, "
                        "entity_type = COALESCE(entity_type, 'file') WHERE id = %s",
                        (canon, keep_id),
                    )
                for eid, name, _ in members:
                    cur.execute(
                        """INSERT INTO entity_aliases (entity_id, alias, source)
                           VALUES (%s, %s, 'path_resolved') ON CONFLICT DO NOTHING""",
                        (keep_id, name[:500]),
                    )
                    aliases += cur.rowcount
                    if eid != keep_id:
                        cur.execute("DELETE FROM entities WHERE id = %s", (eid,))
                        merged += cur.rowcount
        conn.commit()

    collapsed = sum(len(m) for m in groups.values()) - len(groups)
    conn.close()
    return {
        "entities_in": len(rows),
        "resolved_to": len(groups),
        "surface_forms_folded": collapsed,
        "unresolved": unresolved,
        "merged": merged,
        "aliases": aliases,
    }
