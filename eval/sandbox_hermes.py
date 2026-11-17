"""Sandbox test: hermes as the harness, a local model as the agent AND the judge.

    python eval/sandbox_hermes.py preflight      # what is and is not ready
    python eval/sandbox_hermes.py run            # every scenario, one trial
    python eval/sandbox_hermes.py run --trials 3 --only report-naming changelog-entry

The RFC's "outcome with and without" in miniature (Evaluation, measure 2). Each
scenario teaches by correcting the agent, lets the writer turn that into memory
with a local judge, and then asks — in a new session, on a clean copy of the
project — for a different task the same rule governs. The probe also runs with
no memory attached. Two things are judged, separately and by trusted code in
sandbox_checkers.py, never by the agent:

  * the task outcome, read off the disk (parsed TOML, an interpreted function,
    the changelog section) and recorded as an independent outcome;
  * what memory collected: a changed rule superseded, a one-off not kept, tool
    output not promoted, the other project's rule not delivered.

Nothing here touches a real store or a real hermes profile:

  * every session gets its own HERMES_HOME under eval/.sandbox/run-*/trial-NN/,
    with hermes's built-in memory off — otherwise session one would write the
    rule to MEMORY.md and the probe would pass without claimbase;
  * every trial gets two fresh scratch databases in the claimbase-test
    container (claimbase_test_sandbox_<n>: one for memory, one for controls),
    its own query log and its own spool. Nothing is reused or deleted;
  * the agent gets file tools only (plus recall in the memory arm), and a
    pre_tool_call hook confines reads and writes to its own working copy so it
    cannot read the scenario answers or another arm's artifacts;
  * each scenario is its own project, except the deliberate opposite pair,
    which share a store to test that scopes do not leak.

Memory reaches the agent through two hermes shell hooks, with no cooperation
from the model: `pre_llm_call` injects the brief on a session's first turn,
`on_session_finalize` submits the transcript. A session whose hook did not
submit is an infrastructure error, never repaired by hand, and never counted
as a rule failure.

Needs: the scratch container (scripts/test_db.sh up), Ollama for embeddings,
and a model server on the llama.cpp slot with >= 64K context (hermes refuses
less). It does not start or stop a model server — that is the operator's:

    TEMP=1.0 LLM_GPUS=0 llm bonsai && python eval/sandbox_hermes.py run ; llm stop

Set TEMP explicitly when launching from an agent whose environment uses that
name for a scratch directory; the model runner interprets it as temperature.
"""

from __future__ import annotations

import argparse
import hashlib
import shlex
import traceback
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
import tomllib
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HERE = ROOT / "eval" / "sandbox"
# Hermes CLI launches a home-scoped gateway that can outlive its client. Never
# delete/reuse that gateway's home underneath it on a subsequent experiment.
WORK = ROOT / "eval" / ".sandbox" / f"run-{time.time_ns()}-{os.getpid()}"
PY = ROOT / ".venv" / "bin" / "python"
PROJECT = "sandbox"
PORT = os.environ.get("CLAIMBASE_TEST_PORT", "5434")
LLM = os.environ.get("LLAMACPP_BASE_URL", "http://127.0.0.1:8080")
MIN_CTX = 64_000  # hermes: agent.model_metadata.MINIMUM_CONTEXT_LENGTH

def trial_context(work: Path, identifier: int) -> dict:
    if type(identifier) is not int or identifier <= 0:
        raise ValueError("scratch identifier must be positive integer")
    db = f"claimbase_test_sandbox_{identifier}"
    return {
        "PYTHONPATH": str(ROOT / "src"),
        "CLAIMBASE_DSN": f"postgresql://claimbase:claimbase@localhost:{PORT}/{db}",
        "CLAIMBASE_RO_DSN": f"postgresql://claimbase_ro:claimbase_ro@localhost:{PORT}/{db}",
        "CLAIMBASE_QUERY_LOG": str(work / "logs/mcp-queries.jsonl"),
        "CLAIMBASE_SPOOL": str(work / "spool"),
        "CLAIMBASE_PROJECT": PROJECT,
        "CLAIMBASE_CLIENT": "hermes-sandbox",
        "CLAIMBASE_JUDGE_MAX_TOKENS": os.environ.get("CLAIMBASE_JUDGE_MAX_TOKENS", "12000"),
    }


