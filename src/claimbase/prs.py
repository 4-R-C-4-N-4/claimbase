"""Memory PRs — the only way a standing claim changes.

A claim stands until it is refuted, and every refutation is a PR that merges at
once (RFC, Change over time). No queue, no approval step: the amendment becomes
the standing claim, the old version gets an end date and a link to what
replaced it, and the amendment is itself open to refutation.

Three rules keep "merges at once" from meaning "anything can overwrite
anything":

1. **An amendment takes the trust of its evidence.** A PR backed by the user's
   own turn carries human trust; one backed only by an agent's reading carries
   agent trust. This is the existing kind cap (`core/trust.py`) applied to a
   new write path, not a new mechanism.

2. **Evidence that the target outranks does not supersede it.** If an agent's
   reading disagrees with something a human stated, the human's claim keeps
   being served — marked `contested`, with the amendment kept beside it as
   `tentative`, and both on the exception report. Nothing waits for a person
   and nothing a model merely read overwrites what a person said. Without this
   rule any fetched page could rewrite memory by asserting something.

3. **A PR never crosses projects.** A claim in one project cannot refute a
   claim in another.

Undoing is another PR. A revert does not roll anything back in place: it files
a new version carrying the earlier text, which supersedes the amendment. The
history then reads as it happened — believed A, believed B, believed A again —
and a belief that keeps flipping is marked `contested` rather than left to
oscillate silently.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from .core.models import Claim, Event, Kind, Trust
from .core.store import Store
from .core.trust import apply_cap

KINDS = ("correction", "source_mismatch", "narrowing", "revert", "consolidation")
AUTHORS = ("user", "agent", "writer", "verifier")

_RANK = {Trust.HUMAN: 3, Trust.AGENT_GATED: 2, Trust.AGENT: 1, Trust.UNKNOWN: 0}

# What an author's bare say-so is worth when no better evidence is attached. A
# writer PR must state its evidence trust explicitly: it files on behalf of
# whatever the episode was, and that differs per episode.
_AUTHOR_TRUST = {"user": Trust.HUMAN, "agent": Trust.AGENT, "verifier": Trust.AGENT_GATED}

# More merged changes than this to one belief inside the window and it is
# flip-flopping: two sources amending each other back and forth.
OSCILLATION_WINDOW = timedelta(days=30)
OSCILLATION_MAX = 3


class PRError(ValueError):
    pass


@dataclass(slots=True)
class PR:
    id: str
    outcome: str  # merged | contested
    corpus: str
    target: str  # the claim version the PR actually landed against
    amendment_claim: str
    kind: str
    refiled: bool = False  # the named target had already been superseded
    oscillating: bool = False
    amendment_kind: str = ""
    amendment_trust: str = ""

    def summary(self) -> str:
        bits = [f"PR {self.id[:8]} {self.outcome}", self.kind,
                f"{self.amendment_kind}/{self.amendment_trust}"]
        if self.refiled:
            bits.append("re-filed against current version")
        if self.oscillating:
            bits.append("claim now contested: repeated reversals")
        return " · ".join(bits)


_COLS = "id, corpus, content, claim_kind, trust, status, superseded_by, level, meta"


def _claim(cur, claim_id) -> dict | None:
    cur.execute(f"SELECT {_COLS} FROM claims WHERE id = %s", (str(claim_id),))
    r = cur.fetchone()
    if r is None:
        return None
    return dict(zip([c.strip() for c in _COLS.split(",")], r))


def head_of(cur, claim_id) -> dict:
    """Follow supersession to the version currently standing.

    With instant merge, a conflict is a PR filed against a version that has
    since been replaced. It is re-filed against the current one rather than
    rejected — the author's evidence is about the belief, not about a row id.
    """
    row = _claim(cur, claim_id)
    if row is None:
        raise PRError(f"no claim {claim_id}")
    seen = {row["id"]}
    while row["status"] == "superseded" and row["superseded_by"]:
        nxt = _claim(cur, row["superseded_by"])
        if nxt is None or nxt["id"] in seen:
            break
        seen.add(nxt["id"])
        row = nxt
    return row


def _lineage(cur, claim_id) -> uuid.UUID:
    cur.execute(
        "SELECT lineage FROM memory_prs WHERE amendment_claim = %s ORDER BY merged_at LIMIT 1",
        (claim_id,),
    )
    r = cur.fetchone()
    return r[0] if r else claim_id


def open_pr(
    conn,
    *,
    target,
    amendment: str,
    kind: str = "correction",
    author: str = "user",
    corpus: str | None = None,
    evidence_event=None,
    evidence_text: str | None = None,
    evidence_trust: Trust | str | None = None,
    distilled: bool = False,
    amendment_kind: str | None = None,
    reverts=None,
    embed=None,
    now: datetime | None = None,
    meta: dict | None = None,
) -> PR:
    """File a memory PR. It merges, or contests, immediately. Does not commit.

    target           the claim to amend (any version; the head is found)
    evidence_event   an existing episode that backs the amendment, or
    evidence_text    text to record as the evidence event
    evidence_trust   whose word the evidence is; defaults from `author`
    distilled        the amendment's wording is a model's rendering of the
                     evidence rather than the evidence itself — it then enters
                     at most human-gated, however good the evidence was
    embed            text -> vector; without it the amendment is stored
                     unembedded and `claimbase embed` picks it up
    """
    amendment = (amendment or "").strip()
    if not amendment:
        raise PRError("a PR needs an amendment")
    if kind not in KINDS:
        raise PRError(f"unknown PR kind {kind!r}; one of {KINDS}")
    if author not in AUTHORS:
        raise PRError(f"unknown author {author!r}; one of {AUTHORS}")
    if evidence_trust is None:
        if author not in _AUTHOR_TRUST:
            raise PRError("a writer PR must state the trust of its evidence")
        evidence_trust = _AUTHOR_TRUST[author]
    evidence_trust = Trust(evidence_trust)
    now = now or datetime.now(timezone.utc)
    pr_id = uuid.uuid4()

    with conn.cursor() as cur:
        named = _claim(cur, target)
        if named is None:
            raise PRError(f"no claim {target}")
        if corpus and named["corpus"] != corpus:
            raise PRError(
                f"claim {str(target)[:8]} belongs to project {named['corpus']!r}, not "
                f"{corpus!r}; a PR never crosses projects"
            )
        head = head_of(cur, target)
        corpus = head["corpus"]
        if head["status"] not in ("active", "contested", "tentative"):
            raise PRError(f"claim {str(head['id'])[:8]} is {head['status']}; nothing to amend")
        if head["content"].strip() == amendment and kind != "revert":
            raise PRError("the amendment says what the claim already says")

        if evidence_event is None:
            ev = Event(
                source="memory_pr", corpus=corpus,
                source_ref=f"pr:{author}:{now:%Y-%m-%dT%H:%M:%SZ}:{str(pr_id)[:8]}",
                content=f"[pr {pr_id} · {kind} · {author}]\n{evidence_text or amendment}",
                captured_at=now, meta={"author": author, "pr": str(pr_id)},
            )
            evidence_event, _ = Store(conn).upsert_event(ev)

        # Rule 1: the amendment's own trust. A model's wording of what a human
        # said is the human-gated tier's definition.
        a_trust = evidence_trust
        if distilled and _RANK[a_trust] > _RANK[Trust.AGENT_GATED]:
            a_trust = Trust.AGENT_GATED
        try:
            a_kind = Kind(amendment_kind or head["claim_kind"])
        except ValueError:
            a_kind = Kind.OBSERVATION
        capped = apply_cap(Claim(
            event_id=evidence_event, content=amendment, kind=a_kind, trust=a_trust,
            asserted_at=now, valid_from=now,
            # Backed by an episode or a quoted passage — something outside the
            # author's own prose stands behind it.
            corroborated=_RANK[evidence_trust] >= _RANK[Trust.AGENT_GATED],
        ))

        # Rule 2: does the evidence get to supersede this target?
        merged = _RANK[evidence_trust] >= _RANK[Trust(head["trust"])]
        outcome = "merged" if merged else "contested"

        origin = ("stated" if evidence_trust == Trust.HUMAN
                  else "observed" if author == "verifier" else "inferred")
        a_id = uuid.uuid4()
        vec = None
        if embed is not None:
            try:
                vec = str(embed(amendment))
            except Exception:
                vec = None  # an embedder that is down must not block a merge
        cur.execute(
            """INSERT INTO claims (id, corpus, event_id, content, claim_kind, trust,
                   corroborated, asserted_at, valid_from, confidence, status, origin,
                   level, merged_by, embedding, meta)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (a_id, corpus, evidence_event, amendment, str(capped.kind), str(capped.trust),
             capped.corroborated, now, now, 0.8,
             "active" if merged else "tentative", origin, head["level"], pr_id, vec,
             json.dumps({"memory": True, "pr": str(pr_id), "pr_kind": kind,
                         **capped.meta, **(meta or {})})),
        )
        if merged:
            cur.execute(
                """UPDATE claims SET status = 'superseded', superseded_by = %s, valid_to = %s,
                          meta = meta || %s
                    WHERE id = %s""",
                (a_id, now, json.dumps({"superseded_rule": "memory_pr", "pr": str(pr_id)}),
                 head["id"]),
            )
        else:
            cur.execute(
                "UPDATE claims SET status = 'contested', meta = meta || %s WHERE id = %s",
                (json.dumps({"contested_by": str(pr_id), "contested_reason": "outranked"}),
                 head["id"]),
            )

        lineage = _lineage(cur, head["id"])
        cur.execute(
            """INSERT INTO memory_prs (id, corpus, target_claim, amendment_claim, lineage,
                   amendment, kind, author, evidence_event, evidence_trust, outcome,
                   reverts, merged_at, meta)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (pr_id, corpus, head["id"], a_id, lineage, amendment, kind, author,
             evidence_event, str(evidence_trust), outcome, reverts, now,
             json.dumps({"refiled_from": str(named["id"])} if named["id"] != head["id"]
                        else {})),
        )

        # A belief reversed too often in a window is not settled by the latest
        # reversal. Its newest version is still served — with a label.
        oscillating = False
        if merged:
            cur.execute(
                """SELECT count(*) FROM memory_prs
                    WHERE lineage = %s AND outcome = 'merged' AND merged_at > %s""",
                (lineage, now - OSCILLATION_WINDOW),
            )
            if cur.fetchone()[0] > OSCILLATION_MAX:
                oscillating = True
                cur.execute(
                    "UPDATE claims SET status = 'contested', meta = meta || %s WHERE id = %s",
                    (json.dumps({"contested_reason": "oscillation"}), a_id),
                )

    return PR(
        id=str(pr_id), outcome=outcome, corpus=corpus, target=str(head["id"]),
        amendment_claim=str(a_id), kind=kind, refiled=named["id"] != head["id"],
        oscillating=oscillating, amendment_kind=str(capped.kind),
        amendment_trust=str(capped.trust),
    )


def revert(conn, pr_id, *, author: str = "user", reason: str | None = None,
           evidence_trust: Trust | str | None = None, embed=None,
           now: datetime | None = None) -> PR:
    """Undo a PR by filing another.

    For a merged PR: a new version carrying the pre-PR text supersedes whatever
    currently stands in that lineage. For a contested PR — one that never
    superseded anything — the contest is closed: the target stands again and
    the amendment is retracted.
    """
    now = now or datetime.now(timezone.utc)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT p.id, p.corpus, p.target_claim, p.amendment_claim, p.outcome, p.lineage,
                      t.content, t.claim_kind
                 FROM memory_prs p LEFT JOIN claims t ON t.id = p.target_claim
                WHERE p.id::text LIKE %s""",
            (f"{pr_id}%",),
        )
        rows = cur.fetchall()
        if not rows:
            raise PRError(f"no PR {pr_id}")
        if len(rows) > 1:
            raise PRError(f"PR id {pr_id!r} is ambiguous ({len(rows)} matches)")
        pid, corpus, target, amend, outcome, lineage, old_text, old_kind = rows[0]
        if target is None or amend is None or old_text is None:
            raise PRError("that PR's claims no longer exist; nothing to restore")
        cur.execute("SELECT 1 FROM memory_prs WHERE reverts = %s", (pid,))
        if cur.fetchone():
            raise PRError(f"PR {str(pid)[:8]} has already been reverted")

        if outcome == "contested":
            trust = Trust(evidence_trust or _AUTHOR_TRUST.get(author, Trust.AGENT))
            new_id = uuid.uuid4()
            cur.execute(
                """UPDATE claims SET status = 'active',
                          meta = (meta - 'contested_by') - 'contested_reason'
                    WHERE id = %s AND status = 'contested'""", (target,))
            cur.execute(
                "UPDATE claims SET status = 'retracted', valid_to = %s WHERE id = %s",
                (now, amend))
            ev = Event(
                source="memory_pr", corpus=corpus,
                source_ref=f"pr:{author}:{now:%Y-%m-%dT%H:%M:%SZ}:{str(new_id)[:8]}",
                content=f"[pr {new_id} · revert · {author}]\n{reason or 'contest closed'}",
                captured_at=now, meta={"author": author, "pr": str(new_id)},
            )
            eid, _ = Store(conn).upsert_event(ev)
            cur.execute(
                """INSERT INTO memory_prs (id, corpus, target_claim, amendment_claim, lineage,
                       amendment, kind, author, evidence_event, evidence_trust, outcome,
                       reverts, merged_at)
                   VALUES (%s,%s,%s,%s,%s,%s,'revert',%s,%s,%s,'merged',%s,%s)""",
                (new_id, corpus, amend, target, lineage, old_text, author, eid,
                 str(trust), pid, now))
            return PR(id=str(new_id), outcome="merged", corpus=corpus, target=str(amend),
                      amendment_claim=str(target), kind="revert",
                      amendment_kind=old_kind, amendment_trust=str(trust))

    return open_pr(
        conn, target=amend, amendment=old_text, kind="revert", author=author,
        corpus=corpus, evidence_text=reason or f"revert of PR {pid}",
        evidence_trust=evidence_trust, amendment_kind=old_kind, reverts=pid,
        embed=embed, now=now,
    )


def list_prs(conn, corpus: str | None = None, limit: int = 20) -> list[dict]:
    with conn.cursor() as cur:
        cur.execute(
            """SELECT p.id, p.corpus, p.kind, p.author, p.outcome, p.merged_at,
                      p.evidence_trust, p.reverts, t.content, p.amendment,
                      EXISTS (SELECT 1 FROM memory_prs r WHERE r.reverts = p.id)
                 FROM memory_prs p LEFT JOIN claims t ON t.id = p.target_claim
                WHERE (%s::text IS NULL OR p.corpus = %s)
                ORDER BY p.merged_at DESC LIMIT %s""",
            (corpus, corpus, limit),
        )
        return [
            {"id": str(r[0]), "project": r[1], "kind": r[2], "author": r[3],
             "outcome": r[4], "at": r[5].isoformat() if r[5] else None,
             "evidence_trust": r[6], "reverts": str(r[7]) if r[7] else None,
             "was": r[8], "now": r[9], "reverted": r[10]}
            for r in cur.fetchall()
        ]
