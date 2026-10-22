from types import SimpleNamespace

import httpx
import openai
import pytest

from agent_framework import runner
from agent_framework.policies import anomaly_provenance
from p2_anomaly.combined_dev import policy_clients, EvaluationStop


def test_policy_transport_schema_limit_and_restore(monkeypatch):
    requests=[]
    def create(**options):
        requests.append(options)
        return 'response'
    def factory(provider, **kwargs):
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    old_combo=anomaly_provenance.make_inference_client
    monkeypatch.setattr(runner,'make_inference_client',factory)
    with policy_clients():
        client=anomaly_provenance.make_inference_client('compatible',response_schema={})
        assert client.chat.completions.create(response_format={'type':'json_object'},max_completion_tokens=2048)=='response'
    assert requests[0]['max_tokens']==2048
    assert 'max_completion_tokens' not in requests[0]
    assert requests[0]['response_format']['type']=='json_schema'
    assert runner.make_inference_client is factory
    assert anomaly_provenance.make_inference_client is old_combo


def test_api_failure_cannot_be_scored_as_policy_decision(monkeypatch):
    def create(**options):
        raise openai.APIConnectionError(request=httpx.Request('POST','http://localhost'))
    monkeypatch.setattr(runner,'make_inference_client',lambda *a,**k:
        SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    with policy_clients():
        client=runner.make_inference_client('compatible',response_schema={})
        with pytest.raises(EvaluationStop):
            client.chat.completions.create()