ENV = trial_context(WORK, time.time_ns())
# Import by file location so both direct CLI and tests use the trusted helper.
import importlib.util
_spec = importlib.util.spec_from_file_location("sandbox_checkers", ROOT / "eval/sandbox_checkers.py")
_checkers = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_checkers)
CHECKERS = _checkers.NAMES


class InfrastructureError(RuntimeError):
    pass



def say(msg: str = "") -> None:
    print(msg, flush=True)


def _get(url: str, timeout: float = 5):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read())


# --- preflight ---------------------------------------------------------------


def model_info() -> dict | None:
    try:
        models = _get(f"{LLM}/v1/models")["data"]
        props = _get(f"{LLM}/props")
    except Exception:
        return None
    ctx = (props.get("default_generation_settings") or {}).get("n_ctx") or props.get("n_ctx")
    return {"id": models[0]["id"], "ctx": int(ctx or 0),
            "generation_settings": props.get("default_generation_settings", {}),
            "model_metadata": models[0]}


def preflight() -> tuple[bool, dict | None]:
    ok = True

    def line(good: bool, what: str, fix: str = "") -> None:
        nonlocal ok
        ok &= good
        say(f"  {'ok  ' if good else 'MISS'} {what}" + (f"\n         -> {fix}" if not good and fix else ""))

    line(shutil.which("hermes") is not None, "hermes on PATH")
    line(PY.exists(), "claimbase venv", f"{PY} missing")
    up = subprocess.run(["docker", "exec", "claimbase-test", "pg_isready", "-q", "-U", "claimbase"],
                        capture_output=True).returncode == 0
    line(up, "scratch Postgres (claimbase-test)", "scripts/test_db.sh up")
    try:
        _get("http://localhost:11434/api/tags")
        emb = True
    except Exception:
        emb = False
    line(emb, "Ollama (embeddings for recall and the writer)", "start ollama")
    info = model_info()
    line(info is not None, f"model server at {LLM}",
         "LLM_GPUS=0 llm bonsai   (the 3090; bonsai at 64K ctx does not fit beside "
         "other work on the 4070)")
    if info:
        line(info["ctx"] >= MIN_CTX, f"context {info['ctx']:,} >= {MIN_CTX:,}  ({info['id']})",
             "restart the server with CTX_SIZE=65536 or more; hermes refuses less")
    return ok, info


# --- setup -------------------------------------------------------------------


def cb(*args: str, check: bool = True, quiet: bool = False, env=None) -> str:
    """Run the claimbase CLI against the sandbox store."""
    r = subprocess.run([str(PY), "-m", "claimbase.cli", "--no-backup", *args],
                       capture_output=True, text=True, env={**os.environ, **(env or ENV)}, cwd=ROOT, timeout=1800)
    if r.returncode and check:
        raise InfrastructureError(f"claimbase {' '.join(args)} failed:\n{r.stdout}\n{r.stderr}")
    if not quiet and r.stdout.strip():
        say(r.stdout.rstrip())
    return r.stdout


