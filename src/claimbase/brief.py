"""brief() and inspect() — the two reads `recall` does not cover.

`brief` is what a harness asks for once, at session start: a small fixed-budget
set of standing claims for the project it is in. It exists because the store
going unused was never a retrieval problem — an agent that is not prompted to
ask does not ask. A brief costs the harness one call and no judgment.

`inspect` is the other end: one claim, everything known about it. Where it came
from, what it replaced, what replaced it, which PRs touched it, how often it
has been returned and what it has survived. "Every claim can be traced to the
episodes it came from" is a property of the schema; this is the tool that makes
it a property a person can use.

Neither calls a model, and both run on the read-only role.
"""

from __future__ import annotations

from . import projects
from .recall import _near_dup

DEFAULT_BUDGET = 500  # tokens. The RFC's starting guess; tune from miss rate.

# What belongs in front of an agent before it has asked anything. Recently
# exposed claims earn their place by use. With no usage yet, the only claims
# worth unprompted context are the ones a person stood behind and that describe
# how things are done: an extracted observation about one occasion is an answer
# to a question, not a standing instruction.
_STANDING_KINDS = ("practice", "decision", "preference", "plan")
_VOUCHED = ("human", "agent_authored_human_gated")


def _tokens(text: str) -> int:
    return len(text) // 4 + 8  # + the metadata printed beside it


def has_memory_tables(conn) -> bool:
    """False on a store that has not had migration 008. The reads degrade to
    what the older schema can answer instead of failing the call."""
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.exposures') IS NOT NULL")
        return bool(cur.fetchone()[0])


