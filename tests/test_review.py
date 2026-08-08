"""Review queue — the append-only discipline and the sentence splitter."""

from __future__ import annotations

from pathlib import Path

from claimbase.review.queue import Decision, DecisionLog, Item, split_sentences, to_gold_jsonl


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


def test_sentence_split_keeps_bullets_separate() -> None:
    text = "A claim about X. Another about Y.\n\n- a bullet item here\n- second bullet item"
    parts = split_sentences(text)
    assert len(parts) >= 3
    assert any("bullet item here" in p for p in parts)


def test_sentence_split_drops_fragments() -> None:
    assert split_sentences("ok. no. yes.") == []  # nothing over 15 chars survives
