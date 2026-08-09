"""claimbase CLI.

    python -m claimbase import [--corpus guru]
    python -m claimbase stats
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

from .core.store import Store, connect

ROOT = Path(__file__).resolve().parent.parent.parent
CORPORA = ROOT / "corpora"
HARNESSES = ROOT / "harnesses"


def load_corpus(name: str) -> dict:
    with (CORPORA / f"{name}.toml").open("rb") as fh:
        spec = tomllib.load(fh)
    for s in spec["source"]:
        if "path" in s:
            s["resolved"] = Path(s["path"]).expanduser()
    return spec


def build_adapters(spec: dict, cache: Path | None = None) -> list:
    """Instantiate exactly the adapters the corpus definition names.

    Deliberately explicit: a corpus that names an unknown adapter should fail here
    rather than silently import less than it claims to.
    """
    from .sources.agent_memory import AgentMemory
    from .sources.git_log import GitLog
    from .sources.markdown_docs import MarkdownDocs
    from .sources.pull_requests import PullRequests
    from .sources.run_artifacts import RunArtifacts
    from .sources.todo_store import TodoStore

    corpus = spec["name"]
    repos = {s["name"]: s["resolved"] for s in spec["source"] if s["kind"] == "repo"}

    def repos_for(adapter: str) -> dict:
        return {
            s["name"]: s["resolved"]
            for s in spec["source"]
            if s["kind"] == "repo" and adapter in s.get("adapters", [])
        }

    adapters = []
    if r := repos_for("todo_store"):
        adapters.append(TodoStore(r, corpus))
    if r := repos_for("markdown_docs"):
        adapters.append(MarkdownDocs(r, corpus))
    if r := repos_for("git_log"):
        adapters.append(GitLog(r, corpus))
    if repos_for("run_artifacts"):
        bench = repos.get("rellm")
        adapters.append(RunArtifacts(bench / "runs" / "bench" if bench else None, corpus))
    adapters.append(PullRequests(repos, corpus, cache=cache))
    mem = [s for s in spec["source"] if s["kind"] == "agent_memory"]
    if mem:
        adapters.append(AgentMemory(mem, HARNESSES, corpus))
    return adapters


def cmd_import(args: argparse.Namespace) -> int:
    spec = load_corpus(args.corpus)
    adapters = build_adapters(spec, cache=ROOT / "eval" / ".cache")
    conn = connect()
    store = Store(conn)
    grand = {"events": 0, "new": 0, "claims": 0, "edges": 0, "entities": 0, "skipped": 0}

    for src in adapters:
        n_ev = n_new = n_cl = n_ed = n_en = 0
        for unit in src.scan():
            ev = src.to_event(unit)
            if ev is None:
                continue
            eid, inserted = store.upsert_event(ev)
            n_ev += 1
            n_new += int(inserted)
            n_cl += store.replace_claims(eid, src.structured_claims(ev))
            n_ed += store.add_edges(spec["name"], src.edges(ev))
            n_en += store.add_mentions(spec["name"], src.entity_mentions(ev))
        store.add_schema_types(spec["name"], src.declared_types())
        conn.commit()
        skipped = len(getattr(src, "skipped", {}) or {})
        grand["events"] += n_ev
        grand["new"] += n_new
        grand["claims"] += n_cl
        grand["edges"] += n_ed
        grand["entities"] += n_en
        grand["skipped"] += skipped
        print(
            f"  {src.name:<16} events {n_ev:>5} (new {n_new:>5})  claims {n_cl:>5}  "
            f"edges {n_ed:>6}  entities {n_en:>5}  skipped {skipped:>4}"
        )

    print(f"\n  {'TOTAL':<16} {grand}")
    conn.close()
    return 0


def cmd_embed(args: argparse.Namespace) -> int:
    """Embed claims that lack a vector. Resumable by construction: the WHERE clause
    is the checkpoint, so an interrupted run costs only the current batch."""
    import json as _json
    import urllib.request

    conn = connect()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, content FROM claims WHERE corpus=%s AND embedding IS NULL",
            (args.corpus,),
        )
        rows = cur.fetchall()
    print(f"  {len(rows)} claims to embed")
    for i in range(0, len(rows), 64):
        batch = rows[i : i + 64]
        payload = _json.dumps(
            {"model": "nomic-embed-text:v1.5", "input": [r[1][:2000] for r in batch]}
        ).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/embed", data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=300) as resp:
            vecs = _json.loads(resp.read())["embeddings"]
        with conn.cursor() as cur:
            for (cid, _), v in zip(batch, vecs):
                cur.execute("UPDATE claims SET embedding=%s WHERE id=%s", (str(v), cid))
        conn.commit()
        print(f"    {min(i + 64, len(rows))}/{len(rows)}", end="\r", flush=True)
    print()
    # Leave the GPU idle — the preferred resting state on this machine.
    try:
        urllib.request.urlopen(
            urllib.request.Request(
                "http://localhost:11434/api/embed",
                data=_json.dumps(
                    {"model": "nomic-embed-text:v1.5", "input": [""], "keep_alive": 0}
                ).encode(),
                headers={"Content-Type": "application/json"},
            ),
            timeout=30,
        ).read()
    except Exception:
        pass
    conn.close()
    return 0


def cmd_assert(args: argparse.Namespace) -> int:
    """The capture path (DESIGN §5 `assert`).

    Some corrections exist nowhere in the corpus — a practice abandoned without
    anyone writing it down. No compiler recovers those, however good: it cannot
    compile what was never captured. This is the write end of the same funnel
    everything else goes through, so an asserted fact carries provenance and a
    timestamp exactly like an imported one.
    """
    import uuid
    from datetime import datetime, timezone

    from .core.models import Event, Kind, Trust

    ev = Event(
        source="assert",
        corpus=args.corpus,
        source_ref=args.ref or f"assert:{datetime.now(timezone.utc):%Y-%m-%dT%H:%M:%SZ}",
        content=args.text,
        captured_at=datetime.now(timezone.utc),
        meta={"kind": args.kind},
    )
    conn = connect()
    store = Store(conn)
    eid, inserted = store.upsert_event(ev)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO claims (id, corpus, event_id, content, claim_kind, trust,
                   corroborated, asserted_at, valid_from, confidence, status, meta)
               VALUES (%s,%s,%s,%s,%s,%s,true,%s,%s,1.0,'active',%s)""",
            (uuid.uuid4(), args.corpus, eid, args.text, args.kind,
             # A human said it directly: the highest trust tier in the system, and
             # the only path by which one enters other than a measurement artifact.
             str(Trust.HUMAN), ev.captured_at, ev.captured_at,
             json.dumps({"asserted": True})),
        )
    conn.commit()
    conn.close()
    print(f"  {'captured' if inserted else 'already present'}: {ev.source_ref}")
    print(f"  {args.kind} / {Trust.HUMAN} — run `embed` then `supersede` to fold it in")
    return 0


