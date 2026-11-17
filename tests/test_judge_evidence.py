"""Judge prompt delivery contract; semantic behavior is checked by local runs."""
from claimbase import llm, writer


def test_local_judge_supplies_evidence_limits_with_the_episode(monkeypatch):
    sent = {}

    def capture(**kwargs):
        sent.update(kwargs)
        return '{"claim":null,"relation":"nothing","kind":null,"target":null}'

    monkeypatch.setattr(llm, 'call_llm', capture)
    judge = writer.LocalJudge('llamacpp', 'test-local-model')
    episode = "The model doesn't have to remember to call anything."
    verdict = judge.score('decision', episode, '>> USER: ' + episode, [])

    assert verdict.relation == 'nothing'
    assert episode in sent['prompt']
    assert 'Trigger labels are heuristic' in sent['system']
    assert 'one failed attempt' in sent['system']
    assert 'Preserve time, conditions and uncertainty' in sent['system']
    assert 'without a durable corrective rule, is null' in sent['system']
