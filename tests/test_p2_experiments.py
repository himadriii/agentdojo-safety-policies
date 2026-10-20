import copy
import json

import pytest

from agent_framework.policies.anomaly_features import FEATURE_NAMES
from agent_framework.policies.anomaly_support import unsupported_reason
from p2_anomaly.diagnostics import clustered_flag_interval
from p2_anomaly.experiments import (
    make_plan, validate_plan, summarize, save, digest, verify_freeze, freeze_candidate,
)


@pytest.fixture(autouse=True)
def declared_test_route(monkeypatch):
    monkeypatch.setenv('REVIEWER_PROVIDER', 'groq')


def test_collection_is_only_development_and_real_reviewer():
    plan = make_plan('collect', repeats=3)
    validate_plan(plan)
    assert len(plan['jobs']) == 63
    assert all(j['attack'] == 'none' and j['policy'] == 'full_approve' and
               j['reviewer'] == 'llm' for j in plan['jobs'])
    plan['jobs'][0]['user_task'] = 'user_task_0'
    with pytest.raises(ValueError, match='partition'):
        validate_plan(plan)


def test_development_reserves_unseen_attacks_and_injections():
    plan = make_plan('development')
    validate_plan(plan)
    assert {j['attack'] for j in plan['jobs']} == {'none', 'important_instructions'}
    for mutate in ({'reviewer': 'mock'}, {'attack': 'tool_knowledge'},
                   {'attack': 'important_instructions', 'injection_task': 'injection_task_2'}):
        bad = copy.deepcopy(plan)
        bad['jobs'][0].update(mutate)
        with pytest.raises(ValueError):
            validate_plan(bad)


def test_category_transfer_has_support_and_side_effect_guards():
    vector = [0.] * len(FEATURE_NAMES)
    bounds = {k: [0, 1] for k in ('log_args', 'n_keys', 'n_emails', 'n_urls')}
    artifact = {'trained_tools': ['search_emails'],
                'tool_table': {'search_emails': 'read', 'get_sent_emails': 'read', 'delete_file': 'destructive'},
                'support_mode': 'category',
                'category_support': {'read': {'calls': 5, 'tasks': 3, 'bounds': bounds}}}
    assert unsupported_reason(artifact, 'get_sent_emails', vector) is None
    assert unsupported_reason(artifact, 'delete_file', vector) == 'unseen_side_effect_tool'
    assert unsupported_reason(artifact, 'unknown', vector) == 'unknown_tool'
    vector[FEATURE_NAMES.index('n_emails')] = 2
    assert unsupported_reason(artifact, 'get_sent_emails', vector) == 'outside_category_shape_support'
    vector[FEATURE_NAMES.index('n_emails')] = 0
    artifact['category_support']['read']['tasks'] = 2
    assert unsupported_reason(artifact, 'get_sent_emails', vector) == 'insufficient_category_support'


def test_clustered_interval_counts_tasks_not_repeats():
    rows = [{'user_task': 'a'}, {'user_task': 'b'}] * 20
    interval = clustered_flag_interval(rows, [True, False] * 20, repetitions=100)
    assert interval['independent_tasks'] == 2
    assert interval['calls'] == 40 and interval['rate'] == .5


def test_summary_does_not_invent_unexecuted_results(tmp_path):
    path = tmp_path / 'plan.json'
    save(path, make_plan('development'))
    report = summarize(path)
    assert all(g['completed'] == 0 and g['tcr_completed'] is None for g in report['groups'])


def test_final_requires_freeze():
    with pytest.raises(ValueError, match='frozen'):
        make_plan('final')


def test_freeze_integrity_checks_artifacts_and_code(tmp_path):
    (tmp_path / 'model.joblib').write_bytes(b'model')
    save(tmp_path / 'freeze.json', {'files': {'model.joblib': digest(tmp_path / 'model.joblib')},
                                   'source': {}})
    verify_freeze(tmp_path)
    (tmp_path / 'model.joblib').write_bytes(b'changed')
    with pytest.raises(ValueError, match='changed'):
        verify_freeze(tmp_path)


def test_reference_only_artifact_cannot_be_frozen(tmp_path):
    from pathlib import Path
    with pytest.raises(ValueError, match='live audited|revoked'):
        freeze_candidate(Path('p2_anomaly/artifacts'), tmp_path / 'frozen')


def test_declared_task_compositions_do_not_cross_test_boundary():
    from agentdojo.task_suite.load_suites import get_suite
    from p2_anomaly.splits import audit, FIT, CALIBRATE, QUARANTINE
    report = audit(get_suite('v1.2', 'workspace'))
    assert {'user_task_6', 'user_task_19', 'user_task_23', 'user_task_38', 'user_task_39'} <= set(report['declared_test_component_overlaps'])
    assert not set(FIT + CALIBRATE) & set(QUARANTINE)


def test_training_rejects_distinct_ids_in_same_family():
    from p2_anomaly.train import fit_artifact
    from agent_framework.policies.anomaly_features import FEATURE_NAMES
    first = {'user_task':'first', 'group_id':'same-family', 'tool':'search_emails', 'features':[0.] * len(FEATURE_NAMES)}
    second = {**first, 'user_task':'second'}
    with pytest.raises(ValueError, match='family leakage'):
        fit_artifact([first],[second],{'search_emails':'read'})


