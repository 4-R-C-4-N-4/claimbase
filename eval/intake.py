"""Turn `questions.md` into scoreable gold questions.

The user writes the question and what would be wrong. Finding which records support
or contradict it is a graph query, and doing that by hand was exactly the kind of
legwork that got pushed onto them once already.

**On circularity.** Candidate refs are found by searching the graph, which risks the
gold set agreeing with the system by construction. Two things keep it honest:

- `stale_refs` are found by searching for the WRONG statement, not the right one. A
  record that asserts the wrong answer is stale regardless of how the ranking feels
  about it, and mislead-rate only asks whether such a record outranks a correct one.
- Everything proposed is printed for a human to confirm before it is written. The
  search proposes; it does not decide.

A question whose TRUE answer has no supporting record is not a failure — it is the
abstention case, and it gets marked rather than dropped.

Run: python eval/intake.py [--write]
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from baselines import to_gold_ref  # noqa: E402
from claimbase.core.store import connect  # noqa: E402
from claimbase.recall import recall  # noqa: E402

SRC = Path(__file__).parent / "questions.md"
OUT = Path(__file__).parent / "gold_recall.jsonl"

BLOCK = re.compile(
    r"^###\s+(?P<q>.+?)\n"
    r"(?:TRUE:\s*(?P<true>.*?)\n)?"
    r"(?:WRONG:\s*(?P<wrong>.*?)\n)?"
    r"(?:UNSURE:\s*(?P<unsure>.*?)\n)?",
    re.M | re.S,
)


def parse(text: str) -> list[dict]:
    out = []
    # Split on headings so a field never swallows the next question's block.
    chunks = re.split(r"\n(?=###\s)", text)
    for ch in chunks:
        m = re.match(r"###\s+(.+)", ch)
        if not m:
            continue
        q = m.group(1).strip()
        if q.startswith("(example"):
            continue

        def field(name: str) -> str:
            fm = re.search(rf"^{name}:\s*(.*?)(?=\n[A-Z]{{4,}}:|\n###|\Z)", ch, re.M | re.S)
            return " ".join(fm.group(1).split()) if fm else ""

        out.append({
            "question": q, "true": field("TRUE"),
            "wrong": field("WRONG"), "unsure": field("UNSURE"),
        })
    return out


ADJUDICATE = """You decide what a record asserts.

You are given two mutually exclusive statements and one record.

Answer with exactly one word:
A        - the record supports statement A
B        - the record supports statement B
NEITHER  - the record is about the topic but takes no position, or is unrelated

Most records are NEITHER. Only answer A or B if the record actually commits to that \
position. Being on the same subject is not support."""


def adjudicate(true_s: str, wrong_s: str, record: str) -> str:
    """Which statement does this record actually assert?

    Similarity cannot do this: a claim and its negation sit almost on top of each
    other in embedding space, being about the same subject. Searching for the WRONG
    statement returned the SAME top records as searching for the TRUE one, which
    would have made gold_refs and stale_refs overlap and both metrics meaningless.
    Entailment is the right question, and it is the same check DESIGN §4.5 specifies
    for contradiction detection.
    """
    from claimbase.llm import call_llm

    reply = call_llm(
        provider="llamacpp", model="Qwen3.5-27B-UD-Q4_K_XL.gguf",
        system=ADJUDICATE,
        prompt=f"STATEMENT A: {true_s}\n\nSTATEMENT B: {wrong_s}\n\nRECORD: {record[:900]}",
        max_tokens=64, timeout=180,
    ).strip().upper()
    for v in ("NEITHER", "A", "B"):
        if reply.startswith(v) or f" {v}" in reply[:40]:
            return v
    return "NEITHER"


def propose_refs(conn, q: dict, k: int = 16) -> tuple[list, list, int]:
    """(gold, stale, n_neither).

    Candidates are gathered from THREE searches — the question, the true statement
    and the wrong one — because a pool drawn only from the question is bounded by
    the retriever being graded. q012's genuinely stale record ("export.py followed
    by a VPS load") exists and simply was not in the top-14 for the question's
    phrasing, so no amount of adjudication would have found it.

    Similarity still cannot tell a claim from its negation — that is why entailment
    decides — but it is a perfectly good way to *gather* candidates, and casting
    three nets catches what one misses.
    """
    seen, gold, stale, neither = set(), [], [], 0
    pool = []
    for probe in (q["question"], q["true"], q["wrong"]):
        if probe:
            pool.extend(recall(probe, conn=conn, k=k))
    for h in pool:
        ref = to_gold_ref(h.source_ref)
        if ref in seen:
            continue
        seen.add(ref)
        verdict = adjudicate(q["true"], q["wrong"], h.content)
        if verdict == "A":
            gold.append((ref, h.kind, h.content[:110]))
        elif verdict == "B":
            stale.append((ref, h.kind, h.content[:110]))
        else:
            neither += 1
    return gold, stale, neither


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true", help="append to gold_recall.jsonl")
    ap.add_argument("--start-id", type=int, default=10)
    args = ap.parse_args()

    rows = parse(SRC.read_text())
    print(f"  {len(rows)} questions in {SRC.name}\n")

    built = []
    with connect() as conn:
        for i, r in enumerate(rows):
            qid = f"q{args.start_id + i:03d}"
            gold, stale, n_neither = propose_refs(conn, r)
            # A question whose correct answer nothing in the corpus supports is the
            # abstention case: the right behaviour is to decline, not to retrieve.
            cls = "abstain" if r["unsure"] or not gold else "stale_answer"
            print(f"  {qid}  [{cls}]  {r['question'][:70]}")
            print(f"    TRUE  -> {[g[0] for g in gold] or '(nothing supports this)'}")
            for g in gold[:2]:
                print(f"        {g[1]:<11} {g[2]}")
            print(f"    WRONG -> {[s[0] for s in stale] or '(nothing asserts this)'}")
            for s in stale[:2]:
                print(f"        {s[1]:<11} {s[2]}")
            print(f"    ({n_neither} candidates took no position)")
            print()
            built.append({
                "id": qid, "question": r["question"], "class": cls,
                "answer": r["true"], "wrong_answer": r["wrong"],
                "gold_refs": [g[0] for g in gold[:3]],
                "stale_refs": [s[0] for s in stale[:3]],
                "provenance": "user-authored (eval/questions.md); refs proposed by "
                              "search over the WRONG/TRUE statements, human-confirmed",
                "needs_user_confirm": True,
            })

    if args.write:
        with OUT.open("a") as fh:
            for b in built:
                fh.write(json.dumps(b) + "\n")
        print(f"  appended {len(built)} to {OUT.name}")
    else:
        print("  (dry run — pass --write to append)")


if __name__ == "__main__":
    main()
