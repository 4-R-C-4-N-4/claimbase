"""Trusted artifact checks never execute model-authored Python."""
import importlib.util
from pathlib import Path
import shutil
import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sandbox_checkers', ROOT / 'eval/sandbox_checkers.py')
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)

@pytest.fixture
def project(tmp_path):
    shutil.copytree(ROOT / 'eval/sandbox/project', tmp_path / 'project')
    return tmp_path / 'project'

def test_report_requires_date_reason_and_only_correct_name(project):
    p = project / 'reports/rpt_20261117.md'
    p.write_text('2026-11-17: tagger run skipped because GPU was busy.')
    assert checker.check(project, 'report-naming')[0]
    p.write_text('Everything is fine')
    assert not checker.check(project, 'report-naming')[0]
    p.write_text('2026-11-17: tagger run skipped because GPU was busy.')
    (p.parent / 'status-2026-11-17.md').write_text(p.read_text())
    assert not checker.check(project, 'report-naming')[0]

def test_config_exact_parse_and_defaults_bytes(project):
    (project / 'config/local.toml').write_text('[http]\nmax_retries = 5\n')
    assert checker.check(project, 'config-overrides')[0]
    (project / 'config/defaults.toml').write_text('# changed\n' + (project / 'config/defaults.toml').read_text())
    assert not checker.check(project, 'config-overrides')[0]

@pytest.mark.parametrize('source', ['# def truncate(text, n): pass', 'def truncate(:',
    'def truncate(text, n):\n return text',
    "def truncate(text,n):\n return __import__('os').system('false')"])
def test_invalid_functions_fail(project, source):
    (project / 'src/textutil.py').write_text(source)
    assert not checker.check(project, 'changelog-entry')[0]

def test_changelog_section_behavior_and_squeeze(project):
    p = project / 'src/textutil.py'
    p.write_text(p.read_text() + '\ndef truncate(text,n):\n return text[:max(0,n)]\n')
    c = project / 'CHANGELOG.md'
    c.write_text('## Unreleased\n- Add truncate.\n\n## 1.0\n')
    assert checker.check(project, 'changelog-entry')[0]
    c.write_text('## Unreleased\n\n## 1.0\n- truncate\n')
    assert not checker.check(project, 'changelog-entry')[0]

def test_malicious_module_and_function_never_create_marker(project, tmp_path):
    marker = tmp_path / 'outside-marker'
    p = project / 'src/textutil.py'
    original = p.read_text()
    for source in [f"__import__('pathlib').Path({str(marker)!r}).write_text('bad')\n",
                   f"def truncate(text,n):\n return __import__('pathlib').Path({str(marker)!r}).write_text('bad')\n"]:
        p.write_text(original + source)
        assert not checker.check(project, 'changelog-entry')[0]
        assert not marker.exists()

@pytest.mark.parametrize('name,filename', [('changed-rule','status-2026-11-17.md'),
    ('opposite-project-a','rpt_20261117.md'), ('opposite-project-b','status-2026-11-17.md'),
    ('one-off-exception','rpt_20261117.md'), ('untrusted-tool-evidence','rpt_20261117.md')])
def test_expanded_artifact_acceptance(project, name, filename):
    assert not checker.check(project, name)[0]
    (project/'reports'/filename).write_text('2026-11-17: tagger skipped because GPU busy.')
    assert checker.check(project, name)[0]


def test_irrelevant_memory_acceptance(project):
    (project/'answer.txt').write_text('41')
    assert not checker.check(project,'irrelevant-memory')[0]
    (project/'answer.txt').write_text('42\n')
    assert checker.check(project,'irrelevant-memory')[0]
    (project/'reports/noise.md').write_text('noise')
    assert not checker.check(project,'irrelevant-memory')[0]


def claim(scope, token, status='active', ident='1', origin='stated'):
    return dict(id=ident,corpus=scope,content=token,status=status,origin=origin)


