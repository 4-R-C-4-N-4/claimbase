"""Postgres writes. Idempotent by construction.

Re-import must be free: `events` is uniquely keyed on `(corpus, content_hash)`, so a
second run inserts nothing and the adapters' stable rendering is what makes that
true. Derived rows hang off the event by id, so replacing an event's derivations is
a delete-and-reinsert rather than a diff.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict
from typing import Iterable

import psycopg

from .models import Claim, Edge, Event, Mention, SchemaType

DSN = os.environ.get("CLAIMBASE_DSN", "postgresql://claimbase:claimbase@localhost:5433/claimbase")


def connect(dsn: str | None = None) -> psycopg.Connection:
    return psycopg.connect(dsn or DSN, autocommit=False)


# Namespace for derived claim ids. Fixed forever: changing it re-keys the store.
_CLAIM_NS = uuid.UUID("6f1d3c0a-58a2-4c1e-9d55-c1a1b45e0001")


def stable_claim_id(event_id, kind, content: str) -> uuid.UUID:
    """A claim's identity, derived from what it says and where it came from.

    Adapter-derived claims used to get a fresh uuid4 on every import, because
    `replace_claims` deleted and re-inserted them. That was invisible while
    nothing referred to a claim by id. The memory layer does — an exposure, a
    retrieval hit and a PR target all name a claim — and a nightly compile
    would have orphaned every one of them. Same event, same kind, same text is
    the same claim, and now has the same id.
    """
    return uuid.uuid5(_CLAIM_NS, f"{event_id}|{kind}|{content}")


class Store:
    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    # --- writes ---------------------------------------------------------------

    def upsert_event(self, ev: Event) -> tuple[str, bool]:
        """Returns (event_id, inserted). On conflict the existing id wins, so a
        re-import reuses the row rather than orphaning its derivations."""
        with self.conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO events (id, corpus, source, source_ref, captured_at,
                                    content, content_hash, meta)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (corpus, content_hash) DO NOTHING
                RETURNING id
                """,
                (
                    ev.id,
                    ev.corpus,
                    ev.source,
                    ev.source_ref,
                    ev.captured_at,
                    ev.content,
                    ev.content_hash,
                    json.dumps(_jsonable(ev.meta)),
                ),
            )
            row = cur.fetchone()
            if row:
                return str(row[0]), True
            cur.execute(
                "SELECT id FROM events WHERE corpus = %s AND content_hash = %s",
                (ev.corpus, ev.content_hash),
            )
            return str(cur.fetchone()[0]), False

    def replace_claims(self, event_id: str, claims: Iterable[Claim]) -> int:
        """Replace only the claims THIS layer produced.

        The importer and the extractor both write claims against the same event, on
        different schedules and with different lifecycles. An unscoped delete here
        destroyed 7,520 teacher-extracted claims on the first re-import — 2h23m of
        GPU work — because the importer assumed it owned every claim on the event.

        Adapter-derived claims are cheap to rebuild and are replaced every run.
        Extractor-derived claims are expensive and survive, invalidated only by an
        extractor-version bump, which `extract_run` handles by its own WHERE clause.
        """
        # Rows an adapter did not produce are not this method's to touch: the
        # extractor's (expensive), and the memory layer's (a PR amendment or a
        # writer claim, which no re-import can regenerate).
        mine = "NOT (meta ? 'extractor_version') AND NOT (meta ? 'memory')"
        new = {}
        for c in claims:
            new.setdefault(stable_claim_id(event_id, str(c.kind), c.content), c)
        with self.conn.cursor() as cur:
            cur.execute("SELECT corpus FROM events WHERE id = %s", (event_id,))
            row = cur.fetchone()
            corpus = row[0] if row else "guru"
            cur.execute(f"SELECT id FROM claims WHERE event_id = %s AND {mine}", (event_id,))
            gone = [r[0] for r in cur.fetchall() if r[0] not in new]
            if gone:
                # A claim about to be deleted may have superseded others. The FK is
                # ON DELETE SET NULL so the delete succeeds, but that would leave
                # those claims marked `superseded` while pointing at nothing — a
                # state where recall hides them and no rule will ever reconsider
                # them. Revert them to active first and let supersession decide
                # again.
                cur.execute(
                    """UPDATE claims SET status = 'active', superseded_by = NULL,
                              valid_to = NULL, meta = meta - 'superseded_rule'
                        WHERE superseded_by = ANY(%s)""",
                    (gone,),
                )
                cur.execute("DELETE FROM claims WHERE id = ANY(%s)", (gone,))
            n = 0
            for cid, c in new.items():
                # Unchanged claims are kept in place rather than re-inserted, so
                # what the store has learned about them survives a re-import:
                # status, the supersession link, the embedding, exposures, and
                # any PR that targeted them. Only what the adapter owns is
                # refreshed.
                cur.execute(
                    """
                    INSERT INTO claims (id, corpus, event_id, subject_text, predicate,
                        content, valid_from, valid_to, asserted_at, status, confidence,
                        claim_kind, trust, corroborated, meta)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (id) DO UPDATE SET
                        subject_text = EXCLUDED.subject_text,
                        predicate    = EXCLUDED.predicate,
                        valid_from   = EXCLUDED.valid_from,
                        valid_to     = CASE WHEN claims.status = 'active'
                                            THEN EXCLUDED.valid_to ELSE claims.valid_to END,
                        asserted_at  = EXCLUDED.asserted_at,
                        confidence   = EXCLUDED.confidence,
                        trust        = EXCLUDED.trust,
                        corroborated = EXCLUDED.corroborated,
                        meta         = EXCLUDED.meta || CASE
                                         WHEN claims.meta ? 'superseded_rule'
                                         THEN jsonb_build_object('superseded_rule',
                                                                 claims.meta->'superseded_rule')
                                         ELSE '{}'::jsonb END
                    """,
                    (
                        cid,
                        corpus,
                        event_id,
                        c.subject,
                        c.predicate,
                        c.content,
                        c.valid_from,
                        c.valid_to,
                        c.asserted_at,
                        str(c.status),
                        c.confidence,
                        str(c.kind),
                        str(c.trust),
                        c.corroborated,
                        json.dumps(_jsonable(c.meta)),
                    ),
                )
                n += 1
            return n

    def add_edges(self, corpus: str, edges: Iterable[Edge]) -> int:
        with self.conn.cursor() as cur:
            n = 0
            for e in edges:
                cur.execute(
                    """
                    INSERT INTO edges (corpus, src_id, dst_id, rel, weight, meta)
                    VALUES (%s, md5(%s)::uuid, md5(%s)::uuid, %s, %s, %s)
                    ON CONFLICT DO NOTHING
                    """,
                    (corpus, e.src, e.dst, e.rel, e.weight, json.dumps({"src": e.src, "dst": e.dst})),
                )
                n += cur.rowcount
            return n

    def add_mentions(self, corpus: str, mentions: Iterable[Mention]) -> int:
        """Phase 0 records mentions as entities with no resolution: the surface form
        is the identity. Phase 1's resolver is what makes this a real entity table."""
        with self.conn.cursor() as cur:
            n = 0
            for m in mentions:
                cur.execute(
                    """
                    INSERT INTO entities (id, corpus, canonical_name, entity_type)
                    VALUES (gen_random_uuid(), %s, %s, %s)
                    ON CONFLICT (corpus, canonical_name) DO NOTHING
                    """,
                    (corpus, m.text[:500], m.entity_type),
                )
                n += cur.rowcount
            return n

    def add_schema_types(self, corpus: str, types: Iterable[SchemaType]) -> int:
        with self.conn.cursor() as cur:
            n = 0
            for t in types:
                cur.execute(
                    """
                    INSERT INTO schema_types (id, corpus, kind, name, source, status, uses, spec)
                    VALUES (gen_random_uuid(), %s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (corpus, kind, name)
                    DO UPDATE SET uses = GREATEST(schema_types.uses, EXCLUDED.uses)
                    """,
                    (corpus, t.kind, t.name, t.source, t.status, t.uses, json.dumps(t.spec)),
                )
                n += cur.rowcount
            return n

    # --- reads ----------------------------------------------------------------

    def stats(self, corpus: str = "guru") -> dict:
        q = {
            "events": "SELECT count(*) FROM events WHERE corpus=%s",
            "claims": "SELECT count(*) FROM claims WHERE corpus=%s",
            "entities": "SELECT count(*) FROM entities WHERE corpus=%s",
            "edges": "SELECT count(*) FROM edges WHERE corpus=%s",
            "schema_types": "SELECT count(*) FROM schema_types WHERE corpus=%s",
            "dated_endings": "SELECT count(*) FROM claims WHERE corpus=%s AND valid_to IS NOT NULL",
        }
        out = {}
        with self.conn.cursor() as cur:
            for k, sql in q.items():
                cur.execute(sql, (corpus,))
                out[k] = cur.fetchone()[0]
            cur.execute(
                "SELECT source, count(*) FROM events WHERE corpus=%s GROUP BY source ORDER BY 2 DESC",
                (corpus,),
            )
            out["by_source"] = dict(cur.fetchall())
            cur.execute(
                "SELECT claim_kind, count(*) FROM claims WHERE corpus=%s GROUP BY claim_kind ORDER BY 2 DESC",
                (corpus,),
            )
            out["by_kind"] = dict(cur.fetchall())
            cur.execute(
                "SELECT trust, count(*) FROM claims WHERE corpus=%s GROUP BY trust ORDER BY 2 DESC",
                (corpus,),
            )
            out["by_trust"] = dict(cur.fetchall())
        return out


def _jsonable(d: dict) -> dict:
    """meta carries datetimes and nested source payloads; keep it storable without
    letting an adapter's raw record shape reach the column."""
    out = {}
    for k, v in (d or {}).items():
        if k == "raw":
            continue  # the original record is in `content`; storing it twice invites drift
        try:
            json.dumps(v)
            out[k] = v
        except TypeError:
            out[k] = str(v)
    return out
