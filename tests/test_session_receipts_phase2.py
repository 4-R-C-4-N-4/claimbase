import json
import sqlite3
import uuid

import pytest

from claimbase import sessions


@pytest.mark.parametrize("mode,accepted", [("batch", True), ("direct", True),
    ("duplicate", False), ("other", False), ("prose", False)])
def test_hermes_batch_receipt_before_clipping(tmp_path, mode, accepted):
    db = tmp_path / 'state.db'
    conn = sqlite3.connect(db)
    conn.executescript('CREATE TABLE sessions (id text, started_at text, ended_at text); CREATE TABLE messages (id integer, session_id text, role text, content text, tool_calls text, tool_name text, tool_call_id text, timestamp text);')
    conn.execute('INSERT INTO sessions VALUES (?,NULL,NULL)', ('s',))
    receipt = str(uuid.uuid4())
    call = [{'id': 'call1', 'function': {'name': 'tool_call', 'arguments': json.dumps({'calls': [{'name': 'mcp__claimbase__recall', 'arguments': {'query': 'q'}}]})}}]
    if mode == "direct":
        call[0]['function'] = {'name': 'mcp__claimbase__recall', 'arguments': '{}'}
    elif mode == "duplicate":
        args = json.loads(call[0]['function']['arguments'])
        args['calls'] *= 2
        call[0]['function']['arguments'] = json.dumps(args)
    elif mode == "other":
        call[0]['function'] = {'name': 'read_file', 'arguments': '{}'}
    elif mode == "prose":
        call = []
    payload = {'_claimbase' : {'call_id': receipt, 'tool': 'recall'}, 'results': [{'id': 'c', 'claim': 'x' * 5000}]}
    wrapped = '<untrusted_tool_result source="mcp__claimbase__recall">\nwarning\n\n' + json.dumps({'result': json.dumps(payload)}) + '\n</untrusted_tool_result>'
    conn.execute('INSERT INTO messages VALUES (1,?,?,?,?,?,?,NULL)', ('s', 'assistant', '', json.dumps(call), None, None))
    conn.execute('INSERT INTO messages VALUES (2,?,?,?,?,?,?,NULL)', ('s', 'tool', wrapped, None, None, 'call1'))
    conn.commit()
    conn.close()
    session = sessions.read_hermes('s', db)
    result = session.turns[-1]
    assert result.receipt == (receipt if accepted else None)
    if accepted:
        assert sessions.returned_claims(result)[0]['id'] == 'c'
    else:
        assert sessions.returned_claims(result) == []
    assert len(result.text) < len(wrapped)


def test_unrelated_tool_cannot_claim_receipt():
    payload = json.dumps({'_claimbase': {'call_id': str(uuid.uuid4()), 'tool': 'recall'}, 'results': [{'id': 'c'}]})
    turn = sessions.Turn('tool_result', payload, tool='read_file')
    assert sessions.returned_claims(turn) == []


@pytest.mark.parametrize('harness,project,tool', [
    ('claude', 'guru', 'recall'), ('hermes', 'other', 'recall'), ('hermes', 'guru', 'brief')])
def test_late_sync_exact_identity_and_conflict(db, tmp_path, harness, project, tool):
    from claimbase import usage, writer
    from conftest import seed_claim
    from datetime import datetime, timezone

    claim = seed_claim(db, 'Use the release tag for deployment.')
    receipt = str(uuid.uuid4())
    turn = sessions.Turn('tool_result', '', tool='mcp__claimbase__recall',
                         receipt=receipt, receipt_tool='recall')
    owner = sessions.Session('hermes', 'same', [turn], project='guru')
    writer.ingest(db, owner)
    other_turn = sessions.Turn('tool_result', '', tool='mcp__claimbase__' + tool, receipt=receipt, receipt_tool=tool)
    writer.ingest(db, sessions.Session(harness, 'other', [other_turn], project=project))
    log = tmp_path / 'log.jsonl'
    log.write_text(json.dumps({'ts': datetime.now(timezone.utc).isoformat(),
        'tool': 'recall', 'project': 'guru', 'call_id': receipt,
        'response': {'results': [{'id': claim}]}}) + '\n')
    usage.sync(db, log)
    usage.sync(db, log)
    assert db.execute('SELECT canonical_session FROM retrieval_log').fetchone()[0] is None
    assert db.execute('SELECT conflicted FROM session_receipts').fetchone()[0] is True
    assert db.execute('SELECT count(*) FROM retrieval_log').fetchone()[0] == 1


