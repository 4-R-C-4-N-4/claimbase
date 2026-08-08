"""Adapter B: the seam's second implementation, and the valid_to mechanism."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from test_conformance import check_source

from claimbase.sources.markdown_docs import MarkdownDocs

REPOS = {
    "guru": Path("/home/ivy/Work/guru"),
    "guru-web": Path("/home/ivy/Work/guru-web"),
    "rellm": Path("/home/ivy/Work/rellm"),
}
LIVE = all((p / ".git").is_dir() for p in REPOS.values())
live_only = pytest.mark.skipif(not LIVE, reason="live repos not present")


def _repo(tmp: Path) -> Path:
    r = tmp / "r"
    (r / "docs").mkdir(parents=True)
    run = lambda *a: subprocess.run(["git", "-C", str(r), *a], capture_output=True)  # noqa: E731
    run("init", "-q")
    run("config", "user.email", "t@t")
    run("config", "user.name", "t")
    return r


def _commit(r: Path, msg: str) -> None:
    subprocess.run(["git", "-C", str(r), "add", "-A"], capture_output=True)
    subprocess.run(["git", "-C", str(r), "commit", "-q", "-m", msg], capture_output=True)


def test_valid_to_comes_from_the_commit_that_removed_the_section(tmp_path: Path) -> None:
    """The mechanism the whole adapter exists for: a section that disappears dates
    the end of the claims it supported — recorded, not guessed."""
    r = _repo(tmp_path)
    doc = r / "docs" / "d.md"
    filler = "x " * 2500
    doc.write_text(f"# D\n\n## Alpha\n\n{filler}\n\n## Beta\n\n{filler}\n")
    _commit(r, "one")
    doc.write_text(f"# D\n\n## Alpha\n\n{filler}\n")  # Beta removed
    _commit(r, "two")

    src = MarkdownDocs({"r": r})
    units = list(src.scan())
    beta = [u for u in units if u["heading"] == "Beta"]
    alpha = [u for u in units if u["heading"] == "Alpha"]
    assert len(beta) == 1 and beta[0]["valid_to"] is not None, "removed section must be dated"
    assert all(u["valid_to"] is None for u in alpha), "surviving section must stay open"

    ev = src.to_event(beta[0])
    claim = next(iter(src.structured_claims(ev)))
    assert claim.valid_to == beta[0]["valid_to"]
    assert claim.valid_from is not None


def test_one_event_per_revision(tmp_path: Path) -> None:
    r = _repo(tmp_path)
    doc = r / "docs" / "d.md"
    doc.write_text("# D\n\nfirst\n")
    _commit(r, "one")
    doc.write_text("# D\n\nsecond\n")
    _commit(r, "two")

    src = MarkdownDocs({"r": r})
    events = [src.to_event(u) for u in src.scan()]
    events = [e for e in events if e]
    assert len(events) == 2, "a doc revised twice is two events, not one"
    assert len({e.source_ref for e in events}) == 2, "each revision needs its own ref"
    assert len({e.content_hash for e in events}) == 2


def test_short_docs_are_not_split(tmp_path: Path) -> None:
    r = _repo(tmp_path)
    (r / "docs" / "d.md").write_text("# D\n\n## A\n\nshort\n\n## B\n\nalso short\n")
    _commit(r, "one")
    assert len(list(MarkdownDocs({"r": r}).scan())) == 1


@live_only
def test_conformance_against_live_docs() -> None:
    src = MarkdownDocs(REPOS)
    stats = check_source(src)
    assert stats["events"] > 80, stats
    print(f"\n  markdown_docs: {stats}, skipped={len(src.skipped)}")


@live_only
def test_live_corpus_has_dated_endings() -> None:
    """36 markdown files have multi-commit chains; some section must have ended."""
    src = MarkdownDocs(REPOS)
    ended = [u for u in src.scan() if u["valid_to"] is not None]
    print(f"\n  sections with a recorded end date: {len(ended)}")
    assert ended, "no valid_to recovered — the git mechanism is not working"


@live_only
def test_declared_types_pick_up_filename_conventions() -> None:
    types = {t.name for t in MarkdownDocs(REPOS).declared_types()}
    assert {"BRD", "IMPL"} <= types
