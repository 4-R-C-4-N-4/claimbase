"""Run the teacher over prose events and store the claims.

Resumable by construction: an event recorded in extraction_progress for this
extractor version is skipped, so an interrupted run costs only the passage in
flight. That matters at ~7s/passage over ~1,800 events. Progress is recorded
only for responses that parsed — an unparseable response is retried next run,
never silently recorded as read (migrations/006_extraction_progress.sql).

Sub-threshold extractions land in `claims_review`, never in `claims` — precision
over recall, because a hallucinated claim is worse than a missing one.
"""

from __future__ import annotations

import argparse
import json
import os
import time
import uuid

from .core.store import connect
from .extract import EXTRACTOR_VERSION, SYSTEM, TEACHER_MODEL, extract, parsed_ok

# Sources whose content is prose worth extracting from. run_artifacts is tabular
# and git_log is one-line subjects already captured structurally; neither has
# prose for a model to read.
PROSE_SOURCES = ("markdown_docs", "todo_store", "pull_requests", "agent_memory")

THRESHOLD = 0.6

# Pending = prose the current extractor version has not READ, per
# extraction_progress — not "has no surviving claims", which re-extracted every
# legitimately-empty event forever. Shared with `claimbase status` so the count
# it reports and the work this run selects can never disagree.
PENDING_SQL = """
    SELECT e.id, e.content, e.captured_at
    FROM events e
    WHERE e.corpus = %s AND e.source = ANY(%s) AND length(e.content) >= %s
      AND NOT EXISTS (
        SELECT 1 FROM extraction_progress p
        WHERE p.event_id = e.id AND p.version = %s
      )
    ORDER BY length(e.content) DESC
"""


def pending_events(conn, corpus: str, min_len: int = 200):
    with conn.cursor() as cur:
        cur.execute(PENDING_SQL, (corpus, list(PROSE_SOURCES), min_len, EXTRACTOR_VERSION))
        return cur.fetchall()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default="guru")
    ap.add_argument("--limit", type=int, default=0, help="0 = all pending")
    ap.add_argument("--min-len", type=int, default=200)
    args = ap.parse_args(argv)

    conn = connect()
    pending = pending_events(conn, args.corpus, args.min_len)
    if args.limit:
        pending = pending[: args.limit]

    # Record the run BEFORE extracting, so an interrupted run still leaves a
    # traceable identity for the claims it did write. Without this a scoreboard
    # cannot be attributed to the corpus that produced it, and two runs of the same
    # code look like a regression (findings.md, 2026-08-11).
    import hashlib

    run_id = uuid.uuid4()
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO extractor_runs (id, corpus, version, model, temperature,
                   seed, prompt_sha, n_events, meta)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (run_id, args.corpus, EXTRACTOR_VERSION, TEACHER_MODEL,
             float(os.environ.get("TEMP", 0.2)),
             int(os.environ["SEED"]) if os.environ.get("SEED") else None,
             hashlib.sha256(SYSTEM.encode()).hexdigest()[:16],
             len(pending), json.dumps({"min_len": args.min_len})),
        )
    conn.commit()

    print(f"  {len(pending)} events pending for {EXTRACTOR_VERSION} (run {str(run_id)[:8]})",
          flush=True)
    t0, kept, held, failed = time.time(), 0, 0, 0

    for i, (eid, content, captured_at) in enumerate(pending, 1):
        try:
            claims, raw = extract(content)
        except Exception as e:
            failed += 1
            print(f"    {i}/{len(pending)}  ERROR {type(e).__name__}: {e}", flush=True)
            continue

        # No well-formed array in the response: retry next run, never record it
        # as read — recording it would be the silent gap, not the retry.
        if not claims and not parsed_ok(raw):
            failed += 1
            print(f"    {i}/{len(pending)}  unparseable response, will retry", flush=True)
            continue

        with conn.cursor() as cur:
            for c in claims:
                if c.confidence < THRESHOLD:
                    cur.execute(
                        """INSERT INTO claims_review (id, corpus, event_id, content,
                               claim_kind, confidence, reason, meta)
                           VALUES (%s,%s,%s,%s,%s,%s,'below_threshold',%s)""",
                        (uuid.uuid4(), args.corpus, eid, c.content, c.kind,
                         c.confidence, json.dumps({"extractor_version": EXTRACTOR_VERSION})),
                    )
                    held += 1
                    continue
                cur.execute(
                    """INSERT INTO claims (id, corpus, event_id, content, claim_kind,
                           trust, corroborated, asserted_at, valid_from, confidence,
                           status, run_id, meta)
                       VALUES (%s,%s,%s,%s,%s,'agent',false,%s,%s,%s,'active',%s,%s)""",
                    (uuid.uuid4(), args.corpus, eid, c.content, c.kind,
                     captured_at, captured_at, c.confidence, run_id,
                     json.dumps({"extractor_version": EXTRACTOR_VERSION, "extracted": True,
                                 "run_id": str(run_id)})),
                )
                kept += 1
            cur.execute(
                """INSERT INTO extraction_progress (event_id, version, run_id, n_claims)
                   VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (eid, EXTRACTOR_VERSION, run_id, len(claims)),
            )
        conn.commit()

        if i % 25 == 0 or i == len(pending):
            el = time.time() - t0
            print(
                f"    {i}/{len(pending)}  kept {kept}  held {held}  failed {failed}  "
                f"{el / i:.1f}s/ev  eta {(el / i) * (len(pending) - i) / 60:.0f}m",
                flush=True,
            )

    with conn.cursor() as cur:
        cur.execute(
            "UPDATE extractor_runs SET finished_at = now(), n_claims = %s WHERE id = %s",
            (kept, run_id),
        )
    conn.commit()
    print(f"\n  done: kept {kept}, held {held}, failed {failed}, "
          f"{(time.time() - t0) / 60:.1f} min  (run {str(run_id)[:8]})", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
