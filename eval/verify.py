"""Verify harvested candidates against git, so a human doesn't have to.

A candidate is only a real stale-answer question if a *retrievable* record still
asserts the old answer. Two ways that fails:

  - the stale text was edited away, so nothing retrieves it today (the
    `docs/web-review/edges.md` case: corrected in place 20 minutes later)
  - the two records were never comparable in the first place (bench runs scoring
    different eval sets, where a metric "change" is a change of ruler)

Both are decidable from git and from the run configs. Neither needs judgment.
What survives goes to a human; what doesn't is dropped with its reason recorded.

Run: python3 eval/verify.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from corpus import WORK, Record, load_all  # noqa: E402
from harvest import (  # noqa: E402
    RUN_TS_SUFFIX,
    parse_metrics,
    s1_renames,
    s2_lineage,
    s3_metric_drift,
    s4_retractions,
    symbols,
)

OUT = Path(__file__).parent / "verified.md"


def git(repo: str, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(WORK / repo), *args], capture_output=True, text=True
    ).stdout


def survives_at_head(rec: Record, needle: str) -> tuple[bool, str]:
    """Does this record still assert `needle` in the working tree?

    Tickets and bench reports are archival — written once, never edited — so they
    keep asserting whatever they said. Docs are edited in place, so a doc's claim
    can vanish without leaving a trace in the working tree at all.
    """
    if not rec.path.exists():
        return False, "file deleted"
    text = rec.path.read_text(errors="ignore")
    if needle and needle not in text:
        rel = str(rec.path.relative_to(WORK / rec.repo))
        killed = git(rec.repo, "log", "-1", "--format=%h %ci %s", f"-S{needle}", "--", rel)
        return False, f"removed in place — {killed.strip()[:100] or 'unknown commit'}"
    return True, "still present at HEAD"


def eval_set(bench_dir: str) -> frozenset:
    """The chunk ids a bench actually scored.

    (models, n) agreeing is not proof of the same eval — two benches can score the
    same count of different things. cells.csv names the chunks, so comparability
    becomes a set comparison instead of an inference.
    """
    p = WORK / "rellm" / "runs" / "bench" / bench_dir / "cells.csv"
    if not p.exists():
        return frozenset()
    import csv

    with p.open() as fh:
        return frozenset(row["chunk_id"] for row in csv.DictReader(fh) if "chunk_id" in row)


def bench_config(r: Record) -> tuple:
    """(models, n) — two runs are comparable only if both match."""
    models, n = set(), None
    for line in r.text.splitlines():
        m = re.match(r"^\s*(\S+)\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+\s+[\d.]+%.*?(\d+)\s*$", line)
        if m:
            models.add(m.group(1))
            n = m.group(2)
        m = re.match(r"^\s*(\S+)\s+(?:ALL)\s+\d+\s+\d+\s+\d+\s+\d+\s+.*?(\d+)\s*$", line)
        if m:
            models.add(m.group(1))
            n = m.group(2)
    cells = eval_set(r.meta.get("bench", r.rid))
    # Hash the scored-chunk set, so two benches group together only if they
    # measured the same things — not merely the same number of things.
    return (tuple(sorted(models)), n, hash(cells) if cells else None)


def pair_retraction(cand: dict, recs: list[Record], index: dict[str, list[Record]]) -> dict:
    """Find what a retraction retracts.

    S4 candidates are the *correction* half of a pair; the harvester never
    identifies the record that carried the original belief. Without that half
    there is no stale-answer question, only a note that someone changed their
    mind. Pair on shared distinctive identifiers in the retracting paragraph.
    """
    doc = cand["changed_by"]
    # Symbols from the retracting paragraphs *and* the doc, but only rare ones:
    # sharing `staged_tags` with a record means nothing, sharing `supersede_pending`
    # means a lot. Rarity is what makes a shared symbol evidence.
    cand_syms = symbols(cand["detail"] + " " + " ".join(cand.get("extra", []))) | symbols(doc.text)
    syms = [s for s in cand_syms if 1 < len(index.get(s, [])) <= 12]
    scored: dict[str, int] = defaultdict(int)
    pool: dict[str, Record] = {}
    for s in syms:
        for o in index.get(s, []):
            if o.ts and doc.ts and o.ts < doc.ts and o.ref != doc.ref:
                scored[o.ref] += 1
                pool[o.ref] = o
    ranked = sorted(scored.items(), key=lambda kv: -kv[1])
    cand["live"], cand["dead"] = [], []
    for ref, shared in ranked[:3]:
        if shared < 3:
            break
        ok, why = survives_at_head(pool[ref], "")
        (cand["live"] if ok else cand["dead"]).append(
            (pool[ref], f"{shared} shared identifiers — {why}")
        )
    # Lexical overlap does NOT establish what a retraction retracts — tested on this
    # corpus it paired the v2-regression autopsy with concept-hierarchy/design.md on
    # 15 shared identifiers, which is not remotely what the autopsy disowns. Shipping
    # that as REAL would be the §10.1 failure mode inside the eval harness itself.
    # The suggestions stay, labelled as guesses; the verdict never upgrades on them.
    cand["verdict"] = "RETRACTION CONFIRMED — pairing needs judgment"
    return cand


def verify_stale_set(cand: dict) -> dict:
    """Attach survival verdicts to a candidate's stale records."""
    key = cand.get("key") or ""
    live, dead = [], []
    for s in cand["stale"]:
        ok, why = survives_at_head(s, key if key and key in s.text else "")
        (live if ok else dead).append((s, why))
    cand["live"], cand["dead"] = live, dead
    cand["verdict"] = "REAL" if live else "DROP — nothing stale survives"
    return cand


