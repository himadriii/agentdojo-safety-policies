import json
from pathlib import Path
from agent_framework.policies.anomaly import AnomalyPolicy


def test_score_task_and_family_are_absent_from_both_parts():
    root=Path('p2_anomaly/artifacts/development/quick-loto-task13-v1')
    m=json.loads((root/'manifest.json').read_text());data=json.loads((root/'reference_features.json').read_text())
    for rows in data.values():
        assert all(r['user_task']!=m['excluded_task'] for r in rows)
        assert not {r['group_id'] for r in rows}&set(m['excluded_groups'])
    assert {r['user_task'] for r in data['fit']}.isdisjoint(r['user_task'] for r in data['calibration'])
    assert any(r['user_task'].startswith('slack:') for r in data['fit'])


def test_only_training_artifact_changes_between_arms():
    roots=['p2_anomaly/artifacts/development/disjoint-v1/detector_generic/model.joblib','p2_anomaly/artifacts/development/quick-loto-task13-v1/model.joblib']
    a,b=[AnomalyPolicy(p).artifact for p in roots]
    assert a and b
    for key in ['authorization_guards','context_guards','review_required_tools','feature_transform','support_mode','tool_table']:
        assert a[key]==b[key]


def test_low_reasoning_override_applies_only_to_reviewer_requests(monkeypatch):
    from types import SimpleNamespace
    from agent_framework import inference
    from p2_anomaly.quick_loto import paced_clients

    seen = []
    def factory(*args, **kwargs):
        return SimpleNamespace(
            _client=SimpleNamespace(event_hooks={}),
            chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **options: seen.append(options))),
            close=lambda: None)
    monkeypatch.setattr(inference, 'make_inference_client', factory)
    pacer = SimpleNamespace(observe=lambda response: None, call=lambda create, **options: create(**options))
    with paced_clients(pacer, reviewer_reasoning_effort='low'):
        client = inference.make_inference_client('groq')
        client.chat.completions.create(messages=[], max_tokens=1024)
        client.chat.completions.create(messages=[], tools=[{'type': 'function'}])
    assert seen[0]['reasoning_effort'] == 'low'
    assert seen[0]['max_tokens'] == 1024
    assert 'reasoning_effort' not in seen[1]
    assert seen[1]['max_tokens'] == 4096
