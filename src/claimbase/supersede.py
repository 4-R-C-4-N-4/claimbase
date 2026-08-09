"""Supersession — what makes a claim graph different from a pile of chunks.

DESIGN §4.5. Phase 0 measured retrieval with this layer empty and claims lost to
chunk-RAG, which is the expected result: atomisation alone has no reason to beat
chunking. Claims earn their keep by knowing what is no longer true.

Deterministic rules run first and take no model at all. An LLM adjudicator is only
worth its cost where the structure genuinely underdetermines the answer, and every
claim it can decide cheaply is a claim it never has to guess at.

Nothing is deleted, ever. A superseded claim keeps its row, gains `valid_to` and a
`superseded_by` pointer, and drops out of active recall — so "what did I believe in
June?" stays a legal question (DESIGN §1.4).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .core.store import connect

# Claim kinds that replace their predecessor rather than accumulating alongside it.
# An observation is a report of one occasion and never supersedes anything; a
# hypothesis must never displace a fact (§4.5).
REPLACING = ("decision", "practice", "fact", "capability")


@dataclass
class Superseded:
    old_id: str
    new_id: str
    rule: str
    valid_to: object


def metric_restatement(conn, corpus: str = "guru") -> list[Superseded]:
    """DISABLED 2026-08-09 — a restated measurement does not supersede its predecessor.

    This rule cost q005 its entire score (0.431 -> 0.000) by hiding the older bench
    readings, and the reasoning behind it was simply wrong. "v1 recall was 0.596 on
    22 May" does not stop being true when a later run reports 0.509: it is a dated
    measurement, not a claim about current state. A later run ADDS an observation
    rather than invalidating an earlier one.

    Same shape as capability-vs-practice (PLAN §0.9): what supersedes is a claim
    about how things ARE, and nobody writes those about metrics — they write dated
    readings. A rule for "current F1 of v1" would be correct and has no instances.

    Kept as a record of the mistake and excluded from RULES.

    Original docstring: the same measurement, restated later, on the same ruler. Comparability is keyed on the bench's scored-cell
    count as well as the model and metric — two benches reporting the same number
    for the same model are NOT comparable if they scored different sets, a trap that
    fired three times while building the harness (findings.md).
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, meta->>'metric', subject_text, meta->>'variant',
                   meta->>'n', asserted_at
            FROM claims
            WHERE corpus = %s AND meta ? 'metric' AND status = 'active'
                  AND asserted_at IS NOT NULL
            ORDER BY asserted_at
            """,
            (corpus,),
        )
        rows = cur.fetchall()

    series: dict[tuple, list] = {}
    for cid, metric, model, variant, n, ts in rows:
        series.setdefault((metric, model, variant, n), []).append((cid, ts))

    out = []
    for _key, points in series.items():
        if len(points) < 2:
            continue
        points.sort(key=lambda p: p[1])
        for (old_id, _old_ts), (new_id, new_ts) in zip(points, points[1:]):
            out.append(Superseded(old_id, new_id, "metric_restatement", new_ts))
    return out


def revision_removal(conn, corpus: str = "guru") -> list[Superseded]:
    """Rule 2 — a doc section that git says stopped existing.

    `valid_to` was recorded by the docs adapter from the commit that removed the
    text. A claim whose supporting section is gone is no longer active, and the end
    date is a fact rather than an inference.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, valid_to FROM claims
            WHERE corpus = %s AND valid_to IS NOT NULL AND status = 'active'
                  AND valid_to <= now()
            """,
            (corpus,),
        )
        return [Superseded(cid, None, "revision_removal", vt) for cid, vt in cur.fetchall()]


# Rule 3 was first written as lexical subject-overlap and it found the wrong thing
# entirely: near-DUPLICATES, not contradictions. Two claims extracted from a ticket
# and the doc describing it say the same thing in different words, and lexical
# overlap scores that as high as a genuine disagreement would. Similarity and
# contradiction are opposite signals.
#
# Embeddings separate them, using the banding DESIGN §4.3 already specifies for
# entity resolution:
#
#   cosine >= 0.94   the same assertion restated -> duplicate, fold the older away
#   0.80 - 0.94      same subject, different content -> a CONFLICT for adjudication
#   < 0.80           unrelated; shared vocabulary is a coincidence
#
# Only the top band acts automatically. The middle band is precisely where a machine
# cannot tell "changed my mind" from "said something else about the same thing", so
# it goes to the conflicts queue rather than being guessed at (§4.5).

DUPLICATE_AT = 0.94
CONFLICT_BAND = (0.80, 0.94)


def near_duplicates(conn, corpus: str = "guru", limit_per: int = 4) -> list[Superseded]:
    """Rule 3a — the same assertion restated later. Folding the older one away
    deduplicates the index, which is worth doing on its own: near-identical claims
    compete for rank and crowd out distinct ones."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.id, b.id, b.asserted_at
            FROM claims a
            JOIN LATERAL (
                SELECT c.id, c.asserted_at
                FROM claims c
                WHERE c.corpus = a.corpus AND c.status = 'active'
                      AND c.id <> a.id AND c.embedding IS NOT NULL
                      AND c.asserted_at > a.asserted_at
                      AND 1 - (c.embedding <=> a.embedding) >= %s
                ORDER BY c.embedding <=> a.embedding
                LIMIT %s
            ) b ON true
            WHERE a.corpus = %s AND a.status = 'active'
                  AND a.embedding IS NOT NULL AND a.asserted_at IS NOT NULL
            """,
            (DUPLICATE_AT, limit_per, corpus),
        )
        seen, out = set(), []
        for old_id, new_id, ts in cur.fetchall():
            if old_id in seen:
                continue
            seen.add(old_id)
            out.append(Superseded(old_id, new_id, "near_duplicate", ts))
    return out


def conflict_candidates(conn, corpus: str = "guru", limit_per: int = 3) -> int:
    """Rule 3b — same subject, different content, and a replacing kind on both
    sides. These are the pairs where something may actually have changed; the
    machine opens a conflict and a human decides (§4.5)."""
    lo, hi = CONFLICT_BAND
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO conflicts (id, corpus, claim_a, claim_b, kind)
            SELECT gen_random_uuid(), %s, a.id, b.id, 'contradiction'
            FROM claims a
            JOIN LATERAL (
                SELECT c.id
                FROM claims c
                WHERE c.corpus = a.corpus AND c.status = 'active'
                      AND c.id <> a.id AND c.embedding IS NOT NULL
                      AND c.asserted_at > a.asserted_at
                      AND c.claim_kind = a.claim_kind
                      AND 1 - (c.embedding <=> a.embedding) BETWEEN %s AND %s
                ORDER BY c.embedding <=> a.embedding
                LIMIT %s
            ) b ON true
            WHERE a.corpus = %s AND a.status = 'active'
                  AND a.claim_kind = ANY(%s)
                  AND a.embedding IS NOT NULL AND a.asserted_at IS NOT NULL
            ON CONFLICT DO NOTHING
            """,
            (corpus, lo, hi, limit_per, corpus, list(REPLACING)),
        )
        n = cur.rowcount
    conn.commit()
    return n