def brief(conn, project: str, budget_tokens: int = DEFAULT_BUDGET) -> dict:
    """Standing claims for `project` and the user scope, within a token budget.

    Order: most recently exposed first, then human-stated, then claims that won
    an argument (superseded others), then newest. That is an ordering for
    limited space, not a judgment of truth — a claim left out is unlisted, not
    doubted.
    """
    scopes = projects.scopes(project)
    mem = has_memory_tables(conn)
    exposure_join = (
        """LEFT JOIN (SELECT claim_id, max(at) AS last_exposed, count(*) AS n
                        FROM exposures GROUP BY claim_id) x ON x.claim_id = c.id"""
        if mem else
        "LEFT JOIN (SELECT NULL::uuid AS claim_id, NULL::timestamptz AS last_exposed, "
        "0 AS n WHERE false) x ON x.claim_id = c.id"
    )
    origin_col = "c.origin" if mem else "NULL::text"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT c.id, c.corpus, c.content, c.claim_kind, c.trust, c.status, {origin_col},
                   coalesce(c.valid_from, c.asserted_at), x.last_exposed, coalesce(x.n, 0)
            FROM claims c {exposure_join}
            WHERE c.corpus = ANY(%s)
              AND c.status IN ('active', 'contested')
              AND coalesce(c.meta->>'field', '') <> 'heading'
              AND (x.claim_id IS NOT NULL
                   OR (c.trust = ANY(%s) AND c.claim_kind = ANY(%s)))
            ORDER BY x.last_exposed DESC NULLS LAST,
                     (c.trust = 'human') DESC,
                     (SELECT count(*) FROM claims s WHERE s.superseded_by = c.id) DESC,
                     c.asserted_at DESC NULLS LAST
            LIMIT 300
            """,
            (scopes, list(_VOUCHED), list(_STANDING_KINDS)),
        )
        rows = cur.fetchall()

    out, used, omitted = [], 0, 0
    for cid, corpus, content, kind, trust, status, origin, since, last, n in rows:
        cost = _tokens(content)
        if used + cost > budget_tokens or any(_near_dup(content, o["claim"]) for o in out):
            omitted += 1
            continue
        used += cost
        row = {
            "id": str(cid), "claim": content, "kind": kind,
            "origin": origin or ("stated" if trust == "human" else None),
            "trust": trust, "since": since.date().isoformat() if since else None,
            "project": corpus,
        }
        if status != "active":
            row["status"] = status
        if n:
            row["exposures"] = n
        out.append(row)
    return {
        "project": project, "scopes": scopes,
        "budget_tokens": budget_tokens, "used_tokens": used,
        "claims": out, "omitted": omitted,
    }


def resolve_id(conn, claim_id: str, project: str | None = None) -> str:
    """A full id, from a full id or an unambiguous prefix (>= 6 hex chars) —
    ids are read off a terminal and typed back by people."""
    claim_id = claim_id.strip().lower()
    if len(claim_id) == 36:
        return claim_id
    if len(claim_id) < 6:
        raise ValueError("claim id prefix too short (need 6+ characters)")
    with conn.cursor() as cur:
        cur.execute(
            """SELECT id FROM claims
                WHERE id::text LIKE %s AND (%s::text IS NULL OR corpus = %s) LIMIT 3""",
            (claim_id + "%", project, project),
        )
        rows = cur.fetchall()
    if not rows:
        raise ValueError(f"no claim {claim_id}")
    if len(rows) > 1:
        raise ValueError(f"claim id prefix {claim_id!r} is ambiguous")
    return str(rows[0][0])


def _excerpt(event_text: str, claim_text: str, width: int = 700) -> str:
    """The part of the source the claim came from, when it can be found there;
    otherwise the head. A claim is an index into prose, not a replacement."""
    if len(event_text) <= width:
        return event_text
    probe = claim_text[:40]
    at = event_text.find(probe)
    if at < 0:
        return event_text[:width] + " …"
    lo = max(0, at - width // 3)
    return ("… " if lo else "") + event_text[lo:lo + width] + " …"


def inspect(conn, claim_id: str) -> dict:
    claim_id = resolve_id(conn, claim_id)
    mem = has_memory_tables(conn)
    extra = "c.origin, c.level, c.merged_by" if mem else "NULL, 'specific', NULL"
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT c.content, c.claim_kind, c.trust, c.status, c.corpus, c.asserted_at,
                       c.valid_from, c.valid_to, c.superseded_by, c.corroborated, c.meta,
                       e.source, e.source_ref, e.captured_at, e.content, {extra}
                  FROM claims c JOIN events e ON e.id = c.event_id WHERE c.id = %s""",
            (claim_id,),
        )
        r = cur.fetchone()
        if r is None:
            raise ValueError(f"no claim {claim_id}")
        (content, kind, trust, status, corpus, asserted, vfrom, vto, sup_by, corr, meta,
         source, ref, captured, etext, origin, level, merged_by) = r
        iso = lambda t: t.isoformat() if t else None  # noqa: E731
        out = {
            "id": claim_id, "claim": content, "kind": kind, "trust": trust,
            "origin": origin, "level": level, "status": status, "project": corpus,
            "corroborated": corr, "asserted_at": iso(asserted),
            "valid_from": iso(vfrom), "valid_to": iso(vto),
            "evidence": {"source": source, "ref": ref, "captured_at": iso(captured),
                         "excerpt": _excerpt(etext or "", content)},
        }
        if (meta or {}).get("capped_from"):
            out["capped_from"] = meta["capped_from"]

        # Version history, both directions.
        cur.execute(
            """SELECT id, content, asserted_at, meta->>'superseded_rule' FROM claims
                WHERE superseded_by = %s ORDER BY asserted_at DESC NULLS LAST LIMIT 12""",
            (claim_id,),
        )
        out["supersedes"] = [
            {"id": str(a), "claim": b, "asserted_at": iso(c), "rule": d}
            for a, b, c, d in cur.fetchall()
        ]
        chain, nxt, seen = [], sup_by, {claim_id}
        while nxt and str(nxt) not in seen and len(chain) < 12:
            seen.add(str(nxt))
            cur.execute(
                "SELECT id, content, status, asserted_at, superseded_by FROM claims WHERE id = %s",
                (nxt,),
            )
            row = cur.fetchone()
            if row is None:
                break
            chain.append({"id": str(row[0]), "claim": row[1], "status": row[2],
                          "asserted_at": iso(row[3])})
            nxt = row[4]
        out["superseded_by"] = chain

        if not mem:
            out["memory"] = "migration 008 not applied: no PRs, exposures or usage"
            return out

        cur.execute(
            """SELECT id, kind, author, outcome, merged_at, evidence_trust, amendment,
                      target_claim = %s
                 FROM memory_prs WHERE target_claim = %s OR amendment_claim = %s
                ORDER BY merged_at""",
            (claim_id, claim_id, claim_id),
        )
        out["prs"] = [
            {"id": str(a), "kind": b, "author": c, "outcome": d, "at": iso(e),
             "evidence_trust": f, "amendment": g,
             "role": "amended by this PR" if h else "created by this PR"}
            for a, b, c, d, e, f, g, h in cur.fetchall()
        ]
        cur.execute(
            "SELECT kind, count(*), max(at) FROM exposures WHERE claim_id = %s GROUP BY kind",
            (claim_id,),
        )
        exp = {k: {"n": n, "last": iso(last)} for k, n, last in cur.fetchall()}
        cur.execute(
            """SELECT count(*), max(l.ts) FROM retrieval_hits h
                 JOIN retrieval_log l ON l.id = h.log_id WHERE h.claim_id = %s""",
            (claim_id,),
        )
        n_ret, last_ret = cur.fetchone()
        cur.execute("SELECT kind, count(*) FROM feedback WHERE claim_id = %s GROUP BY kind",
                    (claim_id,))
        out["usage"] = {
            "returned": {"n": n_ret, "last": iso(last_ret)},
            "exposures": exp,
            "feedback": dict(cur.fetchall()),
        }
    return out