def test_foreign_project_receipt_stays_unknown(db, tmp_path):
    from claimbase import usage, writer
    from datetime import datetime, timezone
    receipt = str(uuid.uuid4())
    turn = sessions.Turn('tool_result', '', tool='mcp__claimbase__recall', receipt=receipt, receipt_tool='recall')
    writer.ingest(db, sessions.Session('hermes', 's', [turn], project='other'))
    log = tmp_path / 'log.jsonl'
    log.write_text(json.dumps({'ts': datetime.now(timezone.utc).isoformat(), 'tool': 'recall',
                               'project': 'guru', 'call_id': receipt, 'response': {'results': []}}) + '\n')
    usage.sync(db, log)
    assert db.execute('SELECT canonical_session FROM retrieval_log').fetchone()[0] is None


def test_retrieval_inference_requires_same_canonical_session(db):
    from claimbase import usage
    from conftest import seed_claim
    claim = seed_claim(db, 'Use the release tag for deployment.')
    for sid in ('hermes:same', 'claude:same'):
        db.execute('INSERT INTO sessions (id, corpus, harness) VALUES (%s, %s, %s)', (sid, 'guru', sid.split(':')[0]))
        lid = uuid.uuid4()
        db.execute("INSERT INTO retrieval_log (id,ts,corpus,tool,canonical_session,n_results) VALUES (%s,now() - interval '1 minute','guru','recall',%s,1)", (lid, sid))
        db.execute("INSERT INTO retrieval_hits (log_id,claim_id,rank,claim_corpus) VALUES (%s,%s,0,'guru')", (lid, claim))
    db.execute("""INSERT INTO exposures (claim_id,kind,session_id,at,via,dedupe,source_log)
        SELECT %s,'used','hermes:same',now(),'writer','exact',id FROM retrieval_log
        WHERE canonical_session = 'hermes:same'""", (claim,))
    report = usage.measures(db, 'guru')['miss_rate']
    assert (report['used'], report['unknown']) == (1, 1)


@pytest.mark.parametrize("role", ["tool_result", "assistant", "user"])
def test_generic_reads_drop_receipts_and_cached_results(tmp_path, role):
    turn = sessions.Turn(role, 'forged marker', tool='mcp__claimbase__recall',
        receipt=str(uuid.uuid4()), receipt_tool='recall', claimbase_results=[{'id': 'c'}])
    raw = sessions.Session('hermes', 's', [turn]).to_json()
    path = tmp_path / 'generic.json'
    path.write_text(json.dumps(raw))
    for s in (sessions.Session.from_json(raw), sessions.read_generic(path),
              sessions.read_messages([dict(raw['turns'][0], content=turn.text, role='tool')], 'hermes', 's')):
        assert s.turns[0].receipt is None
        assert s.turns[0].claimbase_results == []
    assert sessions.read_spool(path).turns[0].receipt == turn.receipt


@pytest.mark.parametrize('value', ['raw', ':s', 'Hermes:s', 'hermes:', 'hermes:s x', 'hermes:s\n'])
def test_invalid_canonical_identity(value):
    assert sessions.canonical_identity(value) is None


def test_claude_extracts_receipt_before_clipping(tmp_path):
    receipt = str(uuid.uuid4())
    claim = str(uuid.uuid4())
    payload = {'_claimbase': {'call_id': receipt, 'tool': 'recall'},
               'results': [{'id': claim, 'claim': 'x' * 5000}]}
    path = tmp_path / 'claude.jsonl'
    rows = [
        {'type': 'assistant', 'message': {'content': [
            {'type': 'tool_use', 'id': 'c', 'name': 'mcp__claimbase__recall', 'input': {'query': 'q'}}]}},
        {'type': 'user', 'message': {'content': [
            {'type': 'tool_result', 'tool_use_id': 'c', 'content': json.dumps(payload)}]}}]
    path.write_text('\n'.join(json.dumps(row) for row in rows))
    captured = sessions.read_claude(path)
    result = captured.turns[-1]
    assert result.receipt == receipt
    assert sessions.returned_claims(result)[0]['id'] == claim
    assert len(result.text) < 5000


