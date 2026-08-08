"""The adapter seam (PLAN §2.1).

An adapter turns some corner of the world into events, claims, mentions, edges and
schema types. Nothing downstream knows which adapter produced what — `Event.source`
is provenance for a human reading a result, never dispatch.

The contract is written against the *hard* cases even though no Phase 0 adapter
exercises them, because a contract shaped around the easy ones gets rewritten on
first contact with a real second source:

  - `scan()` yields opaque units. Not paths. Hermes sessions are SQLite rows and
    have no path identity at all.
  - `captured_at` is nullable. Two rellm run directories have no parseable timestamp,
    and inventing one would be a lie with a timestamp (DESIGN §4.4).
  - `structured_claims()` may yield nothing. The docs adapter contributes almost no
    structured signal and the run adapter contributes no prose — a source that feeds
    only one half of the pipeline must be ordinary, not a special case.
"""

from __future__ import annotations

from typing import Iterable, Iterator, Protocol, runtime_checkable

from .models import Claim, Edge, Event, Mention, SchemaType


@runtime_checkable
class Source(Protocol):
    """Implemented by every module under claimbase.sources."""

    name: str

    def scan(self) -> Iterator[object]:
        """Yield raw units — whatever this source's natural unit is. A file, a
        directory, a database row, an API object. Core never inspects these."""
        ...

    def to_event(self, unit: object) -> Event | None:
        """Render one unit to canonical text plus provenance. Returning None skips
        the unit; skips must be counted and reported, never silent."""
        ...

    def structured_claims(self, event: Event) -> Iterable[Claim]:
        """Claims derivable without a model. May be empty."""
        return ()

    def entity_mentions(self, event: Event) -> Iterable[Mention]:
        return ()

    def edges(self, event: Event) -> Iterable[Edge]:
        return ()

    def declared_types(self) -> Iterable[SchemaType]:
        """Conventions this source already encodes — frequency is accumulated
        review (DESIGN §7 step 3)."""
        return ()


class Registry:
    """Adapters register by name; corpora reference them by name in TOML.

    Deliberately not an import-time scan of the sources package: a corpus should
    fail loudly on an unknown adapter name rather than silently pick up whatever
    modules happen to be importable.
    """

    def __init__(self) -> None:
        self._sources: dict[str, Source] = {}

    def register(self, source: Source) -> Source:
        if source.name in self._sources:
            raise ValueError(f"adapter {source.name!r} already registered")
        self._sources[source.name] = source
        return source

    def get(self, name: str) -> Source:
        if name not in self._sources:
            raise KeyError(
                f"unknown adapter {name!r}; corpus definitions may only name "
                f"registered adapters. known: {sorted(self._sources)}"
            )
        return self._sources[name]

    def __contains__(self, name: object) -> bool:
        return name in self._sources

    def names(self) -> list[str]:
        return sorted(self._sources)


REGISTRY = Registry()
