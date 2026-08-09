"""MCP server — the agent-facing query layer (DESIGN §5).

Shipped before the human-facing views on purpose: it makes every Claude session a
consumer on day one, and dogfooding pressure lands where it should.

Every answer carries **epistemic metadata**. That is the whole point of the layer —
an agent asking "is auto-promote the current path?" should get *"no; practice, human,
2026-08-09, supersedes 18 claims"*, not two contradictory paragraphs and a shrug.

`assert` is deliberately the same funnel as any importer: agents write through the
capture path, with no privileged access. An agent's assertion enters at `agent` trust
and cannot become a `fact` or `decision` on its own say-so — the same cap every
adapter lives under.

    claimbase-mcp                # stdio, for a Claude Code MCP config entry
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from mcp.server import MCPServer

from .core.store import connect

SERVER = MCPServer(
    "claimbase",
    instructions=(
        "A compiled claim graph over the guru project (guru, guru-web, rellm). "
        "Answers carry provenance, claim kind, assertion date and supersession "
        "standing, so they distinguish what is true now from what was true. "
        "Prefer `recall` over grepping the repos."
    ),
)
CORPUS = "guru"


def _fmt_hit(h) -> dict:
    return {
        "claim": h.content,
        "kind": h.kind,
        "trust": h.trust,
        "asserted_at": h.asserted_at.isoformat() if h.asserted_at else None,
        "source": f"{h.source}: {h.source_ref}",
        "supersedes": h.superseded_count,
        "score": round(h.score, 3),
        "cosine": round(h.cosine, 3),
    }


@SERVER.tool()
def recall(query: str, k: int = 8, as_of: str | None = None,
           include_superseded: bool = False, intent: str | None = None) -> dict:
    """Answer a question from the claim graph.

    PASS THE QUESTION, NOT KEYWORDS. Phrasing carries meaning the ranking uses:
    "why is X still pending" is a question about mechanism and wants a durable
    explanation, while "is X still the current path" is about currency and wants the
    newest practice. Reduced to "X pending" both look identical and the wrong claims
    win. Full questions retrieve at least as well here — this is not a keyword index.

    Returns claims ranked by epistemic standing — similarity, provenance, currency,
    and whether a claim superseded others — each with its source, kind, assertion
    date, and the intent the question was read as.

    as_of: ISO date. Answers as the graph stood then ("what did I believe in June?").
    intent: override if the reading looks wrong — mechanism | current | historical |
    neutral.
    """
    return _dispatch("recall", {"query": query, "k": k, "as_of": as_of,
                                "include_superseded": include_superseded,
                                "intent": intent})


@SERVER.tool()
def timeline(subject: str, limit: int = 20) -> dict:
    """How belief about a subject changed over time.

    Matching claims in assertion order, showing which superseded which. Use when an
    answer may have changed rather than merely being unknown.
    """
    return _dispatch("timeline", {"subject": subject, "limit": limit})


@SERVER.tool()
def conflicts(limit: int = 20) -> dict:
    """Open contradictions the compiler could not settle. Empty is the normal state."""
    return _dispatch("conflicts", {"limit": limit})


@SERVER.tool()
def assert_claim(text: str, kind: str = "observation") -> dict:
    """Capture a fact into the graph.

    Use when you learn something the corpus does not record — especially that a
    practice has changed, which no amount of compiling can recover. Enters at agent
    trust and is capped accordingly: it cannot become a fact on its own say-so.

    kind: practice | decision | observation | hypothesis | plan | task | preference
    """
    return _dispatch("assert", {"text": text, "kind": kind})


@SERVER.tool()
def stats() -> dict:
    """What the corpus contains: counts by source, kind and trust."""
    return _dispatch("stats", {})


def _dispatch(name: str, args: dict) -> Any:
    if name == "recall":
        from .recall import recall

        as_of = None
        if args.get("as_of"):
            as_of = datetime.fromisoformat(args["as_of"]).replace(tzinfo=timezone.utc)
        with connect() as conn:
            hits = recall(
                args["query"], conn=conn, corpus=CORPUS, k=int(args.get("k", 8)),
                as_of=as_of, include_superseded=bool(args.get("include_superseded")),
                intent=args.get("intent"),
            )
        return {"query": args["query"], "results": [_fmt_hit(h) for h in hits]}

    if name == "timeline":
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.content, c.claim_kind, c.trust, c.status, c.asserted_at,
                       c.valid_to, e.source_ref, e.source
                FROM claims c JOIN events e ON e.id = c.event_id
                WHERE c.corpus = %s AND c.content ILIKE %s AND c.asserted_at IS NOT NULL
                ORDER BY c.asserted_at
                LIMIT %s
                """,
                (CORPUS, f"%{args['subject']}%", int(args.get("limit", 20))),
            )
            rows = cur.fetchall()
        return {
            "subject": args["subject"],
            "timeline": [
                {
                    "claim": r[0], "kind": r[1], "trust": r[2], "status": r[3],
                    "asserted_at": r[4], "valid_to": r[5],
                    "source": f"{r[7]}: {r[6]}",
                }
                for r in rows
            ],
        }

    if name == "conflicts":
        with connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT k.kind, k.resolution, a.content, b.content
                FROM conflicts k
                JOIN claims a ON a.id = k.claim_a
                LEFT JOIN claims b ON b.id = k.claim_b
                WHERE k.corpus = %s AND k.resolution IS NULL
                LIMIT %s
                """,
                (CORPUS, int(args.get("limit", 20))),
            )
            rows = cur.fetchall()
        return {"open": len(rows),
                "conflicts": [{"kind": r[0], "a": r[2], "b": r[3]} for r in rows]}

    if name == "assert":
        import uuid

        from .core.models import Event, Trust
        from .core.store import Store
        from .core.trust import apply_cap
        from .core.models import Claim, Kind

        now = datetime.now(timezone.utc)
        ev = Event(
            source="assert", corpus=CORPUS,
            source_ref=f"mcp:{now:%Y-%m-%dT%H:%M:%SZ}",
            content=args["text"], captured_at=now, meta={"via": "mcp"},
        )
        with connect() as conn:
            eid, _ = Store(conn).upsert_event(ev)
            claim = apply_cap(
                Claim(event_id=ev.id, content=args["text"],
                      kind=Kind(args.get("kind", "observation")),
                      trust=Trust.AGENT, asserted_at=now, valid_from=now, confidence=0.7)
            )
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO claims (id, corpus, event_id, content, claim_kind,
                           trust, corroborated, asserted_at, valid_from, confidence,
                           status, meta)
                       VALUES (%s,%s,%s,%s,%s,%s,false,%s,%s,%s,'active',%s)""",
                    (uuid.uuid4(), CORPUS, eid, claim.content, str(claim.kind),
                     str(claim.trust), now, now, claim.confidence,
                     json.dumps({"asserted": True, "via": "mcp", **claim.meta})),
                )
            conn.commit()
        return {
            "captured": ev.source_ref,
            "kind": str(claim.kind),
            "trust": str(claim.trust),
            "note": "run `claimbase embed` to make it retrievable",
        }

    if name == "stats":
        from .core.store import Store

        with connect() as conn:
            return Store(conn).stats(CORPUS)

    return {"error": f"unknown tool {name!r}"}


def main() -> None:
    import anyio

    anyio.run(SERVER.run_stdio_async)


if __name__ == "__main__":
    main()