def main() -> None:
    recs = load_all()
    index: dict[str, list[Record]] = defaultdict(list)
    for r in recs:
        for s in symbols(r.text):
            index[s].append(r)

    lines = [
        "# Verified stale-answer candidates",
        "",
        "Produced by `eval/verify.py`. Each candidate is tested against git and the run",
        "configs; only what survives needs a human. Drops keep their reason.",
        "",
    ]

    # --- S3: comparability is a config question, not a judgment call -----------
    runs = [r for r in recs if r.kind == "run"]
    configs = {r.rid: bench_config(r) for r in runs}
    by_config: dict[tuple, list[Record]] = defaultdict(list)
    for r in runs:
        by_config[configs[r.rid]].append(r)

    lines += ["## Bench comparability", "", "| bench | models | n | comparable group |", "|---|---|---|---|"]
    groups = {cfg: f"G{i + 1}" for i, cfg in enumerate(sorted(by_config, key=str))}
    for r in sorted(runs, key=lambda r: (r.ts or r.ts.min)):
        models, n, _ = configs[r.rid]
        lines.append(
            f"| `{RUN_TS_SUFFIX.sub('', r.meta.get('bench', r.rid)).strip('-')}"
            f"{'#human' if r.meta.get('variant') == 'human' else ''}` "
            f"| {', '.join(models) or '—'} | {n or '—'} | {groups[configs[r.rid]]} |"
        )
    lines.append("")

    # A metric series is only a real change if it stays inside one comparable group.
    series: dict[tuple[str, str], list[tuple[Record, float]]] = defaultdict(list)
    for r in runs:
        variant = r.meta.get("variant", "teacher")
        for model, metric, val in parse_metrics(r):
            series[(model, f"{metric} ({variant}-graded)")].append((r, val))

    real_metric, cross_ruler = [], []
    for (model, metric), points in series.items():
        points.sort(key=lambda p: p[0].ts)
        for cfg, pts in {
            c: [p for p in points if configs[p[0].rid] == c] for c in {configs[p[0].rid] for p in points}
        }.items():
            vals = [v for _, v in pts]
            if len(pts) > 1 and max(vals) - min(vals) >= 0.02:
                real_metric.append((model, metric, groups[cfg], pts))
        if len({configs[p[0].rid] for p in points}) > 1:
            cross_ruler.append((model, metric))

    lines += [
        f"## S3 — metric drift: {len(real_metric)} real, {len(cross_ruler)} cross-ruler artifacts",
        "",
        "A metric that moves *between* comparability groups changed ruler, not value —",
        "exactly the confusion the v2-regression autopsy calls a measurement artifact.",
        "",
    ]
    for model, metric, g, pts in sorted(real_metric, key=lambda x: -abs(x[3][-1][1] - x[3][0][1]))[:8]:
        run = " → ".join(
            f"**{v:.3f}** ({RUN_TS_SUFFIX.sub('', r.meta.get('bench', r.rid)).strip('-')}, {r.ts:%b %d})"
            for r, v in pts
        )
        lines.append(f"- **`{model}` {metric}** [{g}]: {run}")
    if cross_ruler:
        lines += [
            "",
            f"*Dropped as cross-ruler ({len(cross_ruler)}): "
            + ", ".join(f"`{m}` {k}" for m, k in cross_ruler[:6])
            + ("…" if len(cross_ruler) > 6 else "")
            + "*",
        ]
    lines.append("")

    # --- S1 / S2 / S4: does anything stale actually survive? ------------------
    for name, cands, how in [
        ("S1 — rename / replace", s1_renames(recs, index), verify_stale_set),
        ("S2 — doc lineage", s2_lineage(recs), verify_stale_set),
        (
            "S4 — explicit retraction",
            s4_retractions(recs),
            lambda c: pair_retraction(c, recs, index),
        ),
    ]:
        checked = [how(c) for c in cands]
        real = [c for c in checked if c["verdict"] == "REAL"]
        dropped = [c for c in checked if c["verdict"] != "REAL"]
        lines += [f"## {name}: {len(real)} real of {len(checked)}", ""]
        for c in real[:10]:
            lines.append(f"### {c['question']}")
            lines.append(f"\n- **evidence:** {c['detail']}")
            for s, why in c["live"][:3]:
                lines.append(f"- **stale, retrievable today:** `{s.ref}` ({s.ts:%Y-%m-%d}) — {why}")
            for s, why in c["dead"][:2]:
                lines.append(f"- ~~`{s.ref}`~~ — {why}")
            lines.append("")
        for c in dropped:
            lines.append(f"### {c['question']}  *[{c['verdict']}]*")
            lines.append(f"\n- **evidence:** {c['detail'][:300]}")
            for s, why in c.get("live", [])[:2]:
                lines.append(f"- *lexical guess, unreliable:* `{s.ref}` ({s.ts:%Y-%m-%d}) — {why}")
            lines.append("")
        lines.append("")

    OUT.write_text("\n".join(lines))
    print(f"→ {OUT}")
    print(f"  bench comparability groups: {len(by_config)}")
    print(f"  metric series: {len(real_metric)} real, {len(cross_ruler)} cross-ruler")


if __name__ == "__main__":
    main()
