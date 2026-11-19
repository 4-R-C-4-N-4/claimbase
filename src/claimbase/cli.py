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


# Commands that can destroy work. Extraction costs hours of GPU; entities and
# links cost seconds. Anything that deletes or rewrites claims takes a snapshot
# first, because both times claims were lost it was a command that looked routine.
DESTRUCTIVE = {"import", "entities", "link", "supersede", "resolve", "compile"}


def auto_backup(label: str) -> None:
    import subprocess

    script = ROOT / "scripts" / "backup_db.sh"
    if not script.exists():
        return
    r = subprocess.run([str(script), label], capture_output=True, text=True)
    if r.returncode == 0:
        line = next((l for l in r.stdout.splitlines() if l.strip().startswith("ok:")), "ok")
        print(f"  {line.strip()}")
    else:
        # A failed backup must stop the destructive command, not warn and continue.
        raise SystemExit(f"  backup failed, refusing to proceed:\n{r.stderr.strip()}")


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

    # Captured facts are events like any other, but no adapter produces them, so
    # nothing regenerated their claims after the store was rebuilt — and the one
    # answer the compiler could never recover was also the one it could not restore.
    # Rebuilding them here makes capture derived, which is the guarantee the rest of
    # the pipeline already keeps.
    n_cap = rebuild_captured(store, conn, spec["name"])
    if n_cap:
        print(f"  {'captured':<16} claims {n_cap:>5}  (rebuilt from assert events)")
    print(f"\n  {'TOTAL':<16} {grand}")
    conn.close()
    return 0


def rebuild_captured(store, conn, corpus: str) -> int:
    """Recreate claims for `assert` events that have none."""
    from .core.models import Kind, Trust
    from .core.store import stable_claim_id

    made = 0
    with conn.cursor() as cur:
        cur.execute(
            """SELECT e.id, e.content, e.captured_at, e.meta, e.source_ref
                 FROM events e
                WHERE e.corpus = %s AND e.source = 'assert'
                  AND NOT EXISTS (SELECT 1 FROM claims c WHERE c.event_id = e.id)""",
            (corpus,),
        )
        for eid, content, ts, meta, ref in cur.fetchall():
            meta = meta or {}
            # A capture made through MCP is an agent's; one made on the CLI is the
            # user speaking directly. The tier decides what the claim may assert.
            via_mcp = meta.get("via") == "mcp"
            trust = Trust.AGENT if via_mcp else Trust.HUMAN
            kind = Kind(meta.get("kind", "observation" if via_mcp else "practice"))
            cur.execute(
                """INSERT INTO claims (id, corpus, event_id, content, claim_kind, trust,
                       corroborated, asserted_at, valid_from, confidence, status, meta)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'active',%s)""",
                (stable_claim_id(eid, str(kind), content), corpus, eid, content,
                 str(kind), str(trust),
                 not via_mcp, ts, ts, 1.0 if not via_mcp else 0.7,
                 json.dumps({"asserted": True, "rebuilt": True, **meta})),
            )
            made += 1
    conn.commit()
    return made


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
    from datetime import datetime, timezone

    from .core.models import Event, Kind, Trust
    from .core.store import stable_claim_id

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
               VALUES (%s,%s,%s,%s,%s,%s,true,%s,%s,1.0,'active',%s)
               ON CONFLICT (id) DO NOTHING""",
            (stable_claim_id(eid, args.kind, args.text), args.corpus, eid, args.text,
             args.kind,
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


def _embed_one(text: str) -> list[float]:
    """One embedding via Ollama. Shared by recall and the eval harness so the
    scoreboard measures the shipped path rather than a copy of it."""
    import json as _json
    import urllib.request

    payload = _json.dumps({"model": "nomic-embed-text:v1.5", "input": [text]}).encode()
    req = urllib.request.Request(
        "http://localhost:11434/api/embed", data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        return _json.loads(resp.read())["embeddings"][0]


def cmd_recall(args: argparse.Namespace) -> int:
    from .recall import recall

    with connect() as conn:
        hits = recall(args.query, conn=conn, corpus=args.corpus, k=args.k,
                      include_superseded=args.include_superseded)
    for h in hits:
        print(f"\n  [{h.score:.3f}] {h.content[:300]}")
        print(f"      {h.why()}")
        print(f"      {h.source}: {h.source_ref}")
    if not hits:
        print("  (nothing)")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Pin a directory tree to a project with a `.claimbase` marker.

    Inside a git repo the marker goes at the repo root and, unless --name is
    given, records the name the project already resolves to, so existing
    memory stays attached. In a plain folder it goes in that folder, named
    after it. Commit the file so clones and renames keep the identity."""
    from . import projects

    here = Path(args.path or ".").expanduser().resolve()
    if not here.is_dir():
        print(f"  not a directory: {here}", file=sys.stderr)
        return 2
    root = projects._git_root(here) or here
    if root.is_file():
        root = root.parent
    name = projects.normalize(args.name) if args.name else projects.resolve(cwd=root)
    if name == projects.USER_SCOPE:
        if args.name:
            print("  'self' is the user scope; a directory cannot be pinned to it",
                  file=sys.stderr)
            return 2
        name = projects.normalize(root.name)
    marker = root / projects.MARKER
    if marker.exists() and not args.force:
        current = projects.read_marker(marker)
        print(f"  {marker} already pins this tree to {current!r}; --force to replace",
              file=sys.stderr)
        return 1
    marker.write_text(
        "# Claimbase project identity. Commit this file: memory for everything\n"
        "# under this directory is filed under the name below, whatever the\n"
        "# directory is called or wherever it is cloned.\n"
        f'project = "{name}"\n')
    print(f"  {marker}\n  project: {name}")
    return 0


