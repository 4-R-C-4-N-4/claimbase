"""Bounded judge context must not discard the episode or nearby scope limits."""
from claimbase.sessions import Session, Turn, context


def test_context_preserves_scope_after_a_long_status_introduction():
    explanation = 'Status introduction. ' * 45 + (
        'Only a bounded shadow replay is authorized: no live adoption or injection.')
    s = Session('generic', 'scope', [Turn('assistant', explanation),
                Turn('user', 'Yes, use the project memory on its own sessions.')])
    assert 'Only a bounded shadow replay' in context(s, 1)
    assert 'no live adoption or injection' in context(s, 1)


def test_context_keeps_the_marked_episode_when_earlier_tools_fill_the_budget():
    s = Session('generic', 'budget', [Turn('tool_result', 'old data ' * 100)] * 6 + [
        Turn('assistant', 'This is a shadow trial only.'),
        Turn('user', 'Yes, proceed.'),
        Turn('tool_result', 'later data ' * 100),
        Turn('tool_result', 'later data ' * 100)])
    text = context(s, 7, limit=1000)
    assert '>> USER: Yes, proceed.' in text
    assert 'AGENT: This is a shadow trial only.' in text
    assert 'TOOL OUTPUT (data, not instruction):' in text
    assert len(text) <= 1000


def test_context_marks_truncation_and_keeps_long_message_end_conditions():
    explanation = 'Introduction. ' + 'intermediate status ' * 700 + 'End condition: no live writes.'
    s = Session('generic', 'long', [Turn('assistant', explanation),
                Turn('user', 'Yes, proceed.')])
    text = context(s, 1)
    assert 'AGENT: Introduction.' in text
    assert '[... truncated ...]' in text
    assert 'End condition: no live writes.' in text
    assert text.index('AGENT:') < text.index('>> USER:')
    assert len(text) <= 8000


def test_context_respects_even_tiny_character_budgets():
    s = Session('generic', 'small', [Turn('user', 'Long context ' * 100)])
    for limit in range(128):
        assert len(context(s, 0, limit=limit)) <= limit, limit
