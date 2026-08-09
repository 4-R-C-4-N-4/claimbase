"""Bench through the MCP transport, not around it.

`baselines.py` imports `claimbase.recall` directly. That is one layer short of what
an agent actually touches: tool schema, argument coercion, JSON serialisation and the
stdio round trip all sit between `recall()` and an answer, and none of them are
measured by calling the function.

This is the same mistake as the earlier one where the eval had its own copy of
retrieval — a scoreboard that skips a layer cannot see that layer break.

Run: python eval/mcp_bench.py
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from baselines import load_gold, ndcg, stale_wins, to_gold_ref  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / ".venv" / "bin" / "python"


async def run() -> None:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    gold = load_gold()
    env = dict(os.environ, PYTHONPATH=str(ROOT / "src"))
    params = StdioServerParameters(
        command=str(PYTHON), args=["-m", "claimbase.mcp_server"], env=env
    )

    rows, latencies = [], []
    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            tools = {t.name for t in (await session.list_tools()).tools}
            print(f"  tools: {sorted(tools)}\n")

            for g in gold:
                t0 = time.time()
                res = await session.call_tool("recall", {"query": g["question"], "k": 10})
                dt = time.time() - t0
                latencies.append(dt)
                payload = json.loads(res.content[0].text)
                if "error" in payload:
                    print(f"  {g['id']}  ERROR {payload['error']}")
                    continue
                # Fold to source records exactly as the direct-call path does, so any
                # divergence here is the transport's doing and not the metric's.
                best: dict[str, float] = {}
                for h in payload["results"]:
                    ref = to_gold_ref(h["source"].split(": ", 1)[-1])
                    best[ref] = max(best.get(ref, 0.0), h["score"])
                ranked = [k for k, _ in sorted(best.items(), key=lambda kv: -kv[1])]
                gold_set, stale_set = set(g["gold_refs"]), set(g["stale_refs"])
                rows.append(
                    {
                        "id": g["id"],
                        "ndcg": ndcg(ranked, gold_set),
                        "mislead": stale_wins(ranked, stale_set, gold_set),
                        "secs": round(dt, 2),
                    }
                )

    def avg(key):
        vals = [r[key] for r in rows if r[key] is not None and r[key] == r[key]]
        return sum(vals) / len(vals) if vals else float("nan")

    print(f"  {'id':<6} {'nDCG':>7} {'mislead':>8} {'secs':>6}")
    print("  " + "-" * 30)
    for r in rows:
        f = lambda v: "  —  " if v is None or v != v else f"{v:.3f}"  # noqa: E731
        print(f"  {r['id']:<6} {f(r['ndcg']):>7} {f(r['mislead']):>8} {r['secs']:>6.2f}")
    print("  " + "-" * 30)
    print(f"  {'MEAN':<6} {avg('ndcg'):>7.3f} {avg('mislead'):>8.3f} "
          f"{statistics.mean(latencies):>6.2f}")
    print(f"\n  p95 latency {sorted(latencies)[int(len(latencies) * 0.95) - 1]:.2f}s "
          f"(query embedding dominates; the graph read is a single indexed scan)")
    Path(__file__).parent.joinpath("results-mcp.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    asyncio.run(run())
