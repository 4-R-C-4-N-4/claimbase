"""The writer, end to end against the scratch database, with a scripted judge
standing in for the local model. What is under test is everything around the
judgment: that a verdict turns into the right rows, and that nothing turns
into rows without one."""

import json
from datetime import datetime, timezone

import pytest

from claimbase import sessions, usage, writer
from claimbase.sessions import Session, Turn
from claimbase.writer import Verdict
from conftest import claim_row, seed_claim

T0 = "2026-11-16T10:00:00+00:00"


class Scripted:
    """Answers by episode type; records what it was shown."""

    name = "scripted"

    def __init__(self, **by_type):
        self.by_type, self.seen = by_type, []

    def score(self, episode_type, text, context, candidates):
        self.seen.append((episode_type, text, context, candidates))
        v = self.by_type.get(episode_type, Verdict("nothing"))
        return v(candidates) if callable(v) else v


def _session(sid, *turns, project="guru", outcome=None):
    return Session("claude", sid, list(turns), project=project, outcome=outcome,
                   started_at=T0, ended_at="2026-11-16T10:30:00+00:00")


def _trigger(db, sid):
    with db.cursor() as cur:
        cur.execute("""SELECT type, rule, relation, claim_id, pr_id, judge, scored_at
                         FROM triggers WHERE session_id = %s ORDER BY turn""", (sid,))
        cols = "type rule relation claim_id pr_id judge scored_at".split()
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _count(db, sql, *args):
    with db.cursor() as cur:
        cur.execute(sql, args)
        return cur.fetchone()[0]


CORRECTION = (
    Turn("user", "promote the new tags", ts=T0),
    Turn("assistant", "Running auto_promote.py over the staged tags.", ts=T0),
    Turn("user", "no, don't run auto-promote — tags only go through the review queue", ts=T0),
)


def test_ingest_records_everything_and_judges_nothing(db):
    s = _session("s1", *CORRECTION, outcome="abandoned")
    r = writer.ingest(db, s)
    db.commit()

    assert r == {"session": "claude:s1", "project": "guru", "turns": 3,
                 "episodes": 3, "triggers": 1, "used": 0}
    assert _count(db, "SELECT count(*) FROM events WHERE source = 'session' AND corpus = 'guru'") == 3
    assert _count(db, "SELECT count(*) FROM claims") == 0, "no claim without a verdict"
    t = _trigger(db, "claude:s1")[0]
    assert t["type"] == "correction" and t["scored_at"] is None

    writer.ingest(db, s)  # the same transcript again
    db.commit()
    assert _count(db, "SELECT count(*) FROM events") == 3
    assert _count(db, "SELECT count(*) FROM triggers") == 1


def test_user_correction_becomes_a_pr_that_merges_at_once(db, embed):
    old = seed_claim(db, "Staged tags are promoted by running auto_promote.py.",
                     trust="human", kind="practice")
    s = _session("s1", *CORRECTION)
    writer.ingest(db, s)
    judge = Scripted(correction=Verdict(
        "contradicting", "Staged tags are promoted only through the review queue; "
        "auto_promote.py is not run.", "practice", 0))
    tally = writer.score(db, s, judge)

    assert tally["contradicting"] == 1 and tally["contested"] == 0
    assert claim_row(db, old)["status"] == "superseded"
    t = _trigger(db, "claude:s1")[0]
    new = claim_row(db, t["claim_id"])
    assert new["status"] == "active" and new["origin"] == "stated"
    assert new["trust"] == "agent_authored_human_gated", "the wording is the judge's"
    assert new["claim_kind"] == "practice"
    assert t["pr_id"] and t["relation"] == "contradicting" and t["judge"] == "scripted"
    # The judge saw the user's turn marked, and the store's candidate.
    _, _, context, cands = judge.seen[0]
    assert ">> USER: no, don't run auto-promote" in context
    assert cands == ["Staged tags are promoted by running auto_promote.py."]


