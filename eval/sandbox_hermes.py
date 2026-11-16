"""Sandbox test: hermes as the harness, a local model as the agent AND the judge.

    python eval/sandbox_hermes.py preflight      # what is and is not ready
    python eval/sandbox_hermes.py run            # control -> teach -> writer -> probe
    python eval/sandbox_hermes.py run --only report-naming --skip-control

The RFC's "outcome with and without" in miniature (Evaluation, measure 2). Each
scenario teaches one house rule by correcting the agent, lets the writer turn
that correction into memory, and then asks — in a new session, on a clean
copy of the project — for a different task the same rule governs. The probe
also runs with no memory attached. The outcome is read off the disk.

Nothing here touches a real store or a real hermes profile:

  * hermes runs under its own HERMES_HOME (eval/.sandbox/home-*), with its
    built-in memory switched off — otherwise session one would write the rule
    to hermes's own MEMORY.md and the probe would pass without claimbase;
  * claimbase runs against its own database in the scratch container
    (claimbase_sandbox), its own query log and its own spool;
  * the agent gets file tools only, and a pre_tool_call hook refuses any write
    outside the scenario's working copy.

Memory reaches the agent through two hermes shell hooks, with no cooperation
from the model: `pre_llm_call` injects the brief on a session's first turn,
`on_session_finalize` submits the transcript. The `recall` tool is also wired,
for the model to use or not.

Needs: the scratch container (scripts/test_db.sh up), Ollama for embeddings,
and a model server on the llama.cpp slot with >= 64K context (hermes refuses
less). It does not start or stop a model server — that is the operator's:

    LLM_GPUS=0 llm bonsai && python eval/sandbox_hermes.py run ; llm stop
"""

from __future__ import annotations

import argparse
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
WORK = ROOT / "eval" / ".sandbox"
PY = ROOT / ".venv" / "bin" / "python"
PROJECT = "sandbox"
DB = "claimbase_sandbox"
PORT = os.environ.get("CLAIMBASE_TEST_PORT", "5434")
DSN = f"postgresql://claimbase:claimbase@localhost:{PORT}/{DB}"
RO_DSN = f"postgresql://claimbase_ro:claimbase_ro@localhost:{PORT}/{DB}"
LLM = os.environ.get("LLAMACPP_BASE_URL", "http://127.0.0.1:8080")
MIN_CTX = 64_000  # hermes: agent.model_metadata.MINIMUM_CONTEXT_LENGTH

ENV = {
    "PYTHONPATH": str(ROOT / "src"),
    "CLAIMBASE_DSN": DSN,
    "CLAIMBASE_RO_DSN": RO_DSN,
    "CLAIMBASE_QUERY_LOG": str(WORK / "logs" / "mcp-queries.jsonl"),
    "CLAIMBASE_SPOOL": str(WORK / "spool"),
    "CLAIMBASE_PROJECT": PROJECT,
    "CLAIMBASE_CLIENT": "hermes-sandbox",
    # Bonsai-class models reason at length, and a cap that ends mid-thought
    # returns an empty answer.
    "CLAIMBASE_JUDGE_MAX_TOKENS": os.environ.get("CLAIMBASE_JUDGE_MAX_TOKENS", "12000"),
}


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
    return {"id": models[0]["id"], "ctx": int(ctx or 0)}


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


def cb(*args: str, check: bool = True, quiet: bool = False) -> str:
    """Run the claimbase CLI against the sandbox store."""
    r = subprocess.run([str(PY), "-m", "claimbase.cli", "--no-backup", *args],
                       capture_output=True, text=True, env={**os.environ, **ENV}, cwd=ROOT)
    if r.returncode and check:
        raise SystemExit(f"claimbase {' '.join(args)} failed:\n{r.stdout}\n{r.stderr}")
    if not quiet and r.stdout.strip():
        say(r.stdout.rstrip())
    return r.stdout


def write_wrappers() -> tuple[Path, Path]:
    """Hooks are run with shell=False and whatever environment hermes passes
    on, so each is a script that carries its own."""
    bindir = WORK / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    exports = "\n".join(f"export {k}={json.dumps(v)}" for k, v in ENV.items())
    cbw = bindir / "cb"
    cbw.write_text(f"#!/usr/bin/env bash\n{exports}\ncd {json.dumps(str(ROOT))}\n"
                   f"exec {json.dumps(str(PY))} -m claimbase.cli --no-backup \"$@\"\n")
    guard = bindir / "guard"
    guard.write_text(f"""#!{PY}
# pre_tool_call: a write may only land inside a scenario working copy.
import json, os, sys
allowed = {str(WORK / "work")!r}
try:
    p = json.load(sys.stdin)
    path = (p.get("tool_input") or {{}}).get("path") or ""
    full = os.path.realpath(os.path.join(p.get("cwd") or os.getcwd(), os.path.expanduser(path)))
    if path and not (full == allowed or full.startswith(allowed + os.sep)):
        print(json.dumps({{"action": "block",
                          "message": f"sandbox: writes are confined to {{allowed}}"}}))
except Exception as e:
    print(json.dumps({{"action": "block", "message": f"sandbox guard error: {{e}}"}}))
""")
    for f in (cbw, guard):
        f.chmod(0o755)
    return cbw, guard