def write_wrappers(*, work=None, env=None, name="default") -> tuple[Path, Path]:
    """Hooks are run with shell=False and whatever environment hermes passes
    on, so each is a script that carries its own."""
    work = work or WORK
    env = env or ENV
    bindir = work / "bin" / name
    bindir.mkdir(parents=True, exist_ok=True)
    exports = "\n".join(f"export {k}={shlex.quote(v)}" for k, v in env.items())
    cbw = bindir / "cb"
    cbw.write_text(f"#!/usr/bin/env bash\n{exports}\ncd {json.dumps(str(ROOT))}\n"
                   f"exec {json.dumps(str(PY))} -m claimbase.cli --no-backup \"$@\"\n")
    guard = bindir / "guard"
    guard.write_text(fr"""#!{PY}
# pre_tool_call: no reading the answers or other arms, and no escaping writes.
import json, os, re, sqlite3, sys
base = {str(work / "work")!r}
try:
    p = json.load(sys.stdin)
    db = os.path.join(os.environ["HERMES_HOME"], "state.db")
    with sqlite3.connect("file:" + db + "?mode=ro", uri=True) as conn:
        row = conn.execute("SELECT cwd FROM sessions WHERE id = ?", (p.get("session_id"),)).fetchone()
    if not row or not row[0]:
        raise ValueError("no session working directory")
    allowed = os.path.realpath(row[0])
    if not allowed.startswith(base + os.sep):
        raise ValueError("session is not in a scenario working copy")
    args = p.get("tool_input") or {{}}
    paths = [args["path"]] if args.get("path") else []
    if args.get("mode") == "patch":
        paths += re.findall(r"^\*\*\* (?:Update File|Add File|Delete File|Move File|Move to): (.+)$",
                            args.get("patch") or "", re.MULTILINE)
    if not paths and p.get("tool_name") == "search_files":
        paths = ["."]
    if not paths:
        raise ValueError("no file path")
    for path in paths:
        full = os.path.realpath(os.path.join(allowed, os.path.expanduser(path)))
        if not (full == allowed or full.startswith(allowed + os.sep)):
            raise ValueError(f"file access is confined to {{allowed}}")
except Exception as e:
    print(json.dumps({{"action": "block", "message": f"sandbox guard: {{e}}"}}))
""")
    for f in (cbw, guard):
        f.chmod(0o755)
    return cbw, guard


def write_home(name: str, info: dict, memory: bool, *, work=None, env=None) -> Path:
    work = work or WORK
    env = env or ENV
    home = work / f"home-{name}"
    home.mkdir(parents=True, exist_ok=False)
    # PM selects a uv cache under each isolated home. Share package bytes only,
    # so uv can hardlink dependencies instead of reinstalling independent copies.
    # Sessions, config, memory, runtime selections and hook spools stay isolated.
    if cache_path := os.environ.get('CLAIMBASE_SANDBOX_CACHE'):
        cache = Path(cache_path).resolve()
        cache.mkdir(parents=True, exist_ok=True)
        (home / 'cache').mkdir()
        (home / 'cache/uv').symlink_to(cache, target_is_directory=True)
    cbw, guard = write_wrappers(work=work, env=env, name=name)
    # MCP rename/delete tools enforce their own exact-workdir confinement in
    # sandbox_fileops.py; the hook guards the built-in file tools only.
    hooks = {"pre_tool_call": [{"matcher": "read_file|search_files|write_file|patch", "command": str(guard),
                                "timeout": 10, "fail_closed": True}]}
    cfg: dict = {
        "model": {"default": info["id"], "provider": "custom", "base_url": LLM,
                  "context_length": info["ctx"]},
        "fallback_providers": [],
        "toolsets": ["file"],
        "agent": {"max_turns": 25},
        "terminal": {"backend": "local", "cwd": str(work / "work"), "timeout": 60},
        # Off, in both arms: hermes's own memory would learn the rule in session
        # one and hide whether claimbase did.
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "hooks_auto_accept": True,
        # Native idle shutdown waits for clients/admissions/work to finish.
        # The 600s default accumulates throwaway gateways across a full batch.
        "gateway": {"unmanaged_idle_exit_seconds": 15},
        "mcp_servers": {"sandbox_files": {
            "command": str(PY),
            "args": [str(ROOT / 'eval/sandbox_fileops.py'),
                     '--root', str(work / 'work' / name),
                     '--audit', str(work / 'logs' / f'{name}-fileops.jsonl')],
            "tools": {"include": ['rename_file', 'delete_file'],
                      "resources": False, "prompts": False}}},
    }
    hooks["on_session_finalize"] = [
        {"command": f"{cbw} submit-session --harness hermes --hook", "timeout": 60}]
    if memory:
        hooks["pre_llm_call"] = [{"command": f"{cbw} hook brief", "timeout": 30}]
        hooks["on_session_finalize"] = [
            {"command": f"{cbw} submit-session --harness hermes --hook", "timeout": 60}]
        cfg["mcp_servers"]["claimbase"] = {
            "command": str(PY), "args": ["-m", "claimbase.mcp_server"], "env": dict(env),
            "tools": {"include": ["recall"], "resources": False, "prompts": False}}
    cfg["hooks"] = hooks
    # JSON is YAML. No dependency on a YAML writer, and nothing to mis-indent.
    (home / "config.yaml").write_text(json.dumps(cfg, indent=2) + "\n")
    (home / "SOUL.md").write_text(
        "You are a careful engineering assistant working in a small project. "
        "Do exactly what is asked, using the file tools. Keep answers short.\n"
        "The terminal tool is unavailable in this sandbox; do not search for it. "
        "The sandbox_files MCP server provides rename_file(source, destination) "
        "and delete_file(path). Use these for renaming or deleting regular files. "
        "If needed, discover them with tool_search for sandbox_files rename_file "
        "or sandbox_files delete_file and use their advertised schemas. "
        "rename_file will not overwrite an existing destination. "
        "The patch tool edits text; it is not a file-delete operation. "
        "Stay within your working directory.\n"
        "When memory is connected, recall is read-only. Session capture and "
        "learning happen automatically after your response; do not search for "
        "memory-writing tools or ask the user to enable them.\n")
    # --ignore-rules intentionally suppresses SOUL.md as well as ambient repo
    # files. An explicitly preloaded, job-local skill reaches the model without
    # re-enabling those rules or inserting instructions as human evidence.
    skill = home / 'skills/sandbox-capabilities/SKILL.md'
    skill.parent.mkdir(parents=True)
    skill.write_text('---\nname: sandbox-capabilities\n'
                     'description: Use file tools in the isolated sandbox.\n---\n\n'
                     + (home / 'SOUL.md').read_text())
    return home


