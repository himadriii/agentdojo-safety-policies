import json
from types import SimpleNamespace as NS

import httpx
import openai
import pytest
from agentdojo.functions_runtime import FunctionCall
from p2_anomaly.local20 import LocalClient,native_messages,CONTEXT_LENGTH,LOGICAL_MODEL
from p2_anomaly.hosted20 import HostedStop


def test_native_bridge_keeps_tool_identity_reasoning_and_disallows_truncation():
    requests=[]
    def respond(request):
        body=json.loads(request.content);requests.append(body)
        return httpx.Response(200,json={'message':{'role':'assistant','thinking':'private reasoning',
            'content':'','tool_calls':[{'function':{'name':'get_balance','arguments':{}}}]},
            'done_reason':'stop','prompt_eval_count':24,'eval_count':8})
    client=LocalClient(http=httpx.Client(base_url='http://127.0.0.1:11434',transport=httpx.MockTransport(respond)),health=lambda:1)
    history=[{'role':'assistant','content':None,'reasoning':'earlier thought','tool_calls':[
        {'id':'call-A','function':{'name':'get_balance','arguments':'{}'}}]},
        {'role':'tool','tool_call_id':'call-A','content':'200'}]
    result=client.chat.completions.create(model=LOGICAL_MODEL,messages=history,max_tokens=100,
        reasoning_effort='low',temperature=0)
    payload=requests[0]
    assert payload['messages'][0]['thinking']=='earlier thought'
    assert payload['messages'][1]['tool_name']=='get_balance'
    assert payload['truncate'] is False and payload['shift'] is False
    assert payload['options']=={'num_ctx':CONTEXT_LENGTH,'num_predict':100,'temperature':0}
    assert payload['think']=='low'
    assert result.choices[0].finish_reason=='tool_calls'
    assert result.choices[0].message.model_extra['reasoning']=='private reasoning'
    assert result.usage.total_tokens==32
    assert json.loads(result.choices[0].message.tool_calls[0].function.arguments)=={}
    with pytest.raises(ValueError,match='Orphan'):native_messages([{'role':'tool','content':'x','tool_call_id':'missing'}])


def test_local_bridge_stops_and_unloads_only_its_model_on_critical_memory():
    requests=[]
    def respond(request):requests.append(request);return httpx.Response(200,json={'done':True})
    client=LocalClient(http=httpx.Client(base_url='http://127.0.0.1:11434',transport=httpx.MockTransport(respond)),health=lambda:4)
    with pytest.raises(HostedStop,match='MEMORY_PRESSURE'):
        client.create(model=LOGICAL_MODEL,messages=[])
    assert len(requests)==1 and requests[0].url.path=='/api/generate'
    assert json.loads(requests[0].content)=={'model':'gpt-oss:20b','keep_alive':0}


def test_local_context_error_stops_without_retry_or_fallback():
    requests=[]
    def respond(request):requests.append(request);return httpx.Response(400,json={'error':'input exceeds context length'})
    client=LocalClient(http=httpx.Client(base_url='http://127.0.0.1:11434',transport=httpx.MockTransport(respond)),health=lambda:1)
    with pytest.raises(openai.BadRequestError):client.create(model=LOGICAL_MODEL,messages=[])
    assert len(requests)==1 and client.last_http_status==400


def test_local_reviewer_uses_schema_and_low_reasoning_without_changing_decision():
    from p2_anomaly.review_protocol import reviewer_json_variant,RESPONSE_FORMAT
    from p2_anomaly import hosted20
    requests=[]
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json={'message':{'role':'assistant','content':'{"decision":"deny","reason":"Unrequested transfer"}'},'done_reason':'stop'})
    client=LocalClient(http=httpx.Client(base_url='http://127.0.0.1:11434',transport=httpx.MockTransport(respond)),health=lambda:1)
    with reviewer_json_variant(True):
        reviewer=hosted20.HostedReviewer(client=client)
        assert reviewer.review({'task':'Read balance','trajectory':[],
            'proposed_call':FunctionCall(function='send_money',args={'recipient':'unknown','amount':10})})=='deny'
    assert requests[0]['format']==RESPONSE_FORMAT['json_schema']['schema']
    assert requests[0]['think']=='low'
    assert requests[0]['options']['num_predict']==2048


def test_local_factories_reject_cloud_routes_and_restore(monkeypatch,tmp_path):
    from p2_anomaly import local20,hosted20
    from agent_framework import runner
    expected={'model_digest':'fixture'}
    monkeypatch.setattr(local20,'runtime_identity',lambda:expected)
    previous=runner.make_inference_client,hosted20.make_inference_client,runner.build_pipeline
    with pytest.raises(RuntimeError):
        with local20.local_factories(True,tmp_path,expected):
            with pytest.raises(ValueError,match='cloud'):runner.make_inference_client('groq')
            assert runner.make_inference_client('compatible').local_ollama
            raise RuntimeError()
    assert (runner.make_inference_client,hosted20.make_inference_client,runner.build_pipeline)==previous


def test_openai_omitted_values_become_explicit_local_defaults():
    requests=[]
    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200,json={'message':{'role':'assistant','content':'done'},'done_reason':'stop'})
    client=LocalClient(http=httpx.Client(base_url='http://127.0.0.1:11434',transport=httpx.MockTransport(respond)),health=lambda:1)
    client.create(model=LOGICAL_MODEL,messages=[],temperature=openai.NOT_GIVEN,
                  reasoning_effort=openai.NOT_GIVEN,tools=openai.NOT_GIVEN,
                  tool_choice=openai.NOT_GIVEN,max_tokens=openai.NOT_GIVEN)
    assert requests[0]['options']['temperature']==0
    assert requests[0]['options']['num_predict']==4096
    assert requests[0]['think']=='medium'
    assert 'tools' not in requests[0]
