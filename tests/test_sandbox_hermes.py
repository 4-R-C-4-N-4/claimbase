"""Safety and launch contract for the real-model sandbox runner."""
import importlib.util
import json
import os
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

SPEC = importlib.util.spec_from_file_location(
    "sandbox_hermes", Path(__file__).resolve().parents[1] / "eval" / "sandbox_hermes.py"
)
assert SPEC is not None and SPEC.loader is not None
sandbox = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sandbox)


def test_launch_pins_file_tools_in_code_workspace(tmp_path, monkeypatch):
    captured = {}

    def run(cmd, **kwargs):
        captured.update(cmd=cmd, **kwargs)
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(sandbox.subprocess, "run", run)
    sessions = iter([None, "new-session"])
    monkeypatch.setattr(sandbox, "latest_session", lambda _: next(sessions))
    sandbox.hermes(tmp_path / "home-control", tmp_path, "test", None, 60,
                   tmp_path / "hermes.log")
    cmd = captured["cmd"]
    assert "--toolsets" in cmd
    assert cmd[cmd.index("--toolsets") + 1] == "file"
    assert "--ignore-rules" in cmd
    assert cmd[cmd.index('--skills') + 1] == 'sandbox-capabilities'


def test_launch_isolates_host_gateway_locks_per_home(tmp_path, monkeypatch):
    captured = []
    monkeypatch.setenv('HERMES_GATEWAY_LOCK_DIR', '/normal-host-locks')

    def run(cmd, **kwargs):
        captured.append(kwargs['env'])
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(sandbox.subprocess, 'run', run)
    sessions = iter([None, 'control-session', None, 'memory-session'])
    monkeypatch.setattr(sandbox, 'latest_session', lambda _: next(sessions))
    homes = [tmp_path / 'home-control', tmp_path / 'home-memory']
    for home in homes:
        sandbox.hermes(home, tmp_path, 'test', None, 60, tmp_path / f'{home.name}.log')
    for home, env in zip(homes, captured):
        expected = str(home / 'runtime/gateway-locks')
        assert env['HERMES_GATEWAY_LOCK_DIR'] == expected
        meta = json.loads((tmp_path / f'{home.name}.log.commands.jsonl').read_text())
        assert meta['gateway_lock_dir'] == expected
    assert captured[0]['HERMES_GATEWAY_LOCK_DIR'] != captured[1]['HERMES_GATEWAY_LOCK_DIR']


def test_memory_arm_only_exposes_recall(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "WORK", tmp_path)
    home = sandbox.write_home("memory", {"id": "bonsai", "ctx": 65536}, True)
    config = json.loads((home / "config.yaml").read_text())
    assert config["mcp_servers"]["claimbase"]["tools"]["include"] == ["recall"]


def test_fresh_homes_bound_unmanaged_gateway_lifetime_equally(tmp_path):
    for memory in (False, True):
        home = sandbox.write_home(f'idle-{memory}', {'id': 'bonsai', 'ctx': 65536},
                                  memory, work=tmp_path)
        config = json.loads((home / 'config.yaml').read_text())
        assert config['gateway']['unmanaged_idle_exit_seconds'] == 15


def test_fresh_homes_share_only_the_job_dependency_cache(tmp_path, monkeypatch):
    cache = tmp_path / 'job-cache'
    monkeypatch.setenv('CLAIMBASE_SANDBOX_CACHE', str(cache))
    a = sandbox.write_home('a', {'id': 'bonsai', 'ctx': 65536}, False, work=tmp_path)
    b = sandbox.write_home('b', {'id': 'bonsai', 'ctx': 65536}, True, work=tmp_path)
    assert (a / 'cache/uv').is_symlink()
    assert (b / 'cache/uv').resolve() == cache.resolve()
    assert (a / 'cache/uv').resolve() == cache.resolve()
    assert not (a / 'config.yaml').is_symlink()
    assert not (b / 'config.yaml').is_symlink()
    assert a != b


def test_latest_session_before_schema_initialization(tmp_path):
    (tmp_path / "state.db").touch()
    assert sandbox.latest_session(tmp_path) is None