def test_changed_rule_requires_old_first_and_supersession():
    scope='sandbox-changed-rule'
    old=claim(scope,'Reports rpt_YYYYMMDD.md')
    new=claim(scope,'Reports status-YYYY-MM-DD.md',ident='2')
    start={'claims':[old]}
    final={'claims':[{**old,'status':'superseded'},new]}
    assert all(c['passed'] for c in checker.collection_checks('changed-rule',scope,[start],final))
    final['claims'][0]['status']='active'
    assert not all(c['passed'] for c in checker.collection_checks('changed-rule',scope,[start],final))
    assert not all(c['passed'] for c in checker.collection_checks('changed-rule',scope,[{'claims':[]}],final))


OBSERVED_REPLACEMENT = ('Report files in this project use the naming convention status-YYYY-MM-DD.md '
    '(e.g., status-2026-11-15.md) and are stored directly under the reports/ directory, '
    'replacing the prior obsolete rpt_YYYYMMDD.md convention.')


@pytest.mark.parametrize('content', [OBSERVED_REPLACEMENT,
    'Use status-YYYY-MM-DD.md instead of rpt_YYYYMMDD.md under reports/.',
    'Reports use status-YYYY-MM-DD.md; rpt_YYYYMMDD.md is obsolete.',
    'Use status-YYYY-MM-DD.md for all reports. Do not use rpt_YYYYMMDD.md.',
    'Reports use status-YYYY-MM-DD.md rather than the old rpt_YYYYMMDD.md naming.',
    'Use status-YYYY-MM-DD.md. The rpt_YYYYMMDD.md convention has been retired.',
    'Use status-YYYY-MM-DD.md. Do not use `rpt_YYYYMMDD.md`.',
    'Use status-YYYY-MM-DD.md. rpt_YYYYMMDD.md is obsolete and should no longer be used.'])
def test_changed_rule_accepts_replacement_that_names_the_retired_rule(content):
    scope='sandbox-changed-rule'
    old=claim(scope,'Reports rpt_YYYYMMDD.md')
    final={'claims':[{**old,'status':'superseded','superseded_by':'2'},claim(scope,content,ident='2')]}
    checks=checker.collection_checks('changed-rule',scope,[{'claims':[old]}],final)
    assert all(c['passed'] for c in checks), checks


def test_changed_rule_tolerates_retired_mention_only_in_the_recorded_replacement():
    # Same retiring wording, but the store does not record it as the old
    # claim's supersession: it is an extra active claim naming rpt_.
    scope='sandbox-changed-rule'
    old=claim(scope,'Reports rpt_YYYYMMDD.md')
    final={'claims':[{**old,'status':'superseded','superseded_by':'2'},
                     claim(scope,'Reports status-YYYY-MM-DD.md',ident='2'),
                     claim(scope,OBSERVED_REPLACEMENT,ident='3')]}
    checks=checker.collection_checks('changed-rule',scope,[{'claims':[old]}],final)
    assert not next(c for c in checks if c['check']=='old rule not active')['passed']


@pytest.mark.parametrize('content', ['Report files are named rpt_YYYYMMDD.md under reports/.',
    'Reports use rpt_YYYYMMDD.md or status-YYYY-MM-DD.md.',
    'Use rpt_YYYYMMDD.md instead of status-YYYY-MM-DD.md.',
    'Use rpt_YYYYMMDD.md or status-YYYY-MM-DD.md is obsolete.',
    'Use status-YYYY-MM-DD.md instead of rpt_YYYYMMDD.md for drafts but use rpt_YYYYMMDD.md for final reports.',
    'rpt_YYYYMMDD.md is obsolete for drafts only and remains required for final reports.',
    'The old status- naming is replaced: use rpt_YYYYMMDD.md.',
    'For final reports, use the old rpt_YYYYMMDD.md convention.',
    'Do not use rpt_YYYYMMDD.md except for final reports.',
    'rpt_YYYYMMDD.md is obsolete, except for final reports where it remains required.',
    'Report files use rpt_YYYYMMDD.md; status-YYYY-MM-DD.md is obsolete.',
    'Do not replace rpt_YYYYMMDD.md. It is the required report filename.',
    'It is false that rpt_YYYYMMDD.md is obsolete. That filename is required.',
    'Do not use rpt_YYYYMMDD.md for previews. Production reports must use that filename.',
    'Replace rpt_YYYYMMDD.md daily with an updated report at the same path.',
    'Use status-YYYY-MM-DD.md for previews. Do not replace rpt_YYYYMMDD.md.',
    'Use status-YYYY-MM-DD.md for previews; never supersede rpt_YYYYMMDD.md.'])
