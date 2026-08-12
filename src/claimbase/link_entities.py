"""Link claims to the entities they mention, and expose the same matcher to queries.

Resolution alone changed nothing: a clean entity table that no query path consults
is bookkeeping. This is the part that makes it matter — a claim about
`retriever.ts` and a claim about `guru-web/src/lib/retriever.ts` become claims about
the *same* entity, and a question about guru-web can prefer them over claims about
`guru/retriever.py`.

Matching is by surface form against the alias table, not by embedding. That is the
point: embeddings put `retriever.ts` and `retriever.py` almost on top of each other,
which is precisely why q013 fails. Lexical identity is the signal similarity throws
away, and the alias table is what makes lexical identity survive path variation.
"""

from __future__ import annotations

import re

from .core.store import connect

# Tokens that could name a file or an identifier. Deliberately generous — a false
# candidate costs a dictionary lookup that misses; a missed one costs a link.
TOKEN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_./-]{3,79}")
REPOS = ("guru-web", "guru", "rellm")  # longest first: guru-web contains guru


def build_alias_map(conn, corpus: str = "guru") -> dict[str, str]:
    """surface form (lowercased) -> entity id.

    Both canonical names and aliases, so `retriever.ts`, `lib/retriever.ts` and
    `guru-web/src/lib/retriever.ts` all reach the same row.
    """
    out: dict[str, str] = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, canonical_name FROM entities WHERE corpus = %s", (corpus,)
        )
        for eid, name in cur.fetchall():
            out[name.lower()] = str(eid)
            # The canonical form is `repo:path`; the bare path should match too.
            if ":" in name:
                out[name.split(":", 1)[1].lower()] = str(eid)
        cur.execute(
            """SELECT a.alias, a.entity_id FROM entity_aliases a
               JOIN entities e ON e.id = a.entity_id WHERE e.corpus = %s""",
            (corpus,),
        )
        for alias, eid in cur.fetchall():
            out.setdefault(alias.lower(), str(eid))
    return out


def entities_in(text: str, alias_map: dict[str, str]) -> set[str]:
    """Entity ids named anywhere in `text`."""
    found = set()
    for m in TOKEN.finditer(text or ""):
        tok = m.group(0).lower().rstrip(".,;:)")
        if eid := alias_map.get(tok):
            found.add(eid)
    return found


def repos_in(text: str) -> set[str]:
    """Which projects a question is about, if it says.

    Cheap and load-bearing: q013 asks where *production* retrieval runs, naming
    guru-web rather than any file. Without this the question has no lexical hook at
    all and ranking falls back to similarity, which cannot separate the two
    retrievers.
    """
    low = (text or "").lower()
    out = set()
    for r in REPOS:
        if r in low:
            out.add(r)
            low = low.replace(r, "")  # so "guru-web" does not also match "guru"
    if "production" in low or "prod " in low:
        out.add("guru-web")  # production is guru-web; guru is the local pipeline
    return out


def run(corpus: str = "guru", batch: int = 2000) -> dict:
    conn = connect()
    alias_map = build_alias_map(conn, corpus)
    linked = scanned = 0
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, content, subject_text FROM claims WHERE corpus = %s", (corpus,)
        )
        rows = cur.fetchall()

    with conn.cursor() as cur:
        cur.execute("DELETE FROM claim_entities")
        for i, (cid, content, subject) in enumerate(rows, 1):
            scanned += 1
            for eid in entities_in(f"{content} {subject or ''}", alias_map):
                cur.execute(
                    "INSERT INTO claim_entities (claim_id, entity_id, via) "
                    "VALUES (%s,%s,'alias') ON CONFLICT DO NOTHING",
                    (cid, eid),
                )
                linked += cur.rowcount
            if i % batch == 0:
                conn.commit()
        conn.commit()

    with conn.cursor() as cur:
        cur.execute("SELECT count(DISTINCT claim_id) FROM claim_entities")
        claims_with = cur.fetchone()[0]
    conn.close()
    return {
        "alias_forms": len(alias_map),
        "claims_scanned": scanned,
        "claims_linked": claims_with,
        "links": linked,
    }
