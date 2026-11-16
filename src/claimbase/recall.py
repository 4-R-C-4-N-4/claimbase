"""recall() — retrieval that ranks on epistemic standing, not just resemblance.

The problem this exists for: a captured correction stating that a practice ended is
one claim, and the eight documents still describing that practice are eight claims.
Cosine similarity gives the crowd the win. Being outnumbered is not being wrong, and
a system whose whole premise is *"answers come with epistemic metadata"* (DESIGN §5)
cannot rank purely by resemblance.

So similarity selects the candidates and standing orders them:

    score = cosine x (1 + trust) x (1 + currency) x (1 + settled)
                   x (1 + affinity) x (1 + entity) x (1 + lexical)   [x scaffold penalty]

Candidates come in through two legs — vector nearest-neighbours and a full-text
match on distinctive phrasing (migration 007) — fused into one pool before
scoring, and near-duplicate re-extractions are collapsed at result time so one
fact cannot occupy two slots.

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
# Tempered 0.8 -> 0.55 (2026-08-21): entity linking is coverage-biased — ticket
# claims are densely linked, doc claims often not linked at all — so at 0.8 the
# boost let a linked cos-0.69 claim bury an unlinked cos-0.83 one (q017). The
# cosine-leader guarantee below is the backstop; this keeps the boost a strong
# tie-breaker instead of a veto.
W_ENTITY = 0.55
# Lexical (full-text) match between question and claim, normalized against the
# best lexical score in the candidate pool. Added after the 2026-08-21 reviewer
# eval: vector-only retrieval repeatedly missed active, embedded claims whose
# content shared distinctive *phrases* with the question ("review the chunker
# config", "--respect-reviewed", "boilerplate-survey") while generic neighbours
# won on cosine. Lexical candidates are fetched by websearch_to_tsquery and
# fused into the same pool, so a distinctive phrase is a second way in — not a
# separate ranking.
W_LEXICAL = 0.6
# Structural scaffold claims ("docs/X documents §Y", meta.field = 'heading')
# exist for dating and structure tracking, not for answering. Left unpenalized
# they crowd out content claims exactly when the query names a doc or section:
# in the node-03 failure-modes query they took 7 of 8 result slots while the
# actual failure-mode claims from the same doc sat below the cut. Penalized,
# not excluded — "what does this doc cover" is still a legitimate question.
SCAFFOLD_PENALTY = 0.45
# A query that names a file ("what failure modes are in docs/ingest/03-acquire.md")
# is asking about that document's *content*, but content claims rarely repeat
# their own path, so neither cosine nor the lexical leg connects the two — the
# 2026-08-21 eval showed such queries losing to topically-adjacent hub claims
# while the named doc's claims sat unranked. Provenance is the link: boost
# claims whose source_ref contains a path-shaped token from the query.
W_REF = 0.7
# Two claims this lexically similar are the same fact from adjacent revisions
# of the same document (supersession links exact re-extractions but misses
# paraphrase-level re-wordings). Observed burning two of five result slots on
# one fact (sync_taxonomy pair, schema-diagrams pair). Collapsed at result
# time: the higher-scored claim represents the fact.
NEAR_DUP_JACCARD = 0.6
HALF_LIFE_DAYS = 120.0

# Per project: entities are namespaced by corpus, and two projects can each
# have an "auth service" without the system ever comparing them.
_ALIAS_CACHE: dict[str, dict] = {}


def _alias_map(conn, corpus: str = "guru") -> dict:
    if corpus not in _ALIAS_CACHE:
        from .link_entities import build_alias_map

        _ALIAS_CACHE[corpus] = build_alias_map(conn, corpus)
    return _ALIAS_CACHE[corpus]

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
    # practice/decision earn mechanism affinity too: "why is X done this way" and
    # "why is X off-limits" classify as mechanism and are answered by a stated
    # practice or a recorded decision, not only by capability claims — the
    # node-15 and corpus-toml regressions (2026-08-21) were practice claims
    # losing mechanism questions to boosted neighbours.
    "mechanism":  {"capability": 1.0, "fact": 0.8, "practice": 0.5, "decision": 0.4,
                   "observation": 0.3},
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
    lex: float = 0.0
    scaffold: bool = False
    # `contested` is served, with its label: a claim under dispute is still the
    # best the store has, and hiding it would turn a dispute into a silence.
    status: str = "active"

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
        if self.lex:
            bits.append(f"lex {self.lex:.2f}")
        if self.scaffold:
            bits.append("scaffold")
        if self.status != "active":
            bits.append(self.status.upper())
        return " · ".join(bits)


_TOKEN = re.compile(r"[a-z0-9_./-]+")
# Path-shaped tokens in a query: contain a slash, or look like a filename with a
# code/doc extension. "node 03" is not a path; "docs/ingest/03-acquire.md" and
# "chunk.py" are.
_PATHISH = re.compile(r"[\w.-]*/[\w./-]+|\b[\w-]+\.(?:md|py|sh|toml|sql|ts|tsx|js|yml|yaml|json)\b")
# Workbook nodes are named by number at least as often as by path ("workbook
# node 3", "node 04", "D3 review") and the node docs encode the number in the
# filename (docs/ingest/03-acquire.md, docs/dossiers/D3-review.md). Translate
# the phrasing into a source_ref fragment so those queries reach the doc's
# claims — the original "workbook node 3" miss from the 2026-08-21 eval.
_NODE_NUM = re.compile(r"\bnode\s+0?(\d{1,2})\b", re.I)
_PASSD_NODE = re.compile(r"\bD([1-6])\b")


def _path_tokens(query: str) -> set[str]:
    toks = {t.lower().strip("./") for t in _PATHISH.findall(query) if len(t) > 3}
    toks |= {f"/{int(n):02d}-" for n in _NODE_NUM.findall(query)}
    toks |= {f"/d{n}-" for n in _PASSD_NODE.findall(query)}
    return toks


def _near_dup(a: str, b: str) -> bool:
    """Token-Jaccard near-duplicate test for result collapse.

    The duplicates this exists for are re-extractions of the same sentence from
    adjacent revisions of one document — near-verbatim, so a cheap set overlap
    separates them cleanly from claims that merely share a topic. Embeddings are
    deliberately not used here: topical neighbours sit close in vector space,
    and collapsing those would erase corroboration."""
    ta, tb = set(_TOKEN.findall(a.lower())), set(_TOKEN.findall(b.lower()))
    if not ta or not tb:
        return False
    return len(ta & tb) / len(ta | tb) >= NEAR_DUP_JACCARD


def _collapse_near_dups(hits: list["Hit"], k: int) -> list["Hit"]:
    """Greedy top-k selection skipping near-duplicates of already-kept hits.

    Ranking order is preserved; the best-scored member of each duplicate family
    represents the fact and the rest yield their slots to distinct claims."""
    kept: list[Hit] = []
    for h in hits:
        if any(_near_dup(h.content, p.content) for p in kept):
            continue
        kept.append(h)
        if len(kept) == k:
            break
    return kept


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
    # Standing claims: active, plus contested (served with a label). Tentative
    # claims rest on one episode and are not served until a second supports
    # them; superseded ones only on request.
    where = "" if include_superseded else "AND c.status IN ('active', 'contested')"
    asof = "AND (c.asserted_at IS NULL OR c.asserted_at <= %(now)s)" if as_of else ""

    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT c.id, c.content, c.claim_kind, c.trust, c.asserted_at,
                   e.source_ref, e.source,
                   1 - (c.embedding <=> %(v)s::vector) AS cosine,
                   (SELECT count(*) FROM claims s WHERE s.superseded_by = c.id),
                   c.meta, 0.0 AS lex, c.status
            FROM claims c JOIN events e ON e.id = c.event_id
            WHERE c.corpus = %(corpus)s AND c.embedding IS NOT NULL {where} {asof}
            ORDER BY c.embedding <=> %(v)s::vector
            LIMIT %(cand)s
            """,
            {"v": str(vec), "corpus": corpus, "cand": candidates, "now": now},
        )
        rows = cur.fetchall()

    # The lexical leg: candidates the distinctive phrasing reaches that cosine's
    # top-N missed. Fused into one pool — same scoring, one extra signal — so
    # this widens candidate selection rather than adding a second ranking.
    #
    # OR-of-lexemes, not websearch semantics: websearch_to_tsquery ANDs every
    # term, and a full natural-language question matches nothing under AND. An
    # OR query lets ts_rank_cd reward the claims that match *many* of the
    # question's lexemes with proximity, which is the phrase signal we want.
    #
    # Guarded: on a store without migration 007 the recall degrades to
    # vector-only instead of failing the whole call.
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                WITH q AS (
                    SELECT to_tsquery('english',
                               string_agg('''' || w.lexeme || '''', ' | ')) AS tsq
                    FROM (SELECT DISTINCT lexeme
                          FROM unnest(to_tsvector('english', %(q)s))) w
                )
                SELECT c.id, c.content, c.claim_kind, c.trust, c.asserted_at,
                       e.source_ref, e.source,
                       1 - (c.embedding <=> %(v)s::vector) AS cosine,
                       (SELECT count(*) FROM claims s WHERE s.superseded_by = c.id),
                       c.meta, ts_rank_cd(c.content_tsv, q.tsq, 1) AS lex, c.status
                FROM claims c JOIN events e ON e.id = c.event_id, q
                WHERE c.corpus = %(corpus)s AND c.embedding IS NOT NULL
                  AND c.content_tsv @@ q.tsq {where} {asof}
                ORDER BY lex DESC
                LIMIT %(lexcand)s
                """,
                {"v": str(vec), "q": query, "corpus": corpus,
                 "lexcand": max(candidates // 4, 40), "now": now},
            )
            lex_rows = cur.fetchall()
    except Exception:
        conn.rollback()
        lex_rows = []

    # The provenance leg: when the query names a document or workbook node, the
    # named doc's claims are candidates by fiat — content claims rarely repeat
    # their own path, so neither cosine nor lexemes reliably connects "what does
    # docs/ingest/03-acquire.md say" to the claims extracted from it (W_REF then
    # ranks them; this fetch just gets them into the room).
    ref_rows: list = []
    q_paths = _path_tokens(query)
    if q_paths:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT c.id, c.content, c.claim_kind, c.trust, c.asserted_at,
                           e.source_ref, e.source,
                           1 - (c.embedding <=> %(v)s::vector) AS cosine,
                           (SELECT count(*) FROM claims s WHERE s.superseded_by = c.id),
                           c.meta, 0.0 AS lex, c.status
                    FROM claims c JOIN events e ON e.id = c.event_id
                    WHERE c.corpus = %(corpus)s AND c.embedding IS NOT NULL
                      AND lower(e.source_ref) LIKE ANY(%(pats)s) {where} {asof}
                    ORDER BY c.embedding <=> %(v)s::vector
                    LIMIT 40
                    """,
                    {"v": str(vec), "corpus": corpus, "now": now,
                     "pats": [f"%{p}%" for p in q_paths]},
                )
                ref_rows = cur.fetchall()
        except Exception:
            conn.rollback()

    by_id = {r[0]: list(r) for r in rows}
    for r in lex_rows:
        if r[0] in by_id:
            by_id[r[0]][10] = r[10]  # vector candidate that also matched lexically
        else:
            by_id[r[0]] = list(r)
    for r in ref_rows:
        by_id.setdefault(r[0], list(r))
    rows = list(by_id.values())
    # Normalize against the pool's best lexical score: ts_rank_cd is unbounded
    # and corpus-dependent, so only the relative standing means anything.
    max_lex = max((r[10] for r in rows), default=0.0) or 1.0

    intent = intent if intent in AFFINITY else classify_intent(query)
    currency_scale = CURRENCY_BY_INTENT[intent]
    affinity = AFFINITY[intent]

    from .link_entities import entities_in, repos_in

    q_entities = entities_in(query, _alias_map(conn, corpus))
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
    for cid, content, kind, trust, ts, ref, source, cosine, nsup, meta, lex, status in rows:
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
        lex_norm = float(lex or 0.0) / max_lex
        scaffold = bool(meta) and meta.get("field") == "heading"
        ref_l = (ref or "").lower()
        ref_match = any(p in ref_l for p in q_paths)
        score = (
            float(cosine)
            * (1 + W_TRUST * t)
            * (1 + W_CURRENCY * cur_)
            * (1 + W_SETTLED * settled)
            * (1 + W_AFFINITY * aff)
            * (1 + W_ENTITY * ent_signal)
            * (1 + W_LEXICAL * lex_norm)
            * (1 + W_REF * ref_match)
        )
        if scaffold:
            score *= SCAFFOLD_PENALTY
        hits.append(
            Hit(str(cid), content, kind, trust, ts, ref, source,
                float(cosine), score, int(nsup or 0), entity_hit=bool(matched),
                lex=lex_norm, scaffold=scaffold, status=status)
        )
    hits.sort(key=lambda h: -h.score)
    for h in hits:
        h.intent = intent
    result = _collapse_near_dups(hits, k)

    # Cosine-leader guarantee. Standing signals are tie-breakers, but multiplied
    # together they can bury the most similar claim entirely — a linked cos-0.69
    # claim outscoring an unlinked cos-0.83 one (q017, 2026-08-21) turns
    # tie-breakers into a veto. So the two most question-similar claims always
    # make the cut; standing still decides the order of everything above them.
    leaders = [h for h in sorted(hits, key=lambda h: -h.cosine) if not h.scaffold][:2]
    for lead in leaders:
        if lead in result or any(_near_dup(lead.content, p.content) for p in result):
            continue
        if len(result) < k:
            result.append(lead)
        else:
            for i in range(len(result) - 1, -1, -1):
                if result[i] not in leaders:
                    result[i] = lead
                    break
    return result
