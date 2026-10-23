from types import SimpleNamespace

import pytest
from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.types import text_content_block_from_string as T
from agent_framework.tools_executor import DENIAL_MESSAGE
from p2_anomaly.slack_recovery import slack_variant, GUIDANCE, RECOVERY, VERSION


def test_slack_guidance_uses_real_denial_and_preserves_caller_history(monkeypatch):
    from p2_anomaly import hosted20
    from agent_framework import runner
    captured=[]
    class Base:
        def query(self, query, runtime, env, messages, extra_args):
            captured.append(messages)
            return query,runtime,env,messages,extra_args
    monkeypatch.setattr(hosted20,'HostedAgent',Base)
    monkeypatch.setattr(runner,'build_pipeline',lambda:SimpleNamespace(name='base',inference_config={'agent':{}}))
    runtime=SimpleNamespace(functions={'send_direct_message':None,'send_channel_message':None})
    messages=[{'role':'assistant','content':[]},{'role':'tool','content':[T(DENIAL_MESSAGE)],'error':None}]
    with slack_variant(True):
        agent=hosted20.HostedAgent()
        agent.query('task',runtime,None,messages,None)
        assert captured[-1][-1]['content']==[T(GUIDANCE)]
        assert not any(m.get('content')==[T(RECOVERY)] for m in captured[-1])
        messages[-1]['error']=DENIAL_MESSAGE
        agent.query('task',runtime,None,messages,None)
        assert captured[-1][-1]['content']==[T(RECOVERY)]
        assert len(messages)==2
        assert runner.build_pipeline().inference_config['agent']['slack_guidance']==VERSION
        # Other suites do not receive Slack instructions.
        agent.query('task',FunctionsRuntime([]),None,messages,None)
        assert captured[-1]==messages
    assert hosted20.HostedAgent is Base


def test_slack_patch_restores_factory_on_failure(monkeypatch):
    from p2_anomaly import hosted20
    from agent_framework import runner
    original_agent,original_builder=hosted20.HostedAgent,runner.build_pipeline
    with pytest.raises(RuntimeError):
        with slack_variant(True):
            raise RuntimeError('stop')
    assert hosted20.HostedAgent is original_agent
    assert runner.build_pipeline is original_builder


def test_final_check_is_bounded_and_preserves_denial(monkeypatch):
    from p2_anomaly import hosted20
    from p2_anomaly.slack_recovery import FINAL_CHECK
    calls=[]
    class Base:
        def query(self,query,runtime,env,messages,extra_args):
            calls.append(messages)
            return query,runtime,env,[*messages,{'role':'assistant','content':[T('Unable.')],'tool_calls':[]}],extra_args
    monkeypatch.setattr(hosted20,'HostedAgent',Base)
    runtime=SimpleNamespace(functions={'send_direct_message':None,'send_channel_message':None})
    messages=[{'role':'tool','content':[T('Blocked')],'error':DENIAL_MESSAGE}]
    with slack_variant(True):
        agent=hosted20.HostedAgent()
        result=agent.query('task',runtime,None,messages,None)
        assert len(calls)==2
        assert sum(m.get('content')==[T(FINAL_CHECK)] for m in result[3])==1
        assert result[3][0]['error']==DENIAL_MESSAGE
        agent.query('task',runtime,None,result[3],None)
        assert len(calls)==3
        calls.clear()
        agent.query('task',runtime,None,[],None)
        assert len(calls)==1
