import json
from types import SimpleNamespace

import httpx
import openai
import pytest
from agentdojo.functions_runtime import FunctionsRuntime

from p2_anomaly.quota_adapter import QuotaBoundGroqLLM, QuotaBoundReviewer, QuotaStop, quota_safe_shared_runner
from p2_anomaly.shared_summary import load_summary


def quota():
    return openai.RateLimitError('quota', response=httpx.Response(429, request=httpx.Request('POST', 'https://example.invalid')), body={})


def test_agent_quota_bypasses_upstream_and_shared_runner_retries(monkeypatch):
    from agent_framework import runner
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        raise quota()
    monkeypatch.setattr(runner.time, 'sleep', lambda _: pytest.fail('must not sleep/retry after quota'))
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    agent = QuotaBoundGroqLLM(client, 'model')
    with pytest.raises(QuotaStop):
        runner.run_with_resume(lambda: agent.query('task', FunctionsRuntime([])))
    assert len(calls) == 1
    assert calls[0]['temperature'] is openai.NOT_GIVEN
    assert 'max_tokens' not in calls[0]  # Preserve the shared agent request configuration.


def test_reviewer_quota_cannot_be_swallowed_as_a_denial(monkeypatch):
    from tests.test_llm_reviewer import FakeCompletions, ctx
    monkeypatch.setenv('GROQ_REQUEST_INTERVAL_SECONDS', '0')
    fake = FakeCompletions([quota()])
    reviewer = QuotaBoundReviewer(model='openai/gpt-oss-120b', client=SimpleNamespace(chat=SimpleNamespace(completions=fake)))
    with pytest.raises(QuotaStop):
        reviewer.review(ctx())
    assert len(fake.requests) == 1


def test_scoped_factories_restore_shared_runner_after_failure():
    from agent_framework import runner
    agent, reviewer = runner.make_groq_llm, runner.REVIEWERS['llm']
    with pytest.raises(RuntimeError):
        with quota_safe_shared_runner():
            assert runner.REVIEWERS['llm'] is QuotaBoundReviewer
            raise RuntimeError('stop')
    assert runner.make_groq_llm is agent and runner.REVIEWERS['llm'] is reviewer


def test_loads_summary_from_shared_runner_that_returns_none(tmp_path):
    pipeline = tmp_path / 'pipeline'
    trace = pipeline / 'workspace/user_task_3/none/none.json'
    trace.parent.mkdir(parents=True)
    trace.write_text(json.dumps({'approval_decisions': [{'decision': 'escalate', 'reviewer_reason': 'REVIEWER_ERROR: RateLimitError'}]}))
    original = {'n': 1, 'rows': {'user_task_3|': {'utility': True, 'attack_succeeded': False}}}
    summary_file = pipeline / 'summary_workspace_none.json'
    summary_file.write_text(json.dumps(original))
    result = load_summary(tmp_path, None, {'suite': 'workspace', 'benchmark_version': 'v1.2'}, {'attack': 'none'})
    assert result['pipeline_name'] == 'pipeline'
    assert result['tasks_with_reviewer_errors'] == 1
    assert json.loads(summary_file.read_text()) == original


def test_missing_shared_output_is_not_a_completion(tmp_path):
    with pytest.raises(ValueError, match='exactly one'):
        load_summary(tmp_path, None, {'suite': 'workspace'}, {'attack': 'none'})


def test_shared_collection_rejects_heldout_tasks_and_split_drift():
    import copy
    from p2_anomaly.experiments import make_shared_collection_plan, validate_plan
    plan = make_shared_collection_plan('banking')
    validate_plan(plan)
    bad = copy.deepcopy(plan)
    bad['jobs'][0]['user_task'] = 'user_task_0'
    with pytest.raises(ValueError, match='outside shared DEV'):
        validate_plan(bad)
    bad = copy.deepcopy(plan)
    bad['shared_split_sha256'] = 'changed'
    with pytest.raises(ValueError, match='configuration changed'):
        validate_plan(bad)