def cmd_resolve(args: argparse.Namespace) -> int:
    from .resolve import resolve

    r = resolve(args.corpus)
    print(f"  {r['total']} conflicts resolved, {r['claims_superseded']} claims superseded")
    for rule, n in sorted(r["by_rule"].items(), key=lambda kv: -kv[1]):
        print(f"    {rule:<26} {n:>5}")
    weak = r["needs_review"]
    print(f"\n  {len(weak)} low-confidence, ranked by impact (top 10):")
    for v in weak[:10]:
        print(f"    impact {v.impact:>4.0f}  lean={v.winner:<8} {v.rule}")
    return 0


def cmd_entities(args: argparse.Namespace) -> int:
    from .resolve_entities import run

    r = run(args.corpus, dry_run=args.dry_run)
    for k, v in r.items():
        print(f"  {k:<22} {v:>7,}")
    return 0


def cmd_link(args: argparse.Namespace) -> int:
    from .link_entities import run

    for k, v in run(args.corpus).items():
        print(f"  {k:<18} {v:>8,}")
    return 0


def _extraction_pending(conn, corpus: str) -> int:
    """How many prose events the current extractor version has not read. Uses
    extract_run's own selection, so status and the run can never disagree about
    what 'pending' means."""
    from .extract_run import pending_events

    return len(pending_events(conn, corpus))


