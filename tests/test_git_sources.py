"""Adapters D and F — the two git-derived sources."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from test_conformance import check_source

from claimbase.core.models import Kind, Trust
from claimbase.sources.git_log import GitLog
from claimbase.sources.pull_requests import PullRequests

REPOS = {
    "guru": Path("/home/ivy/Work/guru"),
    "guru-web": Path("/home/ivy/Work/guru-web"),
    "rellm": Path("/home/ivy/Work/rellm"),
}
CACHE = Path(__file__).resolve().parent.parent / "eval" / ".cache"
LIVE = all((p / ".git").is_dir() for p in REPOS.values())
live_only = pytest.mark.skipif(not LIVE, reason="live repos not present")


# --- git log ------------------------------------------------------------------


@live_only
def test_git_log_conformance() -> None:
    src = GitLog(REPOS)
    stats = check_source(src)
    print(f"\n  git_log: {stats}, skipped={len(src.skipped)}")
    assert stats["events"] > 800, stats


@live_only
def test_merge_commits_are_dropped_and_counted() -> None:
    src = GitLog({"guru": REPOS["guru"]})
    list(src.to_event(u) for u in src.scan())
    reasons = set(src.skipped.values())
    assert "mechanical subject" in reasons
    assert len(src.skipped) > 20, "guru has many merge commits; they must be counted"


@live_only
def test_todo_prefix_links_commits_to_tickets() -> None:
    """The seam working: Adapter D emits an edge to a ticket id without knowing
    Adapter A exists, and they meet at the ref."""
    src = GitLog({"guru": REPOS["guru"]})
    linked = 0
    for u in src.scan():
        ev = src.to_event(u)
        if ev and any(e.rel == "references_ticket" for e in src.edges(ev)):
            linked += 1
    print(f"\n  commits referencing a ticket: {linked}")
    assert linked > 400, "586 guru commits carry a todo: prefix"


@live_only
def test_commit_claims_cannot_be_facts() -> None:
    src = GitLog({"rellm": REPOS["rellm"]})
    ev = next(e for e in (src.to_event(u) for u in src.scan()) if e)
    c = next(iter(src.structured_claims(ev)))
    assert c.trust is Trust.AGENT_GATED and c.kind is not Kind.FACT
    assert c.corroborated, "the diff behind a commit is corroboration"


# --- pull requests ------------------------------------------------------------


@pytest.mark.skipif(not (CACHE / "prs-guru.json").exists(), reason="PR cache not built")
def test_pr_conformance_from_cache() -> None:
    src = PullRequests(REPOS, cache=CACHE)
    stats = check_source(src)
    print(f"\n  pull_requests: {stats}, skipped={len(src.skipped)}")
    assert stats["events"] > 150, stats


def test_unmerged_pr_is_skipped(tmp_path: Path) -> None:
    """A proposal is not a record of work done."""
    (tmp_path / "prs-r.json").write_text(
        json.dumps(
            [
                {"number": 1, "title": "open one", "body": "x", "mergedAt": None, "state": "OPEN"},
                {"number": 2, "title": "merged", "body": "y", "mergedAt": "2026-08-01T00:00:00Z"},
            ]
        )
    )
    src = PullRequests({"r": tmp_path}, cache=tmp_path)
    events = [e for e in (src.to_event(u) for u in src.scan()) if e]
    assert len(events) == 1 and events[0].meta["number"] == 2
    assert src.skipped["r#1"] == "not merged"


def test_pr_claim_is_a_corroborated_decision(tmp_path: Path) -> None:
    (tmp_path / "prs-r.json").write_text(
        json.dumps([{"number": 3, "title": "ship it", "body": "", "mergedAt": "2026-08-01T00:00:00Z"}])
    )
    src = PullRequests({"r": tmp_path}, cache=tmp_path)
    ev = src.to_event(next(src.scan()))
    c = next(iter(src.structured_claims(ev)))
    assert c.kind is Kind.DECISION and c.corroborated and c.valid_from == ev.captured_at


def test_pr_branch_links_to_ticket(tmp_path: Path) -> None:
    (tmp_path / "prs-r.json").write_text(
        json.dumps(
            [
                {
                    "number": 4,
                    "title": "t",
                    "body": "",
                    "mergedAt": "2026-08-01T00:00:00Z",
                    "headRefName": "todo/1360a074",
                }
            ]
        )
    )
    src = PullRequests({"r": tmp_path}, cache=tmp_path)
    ev = src.to_event(next(src.scan()))
    assert any(e.dst.endswith("1360a074") for e in src.edges(ev))


@live_only
def test_commit_bodies_do_not_leak_into_paths() -> None:
    """`--format=...%b` plus `--name-only` has no delimiter between a multi-line
    body and the file list. Splitting on the first newline put body prose into
    `paths`, and those became entities — 6,635 of 11,472 entity rows were commit
    message text before this was found."""
    src = GitLog({"guru": REPOS["guru"]})
    bad = []
    for u in src.scan():
        for p in u["paths"]:
            if any(c.isspace() for c in p) or p.startswith("-"):
                bad.append((u["sha"][:8], p[:60]))
    assert not bad[:5], f"prose leaked into paths: {bad[:5]}"
