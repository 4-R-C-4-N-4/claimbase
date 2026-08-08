"""Surface practices the corpus asserts as current but shows no recent sign of.

The auto-promote case (PLAN §0.8) is invisible to every harvest signal, because
nothing in the corpus records the abandonment. But it is *not* invisible to a
staleness sweep: 8+ records assert the workflow, and the script behind it has not
been touched or mentioned since April while the repo stayed busy.

That is design §6's stale sweep — "old asserted_at, no recent corroboration, on an
active entity" — in rough form. It runs here first because it produces the
elicitation list, turning recall ("what have you stopped doing?") into recognition
("the corpus says you do these; last sign of each was N days ago").

The output is questions for a human, never conclusions. A long gap is evidence of
nothing on its own — a stable tool that still works needs no commits.

Run: python3 eval/elicit.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from corpus import REPOS, load_all, repo_path  # noqa: E402

OUT = Path(__file__).parent / "elicitation.md"
NOW = datetime.now(timezone.utc)
MIN_ASSERTIONS = 1  # one doc asserting a workflow is enough to be worth asking about
MIN_GAP_DAYS = 30

# Language that asserts a thing is how work is *done*, not merely that it exists.
PRACTICE = re.compile(
    r"\b(run|runs|running|use|uses|using|invoke|execute|workflow|pipeline|step|"
    r"always|never|should|must|standard|current|default)\b",
    re.I,
)


def git(repo: str, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo_path(repo)), *args], capture_output=True, text=True
    ).stdout


def anchors() -> dict[str, dict]:
    """Executable things a practice can be about: scripts and shell entry points."""
    found: dict[str, dict] = {}
    for repo in REPOS:
        root = repo_path(repo)
        for pat in ("scripts/*.py", "scripts/*.sh", "*.sh"):
            for p in sorted(root.glob(pat)):
                last = git(repo, "log", "-1", "--format=%cI", "--", str(p.relative_to(root))).strip()
                found[p.name] = {
                    "repo": repo,
                    "rel": str(p.relative_to(root)),
                    "last_touched": datetime.fromisoformat(last) if last else None,
                }
    return found


def commit_mentions(repo: str) -> dict[str, datetime]:
    """Latest commit-message mention of each token. One git call per repo."""
    out = git(repo, "log", "--format=%cI%x00%s%x00%b")
    latest: dict[str, datetime] = {}
    for entry in out.split("\n"):
        parts = entry.split("\x00")
        if len(parts) < 2:
            continue
        try:
            ts = datetime.fromisoformat(parts[0])
        except ValueError:
            continue
        for tok in re.findall(r"[\w.-]+\.(?:py|sh)", " ".join(parts[1:])):
            if tok not in latest or ts > latest[tok]:
                latest[tok] = ts
    return latest


def main() -> None:
    recs = load_all()
    anc = anchors()
    print(f"{len(anc)} script anchors across {len(REPOS)} repos")

    # Assertion and exercise are different signals and must not be mixed.
    #
    # A doc *describing* a workflow is the claim under suspicion, not evidence the
    # workflow still happens — the guru ingest workbook written last night describes
    # auto-promote, which is precisely the practice that ended in July. Counting that
    # as a sign of life makes the strongest candidate look freshest.
    #
    # Evidence of *exercise* is work actually done: the file changing, or a ticket
    # resolution / commit message reporting a run.
    asserts: dict[str, list] = defaultdict(list)
    exercised: dict[str, datetime] = {}

    def note_exercise(name: str, ts: datetime | None) -> None:
        if ts and (name not in exercised or ts > exercised[name]):
            exercised[name] = ts

    for r in recs:
        for name in anc:
            if name not in r.text:
                continue
            if r.kind == "doc" and PRACTICE.search(r.text):
                asserts[name].append(r)
            elif r.kind == "ticket":
                # Only a *closed* ticket is evidence of work done; an open one that
                # mentions a script is a plan, which is assertion, not exercise.
                res = (r.meta.get("resolution") or {}).get("note", "")
                if name in res or r.meta.get("state") == "done":
                    note_exercise(name, r.ts)

    for repo in REPOS:
        for tok, ts in commit_mentions(repo).items():
            if tok in anc:
                note_exercise(tok, ts)

    rows = []
    for name, meta in anc.items():
        a = asserts.get(name, [])
        if len(a) < MIN_ASSERTIONS:
            continue
        seen = max(filter(None, (exercised.get(name), meta["last_touched"])), default=None)
        if not seen:
            continue
        gap = (NOW - seen).days
        if gap < MIN_GAP_DAYS:
            continue
        rows.append(
            {
                "name": name,
                "repo": meta["repo"],
                "rel": meta["rel"],
                "gap": gap,
                "seen": seen,
                "touched": meta["last_touched"],
                "asserts": sorted(a, key=lambda r: -(r.ts.timestamp() if r.ts else 0)),
            }
        )

    # Heavily asserted + long unexercised ranks highest.
    rows.sort(key=lambda r: -(r["gap"] * len(r["asserts"])))

    body = [
        "# Elicitation list — practices the corpus asserts but shows no recent sign of",
        "",
        "Generated by `eval/elicit.py`. **Every row is a question, not a finding.**",
        "A long gap is evidence of nothing by itself: a stable tool that still works needs",
        "no commits. Only you know which of these you have actually stopped doing.",
        "",
        "Three possible answers per row, not two — the sweep cannot tell them apart, and",
        "they need different corrections:",
        "",
        "- **A — still current.** Stable tool, no commits needed. Nothing to fix; the gap is noise.",
        "- **B — practice abandoned.** You stopped doing this. Becomes a q003-class gold question:",
        "  the corpus is uniformly wrong and no retriever can recover, only capture can.",
        "- **C — practice continues, implementation moved.** Still done, done differently. The docs",
        "  describe a dead path for a live activity — arguably the most misleading of the three,",
        "  because the answer looks confirmable.",
        "",
        "Category C was discovered by this list flagging its own top two results: `review_tags.py`",
        "and `review_edges.py` are 72d quiet with 23 records between them asserting the CLI flow,",
        "yet tag/edge review is *current* — it migrated to the guru-review web app's HTTP API.",
        "",
        f"{len(rows)} candidates, ranked by (days quiet x records asserting it).",
        "",
        "| A/B/C | script | repo | quiet | asserted by |",
        "|---|---|---|---|---|",
    ]
    for r in rows[:20]:
        refs = ", ".join(f"`{Path(x.rid).name}`" for x in r["asserts"][:3])
        if len(r["asserts"]) > 3:
            refs += f" +{len(r['asserts']) - 3}"
        body.append(
            f"| ☐ | `{r['rel']}` | {r['repo']} | {r['gap']}d | {len(r['asserts'])} records — {refs} |"
        )
    if len(rows) > 20:
        body.append(f"\n*{len(rows) - 20} further candidates below the cut, in results JSON.*")

    body += [
        "",
        "## Validation",
        "",
        "`auto_promote_edges.sh` / `auto_promote.py` are the known-positive control: the",
        "practice demonstrably ended 2026-07-14. If they do not appear high in this list,",
        "the ranking is wrong and the rest of the list should not be trusted.",
        "",
    ]
    ctrl = [r for r in rows if r["name"].startswith("auto_promote")]
    for r in ctrl:
        body.append(f"- `{r['rel']}` — rank {rows.index(r) + 1} of {len(rows)}, {r['gap']}d quiet ✅")
    if not ctrl:
        body.append("- **control absent — ranking is not working.**")

    OUT.write_text("\n".join(body))
    print(f"→ {OUT}  ({len(rows)} candidates)")
    for r in rows[:8]:
        print(f"  {r['gap']:>4}d  {len(r['asserts']):>2} asserts  {r['repo']}:{r['rel']}")


if __name__ == "__main__":
    main()
