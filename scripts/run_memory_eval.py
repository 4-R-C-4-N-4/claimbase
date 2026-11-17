#!/usr/bin/env python3
"""Run Phase 3 locally under a detached user systemd service.

Launch with systemd-run --user --unit=claimbase-memory-eval
  --property=RuntimeMaxSec=infinity --property=TimeoutStopSec=45
  --property=WorkingDirectory=/home/ivy/Work/claimbase-memory
  /home/ivy/Work/claimbase-memory/.venv/bin/python scripts/run_memory_eval.py

Only scratch stores/profiles are used. No cloud credentials are inherited.
A failed control is expected; completion and memory correctness are separate.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import shutil
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
MODEL = "/home/ivy/programs/bonsai/Ternary-Bonsai-2-27B-PQ2_0.gguf"
BASE = "http://127.0.0.1:8080"


def check_disk(path):
    free = shutil.disk_usage(path).free
    if free < 10 * 1024**3:
        raise RuntimeError(f'disk reserve breached: {free / 1024**3:.2f} GiB free; need 10 GiB')
    return free


def save(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, indent=2) + "\n")
    temp.replace(path)


def inspect_batch(path, expected_trials, expected_scenarios):
    batch = json.loads(path.read_text())
    trials = [json.loads(Path(t["path"]).read_text()) for t in batch["trials"]]
    complete = (batch["status"] != "running" and len(trials) == expected_trials
                and batch["attempted_trials"] == expected_trials)
    errors = list(batch.get("errors", []))
    memory = []
    for trial in trials:
        errors.extend(trial.get("errors", []))
        complete &= len(trial["scenarios"]) == expected_scenarios
        for scenario in trial["scenarios"].values():
            for arm in ("control", "teach", "memory"):
                terminal = ("completed", "fail") if arm == "teach" else ("pass", "fail")
                complete &= scenario.get(arm, {}).get("status") in terminal
            memory.append(scenario.get("memory", {}).get("status") == "pass")
    return {"report": str(path), "complete": bool(complete),
            "errors": errors, "memory_pass": sum(memory), "memory_total": len(memory),
            "memory_all_pass": bool(memory) and all(memory)}


def main():
    def interrupted(signum, _frame):
        raise RuntimeError(f"supervisor interrupted by signal {signum}")

    signal.signal(signal.SIGTERM, interrupted)
    root = ROOT / "eval/.sandbox" / f"durable-{time.time_ns()}"
    root.mkdir(parents=True)
    state = {"status": "starting", "directory": str(root), "batches": [],
             "limits": {"overall_seconds": None, "session_seconds": 3600,
                        "context_tokens": 65536, "judge_output_tokens": 16384}}
    status = root / "status.json"
    save(status, state)
    print(f"status: {status}", flush=True)
    # Explicit allowlist: no ambient cloud keys, provider routes or active home.
    env = {key: value for key, value in os.environ.items() if key in {
        "HOME", "USER", "PATH", "TMPDIR", "LANG", "LC_ALL", "XDG_RUNTIME_DIR",
        "DBUS_SESSION_BUS_ADDRESS"}}
    env.update({"PYTHONUNBUFFERED": "1", "TEMP": "1.0", "CTX_SIZE": "65536",
                "CLAIMBASE_SANDBOX_CACHE": str(root / 'uv-cache'),
                # Legacy libolm's CMake minimum predates CMake 4; this is a
                # documented external compatibility setting, scoped to our job.
                "CMAKE_POLICY_VERSION_MINIMUM": "3.5",
                "CUDA_DEVICE_ORDER": "PCI_BUS_ID", "CUDA_VISIBLE_DEVICES": "0",
                "LLAMACPP_BASE_URL": BASE, "CLAIMBASE_JUDGE_PROVIDER": "llamacpp",
                "CLAIMBASE_JUDGE_MODEL": MODEL, "CLAIMBASE_JUDGE_MAX_TOKENS": "16384",
                "HERMES_API_TIMEOUT": "3600", "HERMES_API_CALL_STALE_TIMEOUT": "3600",
                "HERMES_MODEL": MODEL, "HERMES_INFERENCE_PROVIDER": "custom",
                "OPENAI_BASE_URL": BASE + "/v1", "OPENAI_API_KEY": "EMPTY"})
    server = None
    try:
        state['free_bytes'] = check_disk(ROOT)
        state['dependency_cache'] = env['CLAIMBASE_SANDBOX_CACHE']
        save(status, state)
        # Never swap out somebody else's model or claim an existing server.
        try:
            urllib.request.urlopen(BASE + "/health", timeout=3).close()
        except OSError:
            pass
        else:
            raise RuntimeError("port 8080 already serves a model; refusing to replace it")
        with (root / "model.log").open("w") as log:
            server = subprocess.Popen(["/home/ivy/programs/model-runners/run-bonsai.sh"],
                                      env=env, stdout=log, stderr=subprocess.STDOUT)
            for _ in range(300):
                if server.poll() is not None:
                    raise RuntimeError(f"local server exited {server.returncode}; see model.log")
                try:
                    with urllib.request.urlopen(BASE + "/health", timeout=2) as response:
                        if response.status == 200:
                            break
                except OSError:
                    pass
                time.sleep(1)
            else:
                raise RuntimeError("local server startup exceeded 300 seconds")
            commands = [
                ("smoke", ["--only", "changed-rule"], 1, 1),
                ("full", [], 1, 9),
                ("repeated", ["--trials", "3", "--only", "report-naming", "changed-rule",
                              "opposite-project-a"], 3, 4),
            ]
            state["status"] = "running"
            save(status, state)
            for name, extra, trial_count, scenario_count in commands:
                before = set((ROOT / "eval/.sandbox").glob("run-*/results.json"))
                state["active_batch"] = name
                save(status, state)
                command = [str(ROOT / ".venv/bin/python"), "eval/sandbox_hermes.py", "run",
                           "--budget", "3600", *extra]
                print(f"starting {name}", flush=True)
                with (root / f"{name}.log").open("w") as output:
                    # No overall subprocess timeout: local evaluation outlives this chat.
                    state['free_bytes'] = check_disk(ROOT)
                    process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=output,
                                               stderr=subprocess.STDOUT)
                    try:
                        while True:
                            state['free_bytes'] = check_disk(ROOT)
                            save(status, state)
                            try:
                                code = process.wait(timeout=10)
                                break
                            except subprocess.TimeoutExpired:
                                continue
                    finally:
                        if process.poll() is None:
                            process.terminate()
                            try:
                                process.wait(timeout=30)
                            except subprocess.TimeoutExpired:
                                process.kill()
                                process.wait()
                reports = set((ROOT / "eval/.sandbox").glob("run-*/results.json")) - before
                if len(reports) != 1:
                    raise RuntimeError(f"expected exactly one new {name} report, found {len(reports)}")
                result = inspect_batch(reports.pop(), trial_count, scenario_count)
                result.update(name=name, exit_code=code)
                state["batches"].append(result)
                save(status, state)
                print(json.dumps(result), flush=True)
                if code not in (0, 1):
                    raise RuntimeError(f"{name} infrastructure error, exit {code}; see {name}.log")
                if name == 'smoke' and not (result['complete'] and result['memory_all_pass']
                                             and not result['errors']):
                    raise RuntimeError('changed-rule smoke did not pass; full batch not started')
            state["status"] = ("completed" if all(b["complete"] and not b["errors"]
                                                for b in state["batches"]) else "error")
            state["phase3_pass"] = (state["status"] == "completed" and
                                    all(b["memory_all_pass"] for b in state["batches"]))
    except Exception as exc:
        state.update(status="error", error=f"{type(exc).__name__}: {exc}")
    finally:
        if server is not None and server.poll() is None:
            server.terminate()
            try:
                server.wait(timeout=30)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
        state["server_stopped"] = server is None or server.poll() is not None
        state.pop("active_batch", None)
        save(status, state)
        print(json.dumps(state), flush=True)
    return 0 if state["status"] == "completed" else 2


if __name__ == "__main__":
    sys.exit(main())
