"""Local-only Ollama bridge; no cloud fallback or silent context truncation."""
from contextlib import contextmanager
import json
from pathlib import Path
import subprocess
import time
from types import SimpleNamespace
import uuid

import httpx
import openai
from openai.types.chat import ChatCompletion

BASE_URL='http://127.0.0.1:11434'
NATIVE_MODEL='gpt-oss:20b'
LOGICAL_MODEL='openai/gpt-oss-20b'
CONTEXT_LENGTH=16384
VERSION='ollama-native-v1'


def supplied(value,default):
    return default if value is None or isinstance(value,openai.NotGiven) else value


def memory_pressure():
    result=subprocess.run(['/usr/sbin/sysctl','-n','kern.memorystatus_vm_pressure_level'],
                          capture_output=True,text=True,timeout=5,check=True)
    return int(result.stdout.strip())


def native_messages(messages):
    """Keep reasoning and map OpenAI tool-result IDs back to native tool names."""
    names={};converted=[]
    for original in messages:
        m=dict(original);content=m.get('content') or ''
        if isinstance(content,list):
            content=''.join(p.get('text','') for p in content)
        item={'role':'system' if m['role']=='developer' else m['role'],'content':content}
        thinking=m.get('reasoning') or m.get('reasoning_content')
        if thinking:item['thinking']=thinking
        if m.get('tool_calls'):
            item['tool_calls']=[]
            for call in m['tool_calls']:
                function=call['function'];arguments=function['arguments']
                if isinstance(arguments,str):arguments=json.loads(arguments)
                if not isinstance(arguments,dict):raise ValueError('Tool arguments must be an object')
                names[call['id']]=function['name']
                item['tool_calls'].append({'function':{'name':function['name'],'arguments':arguments}})
        if m['role']=='tool':
            if m.get('tool_call_id') not in names:raise ValueError('Orphan tool result')
            item['tool_name']=names[m['tool_call_id']]
        converted.append(item)
    return converted


class LocalClient:
    local_ollama=True
    base_url=BASE_URL

    def __init__(self,logfile=None,http=None,health=memory_pressure):
        self.http=http or httpx.Client(base_url=BASE_URL,timeout=900,trust_env=False)
        self.health=health;self.logfile=Path(logfile) if logfile else None
        self.last_http_status=None;self.last_stop_reason=None
        self.chat=SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def log(self,event):
        if self.logfile:
            self.logfile.parent.mkdir(parents=True,exist_ok=True)
            with self.logfile.open('a') as f:f.write(json.dumps(event,sort_keys=True)+'\n')

    def check_health(self):
        from p2_anomaly.hosted20 import HostedStop
        level=self.health()
        if level>=4:
            self.last_stop_reason='LOCAL_MEMORY_PRESSURE_CRITICAL'
            self.log({'event':'resource_stop','memory_pressure':level})
            # Only unload our own model; never terminate another application.
            try:self.http.post('/api/generate',json={'model':NATIVE_MODEL,'keep_alive':0})
            except httpx.HTTPError:pass
            raise HostedStop(self.last_stop_reason)
        return level

    def create(self,**kwargs):
        if kwargs['model']!=LOGICAL_MODEL:raise ValueError('Local evaluation requires the 20B model')
        if supplied(kwargs.get('stream'),False):raise ValueError('Streaming is not used in benchmark evaluation')
        if supplied(kwargs.get('tool_choice'),'auto')!='auto':raise ValueError('Unsupported tool choice')
        before=self.check_health();self.last_http_status=None;self.last_stop_reason=None
        effort=supplied(kwargs.get('reasoning_effort'),'medium')
        if not isinstance(effort,str):effort='medium'
        if effort not in ('low','medium','high'):raise ValueError('Unsupported reasoning effort')
        payload={'model':NATIVE_MODEL,'messages':native_messages(kwargs['messages']),
            'stream':False,'truncate':False,'shift':False,'think':effort,'keep_alive':'10m',
            'options':{'num_ctx':CONTEXT_LENGTH,'num_predict':supplied(kwargs.get('max_tokens'),4096),
                       'temperature':supplied(kwargs.get('temperature'),0)}}
        tools=supplied(kwargs.get('tools'),None)
        if tools:payload['tools']=tools
        fmt=kwargs.get('response_format')
        if isinstance(fmt,dict):
            if fmt['type']=='json_schema':payload['format']=fmt['json_schema']['schema']
            elif fmt['type']=='json_object':payload['format']='json'
            else:raise ValueError('Unsupported response format')
        started=time.monotonic()
        try:response=self.http.post('/api/chat',json=payload)
        except httpx.HTTPError as exc:
            raise openai.APIConnectionError(request=httpx.Request('POST',BASE_URL+'/api/chat')) from exc
        if response.is_error:
            self.last_http_status=response.status_code
            self.log({'event':'http_error','status':response.status_code})
            body={'code':'local_ollama_error'}
            try:message=str(response.json().get('error','Local inference failed'))
            except ValueError:message='Local inference failed'
            error={400:openai.BadRequestError,429:openai.RateLimitError}.get(response.status_code,openai.APIStatusError)
            raise error(message,response=response,body=body)
        raw=response.json();message=raw['message'];request_id=uuid.uuid4().hex
        calls=[]
        for index,call in enumerate(message.get('tool_calls') or []):
            arguments=call['function']['arguments']
            if isinstance(arguments,str):arguments=json.loads(arguments)
            if not isinstance(arguments,dict):raise ValueError('Native tool arguments must be an object')
            calls.append({'id':f'call_local_{request_id}_{index}','type':'function',
                'function':{'name':call['function']['name'],'arguments':json.dumps(arguments)}})
        assistant={'role':'assistant','content':message.get('content') or None,'tool_calls':calls or None}
        if message.get('thinking'):assistant['reasoning']=message['thinking']
        prompt=raw.get('prompt_eval_count',0);completion=raw.get('eval_count',0)
        self.log({'event':'completion','request_id':request_id,'memory_pressure_before':before,
                  'prompt_tokens':prompt,'completion_tokens':completion,'done_reason':raw.get('done_reason'),
                  'duration_seconds':round(time.monotonic()-started,3)})
        self.check_health()
        return ChatCompletion.model_validate({'id':'local-'+request_id,'object':'chat.completion',
            'created':int(time.time()),'model':LOGICAL_MODEL,
            'choices':[{'index':0,'message':assistant,'finish_reason':'tool_calls' if calls else
                        ('length' if raw.get('done_reason')=='length' else 'stop')}],
            'usage':{'prompt_tokens':prompt,'completion_tokens':completion,'total_tokens':prompt+completion}})

    def close(self):self.http.close()


