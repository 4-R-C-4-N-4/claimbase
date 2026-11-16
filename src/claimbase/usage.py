"""Usage: what was asked, what was returned, what was used — and what that says.

The query log (`logs/mcp-queries.jsonl`) has recorded every MCP call since
2026-08-21. It stays a file and stays the source of truth: the server reads the
database through a role that cannot write. `sync()` derives tables from it,
idempotently, so the measures are SQL.

Six always-on measures (RFC, Analytics):

    miss rate           recalls that returned nothing the session used
    dead weight         standing claims never retrieved
    yield per trigger   claims used / claims collected, per collection trigger
    leak rate           recalls that returned another project's claim unasked
    repeat corrections  corrections on something the store already held
    revert rate         merged PRs later undone

and one exception report, which is the only thing a person is asked to read.

**Read the measures with their denominators.** Attribution is the hard part:
"returned" is a fact, "used" is an inference (lexical overlap between a
returned claim and what the session did next, or explicit feedback). Every
number that depends on use says how many recalls could be judged at all, and
a recall with no submitted session behind it is reported as unknown rather
than counted as a miss.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import projects

# How long after a recall a use can still be credited to it.
USE_WINDOW = timedelta(hours=12)

_READS = ("recall", "brief", "timeline")


def _line_id(line: str) -> uuid.UUID:
    return uuid.UUID(hashlib.md5(line.encode("utf-8", "replace")).hexdigest())


def _results(resp) -> list[dict]:
    if not isinstance(resp, dict):
        return []
    rows = resp.get("results") or resp.get("claims") or resp.get("timeline") or []
    return [r for r in rows if isinstance(r, dict)]


def sync(conn, log_path: str | Path) -> dict:
    """Load new query-log lines into retrieval_log / retrieval_hits / feedback.

    Lines written before claim ids were logged are matched to claims by exact
    text within their project; what cannot be matched is still counted as a
    call, it just has no hits. Does not commit.
    """
    log_path = Path(log_path)
    n = {"lines": 0, "new": 0, "hits": 0, "unmatched": 0, "feedback": 0, "bad": 0}
    if not log_path.exists():
        return n
    with conn.cursor() as cur, log_path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line.strip():
                continue
            n["lines"] += 1
            try:
                rec = json.loads(line)
                ts = datetime.fromisoformat(rec["ts"])
                tool = rec["tool"]
            except (json.JSONDecodeError, KeyError, ValueError):
                n["bad"] += 1
                continue
            lid = _line_id(line)
            args = rec.get("args") or {}
            resp = rec.get("response")
            # The server was hard-wired to one project before `project` existed.
            corpus = rec.get("project") or args.get("project") or "guru"

            if tool == "feedback":
                # The response carries the id as resolved; the argument may
                # have been a prefix typed off a screen.
                claim = (resp.get("claim_id") if isinstance(resp, dict) else None) \
                    or args.get("claim_id")
                try:
                    claim = str(uuid.UUID(str(claim))) if claim else None
                except ValueError:
                    claim = None
                if isinstance(resp, dict) and resp.get("error"):
                    continue  # a rejected call recorded nothing
                cur.execute(
                    """INSERT INTO feedback (id, ts, claim_id, kind, session, client, corpus, note)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (lid, ts, claim, args.get("kind"), rec.get("session"),
                     rec.get("client"), corpus, args.get("note")),
                )
                if cur.rowcount:
                    n["feedback"] += 1
                    # Explicit beats inferred: "helpful" is a use, on the record.
                    if args.get("kind") == "helpful" and claim:
                        cur.execute(
                            """INSERT INTO exposures (claim_id, kind, session_id, at, via, dedupe)
                               SELECT id, 'used', %s, %s, 'feedback', %s FROM claims WHERE id = %s
                               ON CONFLICT DO NOTHING""",
                            (rec.get("session"), ts, f"feedback:{lid}", claim),
                        )
                continue

            rows = _results(resp) if tool in _READS else []
            cur.execute(
                """INSERT INTO retrieval_log (id, ts, client, session, corpus, tool, query,
                                              n_results, ms, error)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (lid, ts, rec.get("client"), rec.get("session"), corpus, tool,
                 args.get("query") or args.get("subject"), len(rows), rec.get("ms"),
                 rec.get("error")),
            )
            if not cur.rowcount:
                continue
            n["new"] += 1
            for rank, r in enumerate(rows):
                cid, ccorpus = r.get("id"), r.get("project")
                if not cid and r.get("claim"):
                    cur.execute(
                        "SELECT id, corpus FROM claims WHERE corpus = %s AND content = %s LIMIT 1",
                        (corpus, r["claim"]),
                    )
                    hit = cur.fetchone()
                    if hit:
                        cid, ccorpus = hit
                if not cid:
                    n["unmatched"] += 1
                    continue
                if not ccorpus:
                    cur.execute("SELECT corpus FROM claims WHERE id = %s", (cid,))
                    got = cur.fetchone()
                    ccorpus = got[0] if got else None
                cur.execute(
                    """INSERT INTO retrieval_hits (log_id, claim_id, rank, claim_corpus)
                       VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (lid, cid, rank, ccorpus),
                )
                n["hits"] += cur.rowcount
    return n


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def measures(conn, project: str, since: datetime | None = None) -> dict:
    since = since or datetime(2000, 1, 1, tzinfo=timezone.utc)
    scopes = projects.scopes(project)
    out: dict = {"project": project}
    with conn.cursor() as cur:
        # --- miss rate ---------------------------------------------------------
        cur.execute(
            """
            WITH r AS (
              SELECT l.id, l.ts, l.n_results, l.session,
                EXISTS (
                  SELECT 1 FROM retrieval_hits h JOIN exposures x ON x.claim_id = h.claim_id
                   WHERE h.log_id = l.id AND x.kind = 'used'
                     AND x.at >= l.ts - interval '1 minute' AND x.at <= l.ts + %(win)s
                ) AS used,
                EXISTS (
                  SELECT 1 FROM sessions s
                   WHERE s.started_at <= l.ts
                     AND coalesce(s.ended_at, s.started_at) + interval '5 minutes' >= l.ts
                     AND (s.corpus = l.corpus OR s.corpus IS NULL)
                ) AS covered,
                EXISTS (
                  SELECT 1 FROM feedback f
                   WHERE f.session = l.session AND f.ts >= l.ts
                     AND f.kind IN ('not_helpful', 'missed')
                ) AS flagged
              FROM retrieval_log l
              WHERE l.tool = 'recall' AND l.error IS NULL
                AND l.corpus = %(p)s AND l.ts >= %(since)s
            )
            SELECT count(*),
                   count(*) FILTER (WHERE used),
                   count(*) FILTER (WHERE n_results = 0),
                   count(*) FILTER (WHERE NOT used AND (n_results = 0 OR covered OR flagged))
            FROM r
            """,
            {"p": project, "since": since, "win": USE_WINDOW},
        )
        total, used, empty, missed = cur.fetchone()
        judged = used + missed
        out["miss_rate"] = {
            "value": _ratio(missed, judged), "recalls": total, "used": used,
            "missed": missed, "empty": empty, "unknown": total - judged,
            "reads": "missed / (used + missed); unknown = no session or feedback to judge by",
        }

        # --- dead weight -------------------------------------------------------
        cur.execute(
            """SELECT count(*),
                      count(*) FILTER (WHERE NOT EXISTS (
                          SELECT 1 FROM retrieval_hits h WHERE h.claim_id = c.id))
                 FROM claims c
                WHERE c.corpus = %s AND c.status IN ('active', 'contested')""",
            (project,),
        )
        standing, never = cur.fetchone()
        out["dead_weight"] = {
            "value": _ratio(never, standing), "standing": standing,
            "never_retrieved": never,
            "reads": "share of standing claims no recall or brief has ever returned",
        }

        # --- yield per trigger -------------------------------------------------
        cur.execute(
            """SELECT t.type, count(*),
                      count(*) FILTER (WHERE t.scored_at IS NOT NULL),
                      count(t.claim_id),
                      count(*) FILTER (WHERE EXISTS (
                          SELECT 1 FROM exposures x
                           WHERE x.claim_id = t.claim_id AND x.kind = 'used'))
                 FROM triggers t
                WHERE t.corpus = ANY(%s)
                GROUP BY t.type ORDER BY 2 DESC""",
            (scopes,),
        )
        out["yield_per_trigger"] = {
            typ: {"triggers": n, "scored": scored, "claims": claims, "used": u,
                  "yield": _ratio(u, claims)}
            for typ, n, scored, claims, u in cur.fetchall()
        }

        # --- leak rate ---------------------------------------------------------
        cur.execute(
            """SELECT count(DISTINCT l.id),
                      count(DISTINCT l.id) FILTER (
                        WHERE h.claim_corpus IS NOT NULL AND h.claim_corpus <> ALL(%s))
                 FROM retrieval_log l JOIN retrieval_hits h ON h.log_id = l.id
                WHERE l.corpus = %s AND l.tool IN ('recall', 'brief') AND l.ts >= %s""",
            (scopes, project, since),
        )
        calls, leaked = cur.fetchone()
        out["leak_rate"] = {
            "value": _ratio(leaked, calls), "calls": calls, "leaked": leaked,
            "reads": "calls that returned a claim from outside the project and user scope",
        }

        # --- repeat corrections ------------------------------------------------
        cur.execute(
            """SELECT count(*) FILTER (WHERE scored_at IS NOT NULL),
                      count(*) FILTER (WHERE relation = 'predicted'),
                      count(*) FILTER (WHERE scored_at IS NULL)
                 FROM triggers WHERE corpus = ANY(%s) AND type = 'correction'""",
            (scopes,),
        )
        scored, repeat, pending = cur.fetchone()
        out["repeat_corrections"] = {
            "value": _ratio(repeat, scored), "corrections": scored, "repeat": repeat,
            "unscored": pending,
            "reads": "corrections on something the store already held; should fall to zero",
        }

        # --- revert rate -------------------------------------------------------
        cur.execute(
            """SELECT p.author, count(*),
                      count(*) FILTER (WHERE EXISTS (
                          SELECT 1 FROM memory_prs r WHERE r.reverts = p.id))
                 FROM memory_prs p
                WHERE p.corpus = ANY(%s) AND p.kind <> 'revert' AND p.outcome = 'merged'
                GROUP BY p.author""",
            (scopes,),
        )
        by = {a: {"merged": m, "reverted": r, "rate": _ratio(r, m)}
              for a, m, r in cur.fetchall()}
        merged = sum(v["merged"] for v in by.values())
        reverted = sum(v["reverted"] for v in by.values())
        out["revert_rate"] = {
            "value": _ratio(reverted, merged), "merged": merged, "reverted": reverted,
            "by_author": by,
            "reads": "a floor: a wrong merge nobody noticed is not counted",
        }

        # --- is anyone asking? -------------------------------------------------
        cur.execute(
            """SELECT count(*), max(ts), count(DISTINCT ts::date)
                 FROM retrieval_log WHERE corpus = %s AND ts >= now() - interval '7 days'""",
            (project,),
        )
        calls7, last, days7 = cur.fetchone()
        cur.execute("SELECT max(ts) FROM retrieval_log WHERE corpus = %s", (project,))
        last_ever = cur.fetchone()[0]
        cur.execute(
            """SELECT count(*) FILTER (WHERE processed_at IS NULL), count(*)
                 FROM sessions WHERE corpus = ANY(%s)""",
            (scopes,),
        )
        s_pending, s_total = cur.fetchone()
        out["activity"] = {
            "calls_7d": calls7, "days_with_calls_7d": days7,
            "last_call": last_ever.isoformat() if last_ever else None,
            "sessions": s_total, "sessions_unprocessed": s_pending,
            # The phase-1 gate, as a number: one harness, daily, for a week.
            "daily_use_gate": days7 >= 7,
        }
    return out