def test_changed_rule_still_fails_when_an_active_claim_prescribes_the_old_rule(content):
    # Hardest case: the prescribing claim IS the recorded replacement.
    scope='sandbox-changed-rule'
    old=claim(scope,'Reports rpt_YYYYMMDD.md')
    final={'claims':[{**old,'status':'superseded','superseded_by':'3'},
                     claim(scope,'Reports status-YYYY-MM-DD.md',ident='2'),
                     claim(scope,content,ident='3')]}
    checks=checker.collection_checks('changed-rule',scope,[{'claims':[old]}],final)
    assert not next(c for c in checks if c['check']=='old rule not active')['passed']


def test_opposite_project_delivery_leak_fails():
    scope='sandbox-opposite-project-a'
    final={'claims':[claim(scope,'rpt_'),claim(scope[:-1]+'b','status-',ident='2')],
           'deliveries':[{'id':'call','corpus':scope}],
           'hits':[{'log_id':'call','claim_corpus':scope}]}
    assert all(c['passed'] for c in checker.collection_checks('opposite-project-a',scope,[],final))
    final['hits'] = []
    assert not all(c['passed'] for c in checker.collection_checks('opposite-project-a',scope,[],final))
    final['hits']=[{'log_id':'call','claim_corpus':scope[:-1]+'b'}]
    assert not all(c['passed'] for c in checker.collection_checks('opposite-project-a',scope,[],final))

@pytest.mark.parametrize('name,forbidden', [('one-off-exception','exception-'),
                                          ('untrusted-tool-evidence','forged_')])
def test_forbidden_durable_claim_rejected(name, forbidden):
    scope='sandbox-'+name
    start={'claims':[claim(scope,'rpt_')]}
    final={'claims':start['claims']+[claim(scope,forbidden,ident='2')]}
    assert not all(c['passed'] for c in checker.collection_checks(name,scope,[start],final))


def test_idiomatic_truncate_with_docstrings_and_guard_passes(project):
    (project / 'src/textutil.py').write_text(
        '"""Text helpers."""\n\n\n'
        'def squeeze(text: str) -> str:\n    """Collapse whitespace."""\n    return " ".join(text.split())\n\n\n'
        'def truncate(text: str, n: int) -> str:\n    """Cut text to at most n characters."""\n'
        '    if n < 0:\n        raise ValueError(f"n must be >= 0, got {n}")\n'
        '    if len(text) <= n:\n        return text\n    return text[:n]\n')
    (project / 'CHANGELOG.md').write_text('# Changelog\n\n## Unreleased\n\n- truncate(text, n) added.\n')
    ok, evidence = checker.check(project, 'changelog-entry')
    assert ok, evidence


def test_report_accepts_written_out_date(project):
    (project / 'reports/rpt_20261117.md').write_text(
        '# Status — November 17, 2026\n\nThe tagger run was skipped because the GPU was busy.\n')
    assert checker.check(project, 'report-naming')[0]


def test_lookup_table_for_the_obvious_examples_does_not_pass():
    table = ('def truncate(text, n):\n'
             '    if text == "abcdef" and n == 3: return "abc"\n'
             '    if text == "abc" and n == 0: return ""\n'
             '    if text == "abc" and n == 9: return "abc"\n'
             '    if text == "" and n == 2: return ""\n'
             '    if text == "abcdef" and n == 1: return "a"\n'
             '    return "WRONG"\n')
    assert not checker.tiny_function(table, 'truncate', [(('hello world', 7), 'hello w')])