def cmd_supersede(args: argparse.Namespace) -> int:
    from .supersede import run

    report = run(args.corpus, args.dry_run)
    for rule, r in report.items():
        print(f"  {rule:<22} found {r['found']:>6}  applied {r['applied']:>6}")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    with connect() as conn:
        s = Store(conn).stats(args.corpus)
    for k in ("events", "claims", "entities", "edges", "schema_types", "dated_endings"):
        print(f"  {k:<14} {s[k]:>7,}")
    for label in ("by_source", "by_kind", "by_trust"):
        print(f"\n  {label}:")
        for k, v in s[label].items():
            print(f"    {k:<32} {v:>7,}")
    return 0


def cmd_review(args: argparse.Namespace) -> int:
    from .review.server import serve

    return serve(args.host, args.port, args.limit)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="claimbase")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("import", help="compile a corpus into the store")
    p.add_argument("--corpus", default="guru")
    p.set_defaults(fn=cmd_import)
    p = sub.add_parser("embed", help="embed claims lacking a vector")
    p.add_argument("--corpus", default="guru")
    p.set_defaults(fn=cmd_embed)
    p = sub.add_parser("assert", help="capture a fact directly (DESIGN §5)")
    p.add_argument("text")
    p.add_argument("--kind", default="practice")
    p.add_argument("--ref", default=None)
    p.add_argument("--corpus", default="guru")
    p.set_defaults(fn=cmd_assert)
    p = sub.add_parser("supersede", help="apply supersession rules")
    p.add_argument("--corpus", default="guru")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_supersede)
    p = sub.add_parser("stats", help="what is in the store")
    p.add_argument("--corpus", default="guru")
    p.set_defaults(fn=cmd_stats)
    p = sub.add_parser("review", help="serve the review queue (grading, conflicts, tensions)")
    p.add_argument("--host", default="0.0.0.0", help="0.0.0.0 so it is reachable over Tailscale")
    p.add_argument("--port", type=int, default=8760)
    p.add_argument("--limit", type=int, default=60)
    p.set_defaults(fn=cmd_review)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
