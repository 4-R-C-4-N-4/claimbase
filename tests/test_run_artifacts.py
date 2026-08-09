"""Adapter C — the properties no other Phase 0 adapter exercises."""

from __future__ import annotations

from pathlib import Path

import pytest
from test_conformance import check_source

from claimbase.core.models import Kind, Trust
from claimbase.sources.run_artifacts import RunArtifacts, _parse_dir_ts

BENCH = Path("/home/ivy/Work/rellm/runs/bench")
live_only = pytest.mark.skipif(not BENCH.is_dir(), reason="rellm bench dir not present")

REPORT = """
=== Per-model summary ===
model           precision     recall       F1    MAE   parse%   lat(s)   n_emit   runs
base                0.291      0.515    0.372   0.52   100.0%    17.93     36.3    181
v3                  0.439      0.545    0.486   0.42   100.0%     9.27     14.2    181

=== Macro-F1 (averaged over concepts that appear in either teacher or model) ===
  base           macro-F1 = 0.264   (over 120 concepts)
"""

HUMAN_REPORT = """
=== Per-model x split, humans-as-truth ===
model        split       TP    FP    FN    TN    prec     rec      F1    spec      n
base         ALL        452   262   355   428   0.633   0.560   0.594   0.620   1497
base         test       452   262   355   428   0.633   0.560   0.594   0.620   1497
"""


def _bench(tmp: Path, name: str, body: str, fname: str = "report.txt") -> Path:
    d = tmp / name
    d.mkdir(parents=True, exist_ok=True)
    (d / fname).write_text(body)
    return tmp


def test_timestamp_comes_from_the_path_not_git() -> None:
    assert _parse_dir_ts("qwen3-4b-v3-2026-08-07T13-26-57Z").year == 2026
    assert _parse_dir_ts("base-prod-tokens-20260527T200153Z").month == 5


def test_undated_directory_yields_null_captured_at(tmp_path: Path) -> None:
    """grammar-test and smoke-human have no timestamp. Inventing one would be a lie
    with a timestamp (DESIGN §4.4)."""
    root = _bench(tmp_path, "grammar-test", REPORT)
    src = RunArtifacts(root)
    ev = src.to_event(next(src.scan()))
    assert ev.captured_at is None
    assert ev.source_ref  # provenance is still complete


def test_unit_is_a_directory_and_both_reports_are_separate_events(tmp_path: Path) -> None:
    """report.txt and report_human.txt disagree about which model wins; collapsing
    them would erase the corpus's best supersession pair."""
    root = _bench(tmp_path, "b-2026-08-07T13-26-57Z", REPORT)
    _bench(tmp_path, "b-2026-08-07T13-26-57Z", HUMAN_REPORT, "report_human.txt")
    src = RunArtifacts(root)
    events = [src.to_event(u) for u in src.scan()]
    assert len(events) == 2
    assert {e.meta["variant"] for e in events} == {"teacher", "human"}


def test_metric_claims_carry_bench_identity(tmp_path: Path) -> None:
    """Comparability is the trap this corpus sets: the bench name and n must travel
    so nothing downstream compares across rulers."""
    root = _bench(tmp_path, "b-2026-08-07T13-26-57Z", REPORT)
    src = RunArtifacts(root)
    claims = list(src.structured_claims(src.to_event(next(src.scan()))))
    assert {c.meta["metric"] for c in claims} >= {"precision", "recall", "F1", "macro-F1"}
    assert all(c.meta["bench"] for c in claims)
    f1 = next(c for c in claims if c.subject == "v3" and c.meta["metric"] == "F1")
    assert f1.meta["value"] == 0.486 and f1.meta["n"] == 181
    assert f1.kind is Kind.OBSERVATION and f1.trust is Trust.HUMAN


def test_human_table_format_is_parsed(tmp_path: Path) -> None:
    root = _bench(tmp_path, "b-2026-08-07T13-26-57Z", HUMAN_REPORT, "report_human.txt")
    src = RunArtifacts(root)
    claims = list(src.structured_claims(src.to_event(next(src.scan()))))
    f1 = next(c for c in claims if c.meta["metric"] == "F1")
    assert f1.meta["value"] == 0.594 and f1.meta["n"] == 1497


def test_directories_without_reports_are_reported_not_dropped(tmp_path: Path) -> None:
    (tmp_path / "cells-only").mkdir()
    src = RunArtifacts(tmp_path)
    list(src.scan())
    assert "cells-only" in src.skipped


def test_contributes_no_prose(tmp_path: Path) -> None:
    """This adapter feeds the graph and not the extractor. A pipeline that assumes
    every source produces prose would break here, which is the point of it."""
    root = _bench(tmp_path, "b-2026-08-07T13-26-57Z", REPORT)
    src = RunArtifacts(root)
    ev = src.to_event(next(src.scan()))
    assert all(c.kind is Kind.OBSERVATION for c in src.structured_claims(ev))


@live_only
def test_conformance_against_live_bench() -> None:
    src = RunArtifacts(BENCH)
    stats = check_source(src)
    print(f"\n  run_artifacts: {stats}, skipped={len(src.skipped)}")
    assert stats["claims"] > 60, stats
    # The two undated directories (grammar-test, smoke-human) carry no report at
    # all, so they are skipped before they could exercise the null-captured_at
    # path. PLAN §0.4 claimed them as a forcing function; they are not one. The
    # nullable contract is still correct — it is simply untested by this corpus,
    # and only the synthetic case above covers it.
    assert {"grammar-test", "smoke-human"} <= set(src.skipped), src.skipped
