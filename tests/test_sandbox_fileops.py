"""Filesystem capability contract independent of model-specific patch dialects."""
import importlib.util
import asyncio
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_ops():
    spec = importlib.util.spec_from_file_location('sandbox_fileops', ROOT / 'eval/sandbox_fileops.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_rename_preserves_contents_and_removes_old_name(tmp_path):
    ops = load_ops().FileOps(tmp_path)
    (tmp_path / 'old.md').write_text('report\n')
    ops.rename_file('old.md', 'new.md')
    assert not (tmp_path / 'old.md').exists()
    assert (tmp_path / 'new.md').read_text() == 'report\n'


def test_delete_removes_only_the_requested_file(tmp_path):
    ops = load_ops().FileOps(tmp_path)
    (tmp_path / 'old.md').write_text('old')
    (tmp_path / 'keep.md').write_text('keep')
    ops.delete_file(str(tmp_path / 'old.md'))
    assert not (tmp_path / 'old.md').exists()
    assert (tmp_path / 'keep.md').read_text() == 'keep'


@pytest.mark.parametrize('attack', ['absolute', 'traversal', 'symlink-parent', 'symlink-leaf'])
def test_both_operations_refuse_escape(tmp_path, attack):
    root = tmp_path / 'scenario'
    root.mkdir()
    outside = tmp_path / 'outside.md'
    outside.write_text('untouched')
    ops = load_ops().FileOps(root)
    if attack == 'absolute':
        path = str(outside)
    elif attack == 'traversal':
        path = '../outside.md'
    elif attack == 'symlink-parent':
        (root / 'escape').symlink_to(tmp_path, target_is_directory=True)
        path = 'escape/outside.md'
    else:
        (root / 'escape.md').symlink_to(outside)
        path = 'escape.md'
    for action in (lambda: ops.delete_file(path), lambda: ops.rename_file(path, 'new.md')):
        with pytest.raises((ValueError, OSError)):
            action()
    assert outside.read_text() == 'untouched'
    assert not (root / 'new.md').exists()


def test_rename_never_overwrites_destination(tmp_path):
    ops = load_ops().FileOps(tmp_path)
    (tmp_path / 'a').write_text('a')
    (tmp_path / 'b').write_text('b')
    with pytest.raises(FileExistsError):
        ops.rename_file('a', 'b')
    assert (tmp_path / 'a').read_text() == 'a'
    assert (tmp_path / 'b').read_text() == 'b'


def test_real_stdio_server_advertises_and_executes_only_confined_file_operations(tmp_path):
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client

    root = tmp_path / 'scenario'
    root.mkdir()
    (root / 'old.md').write_text('report')
    outside = tmp_path / 'outside.md'
    outside.write_text('untouched')
    audit = tmp_path / 'operations.jsonl'

    async def exercise():
        params = StdioServerParameters(command=str(ROOT / '.venv/bin/python'), args=[
            str(ROOT / 'eval/sandbox_fileops.py'), '--root', str(root), '--audit', str(audit)])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write, read_timeout_seconds=10) as session:
                await session.initialize()
                tools = (await session.list_tools()).tools
                assert {t.name for t in tools} == {'rename_file', 'delete_file'}
                result = await session.call_tool('rename_file', {'source': 'old.md', 'destination': 'new.md'})
                assert not result.is_error
                assert (root / 'new.md').read_text() == 'report'
                assert not (root / 'old.md').exists()
                denied = await session.call_tool('delete_file', {'path': str(outside)})
                assert denied.is_error
                result = await session.call_tool('delete_file', {'path': 'new.md'})
                assert not result.is_error

    asyncio.run(exercise())
    assert outside.read_text() == 'untouched'
    assert not (root / 'new.md').exists()
    rows = [json.loads(line) for line in audit.read_text().splitlines()]
    assert [r['tool'] for r in rows] == ['rename_file', 'rename_file', 'delete_file',
                                       'delete_file', 'delete_file', 'delete_file']
    assert [r['status'] for r in rows] == ['started', 'ok', 'started', 'error', 'started', 'ok']
    assert rows[2]['arguments']['path'] == str(outside)
    assert rows[2]['call_id'] == rows[3]['call_id']
    assert 'inside this scenario' in rows[3]['error']


def test_unwritable_audit_refuses_before_mutation(tmp_path):
    module = load_ops()
    victim = tmp_path / 'keep.md'
    victim.write_text('keep')
    with pytest.raises(IsADirectoryError):
        module.call_audited(tmp_path, tmp_path, 'delete_file', {'path': 'keep.md'},
                            lambda: module.FileOps(tmp_path).delete_file('keep.md'))
    assert victim.read_text() == 'keep'
