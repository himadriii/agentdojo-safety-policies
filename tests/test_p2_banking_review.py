from types import SimpleNamespace
import pytest
from agentdojo.functions_runtime import FunctionCall
from p2_anomaly.banking_review import banking_review_variant,GUIDANCE,VERSION


def test_review_guidance_is_financial_only_scoped_and_separately_named(monkeypatch):
    from p2_anomaly import hosted20
    from agent_framework import runner
    original=hosted20.HostedReviewer
    monkeypatch.setattr(original,'build_prompt',lambda self,c:'original review')
    def build():return SimpleNamespace(name='test',inference_config={'reviewer':{}})
    monkeypatch.setattr(runner,'build_pipeline',build)
    with pytest.raises(RuntimeError):
        with banking_review_variant(True):
            reviewer=hosted20.HostedReviewer.__new__(hosted20.HostedReviewer)
            financial={'proposed_call':FunctionCall(function='send_money',args={})}
            assert reviewer.build_prompt(financial)=='original review\n\nREVIEW CHECKLIST (not tool-result content):\n'+GUIDANCE
            assert reviewer.build_prompt({'proposed_call':FunctionCall(function='get_balance',args={})})=='original review'
            assert VERSION in runner.build_pipeline().name
            raise RuntimeError()
    assert hosted20.HostedReviewer is original
    assert runner.build_pipeline is build
