from types import SimpleNamespace

import httpx
import openai
import pytest
from openai.types.chat import ChatCompletionMessage
from agentdojo.functions_runtime import FunctionsRuntime
from p2_anomaly.hosted20 import HostedAgent, HostedReviewer, HostedStop, aggregates, hosted_factories, metrics, schedule


def test_agent_error_stops_without_upstream_retry():
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        raise openai.RateLimitError('limit', response=httpx.Response(429,
            request=httpx.Request('POST', 'https://example.invalid')), body={})
    agent = HostedAgent(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), 'test')
    with pytest.raises(HostedStop):
        agent.query('task', FunctionsRuntime([]))
    assert len(calls) == 1


def test_reviewer_parse_error_is_not_counted_as_a_real_denial():
    from tests.test_llm_reviewer import FakeCompletions, ctx
    reviewer = HostedReviewer(model='test', client=SimpleNamespace(chat=SimpleNamespace(
        completions=FakeCompletions(['not a decision']))))
    with pytest.raises(HostedStop):
        reviewer.review(ctx())


def test_reasoning_is_preserved_but_not_used_as_final_answer():
    from agentdojo.types import text_content_block_from_string as T
    calls=[]
    thinking=ChatCompletionMessage(role='assistant',content=None,tool_calls=[],reasoning='Intermediate model state')
    finished=ChatCompletionMessage(role='assistant',content='The requested answer.',tool_calls=[])
    responses=iter([thinking,finished])
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=next(responses))])
    agent=HostedAgent(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), 'test')
    original=[{'role':'user','content':[T('Original request')]}]
    result=agent.query('Original request',FunctionsRuntime([]),messages=original)
    assert len(calls)==2
    assert calls[1]['messages'][-1]['role']=='assistant'
    assert calls[1]['messages'][-1]['reasoning']=='Intermediate model state'
    assert len(original)==1
    assert result[3][-1]['content'][0]['content']=='The requested answer.'


def test_repeated_reasoning_only_responses_stop_instead_of_fake_completion():
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=ChatCompletionMessage(
            role='assistant',content=None,tool_calls=[],reasoning='Intermediate model state'))])
    agent=HostedAgent(SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))), 'test')
    with pytest.raises(HostedStop,match='REASONING_ONLY'):
        agent.query('task',FunctionsRuntime([]))
    assert len(calls)==3


def test_scoped_hosted_factories_restore_on_failure():
    from agent_framework import runner
    original = runner.make_inference_llm, runner.REVIEWERS['llm']
    with pytest.raises(RuntimeError):
        with hosted_factories():
            assert runner.REVIEWERS['llm'] is HostedReviewer
            raise RuntimeError()
    assert (runner.make_inference_llm, runner.REVIEWERS['llm']) == original


def test_primary_schedule_and_aggregate_do_not_publish_partial_total():
    plan = schedule([2])
    assert len(plan) == 6 and {j['k'] for j in plan} == {2}
    assert aggregates({}, plan) == {}
    with pytest.raises(ValueError):
        schedule([1])


def test_metrics_refuse_incomplete_or_failed_runs():
    summary = {'rows': {}, 'n': 0}
    with pytest.raises(ValueError):
        metrics(summary, 18)
    summary = {'rows': {'one': {}}, 'n': 1, 'tasks_with_errors': 0, 'tasks_with_reviewer_errors': 1}
    with pytest.raises(HostedStop):
        metrics(summary, 1)
