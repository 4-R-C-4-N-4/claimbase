"""Trust tiers and the kind cap.

The rule this exists for: **agent-authored prose may not become `fact` or
`decision`.** That is a general statement about authorship provenance, so it lives
in core. How a tier is *computed* is source-specific and stays in the adapter — a
ticket reads `source.type`, a doc reads the git author, a session adapter reads the
turn role (PLAN §2.2).

Without this, the session and memory adapters would let a model's confident prose
enter the graph as fact, which is Risk §10.1 with extra steps: authoritative-looking
garbage that is worse than the semantic soup it replaced.
"""

from __future__ import annotations

from .models import Claim, Kind, Trust

# Kinds that assert something is settled truth or a taken decision. Everything else
# is either explicitly provisional or explicitly about the speaker.
ASSERTIVE = frozenset({Kind.FACT, Kind.DECISION, Kind.PRACTICE, Kind.CAPABILITY})

# What each tier may claim without corroboration.
_ALLOWED: dict[Trust, frozenset[Kind]] = {
    Trust.HUMAN: frozenset(Kind),
    # The user approved every line, so this is not raw model output — but the
    # phrasing and inferences are still the model's, so it does not get to assert
    # capability or settled fact on its own. Observation and practice it can.
    Trust.AGENT_GATED: frozenset(Kind) - {Kind.FACT, Kind.CAPABILITY},
    Trust.AGENT: frozenset(Kind) - ASSERTIVE,
    Trust.UNKNOWN: frozenset(Kind) - ASSERTIVE,
}

# What an assertive kind degrades to when the tier may not hold it.
_DEGRADE_TO: dict[Kind, Kind] = {
    Kind.FACT: Kind.OBSERVATION,
    Kind.CAPABILITY: Kind.OBSERVATION,
    Kind.DECISION: Kind.OBSERVATION,
    Kind.PRACTICE: Kind.OBSERVATION,
}


def permitted(kind: Kind, trust: Trust, corroborated: bool = False) -> bool:
    """May a claim of this kind be held at this trust tier?

    Corroboration — an agent claim backed by a linked commit, a merged PR, a test —
    lifts an agent to the gated tier, because something outside the model's own prose
    stands behind it.
    """
    if corroborated and trust in (Trust.AGENT, Trust.UNKNOWN):
        trust = Trust.AGENT_GATED
    return kind in _ALLOWED[trust]


def apply_cap(claim: Claim) -> Claim:
    """Degrade a claim whose kind outruns its trust, in place.

    Degrading rather than rejecting is deliberate: the claim still happened and its
    provenance is still worth keeping. DESIGN §4.7 — schema is a lens, never a
    validator, and the same restraint applies here. Dropping the claim would lose
    evidence; demoting it keeps the evidence and withholds the authority.
    """
    if permitted(claim.kind, claim.trust, claim.corroborated):
        return claim
    original = claim.kind
    claim.kind = _DEGRADE_TO.get(original, Kind.OBSERVATION)
    claim.meta = {**claim.meta, "capped_from": str(original), "capped_by_trust": str(claim.trust)}
    return claim


def outranks(a: Claim, b: Claim) -> bool:
    """Does `a` win a conflict against `b` on provenance alone?

    Used by supersession (Phase 2) to keep memory-derived claims from overriding
    artifact-derived ones: a hand-written note is valuable, but when it disagrees
    with a bench report or a commit, the artifact wins (PLAN §0.46).
    """
    rank = {Trust.HUMAN: 3, Trust.AGENT_GATED: 2, Trust.AGENT: 1, Trust.UNKNOWN: 0}
    return rank[a.trust] > rank[b.trust]
