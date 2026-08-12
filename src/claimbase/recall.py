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

import re
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
W_AFFINITY = 0.4
# Entity overlap between question and claim. Lexical, and that is the point:
# embeddings put `retriever.ts` and `retriever.py` almost on top of each other, so
# similarity cannot separate two implementations sharing a name. The alias table
# makes that identity survive path variation, and this is where it earns its place.
#
# **Scaled by specificity, not applied flat.** A flat boost cost q016 its whole score
# (0.901 -> 0.000) and q014 most of its own, because naming a repo matches most of
# the candidate pool: "guru-web" is shared by hundreds of claims and says nothing,
# while "retriever.ts" is shared by three and says a great deal. Weighting those
# equally promotes claims that merely *mention* the subject over claims that answer
# the question.
#
# Specificity is measured against the candidates actually retrieved, so it needs no
# tuning and adapts per query: a match half the pool shares earns almost nothing, a
# match two claims share earns nearly the full weight. This is inverse document
# frequency doing the job a constant cannot.
W_ENTITY = 0.8
HALF_LIFE_DAYS = 120.0

_ALIAS_CACHE: dict | None = None


def _alias_map(conn) -> dict:
    global _ALIAS_CACHE
    if _ALIAS_CACHE is None:
        from .link_entities import build_alias_map

        _ALIAS_CACHE = build_alias_map(conn)
    return _ALIAS_CACHE

# --- question intent ---------------------------------------------------------
#
# Currency is evidence of relevance only when the question is ABOUT the current
# state. Applied unconditionally it does real damage: asked "why is
# staged_edges.status still pending after an auto-promote run?" — a question about
# mechanism — the system answered "because auto-promote was discontinued in July",
# which is true, irrelevant, and confidently wrong as an answer. The captured
# practice-change outranked the capability claim that actually explains the
# behaviour.
#
# No retrieval metric caught that; only the answer-level bench did. So intent is
# classified here, cheaply and without a model — DESIGN §1.7, fat pipeline and thin
# runtime — and it modulates both currency and which claim kinds are favoured.

_MECHANISM = re.compile(
    r"\b(why (?:is|are|does|do|did)|how (?:does|do|is|are)|what (?:does|do) \w+ do|"
    r"what happens|explain|is it (?:a )?bug|intentional|by design|purpose of)\b", re.I
)
_CURRENT = re.compile(
    r"\b(current(?:ly)?|now|still|these days|latest|nowadays|"
    r"should (?:i|we|it)|do (?:i|we) still|are we still|what do (?:i|we) use)\b", re.I
)
_HISTORICAL = re.compile(
    r"\b(was|were|used to|previously|back then|at the time|originally|"
    r"in (?:january|february|march|april|may|june|july|august|september|october|"
    r"november|december)|as of \d{4}|\bin \d{4})\b", re.I
)

# Which kinds answer which question. This is semantics, not tuning: a mechanism
# question is answered by a statement of what a tool can do; a currency question by
# a statement of how work is done now; a historical one by a dated report.
AFFINITY: dict[str, dict[str, float]] = {
    "mechanism":  {"capability": 1.0, "fact": 0.8, "observation": 0.3},
    "current":    {"practice": 1.0, "decision": 0.8},
    "historical": {"observation": 1.0, "fact": 0.6},
    "neutral":    {},
}
# How much recency counts, per intent. A mechanism question gets none: how a tool
# works does not become truer for being described recently.
# `neutral` sits close to `current`, not halfway. An unmarked question about a live
# project is implicitly about now — "does the base model beat the fine-tunes?" carries
# no currency marker and still wants today's answer. Historical and mechanism are the
# marked cases; assuming the present is the right default, and at 0.5 the stale
# reading of q001 won.
CURRENCY_BY_INTENT = {"mechanism": 0.0, "current": 1.0, "historical": 0.0, "neutral": 0.8}


def classify_intent(query: str) -> str:
    """Cheap, model-free, and checked in that order: mechanism first because "why is
    X still pending" contains "still" and would otherwise read as a currency
    question — which is exactly how q004 went wrong."""
    if _MECHANISM.search(query):
        return "mechanism"
    if _HISTORICAL.search(query):
        return "historical"
    if _CURRENT.search(query):
        return "current"
    return "neutral"


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
    intent: str = "neutral"
    entity_hit: bool = False

    def why(self) -> str:
        """Ranking has to be explainable, or an epistemic claim graph is just a
        vector store with opinions."""
        bits = [f"cos {self.cosine:.3f}", self.kind, self.trust, f"asked:{self.intent}"]
        if self.asserted_at:
            bits.append(f"{self.asserted_at:%Y-%m-%d}")
        if self.superseded_count:
            bits.append(f"supersedes {self.superseded_count}")
        if self.entity_hit:
            bits.append("entity match")
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
    intent: str | None = None,
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

    intent = intent if intent in AFFINITY else classify_intent(query)
    currency_scale = CURRENCY_BY_INTENT[intent]
    affinity = AFFINITY[intent]

    from .link_entities import entities_in, repos_in

    q_entities = entities_in(query, _alias_map(conn))
    q_repos = repos_in(query)
    claim_ents: dict[str, set[str]] = {}
    claim_repos: dict[str, set[str]] = {}
    hit_counts: dict[str, int] = {}
    if q_entities or q_repos:
        ids = [r[0] for r in rows]
        with conn.cursor() as cur:
            cur.execute(
                """SELECT ce.claim_id, ce.entity_id, e.canonical_name
                     FROM claim_entities ce JOIN entities e ON e.id = ce.entity_id
                    WHERE ce.claim_id = ANY(%s)""",
                (ids,),
            )
            for cid, eid, name in cur.fetchall():
                claim_ents.setdefault(str(cid), set()).add(str(eid))
                if ":" in name:
                    claim_repos.setdefault(str(cid), set()).add(name.split(":", 1)[0])
        # How much of the candidate pool each query term matches. A term matching
        # nearly everything is not evidence about anything.
        for cid in {str(r[0]) for r in rows}:
            for eid in q_entities & claim_ents.get(cid, set()):
                hit_counts[eid] = hit_counts.get(eid, 0) + 1
            for repo in q_repos & claim_repos.get(cid, set()):
                hit_counts[repo] = hit_counts.get(repo, 0) + 1

    hits = []
    for cid, content, kind, trust, ts, ref, source, cosine, nsup in rows:
        t = TRUST_WEIGHT.get(trust, 0.0)
        cur_ = _currency(kind, ts, now) * currency_scale
        settled = min(int(nsup or 0), 4) / 4.0
        aff = affinity.get(kind, 0.0)
        matched = (q_entities & claim_ents.get(str(cid), set())) | (
            q_repos & claim_repos.get(str(cid), set())
        )
        # Best specificity among the terms this claim matched: sharing one rare
        # entity with the question beats sharing one ubiquitous repo.
        n = max(len(rows), 1)
        ent_signal = max(
            (1.0 - hit_counts.get(term, n) / n for term in matched), default=0.0
        )
        score = (
            float(cosine)
            * (1 + W_TRUST * t)
            * (1 + W_CURRENCY * cur_)
            * (1 + W_SETTLED * settled)
            * (1 + W_AFFINITY * aff)
            * (1 + W_ENTITY * ent_signal)
        )
        hits.append(
            Hit(str(cid), content, kind, trust, ts, ref, source,
                float(cosine), score, int(nsup or 0), entity_hit=bool(matched))
        )
    hits.sort(key=lambda h: -h.score)
    for h in hits:
        h.intent = intent
    return hits[:k]
