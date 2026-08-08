"""The only vocabulary that crosses the adapter seam.

Adapters emit these. Everything downstream — extraction, embedding, supersession,
recall, views — consumes only these. No field here may name a source: no ticket
`analysis[].type`, no `report.txt`, no `.todo`. If an adapter needs something that
is not expressible here, the fix is to generalise the field, not to special-case
the adapter (PLAN §2.2).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4


class Trust(StrEnum):
    """Who authored a claim, and whether a human stood behind it.

    Adapters *declare* this; core enforces what it permits (see trust.py). The
    computation is source-specific — a ticket reads `source.type`, a doc reads the
    git author, a session adapter would read the turn role — but the tiers are not.
    """

    HUMAN = "human"
    AGENT_GATED = "agent_authored_human_gated"  # model wrote it, human kept it
    AGENT = "agent"
    UNKNOWN = "unknown"


class Kind(StrEnum):
    """DESIGN §3.2. Supersession behaviour differs per kind (§4.5), so this is a
    lifecycle-bearing field, not a label."""

    FACT = "fact"
    DECISION = "decision"
    PRACTICE = "practice"  # how work is currently done — see PLAN §0.9
    CAPABILITY = "capability"  # what a tool can do, independent of whether it is used
    PREFERENCE = "preference"
    PLAN = "plan"
    OBSERVATION = "observation"
    HYPOTHESIS = "hypothesis"
    TASK = "task"


class Status(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"
    CONFLICTED = "conflicted"


@dataclass(slots=True)
class Event:
    """Raw capture, immutable. Everything else is derived and rebuildable."""

    source: str  # adapter name — provenance, not dispatch
    source_ref: str  # path@sha, repo#pr, dir name, memory scope + file
    content: str
    captured_at: datetime | None  # None is legal: DESIGN §4.4, better than a guess
    corpus: str = "guru"
    meta: dict = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)

    @property
    def content_hash(self) -> bytes:
        """Dedupe key. Adapters must render content deterministically or re-imports
        will duplicate — the conformance suite checks exactly this."""
        return hashlib.sha256(self.content.encode()).digest()


@dataclass(slots=True)
class Claim:
    event_id: UUID
    content: str
    kind: Kind
    trust: Trust
    asserted_at: datetime | None
    subject: str | None = None  # unresolved mention text until Phase 1
    predicate: str | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    status: Status = Status.ACTIVE
    confidence: float = 0.8
    superseded_by: UUID | None = None
    span: tuple[int, int] | None = None
    corroborated: bool = False  # e.g. an agent claim backed by a linked commit
    meta: dict = field(default_factory=dict)
    id: UUID = field(default_factory=uuid4)


@dataclass(slots=True)
class Mention:
    """An entity as named at a point in text. Resolution is Phase 1; Phase 0 keeps
    the surface form and the type guess, and resolves nothing."""

    text: str
    event_id: UUID
    entity_type: str | None = None
    claim_id: UUID | None = None


@dataclass(slots=True)
class Edge:
    src: str  # opaque ref; resolved to ids at load time
    dst: str
    rel: str  # free text — canonicalisation is schema emergence's job, not the adapter's
    weight: float = 1.0
    meta: dict = field(default_factory=dict)


@dataclass(slots=True)
class SchemaType:
    """A convention observed in a source, with its usage count. Frequency is
    accumulated review (DESIGN §7 step 3)."""

    kind: str  # entity_type | predicate | claim_tag | field_spec
    name: str
    source: str = "migrated"
    status: str = "proposed"
    uses: int = 0
    spec: dict | None = None
