"""Checks for adapters used in historical P2 experiments, not shared main."""
from types import SimpleNamespace

import httpx
import openai
import pytest
from agentdojo.functions_runtime import FunctionsRuntime

from p2_anomaly.historical_providers import NoRetryGroqLLM
from tests.test_llm_reviewer import make, ctx


def quota_error():
    response = httpx.Response(429, request=httpx.Request('POST', 'https://example.invalid'))
    return openai.RateLimitError('quota', response=response, body={'error': {'type': 'tokens'}})


def test_agent_does_not_retry_quota():
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        raise quota_error()
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    agent = NoRetryGroqLLM(client, 'model')
    with pytest.raises(openai.RateLimitError):
        agent.query('task', FunctionsRuntime([]))
    assert len(calls) == 1
    assert calls[0]['temperature'] is openai.NOT_GIVEN


def test_reviewer_propagates_quota_in_free_tier_mode(monkeypatch):
    monkeypatch.setenv('GROQ_STOP_ON_QUOTA', '1')
    from p2_anomaly.historical_reviewer import LLMReviewer
    from tests.test_llm_reviewer import FakeCompletions
    fake = FakeCompletions([quota_error()])
    reviewer = LLMReviewer(model="m", client=SimpleNamespace(chat=SimpleNamespace(completions=fake)))
    with pytest.raises(openai.RateLimitError):
        reviewer.review(ctx())
    assert len(fake.requests) == 1 and reviewer.errors == 1


def test_agent_and_reviewer_share_request_pacing(monkeypatch):
    import p2_anomaly.historical_providers as providers
    now, sleeps = [10.], []
    def sleep(seconds):
        sleeps.append(seconds)
        now[0] += seconds
    monkeypatch.setenv('GROQ_REQUEST_INTERVAL_SECONDS', '20')
    monkeypatch.setattr(providers, '_LAST_REQUEST', None)
    monkeypatch.setattr(providers.time, 'monotonic', lambda: now[0])
    monkeypatch.setattr(providers.time, 'sleep', sleep)
    providers._pace_request()
    providers._pace_request()
    assert sleeps == [20]
