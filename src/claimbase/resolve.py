"""Resolve conflicts by leaning, and rank whatever is left by impact.

Opening 904 conflicts and handing them to a person is not review, it is refusing to
decide. Every conflict gets a verdict here. Where the evidence is thin the verdict is
still recorded, marked low-confidence, and put in front of a human **in order of how
much it changes an answer** — because a queue sorted by nothing is a queue nobody
finishes.

Leaning rules, in order. The first that applies wins:

1. **trust asymmetry** — a human-captured claim beats a model's reading of a doc.
   `trust.outranks()`, finally used for what it was written for.
2. **kind precedence** — a hypothesis never displaces a fact; a fact or decision
   displaces a hypothesis (§4.5).
3. **recency on replacing kinds** — for decisions, practices and capabilities the
   later claim wins, because those describe a current state that changed.
4. **coexist** — observations accumulate. Two reports of different occasions are
   both true and neither supersedes.

Impact, for what survives with low confidence: how loudly the older claim is
currently being asserted. A stale claim surrounded by near neighbours dominates
retrieval; an isolated one bothers nobody, however wrong it is.
"""

from __future__ import annotations

from dataclasses import dataclass

from .core.store import connect

REPLACING = ("decision", "practice", "fact", "capability")
TRUST_RANK = {"human": 3, "agent_authored_human_gated": 2, "agent": 1, "unknown": 0}


@dataclass
class Verdict:
    conflict_id: str
    old_id: str
    new_id: str
    winner: str  # 'newer' | 'older' | 'coexist'
    rule: str
    confidence: float
    impact: float


def _lean(a: dict, b: dict) -> tuple[str, str, float]:
    """(winner, rule, confidence) for claim a (earlier) vs b (later)."""
    ta, tb = TRUST_RANK.get(a["trust"], 0), TRUST_RANK.get(b["trust"], 0)
    if tb > ta:
        return "newer", "trust_asymmetry", 0.9
    if ta > tb:
        # The older claim is better sourced. Recency does not beat provenance:
        # a model's later paraphrase must not displace a human's earlier statement.
        return "older", "trust_asymmetry", 0.8

    if a["kind"] == "hypothesis" and b["kind"] in ("fact", "decision"):
        return "newer", "kind_precedence", 0.85
    if b["kind"] == "hypothesis" and a["kind"] in ("fact", "decision"):
        return "older", "kind_precedence", 0.85

    if a["kind"] == b["kind"] and a["kind"] in REPLACING:
        return "newer", "recency_replacing", 0.7

    if a["kind"] == b["kind"] == "observation":
        return "coexist", "observations_accumulate", 0.9

    return "newer", "recency_default", 0.45  # weakest lean; still a lean


def resolve(corpus: str = "guru", apply_high: float = 0.6) -> dict:
    conn = connect()
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT k.id, a.id, a.content, a.claim_kind, a.trust, a.confidence,
                   b.id, b.content, b.claim_kind, b.trust, b.confidence,
                   -- impact proxy: how many active claims sit close to the older
                   -- one. A stale claim with many near neighbours dominates
                   -- retrieval; an isolated one misleads nobody.
                   (SELECT count(*) FROM claims n
                     WHERE n.corpus = a.corpus AND n.status = 'active'
                       AND n.embedding IS NOT NULL
                       AND 1 - (n.embedding <=> a.embedding) >= 0.88) AS crowd
            FROM conflicts k
            JOIN claims a ON a.id = k.claim_a
            JOIN claims b ON b.id = k.claim_b
            WHERE k.corpus = %s AND k.resolution IS NULL
            """,
            (corpus,),
        )
        rows = cur.fetchall()

    verdicts = []
    for (kid, aid, _ac, ak, at, aconf, bid, _bc, bk, bt, bconf, crowd) in rows:
        a = {"kind": ak, "trust": at, "confidence": aconf}
        b = {"kind": bk, "trust": bt, "confidence": bconf}
        winner, rule, conf = _lean(a, b)
        verdicts.append(Verdict(kid, aid, bid, winner, rule, conf, float(crowd or 0)))

    applied = 0
    with conn.cursor() as cur:
        for v in verdicts:
            cur.execute(
                "UPDATE conflicts SET resolution = %s, resolved_at = now() WHERE id = %s",
                (f"{v.winner}:{v.rule}:{v.confidence:.2f}", v.conflict_id),
            )
            # Only confident leans change the graph. A weak lean is recorded as the
            # proposed answer and surfaced for review, not silently enacted.
            if v.confidence >= apply_high and v.winner in ("newer", "older"):
                loser = v.old_id if v.winner == "newer" else v.new_id
                keeper = v.new_id if v.winner == "newer" else v.old_id
                cur.execute(
                    """UPDATE claims
                          SET status='superseded', superseded_by=%s,
                              valid_to = COALESCE(valid_to, (SELECT asserted_at FROM claims WHERE id=%s)),
                              meta = meta || jsonb_build_object('superseded_rule', %s::text)
                        WHERE id=%s AND status='active'""",
                    (keeper, keeper, f"conflict:{v.rule}", loser),
                )
                applied += cur.rowcount
    conn.commit()
    conn.close()

    weak = sorted(
        [v for v in verdicts if v.confidence < apply_high],
        key=lambda v: -v.impact,
    )
    by_rule: dict[str, int] = {}
    for v in verdicts:
        by_rule[v.rule] = by_rule.get(v.rule, 0) + 1
    return {
        "total": len(verdicts),
        "claims_superseded": applied,
        "by_rule": by_rule,
        "needs_review": weak,
    }