@pytest.mark.parametrize('tool', ['recall', 'brief'])
def test_logged_delivery_cannot_credit_text_before_its_receipt(db, tmp_path, tool):
    from claimbase import usage, writer
    from conftest import seed_claim
    text = 'Deploy using the signed release artifact from the staging bucket.'
    claim = seed_claim(db, text)
    receipt = str(uuid.uuid4())
    s = sessions.Session('hermes', 'ordered', [
        sessions.Turn('assistant', text),
        sessions.Turn('tool_result', '', tool='mcp__claimbase__' + tool,
                      receipt=receipt, receipt_tool=tool, claimbase_results=[])], project='guru')
    writer.ingest(db, s)
    path = tmp_path / 'log'
    _write_log(path, receipt=receipt, claim=claim, tool=tool)
    usage.sync(db, path)
    assert writer.ingest(db, s)['used'] == 0
    assert usage.measures(db, 'guru')['inference']['claim_uses'] == 0


def test_reingest_retracts_old_pre_delivery_inference(db, tmp_path):
    from claimbase import usage, writer
    from conftest import seed_claim
    text = 'Deploy using the signed release artifact from the staging bucket.'
    claim = seed_claim(db, text)
    receipt = str(uuid.uuid4())
    s = sessions.Session('hermes', 'upgrade', [sessions.Turn('assistant', text),
        sessions.Turn('tool_result', '', tool='mcp__claimbase__recall',
                      receipt=receipt, receipt_tool='recall', claimbase_results=[])], project='guru')
    writer.ingest(db, s)
    path = tmp_path / 'log'
    _write_log(path, receipt=receipt, claim=claim)
    usage.sync(db, path)
    db.execute('''INSERT INTO exposures (claim_id, kind, session_id, turn, via, dedupe, source_log)
        SELECT %s, 'used', %s, 0, 'writer', %s, id FROM retrieval_log''',
        (claim, s.id, 'session:' + s.id))
    assert usage.measures(db, 'guru')['inference']['claim_uses'] == 1
    writer.ingest(db, s)
    assert usage.measures(db, 'guru')['inference']['claim_uses'] == 0


@pytest.mark.parametrize('ts', [None, '2026-11-16T10:00:00+00:00', '2026-11-16T09:59:00+00:00'])
def test_log_only_delivery_without_later_timestamp_stays_unknown(db, tmp_path, ts):
    from claimbase import usage, writer
    from conftest import seed_claim
    text = 'Deploy using the signed release artifact from the staging bucket.'
    claim = seed_claim(db, text)
    path = tmp_path / 'log'
    _write_log(path, canonical='hermes:no-order', claim=claim, ts='2026-11-16T10:00:00+00:00')
    usage.sync(db, path)
    s = sessions.Session('hermes', 'no-order', [sessions.Turn('assistant', text, ts=ts)], project='guru')
    assert writer.ingest(db, s)['used'] == 0
    assert usage.measures(db, 'guru')['miss_rate']['unknown'] == 1


def test_log_only_writer_inference_is_revoked_when_receipt_conflicts(db, tmp_path):
    from claimbase import usage, writer
    from conftest import seed_claim
    text = 'Deploy using the signed release artifact from the staging bucket.'
    claim = seed_claim(db, text)
    receipt = str(uuid.uuid4())
    turn = sessions.Turn('tool_result', '', tool='mcp__claimbase__recall',
                         receipt=receipt, receipt_tool='recall', claimbase_results=[])
    a = sessions.Session('hermes', 'a', [turn, sessions.Turn('assistant', text)], project='guru')
    writer.ingest(db, a)
    path = tmp_path / 'log'
    _write_log(path, receipt=receipt, claim=claim)
    usage.sync(db, path)
    assert writer.ingest(db, a)['used'] == 1
    assert usage.measures(db, 'guru')['inference']['claim_uses'] == 1
    writer.ingest(db, sessions.Session('hermes', 'b', [turn], project='guru'))
    usage.sync(db, path)
    assert usage.measures(db, 'guru')['inference']['claim_uses'] == 0
    assert db.execute('SELECT canonical_session FROM retrieval_log').fetchone()[0] is None


