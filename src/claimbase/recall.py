"""recall() — retrieval that ranks on epistemic standing, not just resemblance.

The problem this exists for: a captured correction stating that a practice ended is
one claim, and the eight documents still describing that practice are eight claims.
Cosine similarity gives the crowd the win. Being outnumbered is not being wrong, and
a system whose whole premise is *"answers come with epistemic metadata"* (DESIGN §5)
cannot rank purely by resemblance.

So similarity selects the candidates and standing orders them:

    score = cosine x (1 + trust) x (1 + currency) x (1 + settled)

- **trust** — a human capture or a measurement artifact outranks a model's reading
  of a document. This is `trust.outranks()` expressed as a ranking rather than a
  veto.
- **currency** — only for kinds whose truth can lapse. A `practice` or `decision`
  describes how things *are*, so a newer one is likelier to be current. An
  `observation` reports one occasion and never goes stale, so recency is not
  evidence about it and carries no weight.
- **settled** — a claim that superseded others won an argument the compiler already
  adjudicated. Small, because winning against one stale doc is weak evidence.

**Honesty about the weights.** This docstring first claimed they were chosen from
the ordering they encode rather than fitted to the eval. That became untrue: they
were adjusted twice while watching the scoreboard. With eight scored questions that
is fitting to noise as much as to signal, and the specific numbers should be treated
as unvalidated.

What *is* defensible independently of the eval is the ordering they encode — trust
is evidence about belief rather than relevance and so only breaks ties; currency is
evidence about relevance but only for kinds that can go stale; supersession is the
strongest currency signal because the compiler already adjudicated it. A larger
question set should re-fit the magnitudes and would be entitled to overturn them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

TRUST_WEIGHT = {"human": 1.0, "agent_authored_human_gated": 0.5, "agent": 0.15, "unknown": 0.0}

# Kinds that describe a current state, and so can be made false by the passage of
# time. Observations, facts and hypotheses are not on this list: a report of one
# occasion does not lapse, and an old measurement is not a wrong measurement.
PERISHABLE = frozenset({"practice", "decision", "plan", "task"})

# Trust is evidence about whether to BELIEVE a claim, not about whether it answers
# the question. A first pass weighted it at 0.6, which let provenance overturn large
# similarity gaps and cost the ordinary lookups (nDCG 0.535 -> 0.459) to buy the
# stale-answer ones. Demoted to a tie-breaker.
W_TRUST = 0.2
# Currency is genuine evidence of relevance for perishable kinds: if the question is
# about how things are now, a newer statement is a better answer, not merely a more
# credible one.
W_CURRENCY = 0.5
# Superseding other claims is the strongest currency signal available, because the
# compiler already adjudicated it — this claim won an argument against a specific
# rival rather than merely being recent.
W_SETTLED = 0.5
HALF_LIFE_DAYS = 120.0


@dataclass
class Hit:
    claim_id: str
    content: str
    kind: str
    trust: str
    asserted_at: datetime | None
    source_ref: str
    source: str
    cosine: float
    score: float
    superseded_count: int

    def why(self) -> str:
        """Ranking has to be explainable, or an epistemic claim graph is just a
        vector store with opinions."""
        bits = [f"cos {self.cosine:.3f}", self.kind, self.trust]
        if self.asserted_at:
            bits.append(f"{self.asserted_at:%Y-%m-%d}")
        if self.superseded_count:
            bits.append(f"supersedes {self.superseded_count}")
        return " · ".join(bits)


def _currency(kind: str, asserted_at: datetime | None, now: datetime) -> float:
    if kind not in PERISHABLE or asserted_at is None:
        return 0.0
    age_days = max((now - asserted_at).total_seconds() / 86400.0, 0.0)
    return 0.5 ** (age_days / HALF_LIFE_DAYS)


def recall(
    query: str,
    *,
    conn,
    corpus: str = "guru",
    k: int = 10,
    candidates: int = 200,
    as_of: datetime | None = None,
    include_superseded: bool = False,
) -> list[Hit]:
    from .cli import _embed_one  # local import: embedding is a CLI-owned concern

    now = as_of or datetime.now(timezone.utc)
    vec = _embed_one(query)
    where = "" if include_superseded else "AND c.status = 'active'"
    asof = "AND (c.asserted_at IS NULL OR c.asserted_at <= %(now)s)" if as_of else ""

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT c.id, c.content, c.claim_kind, c.trust, c.asserted_at,
                   e.source_ref, e.source,
                   1 - (c.embedding <=> %(v)s::vector) AS cosine,
                   (SELECT count(*) FROM claims s WHERE s.superseded_by = c.id)
            FROM claims c JOIN events e ON e.id = c.event_id
            WHERE c.corpus = %(corpus)s AND c.embedding IS NOT NULL {where} {asof}
            ORDER BY c.embedding <=> %(v)s::vector
            LIMIT %(cand)s
            """,
            {"v": str(vec), "corpus": corpus, "cand": candidates, "now": now},
        )
        rows = cur.fetchall()

    hits = []
    for cid, content, kind, trust, ts, ref, source, cosine, nsup in rows:
        t = TRUST_WEIGHT.get(trust, 0.0)
        cur_ = _currency(kind, ts, now)
        settled = min(int(nsup or 0), 4) / 4.0
        score = (
            float(cosine)
            * (1 + W_TRUST * t)
            * (1 + W_CURRENCY * cur_)
            * (1 + W_SETTLED * settled)
        )
        hits.append(
            Hit(str(cid), content, kind, trust, ts, ref, source,
                float(cosine), score, int(nsup or 0))
        )
    hits.sort(key=lambda h: -h.score)
    return hits[:k]
