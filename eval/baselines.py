"""The two baselines Phase 0 must beat.

Built before any extraction code exists, so the bar is set by something other
than the system being measured (PLAN §3, Risk §10.1).

  rg      — keyword grep over the source trees, ranked by hit count. The thing
            an agent actually does today when it has no index.
  chunks  — split records into ~800-char chunks, embed with nomic-embed-text,
            cosine top-k. Plain RAG: the honest competitor.

`chunks` is the one that matters. Beating `rg` proves nothing; the Phase 0 claim
is that atomic claims with provenance and validity beat chunks with similarity.

Embeddings are cached under eval/.cache so re-runs cost nothing.

Run: python3 eval/baselines.py [--k 10]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from corpus import REPOS, Record, load_all, repo_path  # noqa: E402

CACHE = Path(__file__).parent / ".cache"
OLLAMA = "http://localhost:11434/api/embed"
EMBED_MODEL = "nomic-embed-text:v1.5"
CHUNK_CHARS = 800
CHUNK_OVERLAP = 120

STOP = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "do", "does", "did", "what",
    "which", "who", "when", "where", "why", "how", "should", "would", "could", "for", "of",
    "in", "on", "at", "to", "and", "or", "it", "its", "this", "that", "still", "current",
    "currently", "now", "path", "used", "use", "run", "after", "beat", "live", "does",
}


# --- baseline 1: rg ----------------------------------------------------------


def keywords(question: str) -> list[str]:
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_.]{2,}", question.lower())
    return [w for w in dict.fromkeys(words) if w not in STOP][:6]


def rg_search(question: str, k: int = 10) -> list[tuple[str, float]]:
    """Rank files by how many of the question's keywords they contain."""
    hits: dict[str, int] = {}
    for kw in keywords(question):
        for repo in REPOS:
            out = subprocess.run(
                ["rg", "-l", "-i", "--glob", "!.git", "-e", re.escape(kw), str(repo_path(repo))],
                capture_output=True,
                text=True,
            ).stdout
            for line in out.splitlines():
                p = Path(line)
                try:
                    rel = p.relative_to(repo_path(repo))
                except ValueError:
                    continue
                hits[f"{repo}:{rel}"] = hits.get(f"{repo}:{rel}", 0) + 1
    ranked = sorted(hits.items(), key=lambda kv: -kv[1])[:k]
    return [(ref, float(n)) for ref, n in ranked]


# --- baseline 2: chunk RAG ---------------------------------------------------


def chunk_records(recs: list[Record]) -> list[dict]:
    out = []
    for r in recs:
        text = r.text
        step = CHUNK_CHARS - CHUNK_OVERLAP
        for i in range(0, max(len(text), 1), step):
            piece = text[i : i + CHUNK_CHARS]
            if len(piece.strip()) < 40:
                continue
            out.append({"ref": r.ref, "kind": r.kind, "offset": i, "text": piece})
    return out


def embed(texts: list[str], batch: int = 64) -> list[list[float]]:
    """Batched embedding via Ollama. Kept dependency-free on purpose — this runs
    before the project has an install step."""
    import urllib.request

    vecs: list[list[float]] = []
    for i in range(0, len(texts), batch):
        payload = json.dumps({"model": EMBED_MODEL, "input": texts[i : i + batch]}).encode()
        req = urllib.request.Request(OLLAMA, data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            vecs.extend(json.loads(resp.read())["embeddings"])
        print(f"    embedded {min(i + batch, len(texts))}/{len(texts)}", end="\r", flush=True)
    print()
    return vecs


def unload_model() -> None:
    """Leave the GPU as we found it — idle is the preferred resting state."""
    import urllib.request

    payload = json.dumps({"model": EMBED_MODEL, "input": [""], "keep_alive": 0}).encode()
    try:
        urllib.request.urlopen(
            urllib.request.Request(OLLAMA, data=payload, headers={"Content-Type": "application/json"}),
            timeout=30,
        ).read()
    except Exception:
        pass


def build_index(recs: list[Record]) -> tuple[list[dict], "object"]:
    import numpy as np

    chunks = chunk_records(recs)
    fingerprint = hashlib.sha256(
        "".join(c["ref"] + str(c["offset"]) for c in chunks).encode()
    ).hexdigest()[:16]
    CACHE.mkdir(exist_ok=True)
    cached = CACHE / f"chunks-{fingerprint}.npy"
    if cached.exists():
        mat = np.load(cached)
        print(f"  chunk index: {len(chunks)} chunks (cached)")
    else:
        print(f"  chunk index: embedding {len(chunks)} chunks…")
        mat = np.array(embed([c["text"] for c in chunks]), dtype="float32")
        mat /= np.linalg.norm(mat, axis=1, keepdims=True) + 1e-9
        np.save(cached, mat)
        unload_model()
    return chunks, mat


def chunk_search(question: str, chunks: list[dict], mat, k: int = 10) -> list[tuple[str, float]]:
    import numpy as np

    q = np.array(embed([question])[0], dtype="float32")
    q /= np.linalg.norm(q) + 1e-9
    sims = mat @ q
    best: dict[str, float] = {}
    for idx in np.argsort(-sims)[: k * 8]:
        ref = chunks[idx]["ref"]
        best[ref] = max(best.get(ref, 0.0), float(sims[idx]))  # best chunk per record
    return sorted(best.items(), key=lambda kv: -kv[1])[:k]


# --- the system under test: claims ------------------------------------------

DSN = "postgresql://claimbase:claimbase@localhost:5433/claimbase"

_TICKET = re.compile(r"^(?P<repo>[\w-]+):\.todo/\w+/(?P<id>\w+)\.json")
_DOC = re.compile(r"^(?P<repo>[\w-]+):(?P<path>[^@]+)")
_RUN = re.compile(r"^rellm:runs/bench/(?P<dir>[^#]+)#(?P<variant>\w+)")


def to_gold_ref(source_ref: str) -> str:
    """Map an event's provenance onto the gold set's naming convention.

    The gold refs were written against eval/corpus.py's record ids, which predate
    the adapters. Normalising here rather than rewriting the gold set keeps the
    questions independent of how the pipeline happens to spell provenance today.
    """
    if m := _RUN.match(source_ref):
        return f"rellm:{m['dir']}#{m['variant']}"
    if m := _TICKET.match(source_ref):
        return f"{m['repo']}:{m['id']}"
    ref = source_ref.split("#")[0]
    if m := _DOC.match(ref):
        return f"{m['repo']}:{m['path']}"
    return source_ref


def claim_search(question: str, k: int = 10, active_only: bool = True) -> list[tuple[str, float]]:
    """Delegates to the shipped `claimbase.recall`.

    An earlier version reimplemented retrieval here, which meant the scoreboard was
    measuring a copy of the system rather than the system. Any ranking change had to
    be made twice to show up, and a divergence between them would have been
    invisible.
    """
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent.parent / "src"))
    import psycopg

    from claimbase.recall import recall as _recall

    with psycopg.connect(DSN) as conn:
        hits = _recall(question, conn=conn, k=k * 4, include_superseded=not active_only)
    best: dict[str, float] = {}
    for h in hits:
        ref = to_gold_ref(h.source_ref)
        best[ref] = max(best.get(ref, 0.0), h.score)
    return sorted(best.items(), key=lambda kv: -kv[1])[:k]


