"""brief, inspect, the usage measures, and the import path's stable ids."""

import json
from datetime import datetime, timedelta, timezone

from claimbase import prs, usage
from claimbase.brief import brief, inspect, resolve_id
from claimbase.core.models import Claim, Event, Kind, Trust
from claimbase.core.store import Store, stable_claim_id
from conftest import TEST_RO_DSN, claim_row, seed_claim

NOW = datetime(2026, 11, 16, 12, tzinfo=timezone.utc)


def _log(path, *records):
    with path.open("a") as fh:
        for r in records:
            fh.write(json.dumps(r) + "\n")


def _expose(db, claim, at=NOW, kind="used", turn=None, session="claude:s"):
    with db.cursor() as cur:
        cur.execute(
            """INSERT INTO exposures (claim_id, kind, session_id, turn, at, dedupe)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (claim, kind, session, turn, at, f"{session}:{claim}:{at}"))
    db.commit()


class TestBrief:
    def test_only_vouched_standing_kinds_until_usage_says_otherwise(self, db):
        keep = seed_claim(db, "Tags go through the review queue, never auto-promote.")
        seed_claim(db, "tag_concepts.py printed 412 rows on 2026-08-01.", kind="observation",
                   trust="agent")
        seed_claim(db, "docs/ingest/03-acquire.md documents Acquire.", meta={"field": "heading"})
        b = brief(db, "guru")
        assert [c["id"] for c in b["claims"]] == [keep]

    def test_exposed_claims_come_first_and_any_kind_can_earn_a_place(self, db):
        a = seed_claim(db, "Main is protected; changes go through PRs.")
        earned = seed_claim(db, "llama-server needs --jinja for tool calls to parse.",
                            kind="observation", trust="agent")
        _expose(db, earned)
        b = brief(db, "guru")
        assert [c["id"] for c in b["claims"]] == [earned, a]
        assert b["claims"][0]["exposures"] == 1

    def test_never_another_projects_claims_but_always_the_users(self, db):
        seed_claim(db, "guru-web deploys from a release tag.", corpus="guru-web")
        mine = seed_claim(db, "The user prefers terse workbook docs.", corpus="self",
                          kind="preference")
        here = seed_claim(db, "The 27B tagger runs with thinking on.")
        b = brief(db, "guru")
        assert {c["id"] for c in b["claims"]} == {mine, here}
        assert b["scopes"] == ["guru", "self"]

    def test_budget_is_a_hard_ceiling(self, db):
        for i in range(40):
            seed_claim(db, f"Rule number {i}: the pipeline stage {i} must be run before "
                           f"stage {i + 1} and never skipped for corpus {i * 7}.",
                       asserted_at=NOW - timedelta(days=i))
        b = brief(db, "guru", budget_tokens=200)
        assert b["used_tokens"] <= 200 and b["omitted"] > 0
        assert "stage 0 " in b["claims"][0]["claim"], "newest first when nothing is exposed"

    def test_superseded_and_tentative_stay_out_contested_is_labelled(self, db):
        old = seed_claim(db, "Extraction runs nightly.")
        prs.open_pr(db, target=old, amendment="Extraction runs weekly.", now=NOW)
        seed_claim(db, "A guess from one episode.", status="tentative")
        held = seed_claim(db, "sync_corpus.sh is the owner's to run.")
        prs.open_pr(db, target=held, amendment="Anyone may run sync_corpus.sh.",
                    author="agent", now=NOW)
        db.commit()
        got = {c["claim"]: c.get("status") for c in brief(db, "guru")["claims"]}
        assert got == {"Extraction runs weekly.": None,
                       "sync_corpus.sh is the owner's to run.": "contested"}

    def test_runs_on_the_read_only_role(self, db):
        import psycopg

        seed_claim(db, "Main is protected.")
        with psycopg.connect(TEST_RO_DSN) as ro:
            assert len(brief(ro, "guru")["claims"]) == 1
            assert usage.measures(ro, "guru")["dead_weight"]["standing"] == 1


def test_inspect_shows_evidence_history_prs_and_usage(db):
    old = seed_claim(db, "Staged tags are promoted by auto_promote.py.", source="markdown_docs",
                     trust="agent")
    pr = prs.open_pr(db, target=old, amendment="Staged tags are promoted via the review queue.",
                     evidence_text="owner retired auto-promote in July", now=NOW)
    db.commit()
    _expose(db, pr.amendment_claim)

    was = inspect(db, old[:8])
    assert was["status"] == "superseded"
    assert was["superseded_by"][0]["claim"] == "Staged tags are promoted via the review queue."
    assert was["prs"][0]["role"] == "amended by this PR"

    now = inspect(db, pr.amendment_claim)
    assert now["origin"] == "stated" and now["supersedes"][0]["id"] == old
    assert now["supersedes"][0]["rule"] == "memory_pr"
    assert "owner retired auto-promote" in now["evidence"]["excerpt"]
    assert now["prs"][0]["role"] == "created by this PR"
    assert now["usage"]["exposures"]["used"]["n"] == 1


def test_resolve_id_rejects_ambiguity_and_short_prefixes(db):
    import pytest

    cid = seed_claim(db, "x")
    assert resolve_id(db, cid[:8]) == cid
    with pytest.raises(ValueError, match="too short"):
        resolve_id(db, cid[:3])
    with pytest.raises(ValueError, match="no claim"):
        resolve_id(db, "deadbeef")


class TestUsage:
    def test_sync_reads_old_and_new_log_lines_and_is_idempotent(self, db, tmp_path):
        a = seed_claim(db, "Tags go through the review queue.")
        b = seed_claim(db, "guru-web deploys from a tag.", corpus="guru-web")
        log = tmp_path / "q.jsonl"
        _log(log,
             # Before this branch: no ids, no session, no project.
             {"ts": "2026-08-21T20:07:36+00:00", "client": "hermes-reviewer", "tool": "recall",
              "args": {"query": "how are tags promoted"}, "ms": 40,
              "response": {"results": [{"claim": "Tags go through the review queue."},
                                       {"claim": "a claim since rebuilt away"}]}},
             {"ts": "2026-11-16T10:00:00+00:00", "client": "claude", "session": "mcp-1",
              "project": "guru-web", "tool": "recall", "args": {"query": "deploy"}, "ms": 12,
              "response": {"results": [{"id": b, "claim": "guru-web deploys from a tag."}]}},
             {"ts": "2026-11-16T10:01:00+00:00", "client": "claude", "session": "mcp-1",
              "project": "guru-web", "tool": "feedback",
              "args": {"kind": "helpful", "claim_id": b[:8]},
              "response": {"recorded": "helpful", "claim_id": b}},
             {"ts": "2026-11-16T10:02:00+00:00", "client": "claude", "session": "mcp-1",
              "project": "guru-web", "tool": "recall", "args": {"query": "rollback"},
              "error": "OperationalError: down"})
        log.open("a").write("not json\n")

        n = usage.sync(db, log)
        db.commit()
        assert n == {"lines": 5, "new": 3, "hits": 2, "unmatched": 1, "feedback": 1, "bad": 1}
        again = usage.sync(db, log)
        assert again["new"] == 0 and again["hits"] == 0 and again["feedback"] == 0

        with db.cursor() as cur:
            cur.execute("SELECT claim_id::text, claim_corpus FROM retrieval_hits ORDER BY claim_corpus")
            assert cur.fetchall() == [(a, "guru"), (b, "guru-web")]
            cur.execute("SELECT kind, via FROM exposures WHERE claim_id = %s", (b,))
            assert cur.fetchall() == [], "legacy feedback has no authenticated session"

    def test_miss_rate_separates_missed_from_unknown(self, db, tmp_path):
        used = seed_claim(db, "Deploy from a release tag.")
        idle = seed_claim(db, "The taxonomy lives in taxonomy.toml.")
        log = tmp_path / "q.jsonl"
        rec = lambda ts, q, rows: {  # noqa: E731
            "ts": ts, "session": "mcp-1", "canonical_session": "claude:s", "project": "guru", "tool": "recall",
            "args": {"query": q}, "response": {"results": rows}}
        _log(log,
             rec("2026-11-16T10:00:00+00:00", "how to deploy", [{"id": used, "claim": "x"}]),
             rec("2026-11-16T10:10:00+00:00", "where is taxonomy", [{"id": idle, "claim": "y"}]),
             rec("2026-11-16T10:20:00+00:00", "what is the gpu rule", []),
             # A different day, no session submitted for it: cannot be judged.
             rec("2026-11-10T09:00:00+00:00", "where is taxonomy", [{"id": idle, "claim": "y"}]))
        usage.sync(db, log)
        with db.cursor() as cur:
            cur.execute("""INSERT INTO sessions (id, corpus, harness, started_at, ended_at)
                           VALUES ('claude:s','guru','claude','2026-11-16T09:55:00+00:00',
                                   '2026-11-16T10:40:00+00:00')""")
        _expose(db, used, at=datetime(2026, 11, 16, 10, 5, tzinfo=timezone.utc))
        db.execute("""UPDATE exposures SET source_log = (
            SELECT id FROM retrieval_log WHERE query = 'how to deploy')
            WHERE claim_id = %s AND via = 'writer'""", (used,))

        usage.sync(db, log)  # session capture permits deferred exact binding
        m = usage.measures(db, "guru")["miss_rate"]
        assert (m["recalls"], m["used"], m["missed"], m["empty"], m["unknown"]) == (4, 1, 1, 1, 2)
        assert m["value"] == round(1 / 2, 3)

        d = usage.measures(db, "guru")["dead_weight"]
        assert (d["standing"], d["never_retrieved"]) == (2, 0)

    def test_leak_rate_counts_a_claim_from_outside_the_scope(self, db, tmp_path):
        other = seed_claim(db, "guru-web secret sauce.", corpus="guru-web")
        mine = seed_claim(db, "The user likes terse docs.", corpus="self")
        log = tmp_path / "q.jsonl"
        _log(log, {"ts": "2026-11-16T10:00:00+00:00", "project": "guru", "tool": "recall",
                   "args": {"query": "q"}, "response": {"results": [
                       {"id": other, "claim": "x"}, {"id": mine, "claim": "y"}]}},
                  {"ts": "2026-11-16T10:01:00+00:00", "project": "guru", "tool": "brief",
                   "args": {}, "response": {"claims": [{"id": mine, "claim": "y"}]}})
        usage.sync(db, log)
        m = usage.measures(db, "guru")["leak_rate"]
        assert (m["calls"], m["leaked"], m["value"]) == (2, 1, 0.5)

    def test_revert_rate_and_the_exception_report(self, db, tmp_path):
        a = seed_claim(db, "Extraction runs nightly.")
        b = seed_claim(db, "Main is protected.")
        seed_claim(db, "Nothing ever happened to this one.")
        p1 = prs.open_pr(db, target=a, amendment="Extraction runs weekly.")
        prs.revert(db, p1.id, reason="misread")
        prs.open_pr(db, target=b, amendment="Main takes direct pushes.", author="agent")
        db.commit()
        log = tmp_path / "q.jsonl"
        for minute in (0, 5):
            _log(log, {"ts": (datetime.now(timezone.utc) - timedelta(minutes=minute)).isoformat(),
                       "project": "guru", "tool": "recall", "session": "m",
                       "args": {"query": "What is the GPU rule?"}, "response": {"results": []}})
        usage.sync(db, log)
        db.commit()

        rr = usage.measures(db, "guru")["revert_rate"]
        assert (rr["merged"], rr["reverted"], rr["value"]) == (1, 1, 1.0)
        assert rr["by_author"] == {"user": {"merged": 1, "reverted": 1, "rate": 1.0}}

        r = usage.exception_report(db, "guru")
        assert not r["empty"]
        assert r["reverts"][0]["restored"] == "Extraction runs nightly."
        assert r["contested"][0]["claim"] == "Main is protected."
        assert r["contested"][0]["challenger"] == "Main takes direct pushes."
        assert r["repeated_misses"] == [{**r["repeated_misses"][0],
                                         "query": "what is the gpu rule?", "times": 2}]

    def test_empty_store_has_an_empty_report_and_null_measures(self, db):
        assert usage.exception_report(db, "guru")["empty"]
        m = usage.measures(db, "guru")
        assert m["miss_rate"]["value"] is None and m["activity"]["daily_use_gate"] is False


class TestStableIds:
    """The import path. A nightly compile must not orphan what the memory layer
    has learned about a claim."""

    def _event(self, db, content="doc text"):
        ev = Event(source="markdown_docs", source_ref="guru:docs/x.md@abc", content=content,
                   captured_at=NOW, corpus="rellm-ish")
        eid, _ = Store(db).upsert_event(ev)
        return eid

    def _claims(self, eid, *texts):
        return [Claim(event_id=eid, content=t, kind=Kind.PRACTICE, trust=Trust.HUMAN,
                      asserted_at=NOW) for t in texts]

    def test_reimport_keeps_identity_and_what_was_learned(self, db):
        eid = self._event(db)
        store = Store(db)
        store.replace_claims(eid, self._claims(eid, "A is done this way.", "B is done that way."))
        db.commit()
        a = str(stable_claim_id(eid, "practice", "A is done this way."))
        assert claim_row(db, a)["corpus"] == "rellm-ish", "the event's project, not a constant"
        with db.cursor() as cur:
            cur.execute("UPDATE claims SET embedding = %s WHERE id = %s",
                        (str([0.1] * 768), a))
        _expose(db, a)
        pr = prs.open_pr(db, target=a, amendment="A is done a new way.", now=NOW)
        db.commit()

        store.replace_claims(eid, self._claims(eid, "A is done this way.", "B is done that way."))
        db.commit()

        row = claim_row(db, a)
        assert row["status"] == "superseded" and str(row["superseded_by"]) == pr.amendment_claim
        assert row["valid_to"] == NOW and row["meta"]["superseded_rule"] == "memory_pr"
        with db.cursor() as cur:
            cur.execute("SELECT embedding IS NOT NULL FROM claims WHERE id = %s", (a,))
            assert cur.fetchone()[0], "unchanged text keeps its vector"
            cur.execute("SELECT count(*) FROM exposures WHERE claim_id = %s", (a,))
            assert cur.fetchone()[0] == 1
        assert claim_row(db, pr.amendment_claim)["status"] == "active", "not an adapter's row"

    def test_a_claim_the_source_dropped_is_removed_and_its_dependents_revived(self, db):
        eid = self._event(db)
        store = Store(db)
        store.replace_claims(eid, self._claims(eid, "new wording"))
        new = str(stable_claim_id(eid, "practice", "new wording"))
        old = seed_claim(db, "old wording")
        with db.cursor() as cur:
            cur.execute("UPDATE claims SET status='superseded', superseded_by=%s WHERE id=%s",
                        (new, old))
        db.commit()

        store.replace_claims(eid, self._claims(eid, "newer wording"))
        db.commit()
        with db.cursor() as cur:
            cur.execute("SELECT count(*) FROM claims WHERE id = %s", (new,))
            assert cur.fetchone()[0] == 0
        assert claim_row(db, old)["status"] == "active"

    def test_duplicate_claims_on_one_event_collapse(self, db):
        eid = self._event(db)
        n = Store(db).replace_claims(eid, self._claims(eid, "same", "same"))
        assert n == 1

    def test_reimport_leaves_extracted_and_memory_claims_alone(self, db):
        """The guard that once cost 7,520 extracted claims, asserted as
        behaviour: rows the importer did not produce are not its to delete,
        and neither is what they superseded."""
        eid = self._event(db)
        store = Store(db)
        store.replace_claims(eid, self._claims(eid, "adapter claim"))
        adapter = str(stable_claim_id(eid, "practice", "adapter claim"))
        ids = {}
        with db.cursor() as cur:
            for name, meta in (("extracted", {"extractor_version": "teacher-27b-v2"}),
                               ("memory", {"memory": True})):
                cur.execute(
                    """INSERT INTO claims (id, corpus, event_id, content, claim_kind, trust, meta)
                       VALUES (gen_random_uuid(), 'rellm-ish', %s, %s, 'observation', 'agent', %s)
                       RETURNING id""", (eid, f"{name} claim", json.dumps(meta)))
                ids[name] = str(cur.fetchone()[0])
        victim = seed_claim(db, "superseded by an extracted claim")
        with db.cursor() as cur:
            cur.execute("UPDATE claims SET status='superseded', superseded_by=%s WHERE id=%s",
                        (ids["extracted"], victim))
        db.commit()

        store.replace_claims(eid, [])  # the adapter now yields nothing for this event
        db.commit()

        with db.cursor() as cur:
            cur.execute("SELECT id::text FROM claims WHERE event_id = %s", (eid,))
            left = {r[0] for r in cur.fetchall()}
        assert left == {ids["extracted"], ids["memory"]} and adapter not in left
        assert claim_row(db, victim)["status"] == "superseded"
