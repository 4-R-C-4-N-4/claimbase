"""The memory tools as a harness sees them.

Two levels: the dispatch seam in-process (fast, with the stand-in embedder),
and the real stdio server as a subprocess pointed at the scratch database —
because "the harness contract is three calls" is a claim about the wire, not
about a Python function."""

import asyncio
import json
import os
from pathlib import Path

import pytest

from claimbase import sessions, usage
from conftest import TEST_DSN, TEST_RO_DSN, claim_row, seed_claim

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "bin" / "python"


@pytest.fixture
def server(db, embed, monkeypatch, tmp_path):
    import claimbase.core.store as store
    import claimbase.mcp_server as m

    monkeypatch.setattr(store, "DSN", TEST_DSN)
    monkeypatch.setattr(m, "RO_DSN", TEST_RO_DSN)
    monkeypatch.setattr(m, "QUERY_LOG", str(tmp_path / "q.jsonl"))
    monkeypatch.setattr(m, "SESSION", "mcp-test")
    monkeypatch.setattr(m, "CLIENT", "pytest")
    monkeypatch.setattr(sessions, "SPOOL", tmp_path / "spool")
    m.log = tmp_path / "q.jsonl"
    return m


def _lines(m):
    return [json.loads(l) for l in m.log.read_text().splitlines()]


def test_recall_is_project_scoped_and_its_log_line_round_trips(server, db):
    here = seed_claim(db, "guru tags go through the review queue before promotion.")
    seed_claim(db, "guru-web tags are rendered from the review queue export.", corpus="guru-web")

    out = server._dispatch("recall", {"query": "how do tags get through the review queue",
                                      "k": 5, "project": None})
    assert out["project"] == "guru"
    assert [r["id"] for r in out["results"]] == [here], "another project's claim is not returned"

    there = server._dispatch("recall", {"query": "tags review queue", "project": "guru-web"})
    assert there["project"] == "guru-web" and len(there["results"]) == 1

    rec = _lines(server)[0]
    assert rec["session"] == "mcp-test" and rec["project"] == "guru"
    n = usage.sync(db, server.log)
    db.commit()
    assert n["new"] == 2 and n["hits"] == 2 and n["unmatched"] == 0
    assert usage.measures(db, "guru")["leak_rate"]["leaked"] == 0


def test_contested_claims_are_served_with_their_label(server, db):
    from claimbase import prs

    held = seed_claim(db, "The 27B tagger runs with thinking on.")
    prs.open_pr(db, target=held, amendment="The 27B tagger runs with thinking off.",
                author="agent")
    db.commit()
    out = server._dispatch("recall", {"query": "does the 27B tagger run with thinking"})
    assert [(r["id"], r.get("status")) for r in out["results"]] == [(held, "contested")]


def test_brief_resolves_the_project_from_a_working_directory(server, db, monkeypatch, tmp_path):
    from claimbase import projects

    monkeypatch.setattr(projects, "declared", lambda: {"guru": [tmp_path / "rellm"]})
    seed_claim(db, "Main is protected; changes go through PRs.")
    out = server._dispatch("brief", {"cwd": str(tmp_path / "rellm" / "out")})
    assert out["project"] == "guru" and len(out["claims"]) == 1
    assert out["_note"] == server.UNTRUSTED
    assert _lines(server)[0]["project"] == "guru"


def test_feedback_writes_no_row_and_still_counts(server, db):
    cid = seed_claim(db, "Deploy from a release tag.")
    assert server._dispatch("feedback", {"kind": "great"})["error"]
    assert server._dispatch("feedback", {"kind": "helpful"})["error"]
    out = server._dispatch("feedback", {"kind": "helpful", "claim_id": cid[:8]})
    assert out == {"recorded": "helpful", "claim_id": cid}
    server._dispatch("feedback", {"kind": "missed", "note": "the GPU release rule"})

    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM feedback")
        assert cur.fetchone()[0] == 0, "the server has not written to the database"
    usage.sync(db, server.log)
    db.commit()
    with db.cursor() as cur:
        cur.execute("SELECT kind, claim_id::text, note FROM feedback ORDER BY ts")
        assert cur.fetchall() == [("helpful", cid, None), ("missed", None, "the GPU release rule")]
        cur.execute("SELECT kind FROM exposures WHERE claim_id = %s", (cid,))
        assert cur.fetchall() == [("used",)]


def test_submit_session_queues_redacted_and_keeps_the_transcript_out_of_the_log(server, db):
    out = server._dispatch("submit_session", {
        "outcome": "done", "project": "guru",
        "messages": [{"role": "user", "content": "the token is sk-abcdefghijklmnopqrstuvwx"},
                     {"role": "assistant", "content": "noted"},
                     {"role": "user", "content": "no, never store tokens in the repo"}]})
    assert out["queued"] == "pytest:mcp-test" and out["turns"] == 3
    assert out["redactions"] == {"api_key": 1}
    queued = sessions.pending()
    assert len(queued) == 1 and "sk-abcdef" not in queued[0].read_text()
    assert "messages" not in _lines(server)[0]["args"]
    assert "sk-abcdef" not in server.log.read_text()


