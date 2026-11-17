"""Usage: what was asked, what was returned, what was used — and what that says.

The query log (`logs/mcp-queries.jsonl`) has recorded every MCP call since
2026-08-21. It stays a file and stays the source of truth: the server reads the
database through a role that cannot write. `sync()` derives tables from it,
idempotently, so the measures are SQL.

Reports distinguish delivery, lexical inference, explicit feedback, and
independent checker outcomes. A checker result does not establish causal memory
use. Nonempty recalls without evidence are unknown; empty results and explicit
negative feedback can establish a miss. Temporal claim attribution remains an
inference until exact retrieval/session identity is available.

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
            try:
                receipt = str(uuid.UUID(str(rec.get("call_id")))) if rec.get("call_id") else None
            except ValueError:
                receipt = None
            from .sessions import canonical_identity
            canonical = canonical_identity(rec.get("canonical_session"))
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
                    """INSERT INTO feedback (id, ts, claim_id, kind, session, client, corpus, note, call_id, declared_session)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                    (lid, ts, claim, args.get("kind"), rec.get("session"),
                     rec.get("client"), corpus, args.get("note"), receipt, canonical),
                )
                if cur.rowcount:
                    n["feedback"] += 1
                continue

            rows = _results(resp) if tool in _READS else []
            cur.execute(
                """INSERT INTO retrieval_log (id, ts, client, session, corpus, tool, query,
                                              n_results, ms, error, call_id, declared_session)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (lid, ts, rec.get("client"), rec.get("session"), corpus, tool,
                 args.get("query") or args.get("subject"), len(rows), rec.get("ms"),
                 rec.get("error"), receipt, canonical),
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
    resolve_receipts(conn)
    return n


def resolve_receipts(conn):
    """Bind only unique, project- and tool-matched logged receipts."""
    with conn.cursor() as cur:
        for table, tool_predicate in (("retrieval_log", "l.tool = b.tool"), ("feedback", "b.tool = 'feedback'")):
            cur.execute(f"UPDATE {table} SET canonical_session = NULL")
            cur.execute(f"""UPDATE {table} l SET canonical_session = s.id
                FROM sessions s WHERE l.declared_session = s.id AND l.corpus = s.corpus
                AND s.id ~ '^[a-z][a-z0-9_-]*:[A-Za-z0-9][A-Za-z0-9_.:/-]*$'
                AND (l.call_id IS NULL OR NOT EXISTS
                    (SELECT 1 FROM session_receipts b WHERE b.call_id = l.call_id))
                AND (l.call_id IS NULL OR
                    (SELECT count(*) FROM retrieval_log r WHERE r.call_id = l.call_id) +
                    (SELECT count(*) FROM feedback f WHERE f.call_id = l.call_id) = 1)""")
            cur.execute(f"""UPDATE {table} l SET canonical_session = b.session_id
                FROM session_receipts b JOIN sessions s ON s.id = b.session_id AND s.corpus = b.corpus
                WHERE l.call_id = b.call_id AND l.corpus = b.corpus AND {tool_predicate}
                  AND NOT b.conflicted
                  AND (l.declared_session IS NULL OR l.declared_session = b.session_id)
                  AND (SELECT count(*) FROM retrieval_log r WHERE r.call_id = b.call_id) +
                      (SELECT count(*) FROM feedback f WHERE f.call_id = b.call_id) = 1""")
        replacement = """SELECT l.id FROM retrieval_log l
            JOIN retrieval_hits h ON h.log_id = l.id
            JOIN session_receipts r ON r.call_id = l.call_id
                AND r.session_id = x.session_id AND r.corpus = l.corpus
                AND r.tool = l.tool AND NOT r.conflicted
            WHERE h.claim_id = x.claim_id AND l.canonical_session = x.session_id
              AND l.tool IN ('brief', 'recall') AND l.error IS NULL
              AND r.delivery_turn < x.turn
            ORDER BY l.ts, l.id LIMIT 1"""
        cur.execute(f"""UPDATE exposures x SET source_log = ({replacement})
            WHERE x.via = 'writer' AND x.source_log IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM retrieval_log original
                  WHERE original.id = x.source_log AND original.canonical_session = x.session_id)
              AND EXISTS ({replacement})""")
        cur.execute("""DELETE FROM exposures x WHERE x.via = 'writer' AND x.source_log IS NOT NULL
            AND NOT EXISTS (SELECT 1 FROM retrieval_log l WHERE l.id = x.source_log
                AND l.canonical_session = x.session_id)""")
        cur.execute("""DELETE FROM exposures x WHERE x.via = 'feedback'
            AND NOT EXISTS (SELECT 1 FROM feedback f WHERE 'feedback:' || f.id::text = x.dedupe
                AND f.canonical_session = x.session_id)""")
        cur.execute("""INSERT INTO exposures (claim_id, kind, session_id, at, via, dedupe)
            SELECT c.id, 'used', f.canonical_session, f.ts, 'feedback', 'feedback:' || f.id::text
              FROM feedback f JOIN claims c ON c.id = f.claim_id
             WHERE f.kind = 'helpful' AND f.canonical_session IS NOT NULL AND c.corpus = f.corpus
            ON CONFLICT DO NOTHING""")


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def record_outcome(conn, project: str, session: str, run: str, checker: str,
                   passed: bool, evidence) -> dict:
    """Record an independent checker result without attributing claim use."""
    if any(not isinstance(x, str) or not x.strip() for x in (project, session, run, checker)):
        raise ValueError("project, session, run and checker must be nonempty strings")
    if type(passed) is not bool:
        raise ValueError("passed must be a boolean")
    def validate_text(value):
        if isinstance(value, str):
            if "\x00" in value:
                raise ValueError("evidence cannot contain null characters")
            value.encode("utf-8")  # PostgreSQL also rejects unpaired surrogates.
        elif isinstance(value, dict):
            for key, child in value.items():
                validate_text(key)
                validate_text(child)
        elif isinstance(value, (list, tuple)):
            for child in value:
                validate_text(child)

    try:
        encoded = json.dumps(evidence, allow_nan=False)
        validate_text(evidence)
    except (TypeError, ValueError) as exc:
        raise ValueError("evidence must be PostgreSQL-compatible JSON") from exc
    with conn.cursor() as cur:
        cur.execute("SELECT corpus FROM sessions WHERE id = %s", (session,))
        row = cur.fetchone()
        if row is None or row[0] != project:
            raise ValueError("session missing or project mismatch")
        cur.execute("""INSERT INTO usage_outcomes (session_id, corpus, run_id, checker, passed, evidence)
                       VALUES (%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT DO NOTHING
                       RETURNING session_id""", (session, project, run, checker, passed, encoded))
        inserted = cur.fetchone() is not None
        cur.execute("""SELECT passed, evidence FROM usage_outcomes
                       WHERE run_id=%s AND checker=%s AND session_id=%s""", (run, checker, session))
        stored_passed, stored_evidence = cur.fetchone()
        if not inserted and (stored_passed != passed or stored_evidence != json.loads(encoded)):
            raise ValueError("outcome key already exists with different result")
    return {"project": project, "session": session, "run": run, "checker": checker,
            "passed": passed, "evidence": stored_evidence}


def measures(conn, project: str, since: datetime | None = None) -> dict:
    since = since or datetime(2000, 1, 1, tzinfo=timezone.utc)
    scopes = projects.scopes(project)
    out: dict = {"project": project}
    with conn.cursor() as cur:
        # --- miss rate ---------------------------------------------------------
        cur.execute(
            """
            WITH r AS (
              SELECT l.id, l.ts, l.n_results, l.canonical_session,
                EXISTS (
                  SELECT 1 FROM retrieval_hits h JOIN exposures x ON x.claim_id = h.claim_id
                   WHERE h.log_id = l.id AND x.kind = 'used'
                     AND x.via = 'writer' AND x.session_id = l.canonical_session
                     AND x.at <= l.ts + %(win)s
                     AND (
                       EXISTS (SELECT 1 FROM session_receipts b
                         WHERE b.call_id = l.call_id AND b.session_id = x.session_id
                           AND b.corpus = l.corpus AND b.tool = l.tool
                           AND NOT b.conflicted AND b.delivery_turn < x.turn)
                       OR (x.source_log = l.id AND x.at > l.ts AND NOT EXISTS
                         (SELECT 1 FROM session_receipts b WHERE b.call_id = l.call_id))
                     )
                ) AS used,
                EXISTS (
                  SELECT 1 FROM feedback f
                   WHERE f.canonical_session = l.canonical_session AND f.corpus = l.corpus AND f.ts >= l.ts
                     AND f.kind IN ('not_helpful', 'missed')
                     AND (f.claim_id IS NULL OR EXISTS (
                       SELECT 1 FROM retrieval_hits fh
                        WHERE fh.log_id = l.id AND fh.claim_id = f.claim_id))
                ) AS flagged
              FROM retrieval_log l
              WHERE l.tool = 'recall' AND l.error IS NULL
                AND l.corpus = %(p)s AND l.ts >= %(since)s
            )
            SELECT count(*),
                   count(*) FILTER (WHERE used),
                   count(*) FILTER (WHERE n_results = 0),
                   count(*) FILTER (WHERE NOT used AND (n_results = 0 OR flagged))
            FROM r
            """,
            {"p": project, "since": since, "win": USE_WINDOW},
        )
        total, used, empty, missed = cur.fetchone()
        judged = used + missed
        out["miss_rate"] = {
            "value": _ratio(missed, judged), "recalls": total, "used": used,
            "missed": missed, "empty": empty, "unknown": total - judged,
            "inferred": used, "reads": "missed / (inferred + missed); other recalls are unknown",
        }

        cur.execute("""SELECT count(*), coalesce(sum(n_results), 0),
                              (SELECT count(*) FROM retrieval_hits h JOIN retrieval_log r ON r.id=h.log_id
                               WHERE r.corpus=%s AND r.ts >= %s AND r.tool IN ('recall','brief','timeline') AND r.error IS NULL)
                       FROM retrieval_log WHERE corpus=%s AND ts >= %s
                         AND tool IN ('recall','brief','timeline') AND error IS NULL""", (project, since, project, since))
        calls, results, hits = cur.fetchone()
        out["delivery"] = {"retrievals": calls, "results": results, "claim_hits": hits}
        cur.execute("SELECT kind, count(*) FROM feedback WHERE corpus=%s AND ts >= %s GROUP BY kind", (project, since))
        out["feedback"] = dict(cur.fetchall())
        cur.execute("""SELECT count(DISTINCT (x.claim_id, x.session_id)),
                              count(DISTINCT x.session_id)
                         FROM exposures x JOIN sessions s ON s.id = x.session_id
                        WHERE x.kind = 'used' AND x.via = 'writer'
                          AND s.corpus = %s AND x.at >= %s""", (project, since))
        inferred, inferred_sessions = cur.fetchone()
        out["inference"] = {"claim_uses": inferred, "sessions": inferred_sessions,
                            "reads": "weak transcript inference, not verified causal use"}
        cur.execute("""SELECT session_id, run_id, checker, passed, evidence FROM usage_outcomes
                       WHERE corpus=%s AND recorded_at >= %s ORDER BY recorded_at, session_id, run_id, checker""", (project, since))
        rows = cur.fetchall()
        out["outcomes"] = {"passed": sum(r[3] for r in rows), "failed": sum(not r[3] for r in rows),
                           "records": [{"session": a, "run": b, "checker": c, "passed": d, "evidence": e}
                                       for a, b, c, d, e in rows],
                           "reads": "independent checks; outcomes do not establish causal memory use"}

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
                           WHERE x.claim_id = t.claim_id AND x.kind = 'used' AND x.via = 'writer'))
                 FROM triggers t
                WHERE t.corpus = ANY(%s)
                GROUP BY t.type ORDER BY 2 DESC""",
            (scopes,),
        )
        out["yield_per_trigger"] = {
            typ: {"triggers": n, "scored": scored, "claims": claims, "used": u, "inferred": u,
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
                         WHERE f.canonical_session = l.canonical_session AND f.corpus = l.corpus AND f.kind = 'missed'
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