def test_tool_failure_cannot_overwrite_what_a_human_stated(db, embed, monkeypatch):
    # The pre-filter has its own test; the stand-in embedder's cosines are not
    # the real model's, so it is taken out of the way here.
    monkeypatch.setattr(writer, "FAILURE_MIN_COSINE", 0.0)
    old = seed_claim(db, "sync_corpus.sh uploads the corpus to the VPS.", trust="human")
    s = _session(
        "s2", Turn("user", "sync the corpus", ts=T0),
        Turn("tool_call", "", tool="Bash", args={"command": "sync_corpus.sh"}, call_id="c"),
        Turn("tool_result", "sync_corpus.sh: corpus upload to VPS refused", is_error=True,
             call_id="c", tool="Bash", args={"command": "sync_corpus.sh"}, ts=T0))
    writer.ingest(db, s)
    tally = writer.score(db, s, Scripted(tool_failure=Verdict(
        "contradicting", "sync_corpus.sh no longer uploads the corpus to the VPS.",
        "observation", 0)))

    assert tally["contested"] == 1
    assert claim_row(db, old)["status"] == "contested", "still served, labelled"
    amend = claim_row(db, _trigger(db, "claude:s2")[0]["claim_id"])
    assert amend["status"] == "tentative" and amend["trust"] == "agent"
    with db.cursor() as cur:
        cur.execute("SELECT kind, outcome, evidence_trust FROM memory_prs")
        assert cur.fetchone() == ("narrowing", "contested", "agent")


def test_a_failure_that_implicates_nothing_is_not_judged(db, embed):
    seed_claim(db, "The concept taxonomy lives in concepts/taxonomy.toml.")
    s = _session(
        "s2b", Turn("user", "build it", ts=T0),
        Turn("tool_call", "", tool="Bash", args={"command": "cargo build"}, call_id="c"),
        Turn("tool_result", "error[E0432]: unresolved import", is_error=True, call_id="c",
             ts=T0))
    writer.ingest(db, s)
    judge = Scripted(tool_failure=Verdict("novel", "cargo build fails.", "observation"))
    tally = writer.score(db, s, judge)
    assert tally["nothing"] == 1 and not judge.seen, "no model call for a transient failure"
    t = _trigger(db, "claude:s2b")[0]
    assert t["judge"] == "prefilter:no-implicated-claim" and t["scored_at"] is not None


def test_what_the_user_states_stands_at_once(db, embed):
    s = _session("s3", Turn("user", "from now on never push to guru main, open a PR", ts=T0))
    writer.ingest(db, s)
    writer.score(db, s, Scripted(decision=Verdict(
        "novel", "Changes to guru go through a pull request; main is never pushed to "
        "directly.", "practice")))
    c = claim_row(db, _trigger(db, "claude:s3")[0]["claim_id"])
    assert c["status"] == "active" and c["origin"] == "stated" and c["corpus"] == "guru"
    assert c["meta"]["memory"] and c["meta"]["trigger"] == "decision"


def test_a_preference_belongs_to_the_user_not_the_project(db, embed):
    s = _session("s4", Turn("user", "remember I prefer terse workbook-style docs", ts=T0))
    writer.ingest(db, s)
    writer.score(db, s, Scripted(decision=Verdict(
        "novel", "The user prefers terse, workbook-register documentation.", "preference")))
    assert claim_row(db, _trigger(db, "claude:s4")[0]["claim_id"])["corpus"] == "self"


@pytest.mark.parametrize("correction,claim", [
    ("No, for this specific project I prefer tabs for indentation.",
     "The user prefers tabs for indentation."),
    ("No, in our newly migrated repository I prefer tabs for indentation.",
     "The user prefers tabs for indentation."),
    ("No, I prefer tabs for indentation.",
     "The user prefers tabs in the currently checked-out codebase."),
    ("No, that file name is wrong for this project. Report files here are always "
     "named rpt_YYYYMMDD.md directly under reports/.",
     "Report files in this project are always named rpt_YYYYMMDD.md under reports/."),
    ("No, in this repository I prefer tabs for indentation.",
     "The user prefers tabs for indentation."),
    ("No, here I prefer local overrides instead of changing generated defaults.",
     "The user prefers local configuration overrides."),
    ("No, I prefer short filenames.",
     "In this project the user prefers short filenames."),
])
def test_project_correction_cannot_escape_scope_as_a_preference(db, embed, correction, claim):
    s = _session("scoped-preference", Turn("assistant", "Done.", ts=T0),
                 Turn("user", correction, ts=T0))
    writer.ingest(db, s)
    writer.score(db, s, Scripted(correction=Verdict("novel", claim, "preference")))
    c = claim_row(db, _trigger(db, s.id)[0]["claim_id"])
    assert c["corpus"] == "guru"
    assert _count(db, "SELECT count(*) FROM claims WHERE corpus = 'self'") == 0