def test_revocation_keeps_inference_supported_by_another_valid_delivery(db, tmp_path):
    from claimbase import usage, writer
    from conftest import seed_claim
    text = 'Deploy using the signed release artifact from the staging bucket.'
    claim = seed_claim(db, text)
    receipts = [str(uuid.uuid4()), str(uuid.uuid4())]
    turns = [sessions.Turn('tool_result', '', tool='mcp__claimbase__recall',
             receipt=receipt, receipt_tool='recall', claimbase_results=[]) for receipt in receipts]
    a = sessions.Session('hermes', 'a', turns + [sessions.Turn('assistant', text)], project='guru')
    writer.ingest(db, a)
    path = tmp_path / 'log'
    for receipt in receipts:
        _write_log(path, receipt=receipt, claim=claim)
    usage.sync(db, path)
    writer.ingest(db, a)
    source, receipt = db.execute('''SELECT x.source_log, l.call_id::text FROM exposures x
        JOIN retrieval_log l ON l.id=x.source_log WHERE x.via='writer' ''').fetchone()
    conflicting = next(turn for turn in turns if turn.receipt == receipt)
    writer.ingest(db, sessions.Session('hermes', 'b', [conflicting], project='guru'))
    usage.sync(db, path)
    assert usage.measures(db, 'guru')['inference']['claim_uses'] == 1
    assert db.execute("SELECT source_log FROM exposures WHERE via='writer'").fetchone()[0] != source


def test_report_does_not_credit_recall_after_an_earlier_supported_action(db, tmp_path):
    from claimbase import usage, writer
    from conftest import seed_claim
    text = 'Deploy using the signed release artifact from the staging bucket.'
    claim = seed_claim(db, text)
    early, late = [str(uuid.uuid4()) for _ in range(2)]
    turns = [sessions.Turn('tool_result', '', tool='mcp__claimbase__recall',
             receipt=r, receipt_tool='recall', claimbase_results=[]) for r in (early, late)]
    s = sessions.Session('hermes', 'report-order', [turns[0],
        sessions.Turn('assistant', text, ts='2026-11-16T10:00:30+00:00'), turns[1]], project='guru')
    writer.ingest(db, s)
    path = tmp_path / 'log'
    _write_log(path, receipt=early, claim=claim, ts='2026-11-16T10:00:00+00:00')
    _write_log(path, receipt=late, claim=claim, ts='2026-11-16T10:01:00+00:00')
    usage.sync(db, path)
    assert writer.ingest(db, s)['used'] == 1
    report = usage.measures(db, 'guru')['miss_rate']
    assert (report['used'], report['unknown']) == (1, 1)


def test_revocation_cannot_replace_credit_with_a_later_delivery(db, tmp_path):
    from claimbase import usage, writer
    from conftest import seed_claim
    text = 'Deploy using the signed release artifact from the staging bucket.'
    claim = seed_claim(db, text)
    early, late = [str(uuid.uuid4()) for _ in range(2)]
    turns = [sessions.Turn('tool_result', '', tool='mcp__claimbase__recall',
             receipt=r, receipt_tool='recall', claimbase_results=[]) for r in (early, late)]
    s = sessions.Session('hermes', 'ordered', [turns[0],
        sessions.Turn('assistant', text), turns[1]], project='guru')
    writer.ingest(db, s)
    path = tmp_path / 'log'
    for receipt in (early, late):
        _write_log(path, receipt=receipt, claim=claim)
    usage.sync(db, path)
    assert writer.ingest(db, s)['used'] == 1
    assert db.execute('SELECT turn FROM exposures WHERE source_log IS NOT NULL').fetchone() == (1,)
    writer.ingest(db, sessions.Session('hermes', 'conflicting', [turns[0]], project='guru'))
    usage.sync(db, path)
    assert usage.measures(db, 'guru')['inference']['claim_uses'] == 0