def write_home(name: str, info: dict, memory: bool) -> Path:
    home = WORK / f"home-{name}"
    home.mkdir(parents=True, exist_ok=True)
    cbw, guard = write_wrappers()
    hooks = {"pre_tool_call": [{"matcher": "write_file|patch", "command": str(guard),
                                "timeout": 10, "fail_closed": True}]}
    cfg: dict = {
        "model": {"default": info["id"], "provider": "custom", "base_url": LLM,
                  "context_length": info["ctx"]},
        "fallback_providers": [],
        "toolsets": ["file"],
        "agent": {"max_turns": 25},
        "terminal": {"backend": "local", "cwd": str(WORK / "work"), "timeout": 60},
        # Off, in both arms: hermes's own memory would learn the rule in session
        # one and hide whether claimbase did.
        "memory": {"memory_enabled": False, "user_profile_enabled": False},
        "hooks_auto_accept": True,
    }
    if memory:
        hooks["pre_llm_call"] = [{"command": f"{cbw} hook brief", "timeout": 30}]
        hooks["on_session_finalize"] = [
            {"command": f"{cbw} submit-session --harness hermes --hook", "timeout": 60}]
        cfg["mcp_servers"] = {"claimbase": {
            "command": str(PY), "args": ["-m", "claimbase.mcp_server"], "env": dict(ENV)}}
    cfg["hooks"] = hooks
    # JSON is YAML. No dependency on a YAML writer, and nothing to mis-indent.
    (home / "config.yaml").write_text(json.dumps(cfg, indent=2) + "\n")
    (home / "SOUL.md").write_text(
        "You are a careful engineering assistant working in a small project. "
        "Do exactly what is asked, using the file tools. Keep answers short.\n")
    return home


def fresh_workdir(scenario: str, arm: str) -> Path:
    d = WORK / "work" / f"{scenario}-{arm}"
    if d.exists():
        shutil.rmtree(d)
    shutil.copytree(HERE / "project", d)
    return d


# --- hermes ------------------------------------------------------------------


def latest_session(home: Path) -> str | None:
    db = home / "state.db"
    if not db.exists():
        return None
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        r = c.execute("SELECT id FROM sessions ORDER BY started_at DESC LIMIT 1").fetchone()
    finally:
        c.close()
    return r[0] if r else None


def hermes(home: Path, workdir: Path, prompt: str, resume: str | None, budget: int,
           log: Path) -> tuple[str | None, float]:
    cmd = ["hermes", "chat", "-Q", "-q", prompt, "--in", str(workdir),
           "--max-turns", "25", "--run-budget", str(budget), "--accept-hooks", "--yolo"]
    if resume:
        cmd += ["--resume", resume]
    env = {**os.environ, "HERMES_HOME": str(home), "HERMES_ACCEPT_HOOKS": "1"}
    before = latest_session(home)
    t0 = time.time()
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, env=env, cwd=workdir,
                           timeout=budget + 120)
        out = f"$ {' '.join(cmd[:4])} …\n{r.stdout}\n--- stderr ---\n{r.stderr}\n"
    except subprocess.TimeoutExpired as e:
        out = f"TIMEOUT after {budget + 120}s\n{e.stdout or ''}\n"
    with log.open("a") as fh:
        fh.write(out)
    sid = resume or latest_session(home)
    if not resume and sid == before:
        sid = None  # hermes never opened a session: the run failed before turn one
    return sid, time.time() - t0


def check(workdir: Path, checks: list[dict]) -> tuple[bool, list[str]]:
    notes, ok = [], True
    for c in checks:
        if "exists" in c:
            good = (workdir / c["exists"]).is_file()
            notes.append(f"{'+' if good else '-'} exists {c['exists']}")
        else:
            f = workdir / c["file"]
            good = f.is_file() and c["contains"] in f.read_text(errors="replace")
            notes.append(f"{'+' if good else '-'} {c['file']} contains {c['contains']!r}")
        ok &= good
    return ok, notes


# --- the run -----------------------------------------------------------------