def _lookup_session(sid):
    return _session(
        sid, Turn("user", "deploy guru-web", ts=T0),
        Turn("tool_call", "", tool="Read", args={"file_path": "docs/deploy.md"}, call_id="c"),
        Turn("tool_result", "Deploy guru-web by running deploy.sh from a release tag.",
             call_id="c", ts=T0))


def test_an_observation_waits_for_a_second_independent_episode(db, embed):
    """Need-driven collection: the deploy command enters the first time an
    agent has to look it up *again*, tentative, and stands once another
    session supports it."""
    judge = Scripted(repeat_lookup=Verdict(
        "novel", "guru-web is deployed by running deploy.sh from a release tag.", "practice"))

    writer.ingest(db, _lookup_session("a"))
    assert not _trigger(db, "claude:a"), "first lookup is just a lookup"

    b = _lookup_session("b")
    writer.ingest(db, b)
    writer.score(db, b, judge)
    t = _trigger(db, "claude:b")[0]
    assert t["type"] == "repeat_lookup"
    first = claim_row(db, t["claim_id"])
    assert first["status"] == "tentative" and first["origin"] == "observed"
    assert first["claim_kind"] == "observation", "an agent's reading is not a practice"

    # A different project's session saying the same thing must not promote it.
    with db.cursor() as cur:
        cur.execute("""INSERT INTO sessions (id, corpus, harness) VALUES ('claude:x','guru','claude')""")
        cur.execute("""INSERT INTO session_lookups VALUES ('claude:x','guru','read:docs/other.md',1)""")
    c = _session(
        "c", Turn("user", "ship it", ts=T0),
        Turn("tool_call", "", tool="Read", args={"file_path": "docs/other.md"}, call_id="c"),
        Turn("tool_result", "Deploy guru-web by running deploy.sh from a release tag.",
             call_id="c", ts=T0))
    writer.ingest(db, c)
    tally = writer.score(db, c, judge)
    assert tally["promoted"] == 1
    assert _trigger(db, "claude:c")[0]["claim_id"] == t["claim_id"]
    promoted = claim_row(db, t["claim_id"])
    assert promoted["status"] == "active" and len(promoted["meta"]["evidence"]) == 2
    assert _count(db, "SELECT count(*) FROM claims WHERE meta ? 'memory'") == 1


def test_a_correction_the_store_already_held_is_a_repeat_correction(db, embed):
    held = seed_claim(db, "Tags are promoted only through the review queue, never auto-promote.")
    s = _session("s5", *CORRECTION)
    writer.ingest(db, s)
    writer.score(db, s, Scripted(correction=Verdict(
        "predicted", "Tags only go through the review queue.", "practice", 0)))

    assert _count(db, "SELECT count(*) FROM exposures WHERE claim_id = %s AND kind = 'predicted'",
                  held) == 1
    assert _count(db, "SELECT count(*) FROM claims") == 1, "nothing new to add"
    m = usage.measures(db, "guru")["repeat_corrections"]
    assert m == {**m, "value": 1.0, "corrections": 1, "repeat": 1}


def test_judge_missing_a_duplicate_does_not_create_one(db, embed):
    held = seed_claim(db, "The user prefers terse workbook register documentation.",
                      corpus="self", kind="preference")
    s = _session("s6", Turn("user", "remember I prefer terse workbook-style docs", ts=T0))
    writer.ingest(db, s)
    writer.score(db, s, Scripted(decision=Verdict(
        "novel", "The user prefers terse workbook register documentation.", "preference")))
    t = _trigger(db, "claude:s6")[0]
    assert t["relation"] == "predicted" and str(t["claim_id"]) == held
    assert _count(db, "SELECT count(*) FROM claims") == 1


def test_a_failing_judge_leaves_the_trigger_for_next_time(db, embed):
    class Broken:
        name = "broken"

        def score(self, *a):
            return writer.parse_verdict("I think the answer is probably yes", 0)

    s = _session("s7", *CORRECTION)
    writer.ingest(db, s)
    tally = writer.score(db, s, Broken())
    assert tally["failed"] == 1 and tally["scored"] == 0
    assert _trigger(db, "claude:s7")[0]["scored_at"] is None
    assert _count(db, "SELECT count(*) FROM claims") == 0