# --- scoring -----------------------------------------------------------------


def load_gold() -> list[dict]:
    p = Path(__file__).parent / "gold_recall.jsonl"
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


def ndcg(ranked: list[str], gold: set[str], k: int = 10) -> float:
    import math

    if not gold:
        return float("nan")  # nothing to find — see stale-rate instead
    dcg = sum(1 / math.log2(i + 2) for i, ref in enumerate(ranked[:k]) if ref in gold)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(gold), k)))
    return dcg / ideal if ideal else 0.0


def stale_wins(ranked: list[str], stale: set[str], gold: set[str], k: int = 10) -> float | None:
    """1.0 if a superseded record outranks every correct one — i.e. would mislead.

    A flat "fraction of top-k that is stale" does not discriminate: a superseded doc
    at rank 9 is harmless, at rank 1 it is the wrong answer. What matters is whether
    the stale record *wins*. When gold_refs is empty (nothing in the corpus states
    the correct answer — the auto-promote case) any stale hit wins by default, which
    is the honest reading: there is nothing for it to lose to.
    """
    if not stale:
        return None
    top = ranked[:k]
    first_stale = next((i for i, r in enumerate(top) if r in stale), None)
    if first_stale is None:
        return 0.0
    first_gold = next((i for i, r in enumerate(top) if r in gold), None)
    return 1.0 if first_gold is None or first_stale < first_gold else 0.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10)
    args = ap.parse_args()

    recs = load_all()
    gold = load_gold()
    print(f"\n{len(recs)} records, {len(gold)} gold questions\n")
    chunks, mat = build_index(recs)

    rows = []
    for g in gold:
        gold_set, stale_set = set(g["gold_refs"]), set(g["stale_refs"])
        r_rg = [ref for ref, _ in rg_search(g["question"], args.k)]
        r_ch = [ref for ref, _ in chunk_search(g["question"], chunks, mat, args.k)]
        r_cl = [ref for ref, _ in claim_search(g["question"], args.k)]
        rows.append(
            {
                "id": g["id"],
                "class": g["class"],
                "rg_ndcg": ndcg(r_rg, gold_set, args.k),
                "ch_ndcg": ndcg(r_ch, gold_set, args.k),
                "rg_stale": stale_wins(r_rg, stale_set, gold_set, args.k),
                "ch_stale": stale_wins(r_ch, stale_set, gold_set, args.k),
                "cl_ndcg": ndcg(r_cl, gold_set, args.k),
                "cl_stale": stale_wins(r_cl, stale_set, gold_set, args.k),
            }
        )
    unload_model()

    def avg(key):
        vals = [r[key] for r in rows if r[key] is not None and r[key] == r[key]]
        return sum(vals) / len(vals) if vals else float("nan")

    hdr = (f"\n{'id':<6} {'class':<13} {'rg':>6} {'chunk':>7} {'claims':>7}   "
           f"{'rg~':>5} {'ch~':>5} {'cl~':>5}")
    print(hdr)
    print("-" * 64)
    for r in rows:
        f = lambda v: "  —  " if v is None or v != v else f"{v:.3f}"  # noqa: E731
        print(
            f"{r['id']:<6} {r['class']:<13} {f(r['rg_ndcg']):>6} {f(r['ch_ndcg']):>7} "
            f"{f(r['cl_ndcg']):>7}   {f(r['rg_stale']):>5} {f(r['ch_stale']):>5} "
            f"{f(r['cl_stale']):>5}"
        )
    print("-" * 64)
    print(
        f"{'MEAN':<20} {avg('rg_ndcg'):>6.3f} {avg('ch_ndcg'):>7.3f} {avg('cl_ndcg'):>7.3f}   "
        f"{avg('rg_stale'):>5.3f} {avg('ch_stale'):>5.3f} {avg('cl_stale'):>5.3f}"
    )
    print("\nnDCG: higher is better.  ~ = mislead-rate: lower is better.")
    print("claims = structured + extracted + captured; supersession + conflict resolution active.")
    Path(__file__).parent.joinpath("results-baselines.json").write_text(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
