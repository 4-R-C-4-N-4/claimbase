# Memory Evaluation Improvements Implementation Plan

> For Hermes: use subagent-driven-development with TDD; implement serially on rfc/harness-memory. The original execution restriction on commits/pushes was superseded by the owner's explicit PR-publication request after the sandbox completed. Live-store migration and normal-profile changes remain unauthorized.

Goal: evaluate whether memory helps tasks without asking the working agent to certify its own use.

Architecture: retain the existing session/spool/writer and read-only MCP boundaries. Treat delivery, weak inferred use, explicit feedback, and externally verified outcomes as distinct evidence. A passing artifact check establishes rule compliance, not causal use of a particular memory. Missing attribution is unknown, not proof of a miss. Every acceptance check is independently executable.

Tech stack: existing Python/psycopg/Postgres/pytest and isolated Hermes + local Bonsai; no hosted judge or external service. A job-local stdio filesystem helper supplies equal confined rename/delete capabilities to both arms.

Baseline: five prior sandbox/scoping regression tests; isolated-HOME suite 171 passed, 2 skipped with tests/test_mcp_sandbox.py excluded. Prior real experiment: 1/3 control, 3/3 memory, but zero lexical-use signals. Existing uncommitted changes are intentional and must be preserved.

## Decisions

- Deliver phases in the order below, verifying each before advancing.
- Do not lower the lexical threshold to fit the three examples, or count prose claims of compliance as independent verification.
- Report artifact success separately from inferred use and explicit helpful feedback. Unknown attribution remains visible.
- Identity joins must be exact, project-safe, and harness-qualified. Never associate by a coincident timestamp or assume a long-lived MCP process is one agent session. Legacy unresolvable identities remain unknown.
- Persist each trial, control and memory outcome, checker evidence, session IDs, model settings, and errors. Do not overwrite prior reports or silently omit failures.
- Sandbox checks may be schema-driven but must not execute arbitrary commands from scenario data. Independent code correctness checks belong in trusted runner code.
- Real-project shadow work is local capture/redaction/proposals only. It does not install hooks into normal profiles, inject memory into active work, alter source projects, or write to the live database.

## Phase 1: Honest measurement states

Files: src/claimbase/usage.py, memory_cli.py, writer.py; additive scratch migration if required; tests/test_memory_reads.py and new evidence tests.

1. Write red-first tests: nonempty delivery with no use signal is unknown; assistant saying 'I used this' is not verified; a genuine independent pass/fail outcome is separate from use; failed task is not automatically a retrieval miss; recording an outcome is idempotent and cross-project associations are rejected.
2. Implement a minimal typed/validated independent-outcome record path on the writer/CLI side, never an unrestricted MCP write. Evidence includes exact session, project, checker identifier, pass/fail and artifact evidence. Do not infer a causal claim association.
3. Report delivery, inferred use, explicit feedback and outcome counts separately in JSON and CLI. Correct the miss denominator: no lexical match alone is not a known miss. Keep historical interfaces where feasible but label their meanings honestly.
4. Run focused tests then the isolated-HOME suite. Do not tune the lexical matcher.

Acceptance: a transcript can have a verified passing outcome and zero inferred uses without being labelled a known miss.

## Phase 2: Exact session attribution

Files: usage.py, writer.py, sessions.py, mcp_server.py, memory_cli.py, tests of capture/MCP/usage; additive migration if needed.

1. Red-first concurrent-session test: same project, same claim, same time window; a signal from A must not credit B. Test identical raw session IDs under different harnesses, legacy unidentified traffic, and cross-project traffic.
2. Carry harness-qualified identity through hook delivery/capture and MCP transport when available. Use transport metadata or harness-owned configuration, not model assertions or a mutable process-global 'current session'. Preserve raw IDs for inspection; unresolved shared-process traffic is unknown.
3. Exact-match coverage, exposure, feedback and outcome joins. Exclude inferred exposures from 'verified' counts.
4. Focused and full isolated tests; verify an actual hook-to-spool-to-usage flow.

Acceptance: no time-window/session crossover; existing history remains readable without guessed attribution.

## Phase 3: Stronger and repeatable sandbox

Files: eval/sandbox_hermes.py, eval/sandbox/scenarios.toml, trusted checker helpers and tests.

- Validate report contents, parse TOML (not substring checks), check generated defaults unchanged, execute the tiny Python function checks independently in a constrained child, and verify changelog placement.
- Add changed-rule, opposite-project, one-off exception, irrelevant-memory and untrusted-evidence scenarios. Do not embed expected rules in the probe prompt or accessible fixtures.
- Repetition support with a bounded selectable trial count; preserve per-trial model settings, session IDs, completion/error states and checker evidence under unique run directories. Fail fast on plumbing errors; count attempted failed trials rather than cherry-picking.
- Record independent outcomes through phase 1's API. Baselines use the same task capability and checker conditions.
- Run deterministic checker/lifecycle regressions before GPU execution. Run the complete expanded scenario set against real Hermes/Bonsai at least once; run a repeated subset and report sample size without claims of statistical significance.

Acceptance: supersession, project isolation, transient instructions, noise and role trust are exercised by unconditional assertions, not just configured as scenario names.

## Phase 4: Retrieval pressure

Files: sandbox runner/scenarios, brief/recall tests (production ranking changes only if evidence demands).

- Seed clearly labelled fixture claims with provenance, unrelated distractors and superseded variants; fixed-budget brief. Distinguish intentionally seeded retrieval fixtures from claims learned through the judge.
- Test relevant claim included versus omitted, then automatic recall recovery when omitted. Track supplied IDs, returned IDs, standing status, task outcome and prompt budget separately.
- Test stale claims never win; another project's claims never leak. Preserve all reports and denominator counts.
- Run deterministic selection tests and a real bounded pressure trial. Do not change ranking merely to force a particular seeded target into the brief.

Acceptance: demonstrate the behavior when the needed rule is absent from the brief, not just when all three claims fit.

## Phase 5: One real-project shadow evaluation

Files: safe eval/shadow CLI/helper, docs and tests. Use claimbase-memory as the initial real project; read actual recorded Hermes sessions, never credentials.

- Project-filter a bounded set of actual sessions from the canonical state database, read-only, through the existing redactor. Use unique scratch spool/database and isolated query log.
- Collect/judge proposed memories without injection, source edits, live memory merges, or profile configuration changes. Check retained claims against original role-tagged evidence. Record false retention/missed-correction audit examples honestly; model opinions alone are not ground truth.
- Exercise the shadow path on genuine sessions with the local judge and save proposal/evidence report. Insufficient representative sessions is a reported limit, not fabricated data or a reason to change projects silently.
- Stop task-started model servers/unload test embeddings; leave live services unchanged.

Acceptance: an actual proposal/evidence artifact from real work, alongside an explicit rollout gate still requiring daily-use evidence.

## Verification and progress

Run all DB-touching checks only against claimbase-test scratch databases on port 5434. Apply new additive migrations there only. Full gate: isolated HOME under $TMPDIR, .venv/bin/python -m pytest -q -rs --ignore=tests/test_mcp_sandbox.py, plus git diff --check and real local-model runs for phases 3–5. Preserve the original successful three-rule run as historical evidence. Update PROGRESS.md per phase and findings.md/GOALS.md with measured results, limitations and review status.

Review: use available Codex CLI (ChatGPT-authenticated); the default delegate provider previously returned HTTP 429. Obtain spec and quality reviews of the exact integrated changes, then independently execute the reported gates. A reviewer unavailable due to quota is recorded as pending, not passed.
