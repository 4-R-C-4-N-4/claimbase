"""Adapter A against the conformance suite and against the real store."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_conformance import check_source

from claimbase.core.models import Kind, Trust
from claimbase.sources.todo_store import TodoStore

REPOS = {
    "guru": Path("/home/ivy/Work/guru"),
    "guru-web": Path("/home/ivy/Work/guru-web"),
}
LIVE = all(p.joinpath(".todo").is_dir() for p in REPOS.values())
live_only = pytest.mark.skipif(not LIVE, reason="live .todo stores not present")


@pytest.fixture(scope="module")
def src() -> TodoStore:
    return TodoStore(REPOS)


# --- synthetic: behaviour that must hold regardless of the live corpus --------


def _ticket(tmp: Path, repo: str, **over) -> Path:
    d = {
        "id": over.pop("id", "abc123"),
        "type": "bug",
        "state": "done",
        "summary": "a summary",
        "source": {"type": "agent"},
        "created_at": "2026-05-01T10:00:00.000Z",
        **over,
    }
    p = tmp / repo / ".todo" / "done"
    p.mkdir(parents=True, exist_ok=True)
    f = p / f"{d['id']}.json"
    f.write_text(json.dumps(d))
    return f


def test_agent_ticket_cannot_produce_a_decision(tmp_path: Path) -> None:
    """A resolution note on an agent-sourced ticket with no commit must degrade —
    otherwise model prose enters the graph as a decision."""
    _ticket(tmp_path, "r", resolution={"note": "we chose pier-and-beam"})
    src = TodoStore({"r": tmp_path / "r"})
    ev = src.to_event(next(src.scan()))
    claims = {c.meta.get("field"): c for c in src.structured_claims(ev)}
    assert claims["resolution"].kind is not Kind.DECISION
    assert claims["resolution"].meta["capped_from"] == "decision"


def test_linked_commit_corroborates(tmp_path: Path) -> None:
    _ticket(tmp_path, "r", resolution={"note": "done", "commit": "deadbeef"})
    src = TodoStore({"r": tmp_path / "r"})
    ev = src.to_event(next(src.scan()))
    res = next(c for c in src.structured_claims(ev) if c.meta.get("field") == "resolution")
    assert res.corroborated and res.kind is Kind.DECISION


def test_human_authored_analysis_overrides_ticket_trust(tmp_path: Path) -> None:
    _ticket(
        tmp_path,
        "r",
        source={"type": "agent"},
        analysis=[{"type": "conclusion", "confidence": "high", "author": "ivy", "content": "x"}],
    )
    src = TodoStore({"r": tmp_path / "r"})
    ev = src.to_event(next(src.scan()))
    a = next(c for c in src.structured_claims(ev) if c.meta.get("field") == "analysis")
    assert a.trust is Trust.HUMAN and a.kind is Kind.FACT


def test_unparseable_ticket_is_skipped_and_counted(tmp_path: Path) -> None:
    p = tmp_path / "r" / ".todo" / "done"
    p.mkdir(parents=True)
    (p / "bad.json").write_text('{"id": "bad", "note": "\\q"}')
    src = TodoStore({"r": tmp_path / "r"})
    assert src.to_event(next(src.scan())) is None
    assert len(src.skipped) == 1  # counted, not silent


def test_rendering_is_order_stable(tmp_path: Path) -> None:
    _ticket(tmp_path, "r", analysis=[{"type": "evidence", "content": "a"}, {"type": "evidence", "content": "b"}])
    src = TodoStore({"r": tmp_path / "r"})
    unit = next(src.scan())
    assert src.to_event(unit).content_hash == src.to_event(unit).content_hash


# --- live store ---------------------------------------------------------------


@live_only
def test_conformance_against_live_store(src: TodoStore) -> None:
    stats = check_source(src)
    assert stats["events"] > 600, stats
    assert stats["claims"] > stats["events"], "expect >1 claim per ticket"
    assert stats["edges"] > 500, stats
    print(f"\n  todo_store: {stats}, skipped={len(src.skipped)}")


@live_only
def test_declared_types_carry_usage_counts(src: TodoStore) -> None:
    types = {t.name: t.uses for t in src.declared_types()}
    assert types["chore"] > types["bug"] > types["refactor"]
    assert all(t.source == "migrated" for t in src.declared_types())
