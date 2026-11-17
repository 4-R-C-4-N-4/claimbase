"""The two experimental arms receive equivalent confined filesystem tools."""
import json
from types import SimpleNamespace

import pytest
from test_sandbox_hermes import sandbox


@pytest.mark.parametrize('memory', [False, True])
def test_fileops_scope_and_launch_are_equal_across_arms(tmp_path, monkeypatch, memory):
    name = 'memory' if memory else 'control'
    home = sandbox.write_home(name, {'id': 'bonsai', 'ctx': 65536}, memory, work=tmp_path)
    cfg = json.loads((home / 'config.yaml').read_text())
    files = cfg['mcp_servers']['sandbox_files']
    assert files['tools']['include'] == ['rename_file', 'delete_file']
    assert files['args'][files['args'].index('--root') + 1] == str(tmp_path / 'work' / name)
    assert 'claimbase' in cfg['mcp_servers'] if memory else 'claimbase' not in cfg['mcp_servers']
    if memory:
        assert cfg['mcp_servers']['claimbase']['tools'] == {
            'include': ['recall'], 'resources': False, 'prompts': False}
    captured = {}

    def run(cmd, **kwargs):
        captured['cmd'] = cmd
        return SimpleNamespace(returncode=0, stdout='', stderr='')

    monkeypatch.setattr(sandbox.subprocess, 'run', run)
    sessions = iter([None, 'new'])
    monkeypatch.setattr(sandbox, 'latest_session', lambda _: next(sessions))
    sandbox.hermes(home, tmp_path / 'work' / name, 'task', None, 60, tmp_path / 'command.log')
    cmd = captured['cmd']
    actual = set(cmd[cmd.index('--toolsets') + 1].split(','))
    assert actual == {'file', 'mcp-sandbox_files'} | ({'mcp-claimbase'} if memory else set())