def trust_correction(conn, corpus: str = "guru", band: float = 0.80) -> list[Superseded]:
    """Rule 4 — a higher-trust claim corrects lower-trust ones on the same subject.

    `trust.outranks()` was written in P0.1 and never wired into supersession, which
    left the system unable to do the one thing capture exists for: a human states
    that a practice ended, and eight stale documents go on asserting it.

    Similarity alone cannot express this. The stale records are not duplicates of
    the correction and they are not the same claim kind, so neither the duplicate
    rule nor the conflict rule touches them. What connects them is *provenance*: a
    human-asserted practice outranks a model's reading of a document, so the later
    high-trust claim ends the earlier low-trust ones.

    Scoped to claims captured through `assert`, not to human trust generally. A first
    pass keyed on trust alone superseded 2,025 claims from a single correction,
    because bench measurements also carry human trust — and a measurement is not a
    correction. What licenses this rule is the deliberate act of capture: someone
    stating that something has changed. Provenance is a licence to correct, not a
    licence to delete broadly.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT b.id, a.id, a.asserted_at
            FROM claims a
            JOIN LATERAL (
                SELECT c.id
                FROM claims c
                WHERE c.corpus = a.corpus AND c.status = 'active'
                      AND c.id <> a.id AND c.embedding IS NOT NULL
                      AND c.trust <> 'human'
                      AND c.asserted_at < a.asserted_at
                      AND 1 - (c.embedding <=> a.embedding) >= %s
            ) b ON true
            JOIN events e ON e.id = a.event_id
            WHERE a.corpus = %s AND a.status = 'active'
                  AND e.source = 'assert' AND a.claim_kind = ANY(%s)
                  AND a.embedding IS NOT NULL AND a.asserted_at IS NOT NULL
            """,
            (band, corpus, list(REPLACING)),
        )
        return [Superseded(old, new, "trust_correction", ts) for old, new, ts in cur.fetchall()]


def apply(supersessions: list[Superseded], conn, dry_run: bool = False) -> int:
    if dry_run:
        return len(supersessions)
    n = 0
    with conn.cursor() as cur:
        for s in supersessions:
            cur.execute(
                """
                UPDATE claims
                SET status = 'superseded',
                    superseded_by = %s,
                    valid_to = COALESCE(valid_to, %s),
                    meta = meta || jsonb_build_object('superseded_rule', %s::text)
                WHERE id = %s AND status = 'active'
                """,
                (s.new_id, s.valid_to, s.rule, s.old_id),
            )
            n += cur.rowcount
    conn.commit()
    return n


RULES = (
    # metric_restatement deliberately absent — see its docstring.
    ("revision_removal", revision_removal),
    ("near_duplicate", near_duplicates),
    ("trust_correction", trust_correction),
)


def run(corpus: str = "guru", dry_run: bool = False) -> dict:
    conn = connect()
    report = {}
    for name, fn in RULES:
        found = fn(conn, corpus)
        applied = apply(found, conn, dry_run)
        report[name] = {"found": len(found), "applied": applied}
    # Conflicts are opened, never resolved automatically: this band is exactly where
    # a machine cannot distinguish a changed mind from a different remark.
    report["conflicts_opened"] = {
        "found": 0 if dry_run else conflict_candidates(conn, corpus), "applied": 0
    }
    conn.close()
    return report
