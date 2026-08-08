"""Harvest stale-answer question candidates from the corpus.

A stale-answer question is one whose correct answer CHANGED during the corpus
window — the class where chunk-RAG fails loudly and a claim graph should not.
These are the questions Phase 0 is judged on (PLAN §1), and they are expensive
to invent but cheap to *find*, because the corpus records its own revisions.

Five signals, each with different false-positive behaviour:

  S1 rename/replace   a record renames X to Y; earlier records describing X are now stale
  S2 doc lineage      v1→v2→v3, proposal→findings: a doc superseded by its successor
  S3 metric drift     the same (model, metric) reported with different values across runs
  S4 retraction       a doc explicitly disowns an earlier reading
  S5 contested symbol a symbol argued about across a long span by many records

Output is a REVIEW QUEUE, not a gold set. Every candidate needs a human to
accept, cut, or rewrite it into a question — that judgment is the part no
harvester can do. Run: python3 eval/harvest.py
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from corpus import Record, load_all  # noqa: E402

OUT = Path(__file__).parent / "candidates.md"
CAP = 15  # max candidates reported per signal; drops are logged, never silent

# --- symbol vocabulary -------------------------------------------------------
# Backticked spans and underscore identifiers. Deliberately narrow: bare
# CamelCase and single words produce far more noise than they are worth.
BACKTICK = re.compile(r"`([^`\n]{3,60})`")
SNAKE = re.compile(r"\b([a-z][a-z0-9]*(?:_[a-z0-9]+){1,4})\b")

RENAMES = [
    re.compile(r"`?([\w./]{4,60})`?\s*(?:→|->|-->)\s*`?([\w./]{4,60})`?"),
    re.compile(r"renam\w*\s+`?([\w./]{4,60})`?\s+(?:to|→)\s+`?([\w./]{4,60})`?", re.I),
    re.compile(r"replac\w*\s+`?([\w./]{4,60})`?\s+with\s+`?([\w./]{4,60})`?", re.I),
]

# This corpus uses "→" constantly for pipeline dataflow ("chunk.py → embed_corpus.py"),
# which is not a rename. Require the containing line to state rename intent, or S1
# degenerates into an index of every pipeline diagram in the repos.
RENAME_INTENT = re.compile(
    r"\b(renam\w*|replac\w*|deprecat\w*|now called|becomes|moved? to|migrat\w*|"
    r"drop\w* in favou?r of|supersed\w*)\b",
    re.I,
)

RETRACTION = re.compile(
    r"\b(measurement artifact|is not a \w+ problem|turns? out|turned out|actually,|"
    r"blind spot|misdiagnos\w*|was wrong|not the (?:real )?(?:cause|problem)|"
    r"supersed\w*|no longer (?:true|holds|accurate)|correction:|revised? (?:reading|conclusion)|"
    r"does not (?:beat|hold|survive)|gate not passed|selection noise)\b",
    re.I,
)

LINEAGE = [
    re.compile(r"^(.*?)v(\d)(.*)$"),  # v2.md / v3.md, guru-v2-proposal
    re.compile(r"^(.*?)(proposal|findings|draft|revised|retro|autopsy)(.*)$", re.I),
]


def symbols(text: str) -> set[str]:
    out = {m.group(1).strip() for m in BACKTICK.finditer(text)}
    out |= {m.group(1) for m in SNAKE.finditer(text)}
    return {s for s in out if len(s) >= 5 and not s.startswith("http")}


def is_identifier(s: str) -> bool:
    """Filter rename captures down to things that look like code, not prose."""
    return bool(re.fullmatch(r"[\w./]{4,60}", s)) and ("_" in s or "." in s or "/" in s)


def lookup_keys(sym: str) -> list[str]:
    """Ways a symbol might appear in the index.

    Renames are usually written qualified — `review_actions.staged_tag_id → target_id` —
    but earlier records mention the bare column. Matching only the qualified form
    silently drops the most common rename shape in this corpus.
    """
    keys = {sym}
    if "." in sym:
        keys.add(sym.rsplit(".", 1)[-1])
    if "/" in sym:
        keys.add(sym.rsplit("/", 1)[-1])
    return [k for k in keys if len(k) >= 5]


# --- signals -----------------------------------------------------------------


def s1_renames(recs: list[Record], index: dict[str, list[Record]]) -> list[dict]:
    out = []
    for r in recs:
        if not r.ts:
            continue
        for pat in RENAMES:
            for m in pat.finditer(r.text):
                line_start = r.text.rfind("\n", 0, m.start()) + 1
                line_end = r.text.find("\n", m.end())
                line = r.text[line_start : line_end if line_end != -1 else len(r.text)]
                if not RENAME_INTENT.search(line):
                    continue
                old = m.group(1).strip("`").rstrip(".,;:")
                new = m.group(2).strip("`").rstrip(".,;:")
                if old == new or not (is_identifier(old) and is_identifier(new)):
                    continue
                seen_refs, stale = set(), []
                for key in lookup_keys(old):
                    for o in index.get(key, []):
                        if o.ts and o.ts < r.ts and o.ref != r.ref and new not in o.text:
                            if o.ref not in seen_refs:
                                seen_refs.add(o.ref)
                                stale.append(o)
                if not stale:
                    continue
                out.append(
                    {
                        "score": len(stale),
                        "question": f"What is `{old}` called / how is it referred to now?",
                        "changed_by": r,
                        "detail": f"`{old}` → `{new}` — “{' '.join(line.split())[:140]}”",
                        "key": old,
                        "stale": stale,
                    }
                )
    # dedupe on the renamed symbol, keeping the best-evidenced
    best: dict[str, dict] = {}
    for c in out:
        prev = best.get(c["key"])
        if prev is None or c["score"] > prev["score"]:
            best[c["key"]] = c
    return sorted(best.values(), key=lambda c: -c["score"])


def s2_lineage(recs: list[Record]) -> list[dict]:
    groups: dict[tuple[str, str, str], list[Record]] = defaultdict(list)
    for r in recs:
        if r.kind != "doc":
            continue
        stem = Path(r.rid).stem
        parent = str(Path(r.rid).parent)
        for pat in LINEAGE:
            m = pat.match(stem)
            if m:
                key = (r.repo, parent, (m.group(1) + m.group(3)).strip("-_ ").lower())
                groups[key].append(r)
                break
    out = []
    for (repo, parent, key), members in groups.items():
        if len(members) < 2:
            continue
        members.sort(key=lambda r: r.ts or r.ts.min)
        # If two docs in a lineage share a date, the ordering is a coin flip —
        # rellm landed most of docs/ in one commit, so git cannot separate them.
        # Say so rather than presenting an arbitrary order as fact.
        dates = {m.ts.date() for m in members if m.ts}
        caveat = "" if len(dates) == len(members) else "  ⚠ same-day; ordering unverified"
        out.append(
            {
                "score": len(members),
                "question": f"[{repo}] What is the current design for '{key or parent}'?",
                "changed_by": members[-1],
                "detail": " → ".join(Path(m.rid).stem for m in members) + caveat,
                "stale": members[:-1],
            }
        )
    return sorted(out, key=lambda c: -c["score"])


RUN_TS_SUFFIX = re.compile(r"-?(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z|\d{8}T\d{6}Z)$")

METRIC_ROW = re.compile(
    r"^\s*(\S+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)%\s+([\d.]+)\s+([\d.]+)\s+(\d+)\s*$"
)
MACRO_ROW = re.compile(r"^\s*(\S+)\s+macro-F1\s*=\s*([\d.]+)")

# report_human.txt uses a different table: model split TP FP FN TN prec rec F1 spec n
HUMAN_ROW = re.compile(
    r"^\s*(\S+)\s+(ALL|test|tune)\s+\d+\s+\d+\s+\d+\s+\d+\s+"
    r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+[\d.]+\s+\d+\s*$"
)


def parse_metrics(r: Record) -> list[tuple[str, str, float]]:
    """(model, metric, value) from a bench report."""
    out, in_summary = [], False
    for line in r.text.splitlines():
        if line.startswith("==="):
            in_summary = "Per-model summary" in line
            continue
        if in_summary:
            m = METRIC_ROW.match(line)
            if m:
                out += [
                    (m.group(1), "precision", float(m.group(2))),
                    (m.group(1), "recall", float(m.group(3))),
                    (m.group(1), "F1", float(m.group(4))),
                ]
        m = MACRO_ROW.match(line)
        if m:
            out.append((m.group(1), "macro-F1", float(m.group(2))))
        m = HUMAN_ROW.match(line)
        if m and m.group(2) == "ALL":  # ALL and test duplicate each other here
            out += [
                (m.group(1), "precision", float(m.group(3))),
                (m.group(1), "recall", float(m.group(4))),
                (m.group(1), "F1", float(m.group(5))),
            ]
    return out


def s3_metric_drift(recs: list[Record]) -> list[dict]:
    series: dict[tuple[str, str], list[tuple[Record, float]]] = defaultdict(list)
    for r in recs:
        if r.kind != "run" or not r.ts:
            continue
        variant = r.meta.get("variant", "teacher")
        for model, metric, val in parse_metrics(r):
            series[(model, f"{metric} ({variant}-graded)")].append((r, val))
    out = []
    for (model, metric), points in series.items():
        if len(points) < 2:
            continue
        points.sort(key=lambda p: p[0].ts)
        vals = [v for _, v in points]
        if max(vals) - min(vals) < 0.02:  # restated, not drifted
            continue
        # Bench identity is load-bearing: a jump between runs may be a different
        # eval, not a different model. Without the bench name a human cannot judge
        # comparability, and the gold answer would be "it depends".
        out.append(
            {
                "score": round((max(vals) - min(vals)) * 100),
                "question": f"What is model `{model}`'s {metric} on the tagging bench?",
                "changed_by": points[-1][0],
                "detail": " → ".join(
                    f"**{v:.3f}** "
                    f"({RUN_TS_SUFFIX.sub('', r.meta.get('bench', r.rid)).strip('-') or r.rid}, "
                    f"{r.ts:%b %d})"
                    for r, v in points
                ),
                "stale": [r for r, _ in points[:-1]],
            }
        )
    return sorted(out, key=lambda c: -c["score"])


def s4_retractions(recs: list[Record]) -> list[dict]:
    out = []
    for r in recs:
        if r.kind != "doc":
            continue
        hits = []
        for para in re.split(r"\n\s*\n", r.text):
            flat = " ".join(para.split())
            if RETRACTION.search(flat) and 40 < len(flat) < 400:
                hits.append(flat)
        if hits:
            out.append(
                {
                    "score": len(hits),
                    "question": f"[{r.repo}] {Path(r.rid).stem}: what did this revise?",
                    "changed_by": r,
                    "detail": hits[0][:300],
                    "stale": [],
                    "extra": hits[1:4],
                }
            )
    return sorted(out, key=lambda c: -c["score"])


def s5_contested(recs: list[Record], index: dict[str, list[Record]]) -> list[dict]:
    """Lowest-precision signal by design: heavy discussion means active development,
    which is only sometimes a changed answer. Gated on a record that actually states
    change intent, otherwise this returns an index of the busiest identifiers."""
    out = []
    for sym, rs in index.items():
        dated = [r for r in rs if r.ts]
        if len(dated) < 6 or not is_identifier(sym):
            continue
        span = max(r.ts for r in dated) - min(r.ts for r in dated)
        if span < timedelta(days=45):
            continue
        kinds = {r.kind for r in dated}
        if len(kinds) < 2:  # cross-source disagreement is the interesting case
            continue
        dated.sort(key=lambda r: r.ts)
        movers = [r for r in dated if RENAME_INTENT.search(r.text) or RETRACTION.search(r.text)]
        if not movers:
            continue
        out.append(
            {
                "score": len(movers) * len(kinds),
                "question": f"What is the current state of `{sym}`?",
                "changed_by": dated[-1],
                "detail": (
                    f"{len(dated)} records over {span.days}d across {'+'.join(sorted(kinds))}; "
                    f"{len(movers)} state change or retraction"
                ),
                "stale": dated[:-1],
            }
        )
    return sorted(out, key=lambda c: -c["score"])


# --- report ------------------------------------------------------------------


def fmt(c: dict) -> str:
    r = c["changed_by"]
    lines = [
        f"### {c['question']}",
        "",
        f"- **evidence:** {c['detail']}",
        f"- **current:** `{r.ref}` ({r.kind}, {r.ts:%Y-%m-%d}) — {r.title[:90] or r.rid}",
    ]
    for s in c["stale"][:4]:
        lines.append(f"- **stale:** `{s.ref}` ({s.kind}, {s.ts:%Y-%m-%d}) — {s.title[:80] or s.rid}")
    if len(c["stale"]) > 4:
        lines.append(f"- **stale:** …and {len(c['stale']) - 4} more")
    for x in c.get("extra", []):
        lines.append(f"- **also:** {x[:200]}")
    return "\n".join(lines) + "\n"


def main() -> None:
    recs = load_all()
    index: dict[str, list[Record]] = defaultdict(list)
    for r in recs:
        for s in symbols(r.text):
            index[s].append(r)

    signals = [
        ("S1 — rename / replace", s1_renames(recs, index)),
        ("S2 — doc lineage", s2_lineage(recs)),
        ("S3 — metric drift", s3_metric_drift(recs)),
        ("S4 — explicit retraction", s4_retractions(recs)),
        ("S5 — contested symbol", s5_contested(recs, index)),
    ]

    body = [
        "# Stale-answer question candidates",
        "",
        "Auto-harvested review queue (`eval/harvest.py`). **Not a gold set.** Each item needs a",
        "human to accept, cut, or rewrite into a question with a gold answer. Target ≥12 accepted",
        "(PLAN §1).",
        "",
        f"Corpus: {len(recs)} records, {sum(len(r.text) for r in recs):,} chars, "
        f"{len(index):,} distinct symbols.",
        "",
    ]
    total = 0
    for name, cands in signals:
        shown = cands[:CAP]
        total += len(shown)
        body.append(f"## {name} — {len(cands)} found, {len(shown)} shown")
        if len(cands) > CAP:
            body.append(f"\n*{len(cands) - CAP} lower-scoring candidates not shown.*")
        body.append("")
        body += [fmt(c) for c in shown] or ["*none*\n"]

    OUT.write_text("\n".join(body))
    print(f"\n{total} candidates → {OUT}")
    for name, cands in signals:
        print(f"  {name:<28} {len(cands):>4} found")


if __name__ == "__main__":
    main()
