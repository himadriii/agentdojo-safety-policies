import json
from pathlib import Path

import pytest
from p2_anomaly.evaluate_shared import jobs, read_result


def fixture_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path('splits').mkdir()
    Path('splits/banking_v1.2.json').write_text(json.dumps({'dev': {
        'user_tasks': ['user_task_4'], 'injection_tasks': ['injection_task_3']}}))
    root = tmp_path / 'run'
    (root / 'pipeline').mkdir(parents=True)
    identity = {'artifact_sha256': 'expected', 'source_sha256': {'runtime': 'same'}}
    (root / 'p2-run-identity.json').write_text(json.dumps(identity))
    data = {'suite': 'banking', 'attack': 'important_instructions', 'k': 2,
            'llm': 'openai/gpt-oss-20b', 'reviewer_model': 'openai/gpt-oss-120b',
            'n': 1, 'tcr': 1.0, 'hitl_load_completed': 1, 'hitl_load_all': 1,
            'tasks_with_errors': 0, 'rows': {'user_task_4|injection_task_3': {
                'attack_succeeded': False, 'completed_safely': True, 'budget_exhausted_denials': 0}}}
    summary = root / 'pipeline/summary_banking_important_instructions.json'
    summary.write_text(json.dumps(data))
    return dict(suite='banking', attack='important_instructions', k=2, outdir=str(root)), summary, data


def test_reports_only_matching_full_runs(tmp_path, monkeypatch):
    job, path, data = fixture_run(tmp_path, monkeypatch)
    result = read_result(job, 'expected')
    assert result['status'] == 'completed' and result['tcr'] == 1.0
    assert result['hitl_load_completed'] == 1
    # A successfully resumed run can retain the marker from its earlier interruption.
    (Path(job['outdir']) / 'quota-stop.json').write_text('{}')
    assert read_result(job, 'expected')['status'] == 'completed'
    with pytest.raises(ValueError, match='artifacts'):
        read_result(job, 'different')
    data['rows'] = {}
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match='Incomplete'):
        read_result(job, 'expected')


def test_pending_or_quota_runs_do_not_get_metrics(tmp_path):
    job = {'outdir': str(tmp_path), 'suite': 'banking', 'attack': 'none', 'k': 2}
    result = read_result(job, 'expected')
    assert result['status'] == 'pending' and 'tcr' not in result
    (tmp_path / 'quota-stop.json').write_text('{}')
    assert read_result(job, 'expected')['status'] == 'quota_stop'


def test_matrix_has_clean_control_and_three_budgets_per_suite(tmp_path):
    schedule = jobs(tmp_path, tmp_path / 'existing')
    assert len(schedule) == 12
    for suite in ('banking', 'slack', 'travel'):
        assert {j['k'] for j in schedule if j['suite'] == suite and j['attack'] != 'none'} == {0, 2, 5}
        assert sum(j['suite'] == suite and j['attack'] == 'none' for j in schedule) == 1
