"""Teacher bake-off: thinking vs no-think, scored on labels that already exist.

Two open questions settled by one run:

1. **Which mode.** Measured on this machine: no-think ~30-34s/passage, thinking
   ~3min (6x). Quality between them has never been measured — the memory note is
   explicit that no-think is "faster and consistent with the applied corpus," not
   better. This is a structured-output task, which is exactly where the plan said
   to settle it.

2. **Is extraction any good at all**, scored against the 728 ticket passages the
   user labelled by hand over four months. No grading session required; PLAN §P0.5
   called this the free second scoreboard.

The ticket vocabulary maps onto claim kinds as the todo adapter maps it, so the
comparison is like-for-like:

    analysis: conclusion -> fact        analysis: evidence -> observation
    analysis: hypothesis -> hypothesis  resolution note    -> decision

Run:  python eval/bakeoff.py --n 40 --mode thinking
      python eval/bakeoff.py --n 40 --mode nothink     (after relaunching no-think)
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from claimbase.extract import EXTRACTOR_VERSION, extract  # noqa: E402

OUT = Path(__file__).parent / "results-bakeoff"

LABEL_TO_KIND = {
    "conclusion": "fact",
    "evidence": "observation",
    "hypothesis": "hypothesis",
    "blame": "observation",
    "resolution": "decision",
}


def labelled_passages(limit: int, seed: int = 11) -> list[dict]:
    """Ticket prose that already carries a human kind label.

    Stratified across labels rather than sampled flat: 622 of the 728 are
    resolutions, so a flat sample would be a decision-detector benchmark and would
    say nothing about the distinction that matters.
    """
    import glob

    buckets: dict[str, list[dict]] = {}
    for f in glob.glob("/home/ivy/Work/guru*/.todo/*/*.json"):
        if f.endswith("config.json"):
            continue
        try:
            d = json.load(open(f))
        except Exception:
            continue
        for a in d.get("analysis") or []:
            lbl, content = a.get("type"), (a.get("content") or "").strip()
            if lbl in LABEL_TO_KIND and len(content) > 120:
                buckets.setdefault(lbl, []).append(
                    {"text": content, "label": lbl, "gold": LABEL_TO_KIND[lbl],
                     "ticket": d.get("id"), "conf": a.get("confidence")}
                )
        r = d.get("resolution") or {}
        if (r.get("note") or "").strip() and len(r["note"]) > 120:
            buckets.setdefault("resolution", []).append(
                {"text": r["note"].strip(), "label": "resolution", "gold": "decision",
                 "ticket": d.get("id"), "conf": None}
            )

    rng = random.Random(seed)
    per = max(1, limit // max(len(buckets), 1))
    out: list[dict] = []
    for lbl, rows in sorted(buckets.items()):
        rng.shuffle(rows)
        out.extend(rows[:per])
    rng.shuffle(out)
    return out[:limit]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--mode", required=True, choices=["thinking", "nothink"])
    ap.add_argument("--max-tokens", type=int, default=8192)
    args = ap.parse_args()

    rows = labelled_passages(args.n)
    print(f"  {len(rows)} labelled passages, mode={args.mode}, {EXTRACTOR_VERSION}")
    OUT.mkdir(exist_ok=True)

    results, t0 = [], time.time()
    for i, r in enumerate(rows, 1):
        started = time.time()
        try:
            claims, raw = extract(r["text"], max_tokens=args.max_tokens)
            err = None
        except Exception as e:  # a run that dies at item 30 of 40 should keep its 29
            claims, raw, err = [], "", f"{type(e).__name__}: {e}"
        dt = time.time() - started
        kinds = [c.kind for c in claims]
        results.append(
            {
                "ticket": r["ticket"], "label": r["label"], "gold": r["gold"],
                "n_claims": len(claims), "kinds": kinds,
                # Two readings: did the human's kind appear at all, and was it the
                # most common one. Extraction splits a passage into several claims,
                # so "contains" is the fair test and "dominant" the strict one.
                "contains": r["gold"] in kinds,
                "dominant": (max(set(kinds), key=kinds.count) == r["gold"]) if kinds else False,
                "secs": round(dt, 1), "error": err,
                "empty_raw": bool(raw) and not claims,
            }
        )
        done = time.time() - t0
        print(
            f"    {i}/{len(rows)}  {dt:5.1f}s  {r['gold']:<11} -> "
            f"{','.join(kinds[:3]) or '(none)':<28} eta {(done/i)*(len(rows)-i)/60:5.1f}m",
            flush=True,
        )

    ok = [r for r in results if not r["error"]]
    n = max(len(ok), 1)
    summary = {
        "mode": args.mode,
        "n": len(ok),
        "errors": sum(1 for r in results if r["error"]),
        "parse_failures": sum(1 for r in ok if r["empty_raw"]),
        "contains_rate": round(sum(r["contains"] for r in ok) / n, 3),
        "dominant_rate": round(sum(r["dominant"] for r in ok) / n, 3),
        "avg_claims": round(sum(r["n_claims"] for r in ok) / n, 2),
        "avg_secs": round(sum(r["secs"] for r in ok) / n, 1),
        "total_min": round((time.time() - t0) / 60, 1),
        "by_gold": {},
    }
    for g in sorted({r["gold"] for r in ok}):
        sub = [r for r in ok if r["gold"] == g]
        summary["by_gold"][g] = {
            "n": len(sub),
            "contains": round(sum(r["contains"] for r in sub) / len(sub), 3),
        }
    (OUT / f"{args.mode}.json").write_text(json.dumps({"summary": summary, "rows": results}, indent=2))
    print("\n  " + json.dumps(summary, indent=2).replace("\n", "\n  "))


if __name__ == "__main__":
    main()
