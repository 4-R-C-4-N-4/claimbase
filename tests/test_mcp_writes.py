"""Agent writes through MCP (CLAIMBASE_MCP_WRITE=1), the distillation path:
a frontier model working in a project records what it learns, and that record
must be scoped to the project, retrievable at once, and offered at the next
session start."""

import pytest

from conftest import claim_row


@pytest.fixture
def writer_server(db, embed, monkeypatch, tmp_path):
    import claimbase.core.store as store
    import claimbase.mcp_server as m
    from conftest import TEST_DSN, TEST_RO_DSN

    monkeypatch.setattr(store, "DSN", TEST_DSN)
    monkeypatch.setattr(m, "RO_DSN", TEST_RO_DSN)
    monkeypatch.setattr(m, "QUERY_LOG", str(tmp_path / "q.jsonl"))
    m.log = tmp_path / "q.jsonl"
    return m


@pytest.fixture
def repo(tmp_path, monkeypatch):
    from claimbase import projects

    monkeypatch.setattr(projects, "declared", lambda: {})
    root = tmp_path / "fresh-project"
    (root / ".git").mkdir(parents=True)
    (root / "src").mkdir()
    return root


def _count(db):
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM claims")
        return cur.fetchone()[0]


def test_a_write_without_a_project_or_cwd_is_refused(writer_server, db):
    out = writer_server._dispatch("assert", {"text": "Tests run with pytest -q.",
                                             "kind": "practice"})
    assert "error" in out and "cwd" in out["error"]
    assert _count(db) == 0, "nothing lands in the server's default project by accident"


def test_an_unknown_kind_is_an_error_not_a_crash(writer_server, db, repo):
    out = writer_server._dispatch("assert", {"text": "x", "kind": "rule",
                                             "cwd": str(repo)})
    assert "error" in out and "practice" in out["error"]
    assert _count(db) == 0


def test_an_asserted_claim_is_scoped_by_cwd_and_recallable_at_once(writer_server, db, repo):
    out = writer_server._dispatch("assert", {
        "text": "Release builds are produced with `make dist`, never by hand.",
        "kind": "practice", "cwd": str(repo / "src")})
    assert out["project"] == "fresh-project" and out["claim_id"]
    row = claim_row(db, out["claim_id"])
    assert row["corpus"] == "fresh-project" and row["trust"] == "agent"
    assert row["meta"]["asserted"] is True

    hits = writer_server._dispatch("recall", {"query": "how are release builds produced",
                                              "project": "fresh-project"})
    assert [r["id"] for r in hits["results"]] == [out["claim_id"]]
    assert writer_server._dispatch("recall", {"query": "how are release builds produced",
                                              "project": "guru"})["results"] == []


def test_asserted_standing_claims_are_offered_in_the_next_brief(writer_server, db, repo):
    standing = writer_server._dispatch("assert", {
        "text": "Every public function gets a docstring.", "kind": "practice",
        "cwd": str(repo)})
    once = writer_server._dispatch("assert", {
        "text": "The nightly job failed on 2026-11-17 with a timeout.",
        "kind": "observation", "cwd": str(repo)})
    b = writer_server._dispatch("brief", {"cwd": str(repo)})
    ids = [c["id"] for c in b["claims"]]
    assert standing["claim_id"] in ids, "an agent-recorded practice is standing context"
    row = next(c for c in b["claims"] if c["id"] == standing["claim_id"])
    assert row["trust"] == "agent", "shown at the trust it was written with"
    assert standing.get("requested_kind") == "practice", "the cap is reported, not hidden"
    assert once["claim_id"] not in ids, "a one-off observation is an answer, not a brief item"


def test_instructions_describe_the_write_path_only_when_it_is_enabled():
    import claimbase.mcp_server as m

    assert "assert_claim" in m.instructions(True)
    assert "assert_claim" not in m.instructions(False)
    assert "You do not decide what to remember" in m.instructions(False)