def test_canonical_harness_collision():
    assert sessions.canonical_identity('hermes:s') != sessions.canonical_identity('claude:s')


def _write_log(path, *, receipt=None, canonical=None, tool='recall', claim=None, **extra):
    from datetime import datetime, timezone
    rec = {'ts': datetime.now(timezone.utc).isoformat(), 'tool': tool, 'project': 'guru',
           'session': 'immutable-raw', 'call_id': receipt, 'canonical_session': canonical,
           'args': {'kind': 'helpful', 'claim_id': claim},
           'response': {'claim_id': claim, 'results': [{'id': claim}] if claim else []}, **extra}
    with path.open('a') as f:
        f.write(json.dumps(rec) + '\n')
    return rec


@pytest.mark.parametrize('tool', ['recall', 'feedback'])
def test_duplicate_events_revoke_binding_but_identical_line_is_idempotent(db, tmp_path, tool):
    from claimbase import usage, writer
    from conftest import seed_claim
    claim = seed_claim(db, 'Deploy using the signed release artifact.')
    receipt = str(uuid.uuid4())
    turn = sessions.Turn('tool_result', '', tool='mcp__claimbase__' + tool,
                         receipt=receipt, receipt_tool=tool)
    writer.ingest(db, sessions.Session('hermes', 'a', [turn], project='guru'))
    path = tmp_path / 'log'
    rec = _write_log(path, receipt=receipt, tool=tool, claim=claim)
    usage.sync(db, path)
    table = 'feedback' if tool == 'feedback' else 'retrieval_log'
    assert db.execute(f'SELECT canonical_session FROM {table}').fetchone()[0] == 'hermes:a'
    with path.open('a') as f:
        f.write(json.dumps(rec) + '\n')
    usage.sync(db, path)
    assert db.execute(f'SELECT count(*) FROM {table}').fetchone()[0] == 1
    _write_log(path, receipt=receipt, tool=tool, claim=claim, ms=123)
    usage.sync(db, path)
    assert db.execute(f'SELECT canonical_session FROM {table}').fetchall() == [(None,), (None,)]
    assert db.execute("SELECT count(*) FROM exposures WHERE via='feedback'").fetchone()[0] == 0


def test_conflict_revokes_prior_feedback_and_stays_conflicted(db, tmp_path):
    from claimbase import usage, writer
    from conftest import seed_claim
    claim = seed_claim(db, 'Deploy using the signed release artifact.')
    receipt = str(uuid.uuid4())
    turn = sessions.Turn('tool_result', '', tool='mcp__claimbase__feedback', receipt=receipt, receipt_tool='feedback')
    a = sessions.Session('hermes', 'a', [turn], project='guru')
    writer.ingest(db, a)
    path = tmp_path / 'log'
    _write_log(path, receipt=receipt, tool='feedback', claim=claim)
    usage.sync(db, path)
    assert db.execute("SELECT count(*) FROM exposures WHERE via='feedback'").fetchone()[0] == 1
    writer.ingest(db, sessions.Session('hermes', 'b', [turn], project='guru'))
    writer.ingest(db, a)
    usage.sync(db, path)
    assert db.execute('SELECT canonical_session FROM feedback').fetchone()[0] is None
    assert db.execute("SELECT count(*) FROM exposures WHERE via='feedback'").fetchone()[0] == 0


@pytest.mark.parametrize('tool', ['recall', 'feedback'])
def test_declared_identity_cannot_be_overridden_by_other_receipt_owner(db, tmp_path, tool):
    from claimbase import usage, writer
    from conftest import seed_claim
    claim = seed_claim(db, 'Use the signed artifact.')
    receipt = str(uuid.uuid4())
    writer.ingest(db, sessions.Session('hermes', 'declared', [], project='guru'))
    path = tmp_path / 'log'
    _write_log(path, receipt=receipt, canonical='hermes:declared', tool=tool, claim=claim)
    usage.sync(db, path)
    turn = sessions.Turn('tool_result', '', tool='mcp__claimbase__' + tool,
                         receipt=receipt, receipt_tool=tool)
    writer.ingest(db, sessions.Session('hermes', 'different', [turn], project='guru'))
    usage.sync(db, path)
    table = 'feedback' if tool == 'feedback' else 'retrieval_log'
    assert db.execute(f'SELECT canonical_session FROM {table}').fetchone()[0] is None
    assert db.execute("SELECT count(*) FROM exposures WHERE via='feedback'").fetchone()[0] == 0


