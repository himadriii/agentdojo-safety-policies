from types import SimpleNamespace as NS
import httpx
import openai
import pytest
from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.types import text_content_block_from_string as T
from p2_anomaly.hosted20 import HostedAgent,HostedStop


def test_groq_tool_format_repair_is_bounded_and_never_retries_quota(monkeypatch):
    import p2_anomaly.hosted20 as module
    response=NS(choices=[NS(message=NS(model_extra={},role='assistant',content='done',tool_calls=None))])
    # Test the transport behavior without coupling to SDK message conversion.
    monkeypatch.setattr(module,'_openai_to_assistant_message',lambda m:{'role':'assistant','content':[T(m.content)],'tool_calls':None})
    request=httpx.Request('POST','https://api.groq.com/openai/v1/chat/completions')
    def err(cls,code,status):return cls('provider failure',response=httpx.Response(status,request=request),body={'code':code})
    for failure,expected in [(err(openai.BadRequestError,'tool_use_failed',400),4),
                             (err(openai.BadRequestError,'invalid_request_error',400),1),
                             (err(openai.RateLimitError,'rate_limit_exceeded',429),1)]:
        calls=[]
        def create(*args,**kwargs):calls.append(1);raise failure
        monkeypatch.setattr(module.chat_completion_request,'__wrapped__',create)
        agent=HostedAgent(NS(base_url='https://api.groq.com/openai/v1'),'test')
        with pytest.raises(HostedStop):agent.query('request',FunctionsRuntime([]))
        assert len(calls)==expected
    calls=[]
    def recover(*args,**kwargs):
        calls.append(1)
        if len(calls)==1:raise err(openai.BadRequestError,'tool_use_failed',400)
        return response
    monkeypatch.setattr(module.chat_completion_request,'__wrapped__',recover)
    assert agent.query('request',FunctionsRuntime([]))[3][-1]['content']==[T('done')]
    assert len(calls)==2
