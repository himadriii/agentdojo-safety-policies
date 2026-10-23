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
