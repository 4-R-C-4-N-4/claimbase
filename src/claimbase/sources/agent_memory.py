"""Adapter E — curated agent memory, read through a harness profile.

Not `claude_memory`. `~/.hermes` already exists on this machine and stores the same
kind of artifact differently: two monolithic files instead of one-per-fact, globally
scoped instead of per-project. An adapter shaped around Claude's layout would have
been rewritten on first contact with it, so layout comes from
`harnesses/<name>.toml` and only the parsing differs.

The material is the densest claim source in the corpus — hand-written, dated,
already atomic — and no repo adapter reaches it, because it lives outside every
repo.

Trust is `agent_authored_human_gated`: a model wrote it, the user kept it. Calling
it `agent` understates the review; calling it `human` overstates the authorship. The
tier is declared in the corpus definition, never inferred here, and it is why these
claims cannot become `fact` or `capability` — when curated memory disagrees with a
bench report or a commit, the artifact wins.
"""

from __future__ import annotations

import re
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from ..core.contract import REGISTRY
from ..core.models import Claim, Edge, Event, Kind, Mention, SchemaType, Trust
from ..core.trust import apply_cap

WIKILINK = re.compile(r"\[\[([^\]]+)\]\]")
FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.S)
H_SPLIT = re.compile(r"^#{1,3}\s+", re.M)

# metadata.type -> claim kind. Nothing here maps to FACT or CAPABILITY: the trust
# cap would degrade it anyway, and asking for it would only hide the reason.
_KIND = {
    "user": Kind.OBSERVATION,
    "feedback": Kind.PREFERENCE,
    "project": Kind.OBSERVATION,
    "reference": Kind.OBSERVATION,
}


def _mini_yaml(block: str) -> dict:
    """Enough YAML for memory frontmatter: flat keys plus one nested level.

    A dependency for four keys would be silly, and the shape is fixed by the
    harness rather than by anything a user types.
    """
    out: dict = {}
    current: dict | None = None
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        indented = line[0] in " \t"
        key, _, val = line.strip().partition(":")
        val = val.strip()
        if indented and current is not None:
            current[key.strip()] = val
        elif not val:
            current = out[key.strip()] = {}
        else:
            out[key.strip()] = val
            current = None
    return out


class AgentMemory:
    name = "agent_memory"

    def __init__(self, sources: list[dict], harness_dir: Path, corpus: str = "guru") -> None:
        """`sources` are corpus-definition entries: harness, scope, trust."""
        self.sources = sources
        self.harness_dir = harness_dir
        self.corpus = corpus
        self.skipped: dict[str, str] = {}
        self._profiles: dict[str, dict] = {}

    def profile(self, harness: str) -> dict:
        if harness not in self._profiles:
            with (self.harness_dir / f"{harness}.toml").open("rb") as fh:
                self._profiles[harness] = tomllib.load(fh)
        return self._profiles[harness]

    # --- contract -------------------------------------------------------------

    def scan(self) -> Iterator[object]:
        for spec in self.sources:
            prof = self.profile(spec["harness"])["memory"]
            layout = prof.get("layout")
            root = Path(prof["root"].replace("{scope}", spec.get("scope", ""))).expanduser()
            if not root.is_dir():
                self.skipped[str(root)] = "memory root not present"
                continue

            if layout == "file_per_fact":
                for p in sorted(root.glob(prof.get("glob", "*.md"))):
                    if p.name == prof.get("index"):
                        # An index of the other files, not content of its own.
                        self.skipped[str(p)] = "index file"
                        continue
                    yield {"spec": spec, "path": p, "text": p.read_text(), "segment": None}

            elif layout == "few_files_many_facts":
                # Hermes keeps many facts per file, so the unit is a segment. The
                # profile decides; the adapter does not assume one fact per file.
                for fname in prof.get("files", []):
                    p = root / fname
                    if not p.exists():
                        continue
                    text = p.read_text()
                    for i, seg in enumerate(s for s in H_SPLIT.split(text) if s.strip()):
                        yield {"spec": spec, "path": p, "text": seg, "segment": i}
            else:
                self.skipped[spec["harness"]] = f"unknown memory layout {layout!r}"

    def to_event(self, unit: object) -> Event | None:
        u: dict = unit  # type: ignore[assignment]
        text, spec, path = u["text"], u["spec"], u["path"]
        if not text.strip():
            self.skipped[str(path)] = "empty"
            return None
        fm = {}
        if m := FRONTMATTER.match(text):
            fm = _mini_yaml(m.group(1))
        ref = f"{spec['harness']}:{spec.get('scope', 'global')}/{path.name}"
        if u["segment"] is not None:
            ref += f"#{u['segment']}"
        return Event(
            source=self.name,
            corpus=self.corpus,
            source_ref=ref,
            content=text,
            # Memory files carry no authored date; mtime is the only signal, and it
            # is honest about being a file-system fact rather than an assertion date.
            captured_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
            meta={
                "harness": spec["harness"],
                "scope": spec.get("scope", "global"),
                "trust": spec.get("trust", Trust.AGENT_GATED.value),
                "frontmatter": fm,
                "name": fm.get("name") or path.stem,
            },
        )

    def structured_claims(self, event: Event) -> Iterable[Claim]:
        fm = event.meta["frontmatter"]
        desc = fm.get("description")
        if not desc:
            return
        meta_type = (fm.get("metadata") or {}).get("type", "")
        yield apply_cap(
            Claim(
                event_id=event.id,
                content=desc,
                kind=_KIND.get(meta_type, Kind.OBSERVATION),
                trust=Trust(event.meta["trust"]),
                asserted_at=event.captured_at,
                valid_from=event.captured_at,
                confidence=0.85,
                meta={"field": "description", "memory_type": meta_type},
            )
        )

    def entity_mentions(self, event: Event) -> Iterable[Mention]:
        yield Mention(text=event.meta["name"], event_id=event.id, entity_type="memory")
        for target in set(WIKILINK.findall(event.content)):
            yield Mention(text=target.strip(), event_id=event.id, entity_type=None)

    def edges(self, event: Event) -> Iterable[Edge]:
        """`[[wikilinks]]` — the only genuine wiki-link entity seed in this corpus.
        DESIGN §7 step 2 assumed a vault full of them; there is none, and this is
        the small real version."""
        src = f"memory:{event.meta['scope']}/{event.meta['name']}"
        for target in set(WIKILINK.findall(event.content)):
            yield Edge(src=src, dst=f"memory:{target.strip()}", rel="links_to")

    def declared_types(self) -> Iterable[SchemaType]:
        counts: dict[str, int] = {}
        for u in self.scan():
            ev = self.to_event(u)
            if not ev:
                continue
            t = (ev.meta["frontmatter"].get("metadata") or {}).get("type")
            if t:
                counts[t] = counts.get(t, 0) + 1
        for name, n in sorted(counts.items(), key=lambda kv: -kv[1]):
            yield SchemaType(kind="claim_tag", name=name, source="migrated", uses=n)


def build(sources: list[dict], harness_dir: Path, corpus: str = "guru") -> AgentMemory:
    return AgentMemory(sources, harness_dir, corpus)


REGISTRY.register(AgentMemory([], Path(".")))
