# Hermes + Bonsai sandbox notes — 2026-11-16

## Result

The expanded sandbox and three fresh subset trials completed with no execution
errors. The local model served as both working agent and writer's judge.

| Batch | Trials | No-memory task passes | Memory task passes | Memory collection passes | Execution errors |
|---|---:|---:|---:|---:|---:|
| smoke | 1 | 1/1 | 1/1 | 1/1 | 0 |
| full | 1 | 2/9 | 9/9 | 9/9 | 0 |
| repeated | 3 | 1/12 | 12/12 | 12/12 | 0 |

The smoke is kept separate, not pooled with the expanded/repeated denominators.
The subset comprises report naming, changed-rule supersession, and opposing
projects A/B. Each fresh subset trial passed all four memory task and collection
checks. Its control passes were 0/4, 0/4, and 1/4. An overall producer status of
`fail` reflects failed no-memory controls, not infrastructure failure; the
supervisor separately verifies completion and memory checks.

## Method and fairness

- Agent and judge: Ternary-Bonsai-2-27B-PQ2_0.gguf on the local llama.cpp Prism
  runtime, RTX 3090, 65,536-token context. Sampling metadata is in the evidence
  JSON. No hosted inference fallback or inherited cloud credentials.
- Teach a rule by correcting the agent in the same resumed session. Judge and
  collect the transcript; probe a different task in a fresh session and fresh
  project copy. The no-memory arm uses the same probe and trusted checker.
- Isolated Hermes homes and separate scratch memory/control databases. Hermes's
  built-in memory is off in both arms. No normal profile or live store changed.
- Both arms receive identical confined file capabilities, including dedicated
  MCP rename/delete tools. The memory arm additionally receives read-only recall
  and a session-start brief. Session-end capture is automatic, not model-attested.
- Hidden naming/configuration rules are absent from probe prompts and accessible
  fixtures. Neutral tool instructions are explicitly preloaded equally in both
  arms; ambient project rules remain suppressed.
- Task results come from trusted code outside the working copies: report paths
  and content, parsed TOML/default preservation, a restricted Python interpreter
  for generated functions, and changelog placement. Agent claims of success are
  not the checker.
- Collection checks independently cover standing practice, supersession,
  real own-scope delivery without foreign delivery, one-off exceptions, irrelevant
  memory, and forged tool-output instructions not becoming human authority.
- Delivery, inferred use, explicit feedback, and independent task outcomes are
  separate measurements. A passing artifact does not prove use of a particular
  claim; missing lexical overlap remains unknown, not a retrieval miss.

## What the real runs exposed

1. A judge-labelled preference was automatically widened to global `self` scope,
   even for a project-local correction. The writer now requires actual personal
   preference evidence and vetoes explicit local qualifiers. This conservative
   English-language guard is not a general semantic guarantee.
2. The sandbox asked Bonsai to rename files while offering replace-only patch
   and no terminal. V4A deletion is model-family-specific in Hermes, not an
   advertised Bonsai capability. The repaired sandbox supplies the same narrow,
   server-confined rename/delete tools to both arms; it does not open shell access.
3. `--ignore-rules` also suppresses SOUL.md. Neutral capability guidance now uses
   an explicit job-local skill, frozen at session creation and retained on resume.
4. Per-home dependency installs exhausted disk. A job-owned shared package cache
   permits hardlink reuse while session/config/runtime selections remain separate.
   The supervisor checks disk every ten seconds with a 10-GiB reserve.
5. Long runs were vulnerable to chat/process lifetime. A detached user-systemd
   supervisor owns the model and serial batches, with no overall timeout and
   bounded per-session guards. It records atomic status and stops its own server.
6. A success-only filesystem audit missed denied calls. The tools now flush an
   attempt before mutation, then append a matched success/error; an unavailable
   audit sink refuses before mutation. Traversal, symlinks, directories, and
   overwriting destinations are rejected server-side.

Failed, interrupted, and contaminated earlier runs were preserved separately,
not repaired or pooled into the successful comparison. The scope-contaminated
trial's 9/9 task outcomes but 6/9 combined checks are not a successful isolation
result. Likewise, the tool-capability and ENOSPC runs are not model-quality scores.

## Verification and evidence

- Last code gate: **284 passed, 2 skipped**, using isolated HOME and excluding
  `tests/test_mcp_sandbox.py`, which depends on the real/live corpus. The two
  skips and excluded file are not represented as executed coverage.
- Real stdio protocol tests verify the two-tool manifest, successful mutations,
  rejected escapes, denial logging, and refusal when audit output is unavailable.
- An independent confinement review approved with limits; its audit finding was
  fixed and regression-tested. External concurrent filesystem mutation remains
  outside the cooperative file-only agent threat model.
- Parent verification read all requested reports, checked denominators and
  collection assertions, and verified local/no-fallback configurations.
- Model shutdown and successful supervisor/service completion were verified.

The portable, allowlisted summary is
[`eval/evidence/2026-11-16-hermes-bonsai.json`](../../eval/evidence/2026-11-16-hermes-bonsai.json).
It records scenario verdicts, model settings, source report paths and SHA-256
hashes. Raw reports, transcripts, scratch databases and runtime caches remain
local under the git-ignored `eval/.sandbox/`; they are not uploaded with this PR.
The hashes identify those artifacts but do not make them remotely downloadable.

## Limits and next steps

### Integrated review: blocked, publish as draft

The independent pre-publication review found two merge blockers, both reproduced
by the parent against the staged implementation:

- `src/claimbase/writer.py:421`: the local-qualifier guard misses intervening
  adjectives. "For this specific project I prefer tabs for indentation" can
  still become global `self` memory. The passing opposite-project scenarios do
  not establish isolation for this wording.
- `src/claimbase/writer.py:329`: session-matched recalls are passed into the
  whole-session availability path. Text written before recall delivery can
  receive inferred-use credit. Preserve delivery ordering; only a verified
  session-start hook brief may be available from the beginning.

These findings do not alter the recorded task/collection verdicts, but they
invalidate an integrated spec sign-off. The PR remains draft. Repair with
regressions, re-review, and rerun evidence affected by behavioral changes before
advancing. A nonblocking review suggestion is to reject malformed decoded query
log record types cleanly rather than abort synchronization.

This is repeatable success on a small synthetic integration suite. It is not
statistical significance, proof of causal use of individual claims, validation
of the judge on representative real sessions, or a production rollout decision.
The agent and judge are the same model; independent code checks the outcomes.

1. Resolve the two integrated-review blockers, rerun affected evidence and
   obtain Phase 3 integrated spec/quality approval before merge.
2. Phase 4: retrieval pressure — fixed-budget briefs with distractors, omitted
   relevant rules, recall recovery, superseded claims and foreign-project claims.
   Do not tune ranking just to force seeded targets into the brief.
3. Phase 5: real-project shadow evaluation on bounded genuine sessions from
   claimbase-memory, using scratch capture/redaction/judging/proposals only.
   No live injection, source edits, profile changes or live memory merges.
4. Explicit owner rollout gates remain: real-session judge validation, approval
   for live migrations/configuration, and a week of daily-use evidence.
