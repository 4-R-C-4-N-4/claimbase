"""Pull request descriptions — the source that answers "when was this last done?"

Added after the user, asked to mark the remaining elicitation rows, said: "I don't
really know about the rest, their PRs likely have the most relevant info, I would
just be checking those." That is a derivable answer, not an unknown — so it should
be derived here rather than checked by hand.

174 PRs across guru (52) and guru-web (122), ~317 KB of description prose,
2026-04-27 → present. rellm has none (no PR flow there).

Why this matters beyond the elicitation list: a PR description is an *outcome
summary* written at merge time — the same claim density as a ticket resolution
note, with a merge date attached. It is also the missing evidence-of-exercise
signal: `scripts/foo.sh` named in a PR merged last week is alive, however old the
file is.

Cached under eval/.cache — `gh` is a network call and this reruns often.

Run: python3 eval/prs.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from corpus import REPOS, repo_path  # noqa: E402

CACHE = Path(__file__).parent / ".cache"
FIELDS = "number,title,body,createdAt,mergedAt,state"


def fetch(repo: str, refresh: bool = False) -> list[dict]:
    CACHE.mkdir(exist_ok=True)
    cached = CACHE / f"prs-{repo}.json"
    if cached.exists() and not refresh:
        return json.loads(cached.read_text())
    out = subprocess.run(
        ["gh", "pr", "list", "--state", "all", "--limit", "500", "--json", FIELDS],
        cwd=repo_path(repo),
        capture_output=True,
        text=True,
    )
    data = json.loads(out.stdout) if out.stdout.strip() else []
    cached.write_text(json.dumps(data))
    return data


def load_all_prs(refresh: bool = False) -> list[dict]:
    prs = []
    for repo in REPOS:
        for p in fetch(repo, refresh):
            p["repo"] = repo
            # Merge date is when the work landed; fall back to creation for open PRs.
            p["ts"] = p.get("mergedAt") or p.get("createdAt")
            prs.append(p)
    return prs


def text_of(pr: dict) -> str:
    return f"{pr.get('title', '')}\n\n{pr.get('body') or ''}"


if __name__ == "__main__":
    prs = load_all_prs("--refresh" in sys.argv)
    by_repo: dict[str, list] = {}
    for p in prs:
        by_repo.setdefault(p["repo"], []).append(p)
    total = sum(len(text_of(p)) for p in prs)
    print(f"{len(prs)} PRs, {total:,} chars")
    for repo, rows in sorted(by_repo.items()):
        dated = sorted(r["ts"][:10] for r in rows if r.get("ts"))
        span = f"{dated[0]} → {dated[-1]}" if dated else "undated"
        merged = sum(1 for r in rows if r.get("mergedAt"))
        print(
            f"  {repo:<9} {len(rows):>4} PRs ({merged} merged)  "
            f"{sum(len(text_of(r)) for r in rows):>8,} chars  {span}"
        )