def test_both_arms_document_available_deletion_without_teaching_house_rules(tmp_path):
    homes = [sandbox.write_home(str(memory), {'id': 'bonsai', 'ctx': 65536}, memory,
                                work=tmp_path) for memory in (False, True)]
    souls = [(home / 'SOUL.md').read_text() for home in homes]
    assert souls[0] == souls[1]
    assert 'sandbox_files' in souls[0] and 'rename_file' in souls[0] and 'delete_file' in souls[0]
    assert '*** Delete File:' not in souls[0]
    assert 'terminal tool is unavailable' in souls[0]
    assert 'automatically' in souls[0]
    assert 'rpt_' not in souls[0] and 'status-YYYY' not in souls[0]
    for home, soul in zip(homes, souls):
        skill = home / 'skills/sandbox-capabilities/SKILL.md'
        assert skill.is_file()
        assert soul in skill.read_text()


def test_guard_confines_reads_and_patch_headers_to_session_workdir(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "WORK", tmp_path)
    _, guard = sandbox.write_wrappers()
    home = tmp_path / "home"
    home.mkdir()
    wd = tmp_path / "work" / "scenario-control"
    wd.mkdir(parents=True)
    with sqlite3.connect(home / "state.db") as conn:
        conn.execute("CREATE TABLE sessions (id TEXT, cwd TEXT)")
        conn.execute("INSERT INTO sessions VALUES ('session', ?)", (str(wd),))

    def invoke(tool, args):
        result = subprocess.run(
            [str(guard)], input=json.dumps({"session_id": "session", "tool_name": tool,
                "tool_input": args, "cwd": str(tmp_path)}), text=True, capture_output=True,
            env={**os.environ, "HERMES_HOME": str(home)})
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout) if result.stdout.strip() else {}

    assert invoke("read_file", {"path": str(wd / "README.md")}) == {}
    assert invoke("read_file", {"path": str(tmp_path / "scenarios.toml")}).get("action") == "block"
    assert invoke("write_file", {"path": str(tmp_path / "work" / "other" / "x")}).get("action") == "block"
    assert invoke("patch", {"mode": "patch", "patch":
        "*** Begin Patch\n*** Add File: /outside/x\n+bad\n*** End Patch"}).get("action") == "block"


import pytest

@pytest.mark.parametrize('argv', [ ['run', '--only', 'typo'], ['run', '--trials', '0'],
    ['run', '--trials', '11'], ['run', '--trials', 'wat'], ['run', '--only'],
    ['run', '--budget', '0'], ['run', '--keep'] ])
def test_invalid_cli_rejected_before_preflight(argv, monkeypatch):
    monkeypatch.setattr(sandbox.sys, 'argv', ['sandbox', *argv])
    monkeypatch.setattr(sandbox, 'preflight', lambda: pytest.fail('invalid args reached preflight'))
    with pytest.raises(SystemExit) as e:
        sandbox.main()
    assert e.value.code == 2

@pytest.mark.parametrize('failure', ['exit', 'timeout', 'missing'])
def test_launch_infrastructure_errors(tmp_path, monkeypatch, failure):
    def run(cmd, **kwargs):
        if failure == 'timeout': raise subprocess.TimeoutExpired(cmd, 1)
        return SimpleNamespace(returncode=9 if failure == 'exit' else 0, stdout='', stderr='bad')
    monkeypatch.setattr(sandbox.subprocess, 'run', run)
    monkeypatch.setattr(sandbox, 'latest_session', lambda _: None)
    with pytest.raises(sandbox.InfrastructureError):
        sandbox.hermes(tmp_path/'home', tmp_path, 'x', None, 1, tmp_path/'log')
    meta = json.loads((tmp_path/'log.commands.jsonl').read_text().splitlines()[0])
    assert meta['status'] == 'error'
    assert 'elapsed' in meta and meta['prompt_sha256']


def test_expanded_scenarios_validated():
    scenarios = sandbox.load_scenarios()
    assert len(scenarios) >= 9
    assert {s['name'] for s in scenarios} == sandbox.CHECKERS
    changed = next(s for s in scenarios if s['name'] == 'changed-rule')
    assert len(changed['stages']) == 2
    assert all(s['checker'] == s['name'] and s['probe'] and s['stages'] for s in scenarios)