def test_submit_session_will_not_read_an_arbitrary_file(server):
    out = server._dispatch("submit_session", {"transcript_path": "~/.ssh/id_rsa"})
    assert "not under a known harness session root" in out["error"]
    assert server._dispatch("submit_session", {})["error"]


def test_agent_pr_needs_evidence_and_cannot_overrule_a_person(server, db):
    human = seed_claim(db, "sync_corpus.sh is run only by the owner.")
    doc = seed_claim(db, "The nightly cron runs at 05:35.", trust="agent", source="markdown_docs")

    assert "evidence" in server._dispatch("open_pr", {
        "claim_id": doc, "amendment": "The nightly cron runs at 04:00.", "evidence": " "})["error"]
    ok = server._dispatch("open_pr", {
        "claim_id": doc[:8], "amendment": "The nightly cron runs at 04:00.",
        "evidence": "crontab -l: `0 4 * * * cron_compile.sh`"})
    assert ok["outcome"] == "merged"
    assert claim_row(db, ok["amendment_claim"])["trust"] == "agent"

    no = server._dispatch("open_pr", {
        "claim_id": human, "amendment": "Anyone may run sync_corpus.sh.",
        "evidence": "a README said so"})
    assert no["outcome"] == "contested" and "stands" in no["note"]
    assert claim_row(db, human)["status"] == "contested"


def test_stats_carries_the_measures_and_the_exception_report(server, db):
    seed_claim(db, "Main is protected.")
    out = server._dispatch("stats", {"project": None})
    assert out["project"] == "guru" and out["claims"] == 1
    assert out["measures"]["dead_weight"]["never_retrieved"] == 1
    assert out["exceptions"]["empty"] is True


def test_inspect_reports_a_bad_id_instead_of_raising(server, db):
    assert server._dispatch("inspect", {"claim_id": "deadbeef"}) == {"error": "no claim deadbeef"}


# --- over the wire -----------------------------------------------------------


async def _call(env, calls):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(command=str(PYTHON), args=["-m", "claimbase.mcp_server"],
                                   env=env)
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            names = {t.name for t in (await s.list_tools()).tools}
            out = []
            for name, args in calls:
                res = await s.call_tool(name, args)
                out.append(res.content[0].text if res.content else "")
            return names, out


@pytest.mark.skipif(not PYTHON.exists(), reason="venv not built")
@pytest.mark.timeout(120)
def test_the_harness_contract_over_stdio(db, tmp_path):
    """brief at start, feedback during, submit_session at end — as a real MCP
    client, against a server that cannot write to the database."""
    cid = seed_claim(db, "Changes to guru go through a pull request, never a push to main.")
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"),
               CLAIMBASE_DSN=TEST_DSN, CLAIMBASE_RO_DSN=TEST_RO_DSN,
               CLAIMBASE_QUERY_LOG=str(tmp_path / "q.jsonl"),
               CLAIMBASE_SPOOL=str(tmp_path / "spool"),
               CLAIMBASE_CLIENT="wire", CLAIMBASE_SESSION="wire-1")
    env.pop("CLAIMBASE_MCP_WRITE", None)

    names, out = asyncio.new_event_loop().run_until_complete(_call(env, [
        ("brief", {}),
        ("inspect", {"claim_id": cid}),
        ("feedback", {"kind": "helpful", "claim_id": cid}),
        ("submit_session", {"outcome": "merged", "messages": [
            {"role": "user", "content": "open the PR"},
            {"role": "assistant", "content": "Opened."}]}),
        ("open_pr", {"claim_id": cid, "amendment": "x", "evidence": "y"}),
    ]))

    assert {"brief", "recall", "inspect", "feedback", "submit_session", "stats"} <= names
    assert "open_pr" not in names and "assert_claim" not in names
    brief, inspected, fb, sub, pr = out
    assert json.loads(brief)["claims"][0]["id"] == cid
    assert json.loads(inspected)["evidence"]["source"] == "assert"
    assert json.loads(fb)["recorded"] == "helpful"
    assert json.loads(sub)["queued"] == "wire:wire-1"
    assert "Unknown tool" in pr, "absent, not merely hidden"
    assert claim_row(db, cid)["status"] == "active"

    log = [json.loads(l) for l in (tmp_path / "q.jsonl").read_text().splitlines()]
    assert [l["tool"] for l in log] == ["brief", "inspect", "feedback", "submit_session"]
    assert {l["session"] for l in log} == {"wire-1"}
    assert len(list((tmp_path / "spool" / "inbox").iterdir())) == 1
