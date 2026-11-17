"""Memory PRs: instant merge, and the three rules that keep it from meaning
"anything can overwrite anything"."""

from datetime import datetime, timedelta, timezone

import pytest

from claimbase import prs
from claimbase.core.models import Trust
from conftest import claim_row, fake_embed, seed_claim

NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


def test_user_pr_merges_at_once(db):
    old = seed_claim(db, "Tags are promoted by auto_promote.py after tagging.")
    pr = prs.open_pr(db, target=old, amendment="Tags are promoted only through the "
                     "/guru-review-tags queue; auto-promote is retired.", now=NOW,
                     embed=fake_embed)
    db.commit()

    assert pr.outcome == "merged"
    was, now = claim_row(db, old), claim_row(db, pr.amendment_claim)
    assert was["status"] == "superseded" and str(was["superseded_by"]) == pr.amendment_claim
    assert was["valid_to"] == NOW, "the old version gets an end date, not a deletion"
    assert now["status"] == "active" and now["origin"] == "stated"
    assert now["trust"] == "human" and str(now["merged_by"]) == pr.id
    assert now["meta"]["memory"] is True, "re-import must know this row is not an adapter's"


def test_agent_reading_does_not_overwrite_a_human_claim(db):
    """Rule 2. The evidence is outranked, so the target keeps being served —
    labelled — and the amendment waits beside it. Nothing blocks."""
    old = seed_claim(db, "The 27B tagger runs with thinking on.", trust="human")
    pr = prs.open_pr(db, target=old, amendment="The 27B tagger runs with thinking off.",
                     author="agent", evidence_text="a blog post said so", now=NOW)
    db.commit()

    assert pr.outcome == "contested"
    assert claim_row(db, old)["status"] == "contested"
    assert claim_row(db, old)["superseded_by"] is None
    assert claim_row(db, pr.amendment_claim)["status"] == "tentative"


def test_agent_pr_merges_against_an_agent_claim_but_cannot_state_a_fact(db):
    """Rule 1. Equal trust merges; the kind cap still applies to what lands."""
    old = seed_claim(db, "sync_corpus.sh uploads the corpus nightly.", trust="agent",
                     kind="fact", source="markdown_docs")
    pr = prs.open_pr(db, target=old, amendment="sync_corpus.sh is run by hand, not nightly.",
                     author="agent", now=NOW)
    db.commit()

    assert pr.outcome == "merged"
    now = claim_row(db, pr.amendment_claim)
    assert now["claim_kind"] == "observation", "an agent's say-so is not a fact"
    assert now["meta"]["capped_from"] == "fact"


def test_distilled_wording_is_gated_however_good_the_evidence(db):
    old = seed_claim(db, "Deploy with deploy.sh from main.", trust="human")
    pr = prs.open_pr(db, target=old, amendment="Deploy with deploy.sh from a release tag.",
                     author="writer", evidence_trust=Trust.HUMAN, distilled=True, now=NOW)
    db.commit()
    assert pr.outcome == "merged", "the user's turn outranks nothing less than itself"
    assert claim_row(db, pr.amendment_claim)["trust"] == "agent_authored_human_gated"


def test_writer_must_state_its_evidence(db):
    old = seed_claim(db, "x is y")
    with pytest.raises(prs.PRError, match="trust of its evidence"):
        prs.open_pr(db, target=old, amendment="x is z", author="writer")


def test_pr_never_crosses_projects(db):
    """Rule 3."""
    other = seed_claim(db, "The auth service issues JWTs.", corpus="guru-web")
    with pytest.raises(prs.PRError, match="never crosses projects"):
        prs.open_pr(db, target=other, amendment="The auth service issues PASETO tokens.",
                    corpus="guru")
    db.rollback()
    assert claim_row(db, other)["status"] == "active"


def test_stale_target_is_refiled_against_the_current_version(db):
    v1 = seed_claim(db, "The brief budget is 300 tokens.")
    a = prs.open_pr(db, target=v1, amendment="The brief budget is 500 tokens.", now=NOW)
    b = prs.open_pr(db, target=v1, amendment="The brief budget is 800 tokens.",
                    now=NOW + timedelta(minutes=1))
    db.commit()

    assert b.refiled and b.target == a.amendment_claim
    assert claim_row(db, a.amendment_claim)["status"] == "superseded"
    assert claim_row(db, b.amendment_claim)["status"] == "active"


def test_revert_is_a_new_version_not_a_rollback(db):
    v1 = seed_claim(db, "Extraction runs nightly at 05:35.")
    a = prs.open_pr(db, target=v1, amendment="Extraction runs weekly.", now=NOW)
    r = prs.revert(db, a.id, reason="misread the crontab", now=NOW + timedelta(hours=1))
    db.commit()

    assert r.kind == "revert" and r.outcome == "merged"
    assert claim_row(db, v1)["status"] == "superseded", "history is not rewritten"
    assert claim_row(db, a.amendment_claim)["status"] == "superseded"
    restored = claim_row(db, r.amendment_claim)
    assert restored["content"] == "Extraction runs nightly at 05:35."
    assert restored["status"] == "active"
    with pytest.raises(prs.PRError, match="already been reverted"):
        prs.revert(db, a.id)


def test_reverting_a_contested_pr_closes_the_contest(db):
    old = seed_claim(db, "Main is protected; changes go through PRs.", trust="human")
    c = prs.open_pr(db, target=old, amendment="Main accepts direct pushes.", author="agent",
                    now=NOW)
    prs.revert(db, c.id, reason="the agent misread a log", now=NOW + timedelta(hours=1))
    db.commit()

    assert claim_row(db, old)["status"] == "active"
    assert "contested_by" not in claim_row(db, old)["meta"]
    assert claim_row(db, c.amendment_claim)["status"] == "retracted"


def test_a_belief_that_keeps_flipping_is_marked_contested(db):
    cur = seed_claim(db, "The default quant is q4_k_m.")
    texts = ["The default quant is q6_k.", "The default quant is q4_k_m again.",
             "The default quant is q6_k after all.", "The default quant is q4_k_m, finally."]
    last = None
    for i, t in enumerate(texts):
        last = prs.open_pr(db, target=cur, amendment=t, now=NOW + timedelta(days=i))
    db.commit()

    assert last.oscillating
    head = claim_row(db, last.amendment_claim)
    assert head["status"] == "contested", "still the newest version, still served, labelled"
    assert head["meta"]["contested_reason"] == "oscillation"


def test_slow_change_is_not_oscillation(db):
    cur = seed_claim(db, "The teacher model is Qwen3.5.")
    last = None
    for i in range(5):
        last = prs.open_pr(db, target=cur, amendment=f"The teacher model is Qwen3.{6 + i}.",
                           now=NOW + timedelta(days=60 * i))
    db.commit()
    assert not last.oscillating


def test_amending_to_the_same_text_is_refused(db):
    old = seed_claim(db, "Ollama serves embeddings on 11434.")
    with pytest.raises(prs.PRError, match="already says"):
        prs.open_pr(db, target=old, amendment="Ollama serves embeddings on 11434.")