def test_use_is_attributed_from_the_transcript(db, embed):
    used = seed_claim(db, "guru-web deploys run deploy.sh from a release tag on the VPS.")
    ignored = seed_claim(db, "The concept taxonomy lives in concepts/taxonomy.toml.")
    result = json.dumps({"results": [
        {"id": used, "claim": "guru-web deploys run deploy.sh from a release tag on the VPS."},
        {"id": ignored, "claim": "The concept taxonomy lives in concepts/taxonomy.toml."}]})
    s = _session(
        "s8", Turn("user", "deploy", ts=T0),
        Turn("tool_call", "", tool="mcp__claimbase__recall", args={"query": "deploy"}, call_id="r"),
        Turn("tool_result", result, call_id="r", ts=T0),
        Turn("assistant", "I'll check out the release tag, then run deploy.sh on the VPS.",
             ts="2026-11-16T10:05:00+00:00"))
    assert writer.ingest(db, s)["used"] == 1
    writer.ingest(db, s)
    db.commit()
    assert _count(db, "SELECT count(*) FROM exposures WHERE claim_id = %s", used) == 1
    assert _count(db, "SELECT count(*) FROM exposures WHERE claim_id = %s", ignored) == 0


def test_run_drains_the_spool_and_scores_later(db, embed, tmp_path):
    seed_claim(db, "Staged tags are promoted by running auto_promote.py.")
    sessions.submit(_session("s9", *CORRECTION), spool=tmp_path)
    quiet = lambda *_: None  # noqa: E731

    first = writer.run(db, judge=None, spool=tmp_path, log=quiet)
    assert first["sessions"] == 1 and first["triggers_waiting"] == 1
    assert not sessions.pending(tmp_path) and len(list((tmp_path / "done").iterdir())) == 1
    assert _count(db, "SELECT count(*) FROM sessions WHERE processed_at IS NULL") == 1

    second = writer.run(db, judge=Scripted(correction=Verdict(
        "contradicting", "Staged tags go through the review queue only.", "practice", 0)),
        spool=tmp_path, log=quiet)
    assert second["sessions"] == 0 and second["score"]["contradicting"] == 1
    assert _count(db, "SELECT count(*) FROM sessions WHERE processed_at IS NULL") == 0
    assert _count(db, "SELECT count(*) FROM memory_prs WHERE outcome = 'merged'") == 1


class TestParseVerdict:
    def test_null_claim_is_nothing_whatever_else_it_says(self):
        v = writer.parse_verdict('{"claim": null, "relation": "novel", "kind": "fact"}', 3)
        assert v.relation == "nothing"

    def test_target_is_one_based_and_bounded(self):
        v = writer.parse_verdict('{"claim": "x is y", "relation": "contradicting", "target": 2}', 3)
        assert v.target == 1
        v = writer.parse_verdict('{"claim": "x is y", "relation": "contradicting", "target": 9}', 3)
        assert v.relation == "novel" and v.target is None

    def test_reads_through_fences_and_preamble(self):
        v = writer.parse_verdict('Sure.\n```json\n{"claim": "x is y", "kind": "wat", '
                                 '"relation": "novel", "target": null}\n```', 0)
        assert v.claim == "x is y" and v.kind == "observation"

    def test_no_json_raises(self):
        with pytest.raises(ValueError):
            writer.parse_verdict("no idea", 0)


def test_a_hook_injected_brief_is_attributed_through_the_query_log(db, embed, tmp_path):
    """A harness hook puts the brief in front of the model without a tool call,
    so the transcript holds no claimbase result. The log does."""
    cid = seed_claim(db, "Report files are named rpt_YYYYMMDD.md under reports/.")
    log = tmp_path / "q.jsonl"
    log.write_text(json.dumps({
        "ts": T0, "client": "hermes-sandbox", "session": "h-77", "canonical_session": "hermes:h-77", "project": "guru",
        "tool": "brief", "args": {},
        "response": {"claims": [{"id": cid, "claim": "Report files are named "
                                 "rpt_YYYYMMDD.md under reports/."}]}}) + "\n")
    usage.sync(db, log)
    s = Session("hermes", "h-77", [
        Turn("user", "write up today's numbers", ts=T0),
        Turn("tool_call", "", tool="write_file",
             args={"path": "reports/rpt_20261116.md", "content": "…"},
             ts="2026-11-16T10:01:00+00:00"),
        Turn("assistant", "Saved the report as reports/rpt_20261116.md, named per the "
             "rpt_YYYYMMDD.md convention for report files.",
             ts="2026-11-16T10:02:00+00:00")],
        project="guru", started_at=T0, ended_at="2026-11-16T10:02:00+00:00")
    assert writer.ingest(db, s)["used"] == 1
    db.commit()
    assert usage.measures(db, "guru")["dead_weight"]["never_retrieved"] == 0