def test_explicit_reviewer_model_reaches_executor(monkeypatch):
    from agent_framework import runner
    from tests.test_executor_contract import ScriptedLLM
    from agent_framework.reviewer import MockReviewer
    reviewers = []
    def factory(model, client):
        r = MockReviewer()
        r.model = model
        reviewers.append(r)
        return r
    monkeypatch.setattr(runner, 'make_groq_llm', lambda _: ScriptedLLM(['x']))
    monkeypatch.setattr(runner, 'make_inference_client', lambda *args, **kwargs: object())
    monkeypatch.setitem(runner.REVIEWERS, 'llm', factory)
    pipeline = runner.build_pipeline('agent', 'full_escalate', 'llm', 2, 'groq', 'explicit-reviewer')
    assert len(reviewers) == 1
    assert pipeline.elements[0].executor.reviewer is reviewers[0]
    assert 'explicit-reviewer' in pipeline.name


def test_run_refuses_missing_credentials_before_network(tmp_path, monkeypatch):
    import p2_anomaly.experiments as experiments
    monkeypatch.setattr(experiments, 'load_dotenv', lambda *_: None)
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    save(tmp_path / 'absent.json', make_plan('collect', 1))
    with pytest.raises(ValueError, match='GROQ_API_KEY missing'):
        experiments.run_plan(tmp_path / 'absent.json', 1)


def test_retry_usage_is_preserved_in_summary(tmp_path):
    plan = make_plan('development')
    path = tmp_path / 'plan.json'
    save(path, plan)
    save(tmp_path / 'ledger.json', {'job_00000': {'status': 'error', 'attempts': [
        {'usage': {'agent': {'calls': 1, 'input_tokens': 10, 'output_tokens': 2}}},
        {'usage': {'agent': {'calls': 1, 'input_tokens': 20, 'output_tokens': 3}}},
    ]}})
    result = summarize(path)
    assert result['response_usage_all_jobs']['agent'] == {'calls': 2, 'input_tokens': 30, 'output_tokens': 5}
    assert all(g['completed'] == 0 for g in result['groups'])


def test_task_usage_reset_keeps_full_experiment_usage():
    from agent_framework.usage import UsageTracker
    tracker = UsageTracker()
    tracker.add('agent', 10, 3)
    tracker.reset()
    tracker.add('agent', 20, 4)
    assert tracker.totals['agent']['input_tokens'] == 20
    assert tracker.lifetime['agent']['input_tokens'] == 30


@pytest.mark.parametrize('status,expected_attempts', [(413, 2), (429, 1)])
def test_request_rejection_skips_episode_but_quota_stops_batch(tmp_path, monkeypatch, status, expected_attempts):
    import httpx
    import openai
    import p2_anomaly.experiments as experiments
    import agent_framework.runner as runner
    monkeypatch.setattr(experiments, 'load_dotenv', lambda *_: None)
    monkeypatch.setenv('GROQ_API_KEY', 'unit-test-not-a-real-key')
    for name in ('GROQ_STOP_ON_QUOTA', 'GROQ_MAX_RETRIES', 'GROQ_REQUEST_INTERVAL_SECONDS'):
        monkeypatch.setenv(name, '0')
    plan = make_plan('collect', 1)
    plan['jobs'] = plan['jobs'][:2]
    path = tmp_path / 'plan.json'
    save(path, plan)
    calls = []
    def run_one(args, k):
        calls.append(args.user_tasks)
        if len(calls) == 1:
            response = httpx.Response(status, request=httpx.Request('POST', 'https://example.invalid'))
            kind = openai.RateLimitError if status == 429 else openai.APIStatusError
            raise kind('rejected', response=response, body={})
        return {'n': 1, 'tasks_with_errors': 0, 'rows': {}}
    monkeypatch.setattr(runner, 'run_one', run_one)
    result = experiments.run_plan(path, 2)
    assert result['attempted_now'] == expected_attempts
    ledger = json.loads((tmp_path / 'ledger.json').read_text())
    assert ledger['job_00000']['error_status'] == status


@pytest.mark.parametrize('resume', [False, True])
def test_new_plan_retains_quota_stop_until_explicit_resume(tmp_path, monkeypatch, resume):
    import p2_anomaly.experiments as experiments
    import agent_framework.runner as runner
    monkeypatch.setattr(experiments, 'load_dotenv', lambda *_: None)
    monkeypatch.setenv('GROQ_API_KEY', 'unit-test-not-a-real-key')
    for name in ('GROQ_STOP_ON_QUOTA', 'GROQ_MAX_RETRIES', 'GROQ_REQUEST_INTERVAL_SECONDS'):
        monkeypatch.setenv(name, '0')
    plan = make_plan('collect', 1)
    plan['jobs'] = plan['jobs'][:1]
    plan['quota_resume_required'] = True
    path = tmp_path / 'plan.json'
    save(path, plan)
    calls = []
    def fake_run(args, k):
        calls.append(1)
        return {'n':1, 'tasks_with_errors':0, 'rows':{}}
    monkeypatch.setattr(runner, 'run_one', fake_run)
    if resume:
        assert experiments.run_plan(path, 1, resume_after_quota=True)['completed'] == 1
        assert calls == [1]
    else:
        with pytest.raises(ValueError, match='quota stop retained'):
            experiments.run_plan(path, 1)
        assert not calls
