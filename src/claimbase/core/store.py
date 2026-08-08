"""Postgres writes. Idempotent by construction.

Re-import must be free: `events` is uniquely keyed on `(corpus, content_hash)`, so a
second run inserts nothing and the adapters' stable rendering is what makes that
true. Derived rows hang off the event by id, so replacing an event's derivations is
a delete-and-reinsert rather than a diff.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from typing import Iterable

import psycopg

from .models import Claim, Edge, Event, Mention, SchemaType

DSN = os.environ.get("CLAIMBASE_DSN", "postgresql://claimbase:claimbase@localhost:5433/claimbase")


def connect(dsn: str | None = None) -> psycopg.Connection:
    return psycopg.connect(dsn or DSN, autocommit=False)


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
        with self.conn.cursor() as cur:
            cur.execute("DELETE FROM claims WHERE event_id = %s", (event_id,))
            n = 0
            for c in claims:
                cur.execute(
                    """
                    INSERT INTO claims (id, corpus, event_id, subject_text, predicate,
                        content, valid_from, valid_to, asserted_at, status, confidence,
                        claim_kind, trust, corroborated, meta)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    """,
                    (
                        c.id,
                        "guru",
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
