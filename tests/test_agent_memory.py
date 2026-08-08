"""Adapter E — and the claim that the harness profile is load-bearing."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_conformance import check_source

from claimbase.core.models import Kind, Trust
from claimbase.sources.agent_memory import AgentMemory

HARNESSES = Path(__file__).resolve().parent.parent / "harnesses"
GURU_SCOPE = Path("~/.claude/projects/-home-ivy-Work-guru/memory").expanduser()
LIVE = GURU_SCOPE.is_dir()
live_only = pytest.mark.skipif(not LIVE, reason="live memory scope not present")

SOURCES = [
    {"harness": "claude", "scope": f"-home-ivy-Work-{s}", "trust": "agent_authored_human_gated"}
    for s in ("guru", "guru-web", "rellm")
]

SAMPLE = """---
name: a-fact
description: something the assistant recorded and the user kept
metadata:
  type: feedback
---

Body prose mentioning [[another-memory]] and [[a-third]].
"""


def _scope(tmp: Path) -> list[dict]:
    d = tmp / "memory"
    d.mkdir(parents=True)
    (d / "a-fact.md").write_text(SAMPLE)
    (d / "MEMORY.md").write_text("- [A fact](a-fact.md) — hook\n")
    return d


@pytest.fixture
def local(tmp_path: Path, monkeypatch) -> AgentMemory:
    _scope(tmp_path)
    prof = tmp_path / "harnesses"
    prof.mkdir()
    (prof / "t.toml").write_text(
        '[memory]\nlayout = "file_per_fact"\n'
        f'root = "{tmp_path}/memory"\nglob = "*.md"\nindex = "MEMORY.md"\n'
    )
    return AgentMemory([{"harness": "t", "trust": "agent_authored_human_gated"}], prof)


def test_index_file_is_skipped_and_reported(local: AgentMemory) -> None:
    units = list(local.scan())
    assert len(units) == 1
    assert any("index file" == v for v in local.skipped.values())


def test_frontmatter_becomes_a_claim_without_a_model(local: AgentMemory) -> None:
    ev = local.to_event(next(local.scan()))
    c = next(iter(local.structured_claims(ev)))
    assert c.content.startswith("something the assistant")
    assert c.kind is Kind.PREFERENCE  # metadata.type: feedback
    assert c.trust is Trust.AGENT_GATED


def test_memory_cannot_assert_fact_or_capability(local: AgentMemory) -> None:
    """The auto-promote lesson: curated memory may say what the workflow is, but a
    claim about what a tool can do has to come from the artifact."""
    from claimbase.core.trust import permitted

    assert not permitted(Kind.FACT, Trust.AGENT_GATED)
    assert not permitted(Kind.CAPABILITY, Trust.AGENT_GATED)
    assert permitted(Kind.PRACTICE, Trust.AGENT_GATED)


def test_wikilinks_become_edges(local: AgentMemory) -> None:
    ev = local.to_event(next(local.scan()))
    dsts = {e.dst for e in local.edges(ev)}
    assert dsts == {"memory:another-memory", "memory:a-third"}


def test_segmented_layout_yields_many_units_per_file(tmp_path: Path) -> None:
    """The reason this is a profile and not a claude-shaped adapter: hermes keeps
    many facts in one file, so the unit is a segment."""
    root = tmp_path / "mem"
    root.mkdir()
    (root / "MEMORY.md").write_text("# One\n\nalpha\n\n# Two\n\nbeta\n\n# Three\n\ngamma\n")
    prof = tmp_path / "harnesses"
    prof.mkdir()
    (prof / "h.toml").write_text(
        '[memory]\nlayout = "few_files_many_facts"\n'
        f'root = "{root}"\nfiles = ["MEMORY.md"]\n'
    )
    src = AgentMemory([{"harness": "h"}], prof)
    assert len(list(src.scan())) == 3, "one file, three facts"


def test_unknown_layout_is_reported_not_crashed(tmp_path: Path) -> None:
    prof = tmp_path / "harnesses"
    prof.mkdir()
    (prof / "x.toml").write_text(f'[memory]\nlayout = "something-new"\nroot = "{tmp_path}"\n')
    src = AgentMemory([{"harness": "x"}], prof)
    assert list(src.scan()) == []
    assert "unknown memory layout" in " ".join(src.skipped.values())


def test_shipped_profiles_parse() -> None:
    src = AgentMemory([], HARNESSES)
    for h in ("claude", "hermes"):
        assert src.profile(h)["memory"]["layout"]


@live_only
def test_conformance_against_live_memory() -> None:
    src = AgentMemory(SOURCES, HARNESSES)
    stats = check_source(src)
    print(f"\n  agent_memory: {stats}, skipped={len(src.skipped)}")
    assert stats["events"] > 30, stats
    assert stats["edges"] > 0, "wikilinks are the only real entity seed here"
