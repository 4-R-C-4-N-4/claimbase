"""Adapter C — dated benchmark run directories.

The contract's real exam. Every other Phase 0 adapter walks a file tree and reads
git; this one has a **directory** for a unit, takes its timestamp from the **path**
(rellm has 20 commits total, so git carries no signal), reads **tables** rather than
prose, and feeds the extractor **nothing**. If the seam survives it unmodified the
seam is probably real.

It also produces the purest bitemporal claims available: "v2 F1 = 0.443 on the
181-run bench" is a measurement with an exactly known assertion date, so the same
metric restated by a later run supersedes with no inference at all.

Two directories have no parseable timestamp in the name. They get `captured_at =
None` rather than an invented date — DESIGN §4.4.

Comparability warning, learned the hard way (findings.md): two benches can report
the same metric for the same model and not be comparable, because they scored
different chunk sets. The bench name and its scored-cell count travel with every
claim so nothing downstream can silently compare across rulers.
"""

from __future__ import annotations

import csv
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Iterator

from ..core.contract import REGISTRY
from ..core.models import Claim, Edge, Event, Kind, Mention, SchemaType, Trust

DIR_TS = re.compile(r"(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z|\d{8}T\d{6}Z)$")

# report.txt — per-model summary
SUMMARY_ROW = re.compile(
    r"^\s*(\S+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)%\s+"
    r"([\d.]+)\s+([\d.]+)\s+(\d+)\s*$"
)
MACRO_ROW = re.compile(r"^\s*(\S+)\s+macro-F1\s*=\s*([\d.]+)")
# report_human.txt — a different table entirely: model split TP FP FN TN prec rec F1 spec n
HUMAN_ROW = re.compile(
    r"^\s*(\S+)\s+(ALL|test|tune)\s+\d+\s+\d+\s+\d+\s+\d+\s+"
    r"([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+[\d.]+\s+(\d+)\s*$"
)

REPORTS = (("report.txt", "teacher"), ("report_human.txt", "human"))


def _parse_dir_ts(name: str) -> datetime | None:
    m = DIR_TS.search(name)
    if not m:
        return None  # honest: some directories simply are not dated
    raw = m.group(1)
    try:
        if "-" in raw[10:]:
            d, t = raw.rstrip("Z").split("T")
            return datetime.fromisoformat(f"{d}T{t.replace('-', ':')}").replace(
                tzinfo=timezone.utc
            )
        return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


class RunArtifacts:
    name = "run_artifacts"

    def __init__(self, bench_root: Path | None, corpus: str = "guru") -> None:
        self.bench_root = bench_root
        self.corpus = corpus
        self.skipped: dict[str, str] = {}

    # --- comparability --------------------------------------------------------

    def _eval_set_size(self, run_dir: Path) -> int | None:
        """How many distinct chunks a bench scored. Two runs are comparable only if
        they scored the same set; the count travels so that a later comparison can
        at least notice a mismatch."""
        p = run_dir / "cells.csv"
        if not p.exists():
            return None
        with p.open() as fh:
            return len({r["chunk_id"] for r in csv.DictReader(fh) if "chunk_id" in r})

    @staticmethod
    def _metrics(text: str) -> list[tuple[str, str, float, int | None]]:
        """(model, metric, value, n) from either report format."""
        out: list[tuple[str, str, float, int | None]] = []
        in_summary = False
        for line in text.splitlines():
            if line.startswith("==="):
                in_summary = "Per-model summary" in line
                continue
            if in_summary and (m := SUMMARY_ROW.match(line)):
                n = int(m.group(9))
                out += [
                    (m.group(1), "precision", float(m.group(2)), n),
                    (m.group(1), "recall", float(m.group(3)), n),
                    (m.group(1), "F1", float(m.group(4)), n),
                ]
            if m := MACRO_ROW.match(line):
                out.append((m.group(1), "macro-F1", float(m.group(2)), None))
            if (m := HUMAN_ROW.match(line)) and m.group(2) == "ALL":
                n = int(m.group(6))  # ALL and test duplicate each other in this table
                out += [
                    (m.group(1), "precision", float(m.group(3)), n),
                    (m.group(1), "recall", float(m.group(4)), n),
                    (m.group(1), "F1", float(m.group(5)), n),
                ]
        return out

    # --- contract -------------------------------------------------------------

    def scan(self) -> Iterator[object]:
        if not self.bench_root or not self.bench_root.is_dir():
            return
        for d in sorted(p for p in self.bench_root.iterdir() if p.is_dir()):
            found = False
            for fname, variant in REPORTS:
                if (d / fname).exists():
                    found = True
                    yield {"dir": d, "file": d / fname, "variant": variant}
            if not found:
                # Metrics are recoverable from cells.csv by aggregation; deliberately
                # out of scope for Phase 0, and said out loud rather than dropped.
                self.skipped[d.name] = "no report.txt or report_human.txt"

    def to_event(self, unit: object) -> Event | None:
        u: dict = unit  # type: ignore[assignment]
        d, path, variant = u["dir"], u["file"], u["variant"]
        return Event(
            source=self.name,
            corpus=self.corpus,
            source_ref=f"rellm:runs/bench/{d.name}#{variant}",
            content=path.read_text(),
            captured_at=_parse_dir_ts(d.name),  # from the path; None is legal
            meta={
                "bench": d.name,
                "variant": variant,
                "eval_set_size": self._eval_set_size(d),
            },
        )

    def structured_claims(self, event: Event) -> Iterable[Claim]:
        m = event.meta
        bench = re.sub(r"-?(\d{4}-\d{2}-\d{2}T[\d-]+Z|\d{8}T\d{6}Z)$", "", m["bench"]) or m["bench"]
        for model, metric, value, n in self._metrics(event.content):
            yield Claim(
                event_id=event.id,
                content=(
                    f"{model} {metric} = {value:.3f} on the {bench} bench "
                    f"({m['variant']}-graded{f', n={n}' if n else ''})"
                ),
                subject=model,
                predicate=metric,
                kind=Kind.FACT,
                # A measurement artifact is not model prose: a script computed it and
                # the numbers are reproducible from cells.csv. This is the highest
                # trust available in the corpus, and it must outrank curated memory.
                trust=Trust.HUMAN,
                asserted_at=event.captured_at,
                valid_from=event.captured_at,
                confidence=1.0,
                meta={
                    "metric": metric,
                    "value": value,
                    "bench": m["bench"],
                    "variant": m["variant"],
                    "n": n,
                    "eval_set_size": m["eval_set_size"],
                },
            )

    def entity_mentions(self, event: Event) -> Iterable[Mention]:
        seen = set()
        for model, metric, _, _ in self._metrics(event.content):
            if model not in seen:
                seen.add(model)
                yield Mention(text=model, event_id=event.id, entity_type="model")
        yield Mention(text=event.meta["bench"], event_id=event.id, entity_type="bench")

    def edges(self, event: Event) -> Iterable[Edge]:
        bench = event.meta["bench"]
        for model in {m for m, _, _, _ in self._metrics(event.content)}:
            yield Edge(src=f"bench:{bench}", dst=f"model:{model}", rel="scored")

    def declared_types(self) -> Iterable[SchemaType]:
        for name in ("precision", "recall", "F1", "macro-F1"):
            yield SchemaType(kind="predicate", name=name, source="migrated", uses=0)


def build(bench_root: Path | None, corpus: str = "guru") -> RunArtifacts:
    return RunArtifacts(bench_root, corpus)


REGISTRY.register(RunArtifacts(None))