def _teacher_up() -> bool:
    import urllib.request

    from .llm import LLAMACPP_BASE_URL

    try:
        with urllib.request.urlopen(f"{LLAMACPP_BASE_URL}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


def _teacher_busy() -> str | None:
    """Someone else's name for the GPU, or None if extraction may use it.

    The teacher shares one llama.cpp slot with the guru pipeline's own long runs
    (overnight tagging, dossier generation). Extraction queueing onto that slot
    would interleave with — and roughly double the wall-clock of — a run the
    owner deliberately started, so a busy GPU defers extraction to the next
    compile rather than competing. Two signals, either one is enough:

    - a known pipeline driver process is alive (the reliable signal — a cron
      firing between two batches of a tagging run sees an idle slot and would
      wrongly conclude the GPU is free), or
    - the server reports requests in flight right now (catches drivers this
      list doesn't know about).
    """
    import subprocess
    import urllib.request

    from .llm import LLAMACPP_BASE_URL

    # Match actual script invocations (scripts/<driver>.py), not any command
    # line that merely mentions a driver name — a shell or editor talking
    # *about* tag_concepts must not read as a tagging run. pgrep never reports
    # itself, so no self-exclusion trick is needed.
    probe = subprocess.run(
        ["pgrep", "-af",
         r"scripts/(tag_concepts|build_dossiers|review_dossiers|embed_corpus)\.py"],
        capture_output=True, text=True,
    )
    if probe.stdout.strip():
        return probe.stdout.strip().splitlines()[0]
    try:
        with urllib.request.urlopen(f"{LLAMACPP_BASE_URL}/metrics", timeout=3) as r:
            for line in r.read().decode().splitlines():
                if line.startswith("llamacpp:requests_processing") and float(line.split()[-1]) > 0:
                    return "llama.cpp reports requests in flight"
    except Exception:
        pass  # no metrics endpoint — the pgrep check above is the real gate
    return None


def cmd_status(args: argparse.Namespace) -> int:
    """Where the compiled corpus stands relative to its sources, and what to run.

    The guru driver-loop pattern (guru docs/ingest/README.md): status reads the
    store and the sources directly, so it reports the truth about the corpus
    rather than the truth about what someone remembers doing. This is also the
    go/no-go a future cron checks before and after a `compile`.
    """
    import subprocess
    from datetime import datetime, timezone

    spec = load_corpus(args.corpus)
    conn = connect()
    stale = False

    print(f"  corpus {spec['name']} — compiled state vs sources\n")
    with conn.cursor() as cur:
        # Repos: the latest commit is the freshness frontier for every adapter
        # reading that repo (git_log refs are `<repo>@<sha>`).
        for s in (x for x in spec["source"] if x["kind"] == "repo"):
            cur.execute(
                """SELECT max(captured_at) FROM events
                   WHERE corpus=%s AND source='git_log' AND source_ref LIKE %s""",
                (spec["name"], f"{s['name']}@%"),
            )
            have = cur.fetchone()[0]
            r = subprocess.run(
                ["git", "-C", str(s["resolved"]), "log", "-1", "--format=%cI"],
                capture_output=True, text=True,
            )
            head = datetime.fromisoformat(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else None
            lag = ""
            if have and head:
                behind = (head - have).days
                if behind > 0:
                    n = subprocess.run(
                        ["git", "-C", str(s["resolved"]), "rev-list", "--count",
                         f"--since={have.isoformat()}", "HEAD"],
                        capture_output=True, text=True,
                    ).stdout.strip()
                    lag = f"  [{behind}d behind, ~{n} commits]"
                    stale = True
            print(f"    {s['name']:<14} compiled to {have:%Y-%m-%d} · HEAD {head:%Y-%m-%d}{lag}"
                  if have and head else f"    {s['name']:<14} never imported")

        # Memory sources: newest fact file vs newest compiled event.
        for s in (x for x in spec["source"] if x["kind"] == "agent_memory"):
            root = Path(f"~/.claude/projects/{s['scope']}/memory").expanduser()
            files = [p for p in root.glob("*.md") if p.name != "MEMORY.md"] if root.exists() else []
            newest = max((f.stat().st_mtime for f in files), default=None)
            cur.execute(
                # `:{scope}/` not `%{scope}%`: -Work-guru is a prefix of
                # -Work-guru-web, so a substring match crosses scopes.
                "SELECT max(captured_at) FROM events WHERE corpus=%s AND source='agent_memory' AND source_ref LIKE %s",
                (spec["name"], f"%:{s['scope']}/%"),
            )
            have = cur.fetchone()[0]
            if newest and have:
                newest_dt = datetime.fromtimestamp(newest, tz=timezone.utc)
                mark = ""
                if newest_dt.date() > have.date():
                    mark = f"  [files newer: {newest_dt:%Y-%m-%d}]"
                    stale = True
                print(f"    {s['name']:<14} compiled to {have:%Y-%m-%d}{mark}")

        pending = _extraction_pending(conn, spec["name"])
        cur.execute("SELECT count(*) FROM claims WHERE corpus=%s AND embedding IS NULL", (spec["name"],))
        unembedded = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM conflicts WHERE corpus=%s AND resolution IS NULL", (spec["name"],))
        open_conflicts = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM claims_review WHERE corpus=%s", (spec["name"],))
        review = cur.fetchone()[0]
    conn.close()

    print(f"\n    prose events awaiting extraction   {pending:>6}"
          f"   (teacher {'up' if _teacher_up() else 'DOWN — extraction will be skipped'})")
    print(f"    claims without embedding           {unembedded:>6}")
    print(f"    open conflicts                     {open_conflicts:>6}")
    print(f"    claims_review backlog              {review:>6}")

    if stale or pending or unembedded:
        print("\n  next: python -m claimbase compile")
    else:
        print("\n  compiled state is current; nothing to do")
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    from .extract_run import main as extract_main

    if not _teacher_up():
        print("  no llama.cpp server at :8080 — start the teacher first "
              "(guru/scripts/run-qwen3.8-tagger.sh or `llm qwen3.8`)")
        return 1
    argv = ["--corpus", args.corpus]
    if args.limit:
        argv += ["--limit", str(args.limit)]
    extract_main(argv)
    return 0


def cmd_compile(args: argparse.Namespace) -> int:
    """The whole engine, in order, incremental at every step: import → extract →
    embed → supersede → resolve. One snapshot up front covers the run. This is
    the command a cron will eventually call; until then it is the command a
    human calls when `status` says the corpus is behind.

    Extraction is the only step with an external dependency (the teacher
    server). When it is down the compile still runs — a corpus current on
    structured claims but behind on prose is strictly better than one behind on
    both — but says so loudly, because silence here is how a corpus quietly
    becomes extraction-stale.
    """
    steps: list[tuple[str, object]] = [("import", cmd_import)]
    busy = _teacher_busy() if _teacher_up() else None
    if busy:
        # An unattended compile must never queue teacher calls onto a slot a
        # deliberate long run is using (an overnight tagging run, a dossier
        # campaign). Prose extraction defers to the next compile; everything
        # CPU-side still runs, same trade as the teacher-down case.
        print(f"  NOTE: GPU busy ({busy}) — skipping extraction so the running")
        print("        job keeps its slot. Prose events accumulate; `status` counts them.")
    elif _teacher_up():
        steps.append(("extract", cmd_extract))
    else:
        print("  NOTE: teacher server down — skipping extraction. Prose events will")
        print("        accumulate; `status` counts them. Start the server and re-run.")
    # entities/link sit between embed and supersede: the entity signal is what
    # cut mislead-rate 0.273 → 0.091 (findings 2026-08-12), and it only covers
    # claims that have been linked — a compile that skipped them would leave
    # every new claim invisible to that ranking leg.
    steps += [("embed", cmd_embed), ("entities", cmd_entities), ("link", cmd_link),
              ("supersede", cmd_supersede), ("resolve", cmd_resolve)]

    for name, fn in steps:
        print(f"\n== {name}")
        rc = fn(args)
        if rc:
            print(f"  {name} failed (rc={rc}); stopping here — later steps read its output")
            return rc
    print("\n== status")
    return cmd_status(args)


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
    ap.add_argument("--no-backup", action="store_true",
                    help="skip the pre-command snapshot (not advised)")
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
    p = sub.add_parser("recall", help="query the claim graph")
    p.add_argument("query")
    p.add_argument("-k", type=int, default=8)
    p.add_argument("--include-superseded", action="store_true")
    p.add_argument("--corpus", default="guru")
    p.set_defaults(fn=cmd_recall)
    p = sub.add_parser("resolve", help="lean on every conflict; rank the rest by impact")
    p.add_argument("--corpus", default="guru")
    p.set_defaults(fn=cmd_resolve)
    p = sub.add_parser("entities", help="resolve path-shaped entities against the filesystem")
    p.add_argument("--corpus", default="guru")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_entities)
    p = sub.add_parser("link", help="link claims to the entities they mention")
    p.add_argument("--corpus", default="guru")
    p.set_defaults(fn=cmd_link)
    p = sub.add_parser("init", help="pin this directory tree to a project (.claimbase marker)")
    p.add_argument("--name", default=None, help="project name (default: what it resolves to now)")
    p.add_argument("--path", default=None, help="directory (default: current)")
    p.add_argument("--force", action="store_true", help="replace an existing marker")
    p.set_defaults(fn=cmd_init)
    p = sub.add_parser("status", help="compiled state vs sources; what to run next")
    p.add_argument("--corpus", default="guru")
    p.set_defaults(fn=cmd_status)
    p = sub.add_parser("extract", help="run the teacher over pending prose events")
    p.add_argument("--corpus", default="guru")
    p.add_argument("--limit", type=int, default=0, help="0 = all pending")
    p.set_defaults(fn=cmd_extract)
    p = sub.add_parser("compile", help="import → extract → embed → supersede → resolve")
    p.add_argument("--corpus", default="guru")
    p.set_defaults(fn=cmd_compile, dry_run=False, limit=0)
    p = sub.add_parser("stats", help="what is in the store")
    p.add_argument("--corpus", default="guru")
    p.set_defaults(fn=cmd_stats)
    p = sub.add_parser("review", help="serve the review queue (grading, conflicts, tensions)")
    p.add_argument("--host", default="0.0.0.0", help="0.0.0.0 so it is reachable over Tailscale")
    p.add_argument("--port", type=int, default=8760)
    p.add_argument("--limit", type=int, default=60)
    p.set_defaults(fn=cmd_review)

    # The memory layer (GOALS.md): brief, inspect, submit-session, writer,
    # replay, pr, usage, report.
    from .memory_cli import register

    register(sub)
    args = ap.parse_args(argv)
    if args.cmd in DESTRUCTIVE and not getattr(args, "dry_run", False) and not args.no_backup:
        auto_backup(f"pre-{args.cmd}")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