def runtime_identity():
    with httpx.Client(base_url=BASE_URL,timeout=15,trust_env=False) as client:
        version=client.get('/api/version');version.raise_for_status()
        tags=client.get('/api/tags');tags.raise_for_status()
        model=next((m for m in tags.json()['models'] if m['name']==NATIVE_MODEL),None)
        if model is None:raise ValueError('Download gpt-oss:20b before local evaluation')
        return {'version':VERSION,'server_version':version.json()['version'],'base_url':BASE_URL,
            'native_model':NATIVE_MODEL,'logical_model':LOGICAL_MODEL,'model_digest':model['digest'],
            'model_details':model.get('details',{}),'context_length':CONTEXT_LENGTH,
            'parallel_requests':1,'loaded_model_copies':1,'truncate':False,'shift':False,
            'critical_memory_stop_level':4,'no_cloud_fallback':True}


@contextmanager
def local_factories(enabled,outdir,expected=None):
    if not enabled:
        yield
        return
    from agent_framework import runner
    from p2_anomaly import hosted20
    if expected is not None and runtime_identity()!=expected:raise ValueError('Local runtime changed')
    originals=runner.make_inference_client,hosted20.make_inference_client
    original_builder=runner.build_pipeline
    clients=[]
    def make_client(provider,**kwargs):
        if provider!='compatible':raise ValueError('Local run cannot call a cloud provider')
        client=LocalClient(Path(outdir)/'local-api.jsonl');clients.append(client);return client
    def build(*args,**kwargs):
        pipeline=original_builder(*args,**kwargs)
        pipeline.name+='-'+VERSION
        for component in ('agent','reviewer'):
            pipeline.inference_config[component]['local_runtime']=expected
        return pipeline
    runner.build_pipeline=build
    runner.make_inference_client=hosted20.make_inference_client=make_client
    try:yield
    finally:
        runner.make_inference_client,hosted20.make_inference_client=originals
        runner.build_pipeline=original_builder
        for client in clients:client.close()
