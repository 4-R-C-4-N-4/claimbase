"""Raw corpus reader — for the eval harness ONLY.

This module deliberately duplicates a little of what the source adapters will do,
because the baselines (`rg`, chunk-RAG) must read the corpus *independently* of any
adapter decision. If the baselines consumed adapter output, a bad adapter would
handicap the baseline it is being measured against, and the Phase 0 scoreboard
would be meaningless.

Nothing here is imported by `claimbase.core` or `claimbase.sources`, and nothing
here should grow claim-shaped concepts. It reads files and returns text.
"""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

CORPORA = Path(__file__).resolve().parent.parent / "corpora"
HARNESSES = Path(__file__).resolve().parent.parent / "harnesses"


def load_corpus_def(name: str = "guru") -> dict:
    """Read a named corpus definition. Sources are declared, never discovered —
    a knowledge base is not a property of the current working directory."""
    with (CORPORA / f"{name}.toml").open("rb") as fh:
        spec = tomllib.load(fh)
    for s in spec["source"]:
        # Not every source is a path. Harness-backed sources declare `harness` +
        # `scope` and are located via harnesses/<name>.toml, because a scope can
        # be a directory key, a database column, or nothing at all.
        if "path" in s:
            s["resolved"] = Path(s["path"]).expanduser()
        elif "harness" in s:
            s["resolved"] = resolve_harness_path(s)
    return spec


def load_harness_profile(name: str) -> dict:
    with (HARNESSES / f"{name}.toml").open("rb") as fh:
        return tomllib.load(fh)


def resolve_harness_path(source: dict) -> Path | None:
    """Where this corpus's slice of a harness's memory lives, if it is a path at all."""
    prof = load_harness_profile(source["harness"])["memory"]
    if prof.get("scoping") != "path":
        return None  # e.g. sqlite-backed or globally-scoped: not addressable as a path
    return Path(prof["root"].replace("{scope}", source.get("scope", ""))).expanduser()


CORPUS = load_corpus_def()
SOURCES = {s["name"]: s for s in CORPUS["source"]}
REPOS = tuple(s["name"] for s in CORPUS["source"] if s["kind"] == "repo")


def repo_path(name: str) -> Path:
    return SOURCES[name]["resolved"]

# Run-directory names carry their own timestamp: <name>-<ISO8601 with - for :>
RUN_TS = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z|\d{8}T\d{6}Z)$")

# Docs often date themselves in the title line ("# ... findings (2026-08-05)").
# This beats git for repos with few commits: rellm landed most of docs/ in one
# commit, so git first-seen collapses distinct docs onto the same day and loses
# the ordering that matters (proposal before findings).
INTEXT_DATE = re.compile(r"(20\d{2}-\d{2}-\d{2})")


@dataclass
class Record:
    """One raw unit of corpus text, with whatever provenance the source affords."""

    kind: str  # ticket | doc | run
    repo: str
    rid: str  # stable identifier within (kind, repo)
    path: Path
    text: str
    ts: datetime | None  # best-known assertion time
    title: str = ""
    meta: dict = field(default_factory=dict)

    @property
    def ref(self) -> str:
        return f"{self.repo}:{self.rid}"


def _parse_ts(s: str) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_dir_ts(name: str) -> datetime | None:
    m = RUN_TS.search(name)
    if not m:
        return None
    raw = m.group(1)
    try:
        if "-" in raw[10:]:  # 2026-08-07T13-26-57Z
            d, t = raw.rstrip("Z").split("T")
            return datetime.fromisoformat(f"{d}T{t.replace('-', ':')}").replace(tzinfo=timezone.utc)
        # 20260527T200153Z
        return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def git_first_seen(repo: str) -> dict[str, datetime]:
    """path -> date of the earliest commit touching it. One git call per repo."""
    out = subprocess.run(
        ["git", "-C", str(repo_path(repo)), "log", "--reverse", "--format=@%cI", "--name-only"],
        capture_output=True,
        text=True,
    ).stdout
    seen: dict[str, datetime] = {}
    cur: datetime | None = None
    for line in out.splitlines():
        if line.startswith("@"):
            cur = _parse_ts(line[1:])
        elif line.strip() and cur is not None:
            seen.setdefault(line.strip(), cur)
    return seen


