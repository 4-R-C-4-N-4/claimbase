import os
import sys
from pathlib import Path

# src layout without requiring an install step — the seam tests must run on a
# fresh checkout before anything is built.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# The MCP query log is testing data harvested from real agent traffic. Test
# traffic must not land in it (the sandbox probe already polluted the live
# store once — findings 2026-08-12). The MCP tests spawn the server with an
# inherited environment, so disabling here covers the subprocess too.
os.environ["CLAIMBASE_QUERY_LOG"] = ""

# --- scratch database --------------------------------------------------------
#
# The memory-layer tests write: they open PRs, supersede claims, run the
# writer. They get their own database (scripts/test_db.sh up) and skip when it
# is not there. They never see the live store — the DSN is refused unless it
# names a test database, because a truncate against the real one costs hours
# of extraction.

import hashlib
import math
import re
import uuid
from datetime import datetime, timezone

import pytest

TEST_DSN = os.environ.get(
    "CLAIMBASE_TEST_DSN", "postgresql://claimbase:claimbase@localhost:5434/claimbase_test"
)
TEST_RO_DSN = os.environ.get(
    "CLAIMBASE_TEST_RO_DSN", "postgresql://claimbase_ro:claimbase_ro@localhost:5434/claimbase_test"
)

_TABLES = (
    "session_receipts, usage_outcomes, triggers, memory_prs, exposures, feedback, retrieval_hits, retrieval_log, "
    "session_lookups, sessions, claim_entities, conflicts, claims_review, claims, "
    "entity_aliases, entities, edges, schema_types, extraction_progress, "
    "extractor_runs, events"
)


@pytest.fixture
def db():
    import psycopg

    assert "test" in TEST_DSN.rsplit("/", 1)[-1], "refusing to truncate a non-test database"
    try:
        conn = psycopg.connect(TEST_DSN, connect_timeout=2)
    except psycopg.OperationalError:
        pytest.skip("scratch database not up — scripts/test_db.sh up")
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE {_TABLES} CASCADE")
    conn.commit()
    yield conn
    conn.rollback()
    conn.close()


_WORD = re.compile(r"[a-z0-9_./-]+")


def fake_embed(text: str) -> list[float]:
    """A deterministic stand-in for the embedding model: hashed bag of words.
    Texts sharing vocabulary land close together, which is all the tests need
    and keeps them off Ollama and off the GPU."""
    v = [0.0] * 768
    for w in _WORD.findall(text.lower()):
        h = int.from_bytes(hashlib.md5(w.encode()).digest()[:4], "big")
        v[h % 768] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


@pytest.fixture
def embed(monkeypatch):
    """Route every embedding call in the package through the stand-in."""
    import claimbase.cli as cli

    monkeypatch.setattr(cli, "_embed_one", fake_embed)
    return fake_embed


def seed_claim(conn, content: str, *, corpus: str = "guru", kind: str = "practice",
               trust: str = "human", status: str = "active", source: str = "assert",
               asserted_at: datetime | None = None, meta: dict | None = None,
               origin: str | None = None) -> str:
    """One event and one embedded claim on it. Returns the claim id."""
    import json

    ts = asserted_at or datetime(2026, 9, 1, tzinfo=timezone.utc)
    eid, cid = uuid.uuid4(), uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO events (id, corpus, source, source_ref, captured_at, content,
                                   content_hash, meta)
               VALUES (%s,%s,%s,%s,%s,%s,%s,'{}')""",
            (eid, corpus, source, f"{source}:{str(eid)[:8]}", ts, content,
             hashlib.sha256(f"{eid}{content}".encode()).digest()),
        )
        cur.execute(
            """INSERT INTO claims (id, corpus, event_id, content, claim_kind, trust,
                   asserted_at, valid_from, status, origin, embedding, meta)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (cid, corpus, eid, content, kind, trust, ts, ts, status, origin,
             str(fake_embed(content)), json.dumps(meta or {})),
        )
    conn.commit()
    return str(cid)


def claim_row(conn, claim_id) -> dict:
    cols = "content, claim_kind, trust, status, superseded_by, valid_to, origin, merged_by, corpus, meta"
    with conn.cursor() as cur:
        cur.execute(f"SELECT {cols} FROM claims WHERE id = %s", (str(claim_id),))
        return dict(zip(cols.split(", "), cur.fetchone()))