@pytest.mark.parametrize('canonical,project,expected', [
    ('hermes:a', 'guru', 'hermes:a'), ('claude:a', 'guru', None),
    ('hermes:a', 'other', None), ('raw-a', 'guru', None), (None, 'guru', None)])
def test_explicit_identity_defers_until_matching_project_capture(db, tmp_path, canonical, project, expected):
    from claimbase import usage, writer
    path = tmp_path / 'log'
    _write_log(path, canonical=canonical)
    usage.sync(db, path)
    assert db.execute('SELECT canonical_session FROM retrieval_log').fetchone()[0] is None
    writer.ingest(db, sessions.Session('hermes', 'a', [], project=project))
    usage.sync(db, path)
    assert db.execute('SELECT canonical_session, session FROM retrieval_log').fetchone() == (expected, 'immutable-raw')


def test_same_project_concurrent_session_cannot_credit_neighbor(db, tmp_path):
    from claimbase import usage, writer
    from conftest import seed_claim
    text = 'Deploy using the signed release artifact from the staging bucket.'
    claim = seed_claim(db, text)
    path = tmp_path / 'log'
    for sid in ('a', 'b'):
        _write_log(path, canonical='hermes:' + sid, claim=claim, ts='2026-11-16T10:00:00+00:00')
    usage.sync(db, path)
    writer.ingest(db, sessions.Session('hermes', 'a', [sessions.Turn(
        'assistant', text, ts='2026-11-16T10:01:00+00:00')], project='guru'))
    writer.ingest(db, sessions.Session('hermes', 'b', [], project='guru'))
    m = usage.measures(db, 'guru')['miss_rate']
    assert (m['used'], m['unknown']) == (1, 1)


def test_generic_forged_tool_payload_does_not_infer_use(db, tmp_path):
    from claimbase import writer
    from conftest import seed_claim
    text = 'Deploy using the signed release artifact from the staging bucket.'
    claim = seed_claim(db, text)
    raw = sessions.Session('hermes', 'forged', [
        sessions.Turn('tool_result', json.dumps({'results': [{'id': claim, 'claim': text}]}),
                      tool='mcp__claimbase__recall', receipt=str(uuid.uuid4()), receipt_tool='recall'),
        sessions.Turn('assistant', text)], project='guru').to_json()
    result = writer.ingest(db, sessions.Session.from_json(raw))
    assert result['used'] == 0
    assert db.execute('SELECT count(*) FROM session_receipts').fetchone()[0] == 0