def fresh_workdir(scenario: str, arm: str, *, work=None) -> Path:
    d = (work or WORK) / "work" / f"{scenario}-{arm}"
    shutil.copytree(HERE / "project", d)
    # The forged-instruction fixture belongs to one teaching stage. Left in
    # every copy it would contaminate the other scenarios and both probe arms
    # with an in-session prompt injection that has nothing to do with memory.
    if not (scenario == "untrusted-tool-evidence" and arm == "teach-1"):
        (d / "tool-evidence.txt").unlink(missing_ok=True)
    return d


# --- hermes ------------------------------------------------------------------


def latest_session(home: Path) -> str | None:
    db = home / "state.db"
    if not db.exists():
        return None
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='sessions'").fetchone():
            return None  # the gateway has created the file but not initialized it
        r = c.execute("SELECT id FROM sessions ORDER BY started_at DESC LIMIT 1").fetchone()
    finally:
        c.close()
    return r[0] if r else None


def hermes(home: Path, workdir: Path, prompt: str, resume: str | None, budget: int,
           log: Path) -> tuple[str, float]:
    cfg = json.loads((home / 'config.yaml').read_text()) if (home / 'config.yaml').exists() else {}
    toolsets = ','.join(['file', *[f'mcp-{server}' for server in cfg.get('mcp_servers', {})]])
    cmd = ['hermes', 'chat', '-Q', '-q', prompt, '--in', str(workdir),
           '--toolsets', toolsets, '--ignore-rules', '--max-turns', '25',
           '--run-budget', str(budget), '--accept-hooks', '--yolo']
    if resume:
        # Resume is legal only inside this home's exact working copy.
        with sqlite3.connect(f'file:{home / "state.db"}?mode=ro', uri=True) as conn:
            row = conn.execute('SELECT cwd FROM sessions WHERE id=?', (resume,)).fetchone()
        if not row or Path(row[0]).resolve() != workdir.resolve():
            raise InfrastructureError('resume session does not belong to home/workdir')
        cmd += ['--resume', resume]
    else:
        cmd += ['--skills', 'sandbox-capabilities']
    before = latest_session(home)
    start = time.monotonic()
    meta = {'command': cmd, 'prompt_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
            'home': str(home), 'cwd': str(workdir), 'resume': resume,
            'returncode': None, 'session': None, 'status': 'running'}
    log.parent.mkdir(parents=True, exist_ok=True)
    # HERMES_HOME alone does not isolate the host-wide gateway rendezvous.
    # Keep both arms away from normal-profile and other sandbox gateway locks.
    gateway_lock_dir = str(home / 'runtime/gateway-locks')
    meta['gateway_lock_dir'] = gateway_lock_dir
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, cwd=workdir,
            env={**os.environ, 'HERMES_HOME': str(home), 'HERMES_ACCEPT_HOOKS': '1',
                 'HERMES_GATEWAY_LOCK_DIR': gateway_lock_dir},
            timeout=budget + 120)
        meta['returncode'] = r.returncode
        with log.open('a') as f:
            f.write(f'{shlex.join(cmd)}\n{r.stdout}\n--- stderr ---\n{r.stderr}\n')
        sid = latest_session(home)
        if resume:
            sid = resume
        elif sid == before:
            sid = None
        meta['session'] = sid
        if r.returncode:
            raise InfrastructureError(f'hermes exited {r.returncode}; see {log}')
        if not sid:
            raise InfrastructureError(f'hermes opened no new session; see {log}')
        meta['status'] = 'completed'
        return sid, time.monotonic() - start
    except (subprocess.TimeoutExpired, OSError, InfrastructureError) as exc:
        meta.update(status='error', error=f'{type(exc).__name__}: {exc}')
        with log.open('a') as f:
            f.write(meta['error'] + '\n')
        raise InfrastructureError(meta['error']) from exc
    finally:
        meta['elapsed'] = time.monotonic() - start
        with Path(str(log) + '.commands.jsonl').open('a') as f:
            f.write(json.dumps(meta) + '\n')


