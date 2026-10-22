from types import SimpleNamespace

import httpx
import openai
import pytest

from agent_framework import runner
from agent_framework.policies import anomaly_provenance
from p2_anomaly.combined_dev import policy_clients, EvaluationStop, hosted_clients, hosted_identity, groq_clients


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


def test_hosted_transport_pins_endpoint_and_disables_retries(monkeypatch):
    from p2_anomaly import hosted20
    captured=[]; closed=[]
    def factory(**settings):
        captured.append(settings)
        return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **k: k)),
                               close=lambda:closed.append(True))
    monkeypatch.setattr(openai,'OpenAI',factory)
    old_runner=runner.make_inference_client
    old_agent=hosted20.make_inference_client
    with hosted_clients('https://host.test/v1'):
        client=runner.make_inference_client('compatible')
        options=client.chat.completions.create(model='model',messages=[],temperature=0)
        assert options['temperature']==0
        with pytest.raises(ValueError):
            runner.make_inference_client('groq')
    assert captured[0]['base_url']=='https://host.test/v1'
    assert captured[0]['max_retries']==0
    assert closed==[True]
    assert runner.make_inference_client is old_runner
    assert hosted20.make_inference_client is old_agent


@pytest.mark.parametrize('url',['http://host.test/v1','https://key@host.test/v1','https://host.test/v1?key=secret'])
def test_hosted_url_rejects_embedded_credentials(url):
    with pytest.raises(ValueError):
        hosted_identity(url)


def test_groq_backend_pins_provider_and_shares_pacing_clock(monkeypatch):
    from agent_framework import inference
    from p2_anomaly import hosted20
    requests=[]; closed=[]; observed=[]
    client=SimpleNamespace(close=lambda:closed.append(True),_client=SimpleNamespace(event_hooks={}),
        chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **k:k)))
    def make(provider, **kwargs):
        requests.append(provider)
        return client
    monkeypatch.setattr(inference,'make_inference_client',make)
    old_runner=runner.make_inference_client
    old_agent=hosted20.make_inference_client
    def paced_call(request,*args,**options):
        observed.append(options)
        return request(*args,**options)
    pacer=SimpleNamespace(call=paced_call,observe=lambda response:None)
    with groq_clients(pacer):
        assert runner.make_inference_client('groq') is client
        client.chat.completions.create(model='openai/gpt-oss-20b')
        with pytest.raises(ValueError):runner.make_inference_client('compatible')
    assert requests==['groq'] and closed==[True]
    assert observed[0]['temperature']==0 and observed[0]['max_tokens']==4096
    assert client._client.event_hooks['response']==[pacer.observe]
    assert runner.make_inference_client is old_runner
    assert hosted20.make_inference_client is old_agent