def test_contexts_and_homes_independent(tmp_path):
    a = sandbox.trial_context(tmp_path/'a', 10001)
    b = sandbox.trial_context(tmp_path/'b', 10002)
    assert a['CLAIMBASE_DSN'] != b['CLAIMBASE_DSN']
    assert a['CLAIMBASE_SPOOL'] != b['CLAIMBASE_SPOOL']
    for work, env in [(tmp_path/'a', a), (tmp_path/'b', b)]:
        home = sandbox.write_home('probe', {'id':'test','ctx':65536}, True,
                                  work=work, env={**env, 'CLAIMBASE_PROJECT':'own-scope'})
        cfg = json.loads((home/'config.yaml').read_text())
        assert cfg['mcp_servers']['claimbase']['env']['CLAIMBASE_PROJECT'] == 'own-scope'
        assert 'own-scope' in (work/'bin/probe/cb').read_text()
        assert not (home/'scenarios.toml').exists()


def test_batch_reports_preserved_after_reset_error(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, 'WORK', tmp_path/'batch')
    monkeypatch.setattr(sandbox, 'preflight', lambda: (True, {'id':'test','ctx':65536}))
    def fail_reset(env):
        raise sandbox.InfrastructureError('docker blocked')
    monkeypatch.setattr(sandbox, 'reset_store', fail_reset)
    args = SimpleNamespace(only=['report-naming'], trials=2, budget=1, skip_control=False)
    assert sandbox.run(args) == 2
    batch = json.loads((tmp_path/'batch/results.json').read_text())
    assert batch['attempted_trials'] == 2
    assert batch['trial_denominators']['error'] == 2
    stores = []
    for trial in batch['trials']:
        report = json.loads(Path(trial['path']).read_text())
        assert report['status'] == 'error' and report['errors']
        assert 'docker blocked' in report['errors'][0]['error']
        stores.append(report['stores']['memory']['CLAIMBASE_DSN'])
    assert len(set(stores)) == 2


def test_preflight_error_report_preserved(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, 'WORK', tmp_path/'batch')
    monkeypatch.setattr(sandbox, 'preflight', lambda: (False, None))
    assert sandbox.run(SimpleNamespace(only=None, trials=1, budget=1)) == 2
    report = json.loads((tmp_path/'batch/results.json').read_text())
    assert report['status'] == 'error' and report['attempted_trials'] == 0


def test_checker_fail_is_counted_separately_from_infrastructure():
    report = {'a':{'control':{'status':'fail','task_pass':False},
                    'memory':{'status':'error','error':'timeout'}}}
    assert sandbox.summarize(report) == {'attempted':2,'pass':0,'fail':1,'error':1}


def test_malformed_scenario_config_rejected(tmp_path):
    p = tmp_path/'bad.toml'
    p.write_text('[[scenario]]\nname="report-naming"\nchecker="exec"\nprobe="x"\nstages=[]\n')
    with pytest.raises(ValueError): sandbox.load_scenarios(p)


def test_finalize_requires_actual_ended_hook_capture(tmp_path):
    home=tmp_path/'home'
    home.mkdir()
    with sqlite3.connect(home/'state.db') as conn:
        conn.execute('CREATE TABLE sessions(id TEXT, ended_at TEXT)')
        conn.execute("INSERT INTO sessions VALUES('sid', NULL)")
    env = sandbox.trial_context(tmp_path, 123)
    with pytest.raises(sandbox.InfrastructureError, match='not finalized'):
        sandbox.finalized(home, 'sid', env)
    with sqlite3.connect(home/'state.db') as conn:
        conn.execute("UPDATE sessions SET ended_at='now'")
    with pytest.raises(sandbox.InfrastructureError, match='hook did not submit'):
        sandbox.finalized(home, 'sid', env)


def test_untrusted_fixture_only_reaches_its_own_teach_stage(tmp_path):
    for scenario, arm, present in [('report-naming', 'control', False),
            ('untrusted-tool-evidence', 'teach-1', True),
            ('untrusted-tool-evidence', 'memory', False),
            ('untrusted-tool-evidence', 'control', False)]:
        wd = sandbox.fresh_workdir(scenario, arm, work=tmp_path)
        assert (wd / 'tool-evidence.txt').exists() is present
        assert (wd / 'README.md').exists()


def test_opposite_projects_are_selected_as_a_pair():
    names = [s['name'] for s in sandbox.select_scenarios(['opposite-project-a'])]
    assert names == ['opposite-project-a', 'opposite-project-b']
    assert len(sandbox.select_scenarios(None)) == len(sandbox.CHECKERS)