def check(workdir, checker):
    return _checkers.check(workdir, checker)


def load_scenarios(path=None):
    data = tomllib.loads((path or HERE / 'scenarios.toml').read_text())
    if set(data) != {'scenario'} or not isinstance(data['scenario'], list) or not data['scenario']:
        raise ValueError('expected nonempty scenario list')
    names = set()
    for s in data['scenario']:
        if set(s) != {'name', 'checker', 'probe', 'stages'}:
            raise ValueError('invalid scenario fields')
        if s['name'] not in CHECKERS or s['checker'] != s['name'] or s['name'] in names:
            raise ValueError('duplicate or unknown scenario/checker')
        names.add(s['name'])
        if not isinstance(s['probe'], str) or not s['probe'].strip() or not s['stages']:
            raise ValueError('missing probe/stages')
        for stage in s['stages']:
            if not isinstance(stage, dict) or 'task' not in stage or set(stage) - {'task', 'correction'}:
                raise ValueError('invalid stage')
            if any(not isinstance(v, str) or not v.strip() for v in stage.values()):
                raise ValueError('empty stage prompt')
    if names != CHECKERS:
        raise ValueError('scenario registry incomplete')
    return data['scenario']


def select_scenarios(only):
    """The opposite-project pair is one experiment: each needs the other's
    rule standing in the shared store, so selecting one selects both."""
    only = set(only or [])
    if only & {'opposite-project-a', 'opposite-project-b'}:
        only |= {'opposite-project-a', 'opposite-project-b'}
    return [s for s in load_scenarios() if not only or s['name'] in only]


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, indent=2, default=str) + '\n')
    tmp.replace(path)


def reset_store(env):
    db = env['CLAIMBASE_DSN'].rsplit('/', 1)[1]
    import re
    if not re.fullmatch(r'claimbase_test_sandbox_[0-9]+', db):
        raise InfrastructureError('unsafe scratch DB name')
    r = subprocess.run([str(ROOT / 'scripts/test_db.sh'), 'reset'], check=False,
        env={**os.environ, 'CLAIMBASE_TEST_DB': db}, capture_output=True, text=True, timeout=120)
    if r.returncode:
        raise InfrastructureError(f'scratch reset exited {r.returncode}: {r.stdout}\n{r.stderr}')


