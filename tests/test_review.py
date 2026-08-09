"""Review queue — the append-only discipline and the sentence splitter."""

from __future__ import annotations

from pathlib import Path

from claimbase.review.queue import (
    Decision,
    DecisionLog,
    Item,
    split_sentences,
    to_gold_jsonl,
)


def test_decisions_are_appended_never_edited(tmp_path: Path) -> None:
    """A changed verdict is a new line superseding the old one, so a mis-click is
    recoverable and the grading history stays queryable — the same discipline the
    capture log uses."""
    log = DecisionLog(tmp_path / "d.jsonl")
    log.append(Decision("i1", "graded", {"marks": {"0": "fact"}}))
    log.append(Decision("i1", "graded", {"marks": {"0": "hypothesis"}}))
    assert len(log.path.read_text().strip().splitlines()) == 2, "both lines kept"
    assert log.latest()["i1"]["payload"]["marks"]["0"] == "hypothesis", "last wins"


def test_skip_does_not_count_as_decided(tmp_path: Path) -> None:
    log = DecisionLog(tmp_path / "d.jsonl")
    log.append(Decision("i1", "skip", {}))
    log.append(Decision("i2", "graded", {"marks": {}}))
    assert log.decided_ids() == {"i2"}


def test_graded_with_no_marks_is_still_a_decision(tmp_path: Path) -> None:
    """A segment containing no claims is a real and valuable grade — the negative
    set matters as much as the positives (PLAN P0.0)."""
    log = DecisionLog(tmp_path / "d.jsonl")
    log.append(Decision("i1", "graded", {"marks": {}}))
    assert "i1" in log.decided_ids()


def test_export_only_includes_graded(tmp_path: Path) -> None:
    log = DecisionLog(tmp_path / "d.jsonl")
    items = {
        "a": Item("gold_extract", {"event_id": "e", "source": "s", "source_ref": "r",
                                   "sentences": ["one", "two"]}, id="a"),
        "b": Item("gold_extract", {"event_id": "e2", "source": "s", "source_ref": "r2",
                                   "sentences": ["x"]}, id="b"),
    }
    log.append(Decision("a", "graded", {"marks": {"0": "fact"}}))
    log.append(Decision("b", "skip", {}))
    out = tmp_path / "gold.jsonl"
    assert to_gold_jsonl(log, items, out) == 1
    assert "e2" not in out.read_text()


def test_sentence_split_drops_fragments() -> None:
    """Superseded an earlier test that asserted 4-word fragments survive. They no
    longer do, and that is the fix rather than a regression: a fragment costs the
    grader a decision they cannot make."""
    assert split_sentences("ok. no. yes.") == []


def test_code_tables_and_headings_never_reach_the_grader() -> None:
    """The first version of this queue asked people to classify code fences and
    table rows. A question with no answer is worse than no question."""
    text = (
        "## A heading\n\n"
        "```python\nx = compute(y)\n```\n\n"
        "| col | col |\n|---|---|\n\n"
        "The teacher does not separate reasoning into that field, so the parser accepts it.\n"
    )
    got = split_sentences(text)
    assert got == ["The teacher does not separate reasoning into that field, so the parser accepts it."]


def test_frontmatter_is_stripped() -> None:
    text = (
        "---\nname: a-thing\ndescription: Main is protected\nmetadata:\n  type: feedback\n---\n\n"
        "All work happens on the ticket branch and ships through a pull request.\n"
    )
    assert not any("description:" in s for s in split_sentences(text))


def test_bullets_stay_separate_and_fragments_drop() -> None:
    text = "- short\n- The tier split no longer describes the workflow, since every tier is reviewed.\n"
    got = split_sentences(text)
    assert len(got) == 1 and got[0].startswith("The tier split")


def test_truncated_sentence_is_rejected() -> None:
    assert split_sentences("This one runs off the end of the extract and never") == []


def test_retraction_returns_an_item_to_the_queue(tmp_path: Path) -> None:
    """Undo appends rather than deletes: the item is pending again and the fumbled
    verdict is still on the record."""
    log = DecisionLog(tmp_path / "d.jsonl")
    log.append(Decision("i1", "graded", {"marks": {"0": "fact"}}))
    assert log.decided_ids() == {"i1"}
    log.append(Decision("i1", "retracted", {}))
    assert log.decided_ids() == set()
    assert len(log.path.read_text().strip().splitlines()) == 2


def test_last_graded_finds_the_undo_target(tmp_path: Path) -> None:
    log = DecisionLog(tmp_path / "d.jsonl")
    log.append(Decision("i1", "graded", {}))
    log.append(Decision("i2", "skip", {}))
    assert log.last_graded() == "i1"
    log.append(Decision("i1", "retracted", {}))
    assert log.last_graded() is None


def test_guesser_covers_each_kind() -> None:
    from claimbase.review.queue import guess_kind

    cases = {
        "We decided to drop the 0.85 tier from auto-promotion entirely.": "decision",
        "base F1 = 0.372 on the 181-run bench, well behind v1.": "fact",
        "This probably needs more investigation before we act on it.": "hypothesis",
        "sync_taxonomy.py is idempotent and safe to run on every TOML edit.": "capability",
        "Always run clean_bodies.py after a re-chunk or the output stays pre-clean.": "practice",
        "Next step is to wire the extractor into the nightly sweep.": "plan",
    }
    for text, expected in cases.items():
        assert guess_kind(text) == expected, text


def test_todo_branch_names_are_not_tasks() -> None:
    """`todo/<id>` branches and `todo:<id>` commit prefixes are everywhere in this
    corpus; a case-insensitive TODO cue fired on nearly every one."""
    from claimbase.review.queue import guess_kind

    assert guess_kind("Built on branch `todo/467f527c` with children T1-T9 landed.") != "task"
    assert guess_kind("TODO: still need to backfill the concept_family rows.") == "task"


def test_guess_is_never_empty() -> None:
    from claimbase.review.queue import guess_kind

    assert guess_kind("Some entirely neutral sentence about the corpus size here.")
