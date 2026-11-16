"""CLI for the memory layer (GOALS.md). Registered into `claimbase` by cli.main.

    claimbase brief [--project P | --cwd DIR]
    claimbase inspect <claim-id>
    claimbase submit-session --harness claude --file <session.jsonl>
    claimbase submit-session --hook            # Claude Code SessionEnd hook, JSON on stdin
    claimbase writer run [--no-judge]
    claimbase replay --dsn <scratch dsn> <transcripts…>
    claimbase pr open <claim-id> "<amendment>" [--evidence "…"]
    claimbase pr revert <pr-id> [--reason "…"]
    claimbase pr list
    claimbase usage sync | report
    claimbase report                           # the exception report

Every correction a person makes here is recorded the way an agent's would be:
as a PR with evidence, at human trust. There is no back door that edits a
claim in place.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import projects
from .core.store import connect

ROOT = Path(__file__).resolve().parent.parent.parent


def _project(args) -> str:
    return projects.resolve(getattr(args, "project", None),
                            getattr(args, "cwd", None) or os.getcwd())


def _dump(obj) -> None:
    print(json.dumps(obj, indent=2, default=str, ensure_ascii=False))


# --- reads -------------------------------------------------------------------


def cmd_brief(args) -> int:
    from .brief import brief

    with connect() as conn:
        b = brief(conn, _project(args), args.budget)
    if args.json:
        _dump(b)
        return 0
    print(f"  {b['project']}  ·  {len(b['claims'])} claims  ·  "
          f"{b['used_tokens']}/{b['budget_tokens']} tokens  ·  {b['omitted']} omitted\n")
    for c in b["claims"]:
        tag = " · ".join(str(x) for x in (
            c["kind"], c.get("origin") or c["trust"], c.get("since"),
            c.get("status"), f"x{c['exposures']}" if c.get("exposures") else None) if x)
        scope = "" if c["project"] == b["project"] else f"[{c['project']}] "
        print(f"  {c['id'][:8]}  {scope}{c['claim']}\n            {tag}")
    if not b["claims"]:
        print("  (nothing standing for this project yet)")
    return 0


def cmd_inspect(args) -> int:
    from .brief import inspect

    try:
        with connect() as conn:
            d = inspect(conn, args.claim_id)
    except ValueError as e:
        print(f"  {e}", file=sys.stderr)
        return 1
    if args.json:
        _dump(d)
        return 0
    print(f"\n  {d['claim']}\n")
    print(f"  {d['id']}")
    print(f"  {d['status']} · {d['kind']} · trust {d['trust']} · origin {d['origin'] or '—'}"
          f" · project {d['project']}")
    print(f"  asserted {d['asserted_at'] or '—'}   valid {d['valid_from'] or '—'}"
          f" → {d['valid_to'] or 'now'}")
    ev = d["evidence"]
    print(f"\n  evidence  {ev['source']}: {ev['ref']}")
    for line in ev["excerpt"].splitlines()[:12]:
        print(f"    | {line[:140]}")
    if d["supersedes"]:
        print(f"\n  replaced {len(d['supersedes'])}:")
        for s in d["supersedes"]:
            print(f"    {s['id'][:8]}  {s['claim'][:110]}  ({s['rule'] or '—'})")
    if d["superseded_by"]:
        print("\n  replaced by:")
        for s in d["superseded_by"]:
            print(f"    {s['id'][:8]}  [{s['status']}] {s['claim'][:110]}")
    for pr in d.get("prs", []):
        print(f"\n  PR {pr['id'][:8]}  {pr['kind']} by {pr['author']} → {pr['outcome']}"
              f"  ({pr['role']})")
    if "usage" in d:
        u = d["usage"]
        exp = "  ".join(f"{k} {v['n']}" for k, v in u["exposures"].items()) or "none"
        print(f"\n  returned {u['returned']['n']}×   exposures: {exp}"
              f"   feedback: {u['feedback'] or 'none'}")
    else:
        print(f"\n  {d.get('memory')}")
    return 0


# --- ingest ------------------------------------------------------------------


def cmd_submit_session(args) -> int:
    from . import sessions

    cwd, outcome, sid = args.cwd, args.outcome, args.session_id
    path = args.file
    if args.hook:
        # Claude Code hands a hook its context as JSON on stdin: the transcript
        # path, the session id, the working directory, and why it ended.
        try:
            ctx = json.load(sys.stdin)
        except json.JSONDecodeError as e:
            print(f"  --hook expects JSON on stdin: {e}", file=sys.stderr)
            return 1
        path = path or ctx.get("transcript_path")
        cwd = cwd or ctx.get("cwd")
        sid = sid or ctx.get("session_id")
        outcome = outcome or ctx.get("reason")

    if args.harness == "hermes":
        if not sid:
            print("  hermes sessions are rows, not files: pass --session-id", file=sys.stderr)
            return 1
        s = sessions.read_hermes(sid, args.db)
    else:
        if not path:
            print("  pass --file (or --hook)", file=sys.stderr)
            return 1
        s = sessions.READERS[args.harness](Path(path).expanduser())
        if sid:
            s.session_id = sid
    s.cwd = cwd or s.cwd
    s.project = args.project
    s.outcome = outcome or s.outcome
    out = sessions.submit(s)
    red = s.meta.get("redactions")
    print(f"  queued {s.id}  [{s.project}]  {len(s.turns)} turns"
          + (f"  redacted {red}" if red else "") + f"\n  {out}")
    return 0


def _judge(args):
    """A judge, or None with the reason printed. Scoring shares one llama.cpp
    slot with the pipeline's long runs and yields to them, exactly as
    extraction does: a busy GPU defers scoring, it does not compete."""
    if args.no_judge:
        return None
    from .cli import _teacher_busy, _teacher_up
    from .writer import LocalJudge

    judge = LocalJudge(args.provider, args.model)
    if judge.provider == "llamacpp":
        if not _teacher_up():
            print("  judge: no model server on the llama.cpp slot — ingest only, "
                  "triggers stay unscored")
            return None
        if busy := _teacher_busy():
            print(f"  judge: GPU slot is owned ({busy[:80]}) — ingest only")
            return None
    print(f"  judge: {judge.name}")
    return judge


def cmd_writer(args) -> int:
    from . import writer

    with connect() as conn:
        r = writer.run(conn, judge=_judge(args), limit=args.limit)
    print(f"\n  sessions {r['sessions']}  episodes {r['episodes']}  "
          f"triggers {r['triggers']}  uses {r['used']}")
    if "score" in r:
        print("  scored: " + ("  ".join(f"{k} {v}" for k, v in r["score"].items() if v)
                              or "nothing waiting"))
    elif r.get("triggers_waiting"):
        print(f"  {r['triggers_waiting']} triggers waiting for a judge")
    return 0


def cmd_replay(args) -> int:
    from . import sessions, writer

    name = args.dsn.rsplit("/", 1)[-1].split("?")[0]
    if not any(w in name for w in ("test", "replay", "scratch")) and not args.force:
        print(f"  refusing to replay into {name!r}: replay writes claims and PRs.\n"
              "  Point --dsn at a scratch database (scripts/test_db.sh up), or pass --force.",
              file=sys.stderr)
        return 1
    transcripts = []
    for f in args.files:
        p = Path(f).expanduser()
        s = sessions.read_claude(p) if p.suffix == ".jsonl" else sessions.read_generic(p)
        if args.project:
            s.project = args.project
        transcripts.append(s)
    gold = None
    if args.gold:
        gold = [json.loads(l)["claim"] for l in Path(args.gold).read_text().splitlines()
                if l.strip()]
    with connect(args.dsn) as conn:
        r = writer.replay(conn, transcripts, judge=_judge(args), gold=gold)
    print()
    print(f"  {'rule':<34} {'trig':>5} {'scored':>6} {'novel':>5} {'pred':>5} "
          f"{'contra':>6} {'none':>5} {'durable':>8}")
    for rule, v in r["by_rule"].items():
        d = "—" if v["durable"] is None else f"{v['durable']:.2f}"
        print(f"  {rule:<34} {v['triggers']:>5} {v['scored']:>6} {v['novel']:>5} "
              f"{v['predicted']:>5} {v['contradicting']:>6} {v['nothing']:>5} {d:>8}")
    c = r["claims"]
    print(f"\n  claims {c['total']} (standing {c['standing']}, tentative {c['tentative']})"
          f"   PRs {r['prs']['total']} (contested {r['prs']['contested']})")
    if "gold" in r:
        g = r["gold"]
        print(f"  gold: found {g['found']}/{g['expected']}  recall {g['recall']}  "
              f"precision {g['precision']}")
    return 0


# --- PRs ---------------------------------------------------------------------


def cmd_pr(args) -> int:
    from . import prs
    from .brief import resolve_id
    from .cli import _embed_one

    def embed(text):
        return _embed_one(text)

    with connect() as conn:
        try:
            if args.action == "list":
                rows = prs.list_prs(conn, args.project, args.limit)
                for r in rows:
                    flag = " (reverted)" if r["reverted"] else ""
                    print(f"  {r['id'][:8]}  {r['at'][:16]}  [{r['project']}] {r['kind']} by "
                          f"{r['author']} → {r['outcome']}{flag}")
                    print(f"      was: {(r['was'] or '—')[:120]}")
                    print(f"      now: {r['now'][:120]}")
                if not rows:
                    print("  (no PRs)")
                return 0
            if args.action == "open":
                pr = prs.open_pr(
                    conn, target=resolve_id(conn, args.target), amendment=args.amendment,
                    kind=args.kind, author="user", evidence_text=args.evidence,
                    embed=embed, meta={"via": "cli"})
            else:
                pr = prs.revert(conn, args.target, author="user", reason=args.reason,
                                embed=embed)
            conn.commit()
        except (prs.PRError, ValueError) as e:
            conn.rollback()
            print(f"  {e}", file=sys.stderr)
            return 1
    print(f"  {pr.summary()}")
    print(f"  standing claim: {pr.amendment_claim if pr.outcome == 'merged' else pr.target}")
    return 0


# --- usage -------------------------------------------------------------------


def _pct(v) -> str:
    return "—" if v is None else f"{v * 100:.0f}%"


def print_measures(m: dict) -> None:
    a = m["activity"]
    print(f"\n  {m['project']} — usage")
    print(f"  calls in the last 7 days: {a['calls_7d']} on {a['days_with_calls_7d']} days"
          f"   last call: {(a['last_call'] or 'never')[:16]}"
          f"   daily-use gate: {'met' if a['daily_use_gate'] else 'NOT met'}")
    print(f"  sessions submitted: {a['sessions']} ({a['sessions_unprocessed']} awaiting a judge)\n")
    r = m["miss_rate"]
    print(f"  miss rate           {_pct(r['value']):>5}   {r['missed']} missed / {r['used']} used"
          f" / {r['unknown']} unknown, of {r['recalls']} recalls ({r['empty']} empty)")
    r = m["dead_weight"]
    print(f"  dead weight         {_pct(r['value']):>5}   {r['never_retrieved']:,} of "
          f"{r['standing']:,} standing claims never returned")
    r = m["leak_rate"]
    print(f"  leak rate           {_pct(r['value']):>5}   {r['leaked']} of {r['calls']} calls"
          " returned another project's claim")
    r = m["repeat_corrections"]
    print(f"  repeat corrections  {_pct(r['value']):>5}   {r['repeat']} of {r['corrections']}"
          f" scored corrections ({r['unscored']} unscored)")
    r = m["revert_rate"]
    print(f"  revert rate         {_pct(r['value']):>5}   {r['reverted']} of {r['merged']}"
          " merged PRs later undone (a floor)")
    if m["yield_per_trigger"]:
        print("\n  yield per trigger      triggers  scored  claims   used  yield")
        for t, v in m["yield_per_trigger"].items():
            print(f"    {t:<20} {v['triggers']:>8} {v['scored']:>7} {v['claims']:>7} "
                  f"{v['used']:>6}  {_pct(v['yield']):>5}")
    else:
        print("\n  yield per trigger: no triggers yet (no sessions submitted)")


def print_exceptions(r: dict) -> None:
    print(f"\n  {r['project']} — exceptions, last {r['window_days']} days")
    if r["empty"]:
        print("  nothing to review")
        return
    for c in r["contested"]:
        print(f"\n  CONTESTED {c['id']}  ({c['reason'] or '—'}; held at {c['trust']} trust)")
        print(f"    stands:     {c['claim'][:150]}")
        if c["challenger"]:
            print(f"    challenger: {c['challenger'][:150]}")
    for v in r["reverts"]:
        print(f"\n  REVERT {v['pr']}  {v['at'][:16]} by {v['by']}")
        print(f"    undid:    {(v['undid'] or '—')[:150]}")
        print(f"    restored: {v['restored'][:150]}")
    for q in r["repeated_misses"]:
        print(f"\n  MISSED ×{q['times']}  {q['query'][:150]}")
    for f in r["acted_on_before_failure"]:
        print(f"\n  ACTED ON, THEN A FAILURE  {f['id']}  ({f['session']})")
        print(f"    claim:   {f['claim'][:150]}")
        print(f"    failure: {f['failure'][:150]}")


def cmd_usage(args) -> int:
    from . import usage
    from .mcp_server import _LOG_DEFAULT

    with connect() as conn:
        if args.action == "sync":
            log = Path(args.log or os.environ.get("CLAIMBASE_QUERY_LOG") or _LOG_DEFAULT)
            n = usage.sync(conn, log)
            conn.commit()
            print(f"  {log}\n  lines {n['lines']}  new calls {n['new']}  hits {n['hits']}"
                  f"  feedback {n['feedback']}  unmatched results {n['unmatched']}"
                  + (f"  unparseable {n['bad']}" if n["bad"] else ""))
            return 0
        m = usage.measures(conn, _project(args))
        if args.json:
            _dump(m)
        else:
            print_measures(m)
    return 0


def cmd_report(args) -> int:
    from . import usage

    with connect() as conn:
        r = usage.exception_report(conn, _project(args), args.days)
    _dump(r) if args.json else print_exceptions(r)
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    def scoped(p):
        p.add_argument("--project", default=None,
                       help="default: resolved from the working directory")
        p.add_argument("--cwd", default=None, help=argparse.SUPPRESS)
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("brief", help="the session-start set of standing claims")
    scoped(p)
    p.add_argument("--budget", type=int, default=500, help="tokens")
    p.set_defaults(fn=cmd_brief)

    p = sub.add_parser("inspect", help="one claim: evidence, history, PRs, usage")
    p.add_argument("claim_id", help="full id or a unique prefix")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_inspect)

    p = sub.add_parser("submit-session", help="queue a finished session for the writer")
    p.add_argument("--harness", default="claude", choices=["claude", "hermes", "generic"])
    p.add_argument("--file", help="session file (claude .jsonl, or normalized .json)")
    p.add_argument("--session-id", help="hermes: the row id; others: override")
    p.add_argument("--db", default="~/.hermes/state.db", help="hermes state database")
    p.add_argument("--hook", action="store_true",
                   help="read a Claude Code hook payload (JSON) from stdin")
    p.add_argument("--project", default=None)
    p.add_argument("--cwd", default=None)
    p.add_argument("--outcome", default=None)
    p.set_defaults(fn=cmd_submit_session)

    def judged(p):
        p.add_argument("--no-judge", action="store_true",
                       help="ingest only; leave triggers unscored")
        p.add_argument("--provider", default=None, help="llamacpp (default) | ollama | …")
        p.add_argument("--model", default=None)

    p = sub.add_parser("writer", help="turn queued sessions into memory")
    p.add_argument("action", choices=["run"])
    p.add_argument("--limit", type=int, default=0, help="sessions; 0 = all queued")
    judged(p)
    p.set_defaults(fn=cmd_writer)

    p = sub.add_parser("replay", help="run transcripts through the writer on a scratch db")
    p.add_argument("files", nargs="+")
    p.add_argument("--dsn", required=True)
    p.add_argument("--project", default=None)
    p.add_argument("--gold", help="jsonl of {\"claim\": …} that should have been kept")
    p.add_argument("--force", action="store_true")
    judged(p)
    p.set_defaults(fn=cmd_replay)

    p = sub.add_parser("pr", help="memory PRs: the only way a standing claim changes")
    ps = p.add_subparsers(dest="action", required=True)
    o = ps.add_parser("open", help="amend a claim; merges at once")
    o.add_argument("target", help="claim id or unique prefix")
    o.add_argument("amendment")
    o.add_argument("--evidence", default=None, help="why — recorded as the PR's evidence")
    o.add_argument("--kind", default="correction",
                   choices=["correction", "source_mismatch", "narrowing"])
    r = ps.add_parser("revert", help="undo a PR by filing another")
    r.add_argument("target", help="PR id or unique prefix")
    r.add_argument("--reason", default=None)
    ls = ps.add_parser("list")
    ls.add_argument("--project", default=None)
    ls.add_argument("--limit", type=int, default=20)
    p.set_defaults(fn=cmd_pr)

    p = sub.add_parser("usage", help="the query log as tables, and the six measures")
    p.add_argument("action", choices=["sync", "report"])
    p.add_argument("--log", default=None, help="query log path (default: the server's)")
    scoped(p)
    p.set_defaults(fn=cmd_usage)

    p = sub.add_parser("report", help="the exception report — the only thing to read")
    scoped(p)
    p.add_argument("--days", type=int, default=14)
    p.set_defaults(fn=cmd_report)
