"""Pure-logic tests for the 2026-08-21 recall changes: near-dup collapse,
scaffold identification, path/node token extraction. The DB-touching legs are
covered by the eval harness (eval/baselines.py) against the live store; these
lock the deterministic parts."""

from datetime import datetime, timezone

from claimbase.recall import (
    Hit,
    _collapse_near_dups,
    _near_dup,
    _path_tokens,
    classify_intent,
)


def _hit(content: str, score: float, cosine: float = 0.7, scaffold: bool = False) -> Hit:
    return Hit(
        claim_id=content[:8], content=content, kind="fact", trust="agent",
        asserted_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        source_ref="guru:docs/x.md@abc", source="markdown_docs",
        cosine=cosine, score=score, superseded_count=0, scaffold=scaffold,
    )


class TestNearDup:
    def test_reworded_re_extraction_is_a_dup(self):
        # The observed class: same fact re-extracted from adjacent revisions.
        a = ("The guru system uses a local SQLite database (data/guru.db) for "
             "pipeline writes and an exported Postgres database on a VPS for guru-web reads.")
        b = ("The guru system uses a local SQLite database at data/guru.db where "
             "the pipeline writes and an exported Postgres database on a VPS where guru-web reads.")
        assert _near_dup(a, b)

    def test_same_topic_different_fact_is_not_a_dup(self):
        # Corroboration must survive: distinct claims about one subject stay.
        a = "scripts/sync_taxonomy.py reads concepts/taxonomy.toml and populates concept_families."
        b = "sync_taxonomy.py does not drop orphan nodes, so stale concept entries remain."
        assert not _near_dup(a, b)

    def test_empty_content_is_never_a_dup(self):
        assert not _near_dup("", "anything at all")


class TestCollapse:
    def test_dup_family_yields_one_slot(self):
        a = _hit("alpha beta gamma delta epsilon zeta", 3.0)
        b = _hit("alpha beta gamma delta epsilon zeta eta", 2.0)  # near-dup of a
        c = _hit("entirely different subject matter here", 1.0)
        out = _collapse_near_dups([a, b, c], k=2)
        assert [h.score for h in out] == [3.0, 1.0]

    def test_order_preserved_and_k_respected(self):
        contents = [
            "the chunker strips apparatus before tokenizing",
            "embeddings live in sqlite alongside curation rows",
            "node fifteen belongs to the user alone",
            "taxonomy sync never deletes orphan concepts",
            "review verdicts queue without applying anything",
            "derived parallels rebuild from accepted tags",
        ]
        hits = [_hit(c, 10.0 - i) for i, c in enumerate(contents)]
        out = _collapse_near_dups(hits, k=4)
        assert len(out) == 4
        assert [h.score for h in out] == sorted([h.score for h in out], reverse=True)


class TestPathTokens:
    def test_doc_path(self):
        toks = _path_tokens("What failure modes are in docs/ingest/03-acquire.md?")
        assert "docs/ingest/03-acquire.md" in toks

    def test_bare_filename(self):
        assert "chunk.py" in _path_tokens("why does chunk.py refuse a bare run")

    def test_node_number_maps_to_doc_fragment(self):
        # "workbook node 3" was the original miss: the doc is 03-acquire.md.
        toks = _path_tokens("What does workbook node 3 (acquire) do?")
        assert "/03-" in toks
        assert "/04-" in _path_tokens("how does node 04 survey boilerplate")

    def test_pass_d_node(self):
        assert "/d3-" in _path_tokens("why does D3 review converge the template")

    def test_plain_prose_yields_nothing(self):
        assert _path_tokens("why are tags applied flat at the concept level") == set()


class TestIntent:
    def test_mechanism_still_wins_over_current(self):
        # Guarded behaviour from before the change: "still" must not flip it.
        assert classify_intent("why is staged_edges.status still pending?") == "mechanism"