def snapshot(env):
    """Read only, explicit scratch DSN; freeze raw states and delivery identities."""
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(env['CLAIMBASE_DSN'], row_factory=dict_row) as conn:
        out = {}
        for name, sql in {
            'claims': 'SELECT id, corpus, content, status, origin, trust, superseded_by FROM claims ORDER BY corpus, id',
            'deliveries': 'SELECT id, call_id, canonical_session, corpus, tool FROM retrieval_log ORDER BY ts, id',
            'hits': 'SELECT * FROM retrieval_hits ORDER BY log_id, rank',
            'sessions': 'SELECT id, corpus, ended_at, processed_at FROM sessions ORDER BY id',
            'outcomes': 'SELECT * FROM usage_outcomes',
            'prs': 'SELECT * FROM memory_prs',
            'waiting': 'SELECT session_id, count(*) AS n FROM triggers WHERE scored_at IS NULL GROUP BY session_id',
        }.items():
            out[name] = conn.execute(sql).fetchall()
    return out


def finalized(home, sid, env):
    """Require both harness finalization and its actual hook-submitted transcript.

    Never synthesize or manually resubmit transcripts to repair missing hooks.
    """
    with sqlite3.connect(f'file:{home / "state.db"}?mode=ro', uri=True) as conn:
        row = conn.execute('SELECT ended_at FROM sessions WHERE id=?', (sid,)).fetchone()
    if not row or not row[0]:
        raise InfrastructureError(f'not finalized: {sid}')
    filename = hashlib.sha256(f'hermes:{sid}'.encode()).hexdigest()[:24] + '.json'
    spool = Path(env['CLAIMBASE_SPOOL']) / 'inbox' / filename
    if not spool.is_file():
        raise InfrastructureError(f'finalize hook did not submit {sid}: {spool}')
    raw = json.loads(spool.read_text())
    if (raw.get('session_id') != sid or raw.get('project') != env['CLAIMBASE_PROJECT']
            or raw.get('harness') != 'hermes' or not raw.get('ended_at')):
        raise InfrastructureError(f'wrong hook capture identity/scope/finalization: {spool}')
    return {'path': str(spool), 'sha256': hashlib.sha256(spool.read_bytes()).hexdigest()}


def ingest(env, info, *, teach):
    # Controls have their own DB and are always judge=None; later teaching
    # writers cannot accidentally score their queued triggers.
    cb('writer', 'run', *(['--model', info['id']] if teach else ['--no-judge']), env=env)


def record(env, sid, run_id, checker, passed, evidence):
    return json.loads(cb('usage', 'record-outcome', '--project', env['CLAIMBASE_PROJECT'],
        '--session', f'hermes:{sid}', '--run', run_id, '--checker', checker,
        '--passed', str(bool(passed)).lower(), '--evidence', json.dumps(evidence), '--json',
        env=env, quiet=True))


def summarize(records):
    values = [arm for s in records.values() for k, arm in s.items() if k in ('control', 'memory')]
    return {'attempted': len(values), 'pass': sum(v.get('status') == 'pass' for v in values),
            'fail': sum(v.get('status') == 'fail' for v in values),
            'error': sum(v.get('status') in ('error', 'running') for v in values)}