def render_ticket(d: dict) -> str:
    """Canonical text rendering of a ticket. Stable field order — the same ordering
    discipline the adapter will need for content-hash dedupe, kept in sync by eye."""
    parts = [f"[{d.get('type')}/{d.get('state')}] {d.get('summary', '')}"]
    if d.get("description"):
        parts.append(str(d["description"]))
    for a in d.get("analysis") or []:
        parts.append(
            f"({a.get('type')}, {a.get('confidence')}, {a.get('author')}) {a.get('content', '')}"
        )
    res = d.get("resolution") or {}
    if res.get("note"):
        parts.append(f"(resolution) {res['note']}")
    for f in d.get("files") or []:
        if f.get("note"):
            parts.append(f"({f.get('path')}) {f['note']}")
    return "\n\n".join(parts)


def load_tickets() -> list[Record]:
    recs, skipped = [], []
    for repo in REPOS:
        for p in sorted(repo_path(repo).glob(".todo/*/*.json")):
            if p.name == "config.json":
                continue
            try:
                d = json.loads(p.read_text())
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                skipped.append((str(p), str(e)))
                continue
            recs.append(
                Record(
                    kind="ticket",
                    repo=repo,
                    rid=d.get("id", p.stem),
                    path=p,
                    text=render_ticket(d),
                    ts=_parse_ts(d.get("created_at", "")),
                    title=d.get("summary", ""),
                    meta=d,
                )
            )
    if skipped:
        for path, err in skipped:
            print(f"  skip (unparseable): {path} — {err}")
    return recs


def load_docs() -> list[Record]:
    recs = []
    for repo in REPOS:
        root = repo_path(repo)
        first = git_first_seen(repo)
        paths = sorted(root.glob("docs/**/*.md")) + sorted(root.glob("*.md"))
        for p in paths:
            rel = str(p.relative_to(root))
            try:
                text = p.read_text()
            except UnicodeDecodeError:
                continue
            git_ts = first.get(rel) or datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
            ts, src = git_ts, "git"
            m = INTEXT_DATE.search("\n".join(text.splitlines()[:6]))
            if m:
                claimed = _parse_ts(m.group(1) + "T00:00:00+00:00")
                # Trust a self-declared date only if it precedes the commit that
                # introduced the file — a doc cannot be authored after it landed.
                if claimed and claimed <= git_ts:
                    ts, src = claimed, "in-text"
            recs.append(
                Record(
                    kind="doc",
                    repo=repo,
                    rid=rel,
                    path=p,
                    text=text,
                    ts=ts,
                    title=rel,
                    meta={"ts_source": src},
                )
            )
    return recs


def load_runs() -> list[Record]:
    """One record per bench report. Timestamp comes from the path, not git.

    `report.txt` and `report_human.txt` are separate records: they score against
    different ground truth (teacher labels vs. human-graded labels) and disagree
    about which model wins. Collapsing them would erase the disagreement, which is
    the most interesting thing in this source.
    """
    recs = []
    bench = repo_path("rellm") / "runs" / "bench"
    for d in sorted(p for p in bench.iterdir() if p.is_dir()):
        for fname, variant in (("report.txt", "teacher"), ("report_human.txt", "human")):
            report = d / fname
            if not report.exists():
                continue
            recs.append(
                Record(
                    kind="run",
                    repo="rellm",
                    rid=f"{d.name}#{variant}",
                    path=report,
                    text=report.read_text(),
                    ts=_parse_dir_ts(d.name),
                    title=f"{d.name} ({variant}-graded)",
                    meta={"variant": variant, "bench": d.name},
                )
            )
    return recs


def load_all() -> list[Record]:
    return load_tickets() + load_docs() + load_runs()


if __name__ == "__main__":
    recs = load_all()
    by = {}
    for r in recs:
        by.setdefault((r.kind, r.repo), []).append(r)
    print(f"{len(recs)} records, {sum(len(r.text) for r in recs):,} chars\n")
    for k in sorted(by):
        rs = by[k]
        dated = [r for r in rs if r.ts]
        span = (
            f"{min(r.ts for r in dated):%Y-%m-%d} → {max(r.ts for r in dated):%Y-%m-%d}"
            if dated
            else "undated"
        )
        print(f"  {k[0]:<7} {k[1]:<9} {len(rs):>4}  {sum(len(r.text) for r in rs):>9,} chars  {span}")
    undated = [r for r in recs if not r.ts]
    if undated:
        print(f"\n  undated: {len(undated)} — {[r.ref for r in undated][:5]}")
