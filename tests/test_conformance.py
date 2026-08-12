"""The conformance suite every adapter must pass.

Written before any adapter exists, so the contract shapes the adapters rather than
the first adapter shaping the contract. `check_source()` is the reusable body; each
adapter gets a thin test that calls it.

The fixture adapters below are deliberately awkward — one with no prose, one with no
path, one with a null timestamp — because those are the shapes that broke earlier
assumptions in this project and they should stay covered even before the real
adapters that resemble them land.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable, Iterator

import pytest

from claimbase.core.contract import Registry, Source
from claimbase.core.models import Claim, Edge, Event, Kind, Mention, Trust
from claimbase.core.trust import apply_cap, outranks, permitted


# --- reusable conformance body ----------------------------------------------


def check_source(src: Source) -> dict:
    """Run every adapter invariant. Returns counts so callers can assert on volume."""
    units = list(src.scan())
    events, skipped = [], 0
    for u in units:
        ev = src.to_event(u)
        if ev is None:
            skipped += 1
            continue
        events.append(ev)

    assert src.name, "adapter must declare a name"

    # 1. Provenance is never absent. captured_at may be None (honest); source_ref may not.
    for ev in events:
        assert ev.source_ref, f"{src.name}: event with no source_ref"
        assert ev.source == src.name, f"{src.name}: event.source must name its adapter"
        assert ev.content is not None

    # 2. Idempotence: re-running scan/to_event yields identical content hashes.
    again = [src.to_event(u) for u in src.scan()]
    again = [e for e in again if e is not None]
    assert [e.content_hash for e in events] == [e.content_hash for e in again], (
        f"{src.name}: content_hash unstable across runs — re-import would duplicate"
    )

    # 3. Every claim declares a trust tier, and none exceeds it.
    claims = [c for ev in events for c in src.structured_claims(ev)]
    for c in claims:
        assert isinstance(c.trust, Trust), f"{src.name}: claim without a declared trust tier"
        assert permitted(c.kind, c.trust, c.corroborated), (
            f"{src.name}: claim of kind {c.kind} at trust {c.trust} — "
            f"adapters must apply the cap, not leave it to core"
        )
        assert c.event_id in {e.id for e in events}, f"{src.name}: claim with dangling event_id"

    # Every contract method gets called, including the ones an adapter is likely
    # to omit. This suite missed `declared_types` once and the omission surfaced
    # as an AttributeError mid-import instead of a red test.
    for method in ("scan", "to_event", "structured_claims", "entity_mentions", "edges", "declared_types"):
        assert callable(getattr(src, method, None)), f"{src.name}: missing {method}()"
    types = list(src.declared_types())
    for t_ in types:
        assert t_.name and t_.kind, f"{src.name}: malformed schema type"

    return {
        "types": len(types),
        "units": len(units),
        "events": len(events),
        "skipped": skipped,
        "claims": len(claims),
        "mentions": sum(len(list(src.entity_mentions(e))) for e in events),
        "edges": sum(len(list(src.edges(e))) for e in events),
    }


# --- fixture adapters covering the awkward shapes ----------------------------


class NoProseSource:
    """Tabular source: contributes claims but no material for the extractor.
    Modelled on the bench-report adapter, which feeds zero prose by design."""

    name = "fixture_tabular"

    def scan(self) -> Iterator[object]:
        yield {"model": "v1", "f1": 0.462}
        yield {"model": "v3", "f1": 0.486}

    def to_event(self, unit) -> Event:
        return Event(
            source=self.name,
            source_ref=f"bench/{unit['model']}",
            content=f"{unit['model']} F1 = {unit['f1']}",
            captured_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
        )

    def structured_claims(self, event: Event) -> Iterable[Claim]:
        yield Claim(
            event_id=event.id,
            content=event.content,
            kind=Kind.FACT,
            trust=Trust.HUMAN,
            asserted_at=event.captured_at,
            confidence=1.0,
        )

    def entity_mentions(self, event: Event) -> Iterable[Mention]:
        return ()

    def edges(self, event: Event) -> Iterable[Edge]:
        return ()

    def declared_types(self):
        return ()


class NullTimeSource:
    """A unit with no knowable capture time. Two real run directories have exactly
    this problem; the adapter must pass None rather than invent a date."""

    name = "fixture_undated"

    def scan(self) -> Iterator[object]:
        yield "grammar-test"

    def to_event(self, unit) -> Event:
        return Event(source=self.name, source_ref=f"runs/{unit}", content="x", captured_at=None)

    def structured_claims(self, event: Event) -> Iterable[Claim]:
        return ()

    def entity_mentions(self, event):
        return ()

    def edges(self, event):
        return ()

    def declared_types(self):
        return ()


class AgentProseSource:
    """Model-authored prose. Must not be able to assert fact — the cap is the point."""

    name = "fixture_agent"

    def scan(self) -> Iterator[object]:
        yield "the base model beats the fine-tunes"

    def to_event(self, unit) -> Event:
        return Event(source=self.name, source_ref="session/1", content=unit, captured_at=None)

    def structured_claims(self, event: Event) -> Iterable[Claim]:
        c = Claim(
            event_id=event.id,
            content=event.content,
            kind=Kind.FACT,  # deliberately overreaching
            trust=Trust.AGENT,
            asserted_at=None,
        )
        yield apply_cap(c)

    def entity_mentions(self, event):
        return ()

    def edges(self, event):
        return ()

    def declared_types(self):
        return ()


FIXTURES = [NoProseSource(), NullTimeSource(), AgentProseSource()]


@pytest.mark.parametrize("src", FIXTURES, ids=lambda s: s.name)
def test_fixture_adapters_conform(src) -> None:
    stats = check_source(src)
    assert stats["events"] > 0


def test_protocol_is_structural() -> None:
    for src in FIXTURES:
        assert isinstance(src, Source)


def test_null_captured_at_is_legal() -> None:
    src = NullTimeSource()
    ev = src.to_event(next(src.scan()))
    assert ev.captured_at is None  # a guessed date would be a lie with a timestamp


# --- trust cap ---------------------------------------------------------------


def test_agent_cannot_assert_fact() -> None:
    c = Claim(event_id=None, content="x", kind=Kind.FACT, trust=Trust.AGENT, asserted_at=None)
    c.event_id = c.id  # placeholder; not exercised here
    apply_cap(c)
    assert c.kind is Kind.OBSERVATION
    assert c.meta["capped_from"] == "fact"


def test_corroboration_lifts_an_agent_claim() -> None:
    assert not permitted(Kind.DECISION, Trust.AGENT)
    assert permitted(Kind.DECISION, Trust.AGENT, corroborated=True)


def test_gated_memory_may_state_practice_but_not_capability() -> None:
    """The auto-promote case: curated memory can say what the workflow is, but a
    claim about what a tool *can do* should come from the artifact (PLAN §0.9)."""
    assert permitted(Kind.PRACTICE, Trust.AGENT_GATED)
    assert not permitted(Kind.CAPABILITY, Trust.AGENT_GATED)


def test_human_outranks_gated_memory() -> None:
    a = Claim(event_id=None, content="x", kind=Kind.FACT, trust=Trust.HUMAN, asserted_at=None)
    b = Claim(event_id=None, content="x", kind=Kind.OBSERVATION, trust=Trust.AGENT_GATED, asserted_at=None)
    assert outranks(a, b)
    assert not outranks(b, a)


# --- registry ----------------------------------------------------------------


def test_unknown_adapter_fails_loudly() -> None:
    r = Registry()
    r.register(NoProseSource())
    with pytest.raises(KeyError, match="unknown adapter"):
        r.get("todo_store")


def test_duplicate_registration_is_an_error() -> None:
    r = Registry()
    r.register(NoProseSource())
    with pytest.raises(ValueError, match="already registered"):
        r.register(NoProseSource())


def test_reimport_must_not_destroy_extracted_claims() -> None:
    """The importer and the extractor both write claims against one event. An
    unscoped delete in `replace_claims` wiped 7,520 teacher-extracted claims on the
    first re-import after supersession — hours of GPU work — so the scoping is
    asserted here rather than trusted.
    """
    import inspect

    from claimbase.core.store import Store

    src = inspect.getsource(Store.replace_claims)
    assert "extractor_version" in src, (
        "replace_claims must exclude extractor-derived claims from its delete"
    )
    # Both the delete and the supersession-revert need the guard; the revert reaches
    # claims by the same event_id and would strand extracted ones.
    assert src.count("extractor_version") >= 2


def test_entity_reset_cannot_reach_claims() -> None:
    """`TRUNCATE entities CASCADE` destroyed 8,012 extracted claims: TRUNCATE follows
    every FK regardless of ON DELETE, and claims.subject_id references entities.
    The reset path must use DELETE, and the FK must be SET NULL."""
    import inspect

    from claimbase import resolve_entities

    src = inspect.getsource(resolve_entities.reset)
    # Check executable statements only — the docstring explains the hazard and so
    # necessarily contains the word.
    body = "\n".join(
        ln for ln in src.splitlines()
        if "cur.execute" in ln or "conn." in ln
    )
    assert "TRUNCATE" not in body.upper(), "entity reset must not TRUNCATE — it cascades into claims"
    assert "DELETE FROM entities" in body