def exception_report(conn, project: str, days: int = 14) -> dict:
    """What a person should look at. If every list is empty there is nothing
    to review — that is the design, not a gap in the report."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    scopes = projects.scopes(project)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT r.id, r.merged_at, r.author, t.content, r.amendment
                 FROM memory_prs r LEFT JOIN claims t ON t.id = r.target_claim
                WHERE r.corpus = ANY(%s) AND r.kind = 'revert' AND r.merged_at >= %s
                ORDER BY r.merged_at DESC LIMIT 25""",
            (scopes, since),
        )
        reverts = [{"pr": str(a)[:8], "at": b.isoformat(), "by": c, "undid": d,
                    "restored": e} for a, b, c, d, e in cur.fetchall()]

        cur.execute(
            """SELECT c.id, c.content, c.trust, c.meta->>'contested_reason',
                      (SELECT p.amendment FROM memory_prs p
                        WHERE p.id::text = c.meta->>'contested_by')
                 FROM claims c
                WHERE c.corpus = ANY(%s) AND c.status = 'contested'
                ORDER BY c.asserted_at DESC NULLS LAST LIMIT 25""",
            (scopes,),
        )
        contested = [{"id": str(a)[:8], "claim": b, "trust": c, "reason": d,
                      "challenger": e} for a, b, c, d, e in cur.fetchall()]

        cur.execute(
            """SELECT lower(l.query), count(*), max(l.ts)
                 FROM retrieval_log l
                WHERE l.corpus = %s AND l.tool = 'recall' AND l.ts >= %s
                  AND l.query IS NOT NULL
                  AND (l.n_results = 0 OR EXISTS (
                        SELECT 1 FROM feedback f
                         WHERE f.session = l.session AND f.kind = 'missed'
                           AND f.ts BETWEEN l.ts AND l.ts + interval '30 minutes'))
                GROUP BY 1 HAVING count(*) >= 2 ORDER BY 2 DESC LIMIT 25""",
            (project, since),
        )
        misses = [{"query": q, "times": n, "last": t.isoformat()}
                  for q, n, t in cur.fetchall()]

        # A claim the session acted on, then a tool failed a few turns later.
        # Not proof the claim was wrong — a place to look.
        cur.execute(
            """SELECT DISTINCT ON (x.claim_id, t.event_id)
                      c.id, c.content, x.session_id, e.content
                 FROM exposures x
                 JOIN triggers t ON t.session_id = x.session_id AND t.type = 'tool_failure'
                                AND t.turn > x.turn AND t.turn - x.turn <= 12
                 JOIN claims c ON c.id = x.claim_id
                 JOIN events e ON e.id = t.event_id
                WHERE x.kind = 'used' AND x.turn IS NOT NULL
                  AND c.corpus = ANY(%s) AND x.at >= %s
                LIMIT 25""",
            (scopes, since),
        )
        before_failure = [
            {"id": str(a)[:8], "claim": b, "session": c, "failure": (d or "")[:240]}
            for a, b, c, d in cur.fetchall()
        ]
    report = {
        "project": project, "window_days": days,
        "reverts": reverts, "contested": contested,
        "repeated_misses": misses, "acted_on_before_failure": before_failure,
    }
    report["empty"] = not (reverts or contested or misses or before_failure)
    return report
