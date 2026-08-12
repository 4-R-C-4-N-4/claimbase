"""Render the gold set as something a human can actually check.

`guru:eb9d20d6` is not reviewable. A ref has to say what it *is* — a ticket and its
summary, a doc and its heading, a PR and its title — and show the claim text that
caused it to be chosen, or the reviewer is being asked to confirm an opaque token.

Run: python eval/review_gold.py > eval/gold-review.md
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).parent))

from claimbase.core.store import connect  # noqa: E402
from corpus import repo_path  # noqa: E402

GOLD = Path(__file__).parent / "gold_recall.jsonl"

TICKET = re.compile(r"^([\w-]+):([0-9a-f]{8})$")
PR = re.compile(r"^([\w-]+)#(\d+)$")
COMMIT = re.compile(r"^([\w-]+)@([0-9a-f]+)$")
RUN = re.compile(r"^rellm:([\w.-]+)#(teacher|human)$")
MEMORY = re.compile(r"^claude:(.+)$")


def describe(ref: str) -> str:
    """What is this thing, in words."""
    if m := TICKET.match(ref):
        repo, tid = m.groups()
        for state in ("done", "open"):
            p = repo_path(repo) / ".todo" / state / f"{tid}.json"
            if p.exists():
                try:
                    d = json.loads(p.read_text())
                    return (f"ticket  {repo} [{d.get('type')}/{d.get('state')}] "
                            f"{d.get('summary', '')[:96]}")
                except Exception:
                    break
        return f"ticket  {repo} {tid} (not found on disk)"
    if m := PR.match(ref):
        repo, num = m.groups()
        cache = Path(__file__).parent / ".cache" / f"prs-{repo}.json"
        if cache.exists():
            for pr in json.loads(cache.read_text()):
                if str(pr.get("number")) == num:
                    return f"PR      {repo}#{num} {pr.get('title', '')[:96]}"
        return f"PR      {ref}"
    if m := COMMIT.match(ref):
        return f"commit  {m.group(1)}@{m.group(2)[:9]}"
    if m := RUN.match(ref):
        return f"bench   rellm {m.group(1)} ({m.group(2)}-graded)"
    if m := MEMORY.match(ref):
        return f"memory  {m.group(1)}"
    if ref.startswith("assert:"):
        return f"CAPTURED {ref.split(':', 1)[1]}  (you told me this directly)"
    if ":" in ref:
        repo, path = ref.split(":", 1)
        return f"doc     {repo}/{path[:88]}"
    return ref


def claims_for(conn, ref: str, question: str, limit: int = 2) -> list[tuple[str, str, str]]:
    """The claim text that made this ref a candidate.

    Ranked by closeness to the QUESTION, not by length. A first version showed the
    longest claims on the record, which meant the review displayed evidence that was
    not the evidence used — the reviewer was being shown one thing and asked to
    confirm another.
    """
    from claimbase.cli import _embed_one

    vec = _embed_one(question)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT c.content, c.claim_kind, c.status
            FROM claims c JOIN events e ON e.id = c.event_id
            WHERE e.source_ref LIKE %s AND c.embedding IS NOT NULL
            ORDER BY c.embedding <=> %s::vector
            LIMIT %s
            """,
            (f"%{ref.split(':', 1)[-1].split('#')[0]}%", str(vec), limit),
        )
        return cur.fetchall()


def main() -> None:
    rows = [json.loads(l) for l in GOLD.read_text().splitlines() if l.strip()]
    user = [r for r in rows if "user-authored" in r.get("provenance", "")]

    print("# Gold set — your questions, with refs spelled out\n")
    print("Each ref is what the scoreboard treats as *the right record to return* "
          "(supports) or *a record it would be wrong to return as current* (contradicts).")
    print("\nSkim for refs that look wrong. A bad ref makes that question's score "
          "meaningless, which is worse than not having the question.\n")

    with connect() as conn:
        for r in user:
            print(f"\n---\n\n## {r['id']} — {r['question']}\n")
            print(f"**You said true:** {r['answer']}\n")
            if r.get("wrong_answer"):
                print(f"**You said wrong:** {r['wrong_answer']}\n")
            if r["class"] == "abstain":
                print("**Classed `abstain`** — nothing in the corpus takes a position "
                      "either way, so the correct behaviour is to decline rather than "
                      "answer. Not scored on nDCG.\n")

            for label, key in (("SUPPORTS your answer", "gold_refs"),
                               ("CONTRADICTS it (would be a stale answer)", "stale_refs")):
                refs = r.get(key) or []
                print(f"**{label}:**\n")
                if not refs:
                    print("- *(none found)*\n")
                    continue
                for ref in refs:
                    print(f"- `{ref}`")
                    print(f"  - {describe(ref)}")
                    for content, kind, status in claims_for(conn, ref, r["question"]):
                        mark = "" if status == "active" else f" [{status}]"
                        print(f"  - *{kind}{mark}*: {content[:190]}")
                print()


if __name__ == "__main__":
    main()