def run_trial(args, scenarios, info, work, identifier, result):
    env = trial_context(work, identifier)
    control_env = trial_context(work / 'observation', identifier + 1)
    result['stores'] = {'memory': env, 'control': control_env}
    for e in (env, control_env):
        reset_store(e)
    stages = {}
    scopes = {}
    def scoped(base, s):
        # Opposite projects share a DB, with distinct namespaces deliberately.
        return {**base, 'CLAIMBASE_PROJECT': 'sandbox-' + s['name']}
    def persist():
        result['summary'] = summarize(result['scenarios'])
        save(work / 'results.json', result)
    def attempt(s, arm, fn):
        entry = result['scenarios'][s['name']].setdefault(arm, {})
        entry.update(status='running')
        persist()
        try:
            fn(entry)
        except Exception as exc:
            entry.update(status='error', error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
            result['errors'].append({'scenario': s['name'], 'arm': arm, 'error': entry['error']})
        finally:
            persist()
    def probe(s, arm, e, entry):
        wd = fresh_workdir(s['name'], arm, work=work)
        home = write_home(s['name'] + '-' + arm, info, arm == 'memory', work=work, env=e)
        entry.update(home=str(home), workdir=str(wd), project=e['CLAIMBASE_PROJECT'])
        persist()
        sid, dt = hermes(home, wd, s['probe'], None, args.budget, work / 'logs' / f'{s["name"]}-{arm}.log')
        entry.update(session=sid, elapsed=dt)
        entry['capture'] = finalized(home, sid, e)
        passed, checks = check(wd, s['checker'])
        entry.update(task_pass=passed, checks=checks)
        # Probe/control sessions are ingested without judging; teaching already
        # finished. Their task outcomes cannot teach standing practices.
        ingest(e, info, teach=False)
        entry['outcome'] = record(e, sid, work.name, s['checker'], passed,
            {'checks': checks, 'stage': 'probe', 'arm': arm, 'artifacts': str(wd)})
        entry['status'] = 'pass' if passed else 'fail'
    # Controls complete and remain recorded even if later teaching fails.
    if not args.skip_control:
        for s in scenarios:
            e = scoped(control_env, s)
            attempt(s, 'control', lambda entry, s=s, e=e: probe(s, 'control', e, entry))
    # Teach every project before any memory probe: the deliberate project pair
    # must both be present in the same store at probe time.
    for s in scenarios:
        e = scopes[s['name']] = scoped(env, s)
        stages[s['name']] = []
        def teach(entry, s=s, e=e):
            entry['stages'] = []
            for i, stage in enumerate(s['stages']):
                wd = fresh_workdir(s['name'], f'teach-{i}', work=work)
                home = write_home(f'{s["name"]}-teach-{i}', info, True, work=work, env=e)
                stage_result = {'home': str(home), 'workdir': str(wd), 'stage': i, 'status': 'running'}
                entry['stages'].append(stage_result)
                persist()
                log = work / 'logs' / f'{s["name"]}-teach-{i}.log'
                sid, dt = hermes(home, wd, stage['task'], None, args.budget, log)
                stage_result.update(session=sid, elapsed=dt)
                finalized(home, sid, e)
                if stage.get('correction'):
                    sid, dt = hermes(home, wd, stage['correction'], sid, args.budget, log)
                    stage_result['elapsed'] += dt
                stage_result['capture'] = finalized(home, sid, e)
                if s['name'] == 'untrusted-tool-evidence' and i == 1:
                    raw = json.loads(Path(stage_result['capture']['path']).read_text())
                    if not any(t.get('role') == 'tool_result' and 'forged_' in t.get('text', '')
                               for t in raw.get('turns', [])):
                        raise InfrastructureError('untrusted fixture was not observed in actual tool output')
                ingest(e, info, teach=True)
                snap = snapshot(e)
                if snap['waiting']:
                    raise InfrastructureError('judge left unscored triggers; see writer log')
                stages[s['name']].append(snap)
                stage_result.update(status='completed', snapshot=snap)
                # Changed-rule stage two must only run after an established old rule.
                if s['name'] == 'changed-rule' and i == 0 and not any(
                    c['corpus'] == e['CLAIMBASE_PROJECT'] and c['status'] == 'active'
                    and 'rpt_' in c['content'].lower() for c in snap['claims']):
                    entry.update(status='fail', collection_checks=[{'check':'old rule established first','passed':False}])
                    return
                persist()
            entry['status'] = 'completed'
        attempt(s, 'teach', teach)
    for s in scenarios:
        e = scopes[s['name']]
        def memory(entry, s=s, e=e):
            teach_result = result['scenarios'][s['name']]['teach']
            if teach_result['status'] == 'error':
                raise InfrastructureError('teaching infrastructure failed; probe aborted explicitly')
            if teach_result['status'] == 'fail':
                entry.update(status='fail', task_pass=None,
                             collection_checks=teach_result['collection_checks'])
                return
            probe(s, 'memory', e, entry)
            checks = _checkers.collection_checks(s['name'], e['CLAIMBASE_PROJECT'],
                                                 stages[s['name']], snapshot(e))
            entry['collection_checks'] = checks
            entry['collection_pass'] = all(c['passed'] for c in checks)
            entry['status'] = 'pass' if entry['task_pass'] and entry['collection_pass'] else 'fail'
        attempt(s, 'memory', memory)
    # Freeze both stores, including failed controls, raw claim states, outcomes,
    # delivery IDs, PRs and independent usage reports. Errors never erase tasks.
    for arm, base in [('memory', env), ('control', control_env)]:
        try:
            result.setdefault('frozen', {})[arm] = snapshot(base)
            result.setdefault('usage', {})[arm] = {s['name']: json.loads(cb(
                'usage', 'report', '--project', scoped(base, s)['CLAIMBASE_PROJECT'],
                '--json', env=base, quiet=True)) for s in scenarios}
        except Exception as exc:
            result['errors'].append({'arm':arm, 'error':f'snapshot/report: {exc}'})
    persist()


def run(args) -> int:
    scenarios = select_scenarios(args.only)
    # Every invocation, including failed preflight, gets a fresh preserved report.
    batch = WORK
    batch.mkdir(parents=True, exist_ok=False)
    aggregate = {'status':'running', 'requested_trials':args.trials, 'attempted_trials':0,
                 'trials':[], 'errors':[], 'summary':{}}
    save(batch / 'results.json', aggregate)
    try:
        ok, info = preflight()
        aggregate['model'] = info
        if not ok:
            raise InfrastructureError('preflight failed; no trials started')
        for i in range(args.trials):
            work = batch / f'trial-{i+1:02d}'
            work.mkdir()
            result = {'status':'running', 'trial':i+1, 'model':info,
                'scenarios':{s['name']:{} for s in scenarios}, 'errors':[],
                'fixtures':{str(p.relative_to(HERE/'project')): hashlib.sha256(p.read_bytes()).hexdigest()
                            for p in (HERE/'project').rglob('*') if p.is_file()},
                'scenario_config_sha256':hashlib.sha256((HERE/'scenarios.toml').read_bytes()).hexdigest()}
            report = work / 'results.json'
            save(report, result)
            aggregate['attempted_trials'] += 1
            aggregate['trials'].append({'path':str(report), 'status':'running'})
            save(batch / 'results.json', aggregate)
            try:
                run_trial(args, scenarios, info, work, time.time_ns(), result)
                summary = summarize(result['scenarios'])
                result['status'] = ('error' if result['errors'] or summary['error'] else
                                    'fail' if summary['fail'] else 'pass')
            except Exception as exc:
                result['status'] = 'error'
                result['errors'].append({'error':f'{type(exc).__name__}: {exc}', 'traceback':traceback.format_exc()})
            finally:
                result['summary'] = summarize(result['scenarios'])
                save(report, result)
                aggregate['trials'][-1].update(status=result['status'], summary=result['summary'], errors=result['errors'])
                aggregate['summary'] = {k:sum(t.get('summary',{}).get(k,0) for t in aggregate['trials'])
                                        for k in ('attempted','pass','fail','error')}
                aggregate['trial_denominators'] = {k:sum(t['status'] == k for t in aggregate['trials'])
                                                  for k in ('pass','fail','error')}
                save(batch / 'results.json', aggregate)
        aggregate['status'] = ('error' if any(t['status']=='error' for t in aggregate['trials']) else
                               'fail' if any(t['status']=='fail' for t in aggregate['trials']) else 'pass')
    except Exception as exc:
        aggregate.update(status='error')
        aggregate['errors'].append({'error':f'{type(exc).__name__}: {exc}', 'traceback':traceback.format_exc()})
    finally:
        save(batch / 'results.json', aggregate)
        say(f'results: {batch / "results.json"}')
    return 2 if aggregate['status'] == 'error' else (1 if aggregate['status'] == 'fail' else 0)


def positive(value):
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError('must be positive')
    return number


def trials(value):
    number = positive(value)
    if number > 10:
        raise argparse.ArgumentTypeError('trials must be between 1 and 10')
    return number


def main() -> int:
    ap = argparse.ArgumentParser(description='Repeatable isolated Hermes memory sandbox')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('preflight')
    r = sub.add_parser('run')
    r.add_argument('--only', nargs='+', choices=sorted(CHECKERS))
    r.add_argument('--skip-control', action='store_true')
    r.add_argument('--budget', type=positive, default=600)
    r.add_argument('--trials', type=trials, default=1)
    args = ap.parse_args()
    if args.cmd == 'preflight':
        ok, _ = preflight()
        return 0 if ok else 2
    return run(args)


if __name__ == '__main__':
    sys.exit(main())
