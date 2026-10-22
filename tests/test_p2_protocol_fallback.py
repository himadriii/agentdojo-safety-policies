from types import SimpleNamespace
import json
import httpx
import openai
import pytest
from openai.resources.chat.completions import Completions
from p2_anomaly.protocol_fallback import protocol_fallback, MODEL
from p2_anomaly.hosted20 import HostedStop


def setup(monkeypatch,code=400,message='expected peg-native format'):
    from p2_anomaly import protocol_fallback as module
    monkeypatch.setenv('LMSTUDIO_BASE_URL','https://primary.invalid/v1')
    response=httpx.Response(code,request=httpx.Request('POST','https://primary.invalid/v1/chat/completions'))
    cls=openai.RateLimitError if code==429 else openai.BadRequestError
    def failed(self,*args,**kwargs):raise cls('failure',response=response,body={'error':message})
    monkeypatch.setattr(Completions,'create',failed)
    calls=[]
    def recovery(*args,**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(usage=None)
    monkeypatch.setattr(module,'make_inference_client',lambda provider:SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=recovery))))
    return openai.OpenAI(api_key='test',base_url='https://primary.invalid/v1'),calls


def test_only_known_format_error_recovers_same_model_and_payload(monkeypatch,tmp_path):
    client,calls=setup(monkeypatch)
    original=Completions.create
    kwargs={'model':MODEL,'messages':[{'role':'user','content':'request'}]}
    with protocol_fallback(tmp_path,enabled=True):client.chat.completions.create(**kwargs)
    assert calls==[kwargs]
    assert Completions.create is original
    assert json.loads((tmp_path/'protocol-fallback.json').read_text())['attempts'][0]['status']=='completed'


@pytest.mark.parametrize('code,message',[(429,'quota'),(400,'invalid arguments')])
def test_quota_and_unrelated_errors_never_fallback(monkeypatch,tmp_path,code,message):
    client,calls=setup(monkeypatch,code,message)
    with protocol_fallback(tmp_path,enabled=True),pytest.raises(openai.APIError):
        client.chat.completions.create(model=MODEL,messages=[])
    assert not calls


def test_fallback_budget_persists_across_contexts(monkeypatch,tmp_path):
    client,calls=setup(monkeypatch)
    with protocol_fallback(tmp_path,limit=1,enabled=True):
        client.chat.completions.create(model=MODEL,messages=[])
    with protocol_fallback(tmp_path,limit=1,enabled=True),pytest.raises(HostedStop,match='BUDGET'):
        client.chat.completions.create(model=MODEL,messages=[])
    assert len(calls)==1
