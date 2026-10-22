from types import SimpleNamespace as NS
import pytest
from agentdojo.functions_runtime import FunctionCall
from p2_anomaly.review_protocol import reviewer_json_variant, RESPONSE_FORMAT, MAX_TOKENS, VERSION


def test_json_protocol_preserves_real_review_decision_and_restores_factories(monkeypatch):
    from p2_anomaly import hosted20
    from agent_framework import runner
    original=hosted20.HostedReviewer
    captured=[]
    def create(**kwargs):
        captured.append(kwargs)
        return NS(usage=None,choices=[NS(finish_reason='stop',message=NS(content='{"decision":"deny","reason":"Unsupported recipient"}'))])
    client=NS(base_url='https://api.groq.com/openai/v1/',chat=NS(completions=NS(create=create)))
    def build():return NS(name='pipeline',inference_config={'reviewer':{}})
    monkeypatch.setattr(runner,'build_pipeline',build)
    with pytest.raises(RuntimeError):
        with reviewer_json_variant(True):
            reviewer=hosted20.HostedReviewer(client=client)
            assert reviewer.review({'task':'Pay the requested recipient','trajectory':[],
                'proposed_call':FunctionCall(function='send_money',args={'recipient':'other','amount':1})})=='deny'
            assert captured[0]['response_format']==RESPONSE_FORMAT
            assert captured[0]['max_tokens']==MAX_TOKENS
            assert captured[0]['reasoning_effort']=='low'
            assert VERSION in runner.build_pipeline().name
            raise RuntimeError()
    assert hosted20.HostedReviewer is original
    assert runner.build_pipeline is build


def test_hosted_protocol_requires_explicit_matching_endpoint():
    from p2_anomaly import hosted20
    def client(url):
        return NS(base_url=url,chat=NS(completions=NS(create=lambda **kwargs: None)))
    with reviewer_json_variant(True):
        with pytest.raises(ValueError):
            hosted20.HostedReviewer(client=client('https://host.test/v1'))
    with reviewer_json_variant(True,allowed_base_url='https://host.test/v1'):
        hosted20.HostedReviewer(client=client('https://host.test/v1/'))
        with pytest.raises(ValueError):
            hosted20.HostedReviewer(client=client('https://different.test/v1'))