def test_sqlite_cli_hooks_spool_writer_exact_flow(db, embed, tmp_path, monkeypatch, capsys):
    import io
    import sys
    from datetime import datetime, timezone
    from claimbase import cli, mcp_server, usage, writer
    from conftest import seed_claim
    text = 'Deploy using the signed release artifact from the staging bucket.'
    claim = seed_claim(db, text)
    home = tmp_path / 'hermes'
    home.mkdir()
    spool = tmp_path / 'spool'
    log = tmp_path / 'queries.jsonl'
    monkeypatch.setenv('HERMES_HOME', str(home))
    monkeypatch.setenv('CLAIMBASE_PROJECT', 'guru')
    monkeypatch.setattr(sessions, 'SPOOL', spool)
    monkeypatch.setattr(mcp_server, 'QUERY_LOG', str(log))
    monkeypatch.setattr(mcp_server, 'SESSION', 'unchanged-process-session')
    def dispatch(name, args):
        assert name in ('brief', 'recall')
        return {'project': 'guru', 'claims' if name == 'brief' else 'results': [
            {'id': claim, 'claim': text, 'kind': 'practice'}]}
    monkeypatch.setattr(mcp_server, '_dispatch_inner', dispatch)
    ctx = {'hook_event_name': 'pre_llm_call', 'session_id': 'flow',
           'extra': {'is_first_turn': True}}
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps(ctx)))
    assert cli.main(['--no-backup', 'hook', 'brief', '--project', 'guru']) == 0
    assert text in capsys.readouterr().out
    result = mcp_server._dispatch('recall', {'project': 'guru'})
    receipt = result['_claimbase']['call_id']
    call = [{'id': 'c1', 'function': {'name': 'tool_call', 'arguments': json.dumps({
        'calls': [{'name': 'mcp__claimbase__recall', 'arguments': {'query': 'deploy'}}]})}}]
    envelope = '<untrusted_tool_result source="mcp__claimbase__recall">\nwarning\n\n' + json.dumps({'result': json.dumps(result)}) + '\n</untrusted_tool_result>'
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(home / 'state.db') as c:
        c.executescript('CREATE TABLE sessions (id text, started_at text, ended_at text); CREATE TABLE messages (id integer, session_id text, role text, content text, tool_calls text, tool_name text, tool_call_id text, timestamp text);')
        c.execute('INSERT INTO sessions VALUES (?,?,?)', ('flow', now, now))
        for row in [(1, 'assistant', '', json.dumps(call), None),
                    (2, 'tool', envelope, None, 'c1'), (3, 'assistant', text, None, None)]:
            c.execute('INSERT INTO messages VALUES (?, ?, ?, ?, ?, NULL, ?, ?)',
                      (row[0], 'flow', *row[1:], now))
    usage.sync(db, log)
    assert db.execute('SELECT canonical_session FROM retrieval_log').fetchall() == [(None,), (None,)]
    monkeypatch.setattr(sys, 'stdin', io.StringIO(json.dumps({'session_id': 'flow', 'extra': {'reason': 'cli_close'}})))
    assert cli.main(['--no-backup', 'submit-session', '--harness', 'hermes', '--hook']) == 0
    queued = sessions.read_spool(sessions.pending()[0])
    assert queued.turns[1].receipt == receipt
    r = writer.run(db, spool=spool, log=lambda *_: None)
    assert r['used'] == 1
    assert db.execute('SELECT canonical_session FROM retrieval_log').fetchall() == [('hermes:flow',), ('hermes:flow',)]
    assert mcp_server.SESSION == 'unchanged-process-session'
    assert writer._archived('hermes:flow', spool).turns[1].receipt == receipt
    usage.sync(db, log)
    assert db.execute('SELECT count(*) FROM exposures').fetchone()[0] == 1


@pytest.mark.parametrize('canonical,expected', [('hermes:a', 1), ('legacy-a', 0), ('claude:a', 0)])
def test_explicit_canonical_feedback_variant(db, tmp_path, canonical, expected):
    from claimbase import usage, writer
    from conftest import seed_claim
    claim = seed_claim(db, 'Deploy using the signed release artifact.')
    writer.ingest(db, sessions.Session('hermes', 'a', [], project='guru'))
    path = tmp_path / 'log'
    _write_log(path, canonical=canonical, tool='feedback', claim=claim)
    usage.sync(db, path)
    assert db.execute('SELECT count(*) FROM feedback').fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM exposures WHERE via='feedback'").fetchone()[0] == expected


def test_dispatch_explicit_config_and_request_identity_are_local(monkeypatch):
    from claimbase import mcp_server as m
    records = []
    monkeypatch.setattr(m, '_dispatch_inner', lambda *_: {})
    monkeypatch.setattr(m, '_log_call', records.append)
    monkeypatch.setattr(m, 'SESSION', 'legacy-process')
    monkeypatch.setenv('CLAIMBASE_SESSION', 'same')
    monkeypatch.delenv('CLAIMBASE_HARNESS', raising=False)
    m._dispatch('recall', {})
    monkeypatch.setenv('CLAIMBASE_HARNESS', 'hermes')
    m._dispatch('recall', {})
    m._dispatch('recall', {}, canonical_session='claude:same')
    m._dispatch('recall', {})
    m._dispatch('recall', {}, canonical_session='invalid')
    assert [r['canonical_session'] for r in records] == [None, 'hermes:same', 'claude:same', 'hermes:same', None]
    assert {r['session'] for r in records} == {'legacy-process'}
    assert len({r['call_id'] for r in records}) == 5
