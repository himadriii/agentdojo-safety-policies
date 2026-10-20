import json
from pathlib import Path
import zipfile

import pytest

from p2_anomaly.handoff import prepare, bundle, run


def test_preparation_is_portable_gate_first_and_keeps_test_tasks_out(tmp_path):
    destination = tmp_path / 'handoff'
    result = prepare(destination)
    assert result['api_calls'] == 0
    setup = json.loads((destination / 'setup.json').read_text())
    assert not Path(setup['candidate']).is_absolute()
    plan = json.loads((destination / 'development/plan.json').read_text())
    assert len(plan['jobs']) == 12
    for index in range(0, 12, 3):
        triplet = plan['jobs'][index:index + 3]
        assert [j['policy'] for j in triplet] == ['anomaly', 'full_approve', 'full_escalate']
        assert len({(j['user_task'], j['attack'], j['injection_task'], j['k']) for j in triplet}) == 1
    collection = json.loads((destination / 'calibration/plan.json').read_text())
    assert len(collection['jobs']) == 8
    assert all(j['attack'] == 'none' for j in collection['jobs'])
    with pytest.raises(ValueError, match='overwritten'):
        prepare(destination)


def test_bundle_excludes_secrets_and_preserves_incomplete_status(tmp_path):
    destination = tmp_path / 'handoff'
    prepare(destination)
    (destination / '.env').write_text('GROQ_API_KEY=private-test-value')
    (destination / 'unrelated.txt').write_text('private')
    output = tmp_path / 'results.zip'
    bundle(destination, output)
    with zipfile.ZipFile(output) as archive:
        assert '.env' not in archive.namelist()
        assert 'unrelated.txt' not in archive.namelist()
        report = json.loads(archive.read('development/comparison.json'))
        assert all(g['completed'] == 0 and g['tcr_completed'] is None for g in report['groups'])


def test_changed_candidate_blocks_before_api(tmp_path):
    destination = tmp_path / 'handoff'
    prepare(destination)
    path = destination / 'setup.json'
    setup = json.loads(path.read_text())
    setup['candidate_sha256'] = 'wrong'
    path.write_text(json.dumps(setup))
    with pytest.raises(ValueError, match='changed'):
        run(destination, 'development', 1)


def test_quota_stop_applies_across_phases(tmp_path):
    destination = tmp_path / 'handoff'
    prepare(destination)
    (destination / 'development/ledger.json').write_text(json.dumps({
        'job': {'error_type': 'RateLimitError', 'status': 'error'}}))
    with pytest.raises(ValueError, match='quota'):
        run(destination, 'calibration', 1)


def test_course_final_is_preassigned_matched_and_held_out(tmp_path):
    from collections import Counter
    from p2_anomaly.experiments import make_plan, validate_plan, save
    from p2_anomaly.splits import TEST
    save(tmp_path / 'freeze.json', {'files': {}, 'source': {}})
    plan = make_plan('final', frozen=tmp_path, profile='course')
    validate_plan(plan)
    assert len(plan['jobs']) == 108
    assert {j['user_task'] for j in plan['jobs']} == {f'user_task_{i}' for i in TEST}
    assert {j['k'] for j in plan['jobs']} == {2}
    settings = Counter((j['user_task'], j['attack'], j['injection_task']) for j in plan['jobs'])
    assert set(settings.values()) == {3}
    for style in ('important_instructions', 'tool_knowledge'):
        counts = Counter(j['injection_task'] for j in plan['jobs'] if j['attack'] == style)
        assert counts == {f'injection_task_{i}': 9 for i in (2, 7, 9, 10)}
    with pytest.raises(ValueError, match='frozen final'):
        make_plan('development', profile='course')
