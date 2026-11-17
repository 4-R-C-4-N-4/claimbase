import pytest

from claimbase import usage
from conftest import TEST_DSN, TEST_RO_DSN


def test_outcome_database_rejects_cross_project_rows_and_scope_changes(db):
    import psycopg
    with db.cursor() as cur:
        cur.execute("INSERT INTO sessions (id, corpus, harness) VALUES ('hermes:scope', 'guru', 'hermes')")
    db.commit()
    with pytest.raises(psycopg.errors.ForeignKeyViolation), db.transaction():
        db.execute("""INSERT INTO usage_outcomes (session_id, corpus, run_id, checker, passed, evidence)
                      VALUES ('hermes:scope','other','r','c',true,'{}')""")
    usage.record_outcome(db, 'guru', 'hermes:scope', 'r', 'c', True, {})
    with psycopg.connect(TEST_DSN, autocommit=True) as other:
        other.execute("SET lock_timeout = '100ms'")
        with pytest.raises(psycopg.errors.LockNotAvailable):
            other.execute("UPDATE sessions SET corpus='other' WHERE id='hermes:scope'")
    db.commit()
    with pytest.raises(psycopg.errors.ForeignKeyViolation), db.transaction():
        db.execute("UPDATE sessions SET corpus='other' WHERE id='hermes:scope'")
    with psycopg.connect(TEST_RO_DSN) as ro:
        assert usage.measures(ro, 'guru')['outcomes']['passed'] == 1


def test_conflicting_outcome_and_postgres_invalid_json_are_rejected(db):
    db.execute("INSERT INTO sessions (id, corpus, harness) VALUES ('hermes:validation','guru','hermes')")
    usage.record_outcome(db, 'guru', 'hermes:validation', 'r', 'c', True, {})
    with pytest.raises(ValueError, match='different'):
        usage.record_outcome(db, 'guru', 'hermes:validation', 'r', 'c', False, {})
    for evidence in ({'value': '\u0000'}, {'value': float('nan')}, {'value': object()}):
        with pytest.raises(ValueError):
            usage.record_outcome(db, 'guru', 'hermes:validation', 'r', 'invalid', True, evidence)
    assert usage.measures(db, 'guru')['outcomes']['passed'] == 1



def test_outcome_requires_existing_scoped_session_and_is_idempotent(db):
    with db.cursor() as cur:
        cur.execute("INSERT INTO sessions (id, corpus, harness, started_at) VALUES ('hermes:one', 'guru', 'hermes', now())")
    with pytest.raises(ValueError):
        usage.record_outcome(db, 'other', 'hermes:one', 'run', 'check', True, {})
    with pytest.raises(ValueError):
        usage.record_outcome(db, 'guru', 'hermes:missing', 'run', 'check', True, {})
    with pytest.raises(ValueError):
        usage.record_outcome(db, 'guru', 'hermes:one', 'run', 'check', 1, {})
    first = usage.record_outcome(db, 'guru', 'hermes:one', 'run', 'check', True, {'artifact': 'ok'})
    assert usage.record_outcome(db, 'guru', 'hermes:one', 'run', 'check', True, {'artifact': 'ok'}) == first
    usage.record_outcome(db, 'guru', 'hermes:one', 'run', 'other', False, {})
    report = usage.measures(db, 'guru')
    assert (report['outcomes']['passed'], report['outcomes']['failed']) == (1, 1)
    with db.cursor() as cur:
        cur.execute('SELECT count(*) FROM exposures')
        assert cur.fetchone()[0] == 0