def run(args) -> int:
    say("preflight")
    ok, info = preflight()
    if not ok:
        say("\n  not ready — nothing was started.")
        return 2
    scenarios = tomllib.loads((HERE / "scenarios.toml").read_text())["scenario"]
    if args.only:
        scenarios = [s for s in scenarios if s["name"] in args.only]

    if WORK.exists() and not args.keep:
        shutil.rmtree(WORK)
    (WORK / "logs").mkdir(parents=True, exist_ok=True)
    subprocess.run([str(ROOT / "scripts" / "test_db.sh"), "reset"], check=True,
                   env={**os.environ, "CLAIMBASE_TEST_DB": DB}, capture_output=True)
    say(f"\n  store: {DB} (fresh)   model: {info['id']}   ctx {info['ctx']:,}")
    plain = write_home("control", info, memory=False)
    mem = write_home("memory", info, memory=True)
    hlog = WORK / "logs" / "hermes.log"
    results = {s["name"]: {} for s in scenarios}
    t_start = time.time()

    if not args.skip_control:
        say("\ncontrol — the probe with no memory attached")
        for s in scenarios:
            wd = fresh_workdir(s["name"], "control")
            _, dt = hermes(plain, wd, s["probe"], None, args.budget, hlog)
            good, notes = check(wd, s["check"])
            results[s["name"]]["control"] = {"pass": good, "checks": notes, "seconds": round(dt)}
            say(f"  {s['name']:<18} {'PASS' if good else 'fail'}  {dt:5.0f}s  {'  '.join(notes)}")

    say("\nteach — a task, then the user's correction")
    for s in scenarios:
        wd = fresh_workdir(s["name"], "teach")
        sid, dt1 = hermes(mem, wd, s["teach"], None, args.budget, hlog)
        if sid is None:
            say(f"  {s['name']:<18} hermes opened no session — see {hlog}")
            results[s["name"]]["teach"] = {"session": None}
            continue
        _, dt2 = hermes(mem, wd, s["correction"], sid, args.budget, hlog)
        results[s["name"]]["teach"] = {"session": sid, "seconds": round(dt1 + dt2)}
        say(f"  {s['name']:<18} session {sid[:12]}  {dt1 + dt2:5.0f}s")

    say("\nwriter — spool -> episodes -> triggers -> judge")
    cb("writer", "run", "--model", info["id"])
    claims = json.loads(cb("brief", "--project", PROJECT, "--json", "--budget", "2000",
                           quiet=True))["claims"]
    say(f"\n  standing claims after teaching: {len(claims)}")
    for c in claims:
        say(f"    - {c['claim']}  ({c['kind']}, {c.get('origin')})")

    say("\nprobe — same rule, new task, new session, brief injected by hook")
    for s in scenarios:
        wd = fresh_workdir(s["name"], "memory")
        sid, dt = hermes(mem, wd, s["probe"], None, args.budget, hlog)
        good, notes = check(wd, s["check"])
        results[s["name"]]["memory"] = {"pass": good, "checks": notes, "seconds": round(dt),
                                        "session": sid}
        say(f"  {s['name']:<18} {'PASS' if good else 'fail'}  {dt:5.0f}s  {'  '.join(notes)}")

    say("\nwriter — the probe sessions (use attribution, repeat corrections)")
    cb("writer", "run", "--model", info["id"])
    say()
    cb("usage", "report", "--project", PROJECT)
    cb("report", "--project", PROJECT)
    cb("pr", "list", "--project", PROJECT)

    n = len(scenarios)
    ctl = sum(1 for r in results.values() if r.get("control", {}).get("pass"))
    got = sum(1 for r in results.values() if r.get("memory", {}).get("pass"))
    say(f"\n  rule followed without being told again:"
        f"   no memory {ctl}/{n if not args.skip_control else 0}"
        f"   with memory {got}/{n}     ({(time.time() - t_start) / 60:.0f} min)")
    out = ROOT / "eval" / "results-sandbox-hermes.json"
    out.write_text(json.dumps({
        "model": info, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "scenarios": results,
        "claims": claims, "summary": {"n": n, "control": ctl, "memory": got}}, indent=2))
    say(f"  {out}\n  hermes transcripts: {hlog}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("preflight")
    r = sub.add_parser("run")
    r.add_argument("--only", nargs="*", help="scenario names")
    r.add_argument("--skip-control", action="store_true")
    r.add_argument("--budget", type=int, default=600, help="seconds per hermes turn")
    r.add_argument("--keep", action="store_true", help="keep the previous run's hermes homes")
    args = ap.parse_args()
    if args.cmd == "preflight":
        ok, _ = preflight()
        return 0 if ok else 2
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