def test_claim_specific_feedback_does_not_mark_other_retrievals_missed(db):
    import uuid
    from conftest import seed_claim
    claims = [seed_claim(db, text) for text in ('Rule A.', 'Rule B.')]
    with db.cursor() as cur:
        for claim in claims:
            lid = uuid.uuid4()
            cur.execute("""INSERT INTO retrieval_log (id, ts, corpus, tool, session, canonical_session, n_results)
                           VALUES (%s, now() - interval '1 minute', 'guru', 'recall', 'shared', 'hermes:shared', 1)""", (lid,))
            cur.execute("INSERT INTO retrieval_hits VALUES (%s,%s,0,'guru')", (lid, claim))
        cur.execute("""INSERT INTO feedback (id, ts, corpus, session, canonical_session, kind, claim_id)
                       VALUES (%s,now(),'guru','shared','hermes:shared','not_helpful',%s)""", (uuid.uuid4(), claims[1]))
    report = usage.measures(db, 'guru')['miss_rate']
    assert (report['missed'], report['unknown']) == (1, 1)


def test_checker_results_do_not_change_retrieval_miss_or_use_counts(db):
    import uuid
    db.execute("INSERT INTO sessions (id,corpus,harness) VALUES ('hermes:checks','guru','hermes')")
    db.execute("""INSERT INTO retrieval_log (id,ts,corpus,tool,session,n_results)
                  VALUES (%s,now(),'guru','recall','hermes:checks',1)""", (uuid.uuid4(),))
    before = usage.measures(db, 'guru')['miss_rate']
    assert before['unknown'] == 1  # nonempty result without matched claim hits
    usage.record_outcome(db, 'guru', 'hermes:checks', 'r', 'pass', True, {})
    usage.record_outcome(db, 'guru', 'hermes:checks', 'r', 'fail', False, {})
    report = usage.measures(db, 'guru')
    assert report['miss_rate'] == before
    assert report['inference']['claim_uses'] == 0
    assert report['outcomes']['passed'] == report['outcomes']['failed'] == 1


def test_agent_assertion_is_not_independent_verification(db):
    from claimbase import writer
    from claimbase.sessions import Session, Turn
    from conftest import seed_claim
    seed_claim(db, 'Use the release tag for deployment.')
    session = Session('hermes', 'self-report', [Turn('assistant',
        'I used the release tag for deployment and verified my compliance.')], project='guru')
    writer.ingest(db, session)
    report = usage.measures(db, 'guru')
    assert report['outcomes']['passed'] == 0
    assert report['feedback'] == {}


def test_outcome_api_exists():
    assert callable(usage.record_outcome)


def test_delivery_feedback_and_unknown_are_separate(db):
    import uuid
    from conftest import seed_claim

    claim = seed_claim(db, 'Use the release tag.')
    ids = [uuid.uuid4() for _ in range(3)]
    with db.cursor() as cur:
        cur.execute("INSERT INTO sessions (id, corpus, harness, started_at, ended_at) VALUES ('hermes:s', 'guru', 'hermes', now() - interval '1 hour', now())")
        for lid, n in zip(ids, (1, 0, 1)):
            cur.execute("INSERT INTO retrieval_log (id, ts, corpus, tool, session, canonical_session, n_results) VALUES (%s, now() - interval '10 minutes', 'guru', 'recall', %s, %s, %s)", (lid, str(lid), "hermes:" + str(lid), n))
        for lid in (ids[0], ids[2]):
            cur.execute("INSERT INTO retrieval_hits (log_id, claim_id, rank, claim_corpus) VALUES (%s,%s,0,'guru')", (lid, claim))
        cur.execute("INSERT INTO feedback (id, ts, corpus, session, canonical_session, kind) VALUES (%s, now(), 'guru', %s, %s, 'not_helpful')", (uuid.uuid4(), str(ids[2]), "hermes:" + str(ids[2])))
    report = usage.measures(db, 'guru')
    assert report['delivery'] == {'retrievals': 3, 'results': 2, 'claim_hits': 2}
    assert (report['miss_rate']['missed'], report['miss_rate']['unknown']) == (2, 1)
    assert report['feedback']['not_helpful'] == 1
    assert report['outcomes']['passed'] == report['outcomes']['failed'] == 0
