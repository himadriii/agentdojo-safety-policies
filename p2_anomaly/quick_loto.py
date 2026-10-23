"""Two-case matched DEV screening, never a full-suite or held-out result."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import joblib
import openai
from dotenv import dotenv_values
from agent_framework import runner,inference,llm_providers
from p2_anomaly.disjoint_dev import summarize,save,InfrastructureStop,MODEL
from p2_anomaly.train import fit_artifact
from p2_anomaly.groq_pacing import GroqPacer
from agent_framework.policies.anomaly_authorization import VERSION

ROOT=Path(__file__).resolve().parents[1]
TASK='slack:user_task_13'


def build(source,out):
    if out.exists():raise ValueError('Use fresh artifacts')
    m=json.loads((source/'manifest.json').read_text())
    raw=(source/'reference_features.json').read_bytes()
    assert hashlib.sha256(raw.rstrip(b'\n')).hexdigest()==m['data_sha256']
    data=json.loads(raw)
    excluded_groups={r['group_id'] for rows in data.values() for r in rows if r['user_task']==TASK}
    filtered={part:[r for r in data[part] if r['user_task']!=TASK and r['group_id'] not in excluded_groups] for part in ('fit','calibration')}
    assert all(r['user_task']!=TASK and r['group_id'] not in excluded_groups for rows in filtered.values() for r in rows)
    artifact,report=fit_artifact(filtered['fit'],filtered['calibration'],m['tool_table'],review_rate=0.1,support_mode='category')
    artifact.update(feature_transform=m['feature_transform'],authorization_guards=VERSION,context_guards=True,
        review_required_tools=sorted(k for k,v in m['tool_table'].items() if v!='read'))
    out.mkdir(parents=True);joblib.dump(artifact,out/'model.joblib')
    report.update(scope='One-task-out DEV screening; task and known family excluded; previous policy-development exposure remains',
        excluded_task=TASK,excluded_groups=sorted(excluded_groups),fit_score_overlap=[],calibration_score_overlap=[],
        source_data_sha256=m['data_sha256'],model_sha256=hashlib.sha256((out/'model.joblib').read_bytes()).hexdigest())
    save(out/'manifest.json',report);save(out/'reference_features.json',filtered)
    return report


@contextmanager
def paced_clients(pacer):
    original=inference.make_inference_client;old_runner=runner.make_inference_client
    original_make_agent=runner.make_groq_llm
    clients=[]
    def factory(provider,**kwargs):
        client=original(provider,**kwargs);clients.append(client)
        client._client.event_hooks.setdefault('response',[]).append(pacer.observe)
        create=client.chat.completions.create
        def guarded(*args,**options):
            # Explicit common transport settings, never an agent/reviewer prompt change.
            options['temperature']=0
            if isinstance(options.get('max_tokens'),openai.NotGiven) or options.get('max_tokens') is None:options['max_tokens']=4096
            try:return pacer.call(create,*args,**options)
            except openai.APIError as error:
                # Preserve the shared agent's bounded tool-format retries.
                if options.get('tools') and isinstance(error,openai.BadRequestError) and 'tool_use_failed' in str(error):
                    raise
                raise InfrastructureStop(f'{type(error).__name__}; HTTP {getattr(error,"status_code",None)}') from None
        client.chat.completions.create=guarded
        return client
    # The shared Groq agent and compatible adapters are preserved; only its
    # client factory is supplied by the common rate-limited inference factory.
    def make_agent(model):
        from agentdojo.models import MODEL_NAMES
        MODEL_NAMES.setdefault(model,'AI assistant');MODEL_NAMES.setdefault(model.replace('/','_'),'AI assistant')
        return llm_providers.RobustOpenAILLM(factory('groq'),model)
    inference.make_inference_client=runner.make_inference_client=factory;runner.make_groq_llm=make_agent
    try:yield
    finally:
        inference.make_inference_client=original;runner.make_inference_client=old_runner;runner.make_groq_llm=original_make_agent
        for client in clients:client.close()


def main():
    p=argparse.ArgumentParser(__doc__);p.add_argument('--env-file',type=Path,required=True);p.add_argument('--outdir',type=Path,required=True)
    a=p.parse_args();private=dotenv_values(a.env_file)
    os.environ.update(GROQ_API_KEY=private['GROQ_API_KEY'],GROQ_MAX_RETRIES='0',GROQ_TIMEOUT='90',REVIEWER_PROVIDER='groq',REVIEWER_MODEL=MODEL)
    out=a.outdir.resolve();out.mkdir(parents=True,exist_ok=True)
    candidate=ROOT/'p2_anomaly/artifacts/development/quick-loto-task13-v1'
    if not candidate.exists():build(ROOT/'p2_anomaly/artifacts/development/cross-suite-v7',candidate)
    models={'workspace_only':ROOT/'p2_anomaly/artifacts/development/disjoint-v1/detector_generic/model.joblib','leave_task13_out':candidate/'model.joblib'}
    identity={'scope':'Targeted four-episode DEV screening; not representative or held-out','task':'user_task_13','suite':'slack','attacks':['injection_task_1','injection_task_3'],'agent_model':MODEL,'reviewer_model':MODEL,'provider':'groq','k':2,'shared_prompts':True,'temperature':0,'agent_max_tokens':4096,'reviewer_max_tokens':1024,'free_tier_only':True,'model_sha256':{k:hashlib.sha256(v.read_bytes()).hexdigest() for k,v in models.items()},'source_sha256':{str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for folder in ['agent_framework','p2_anomaly'] for f in (ROOT/folder).rglob('*.py') if 'artifacts' not in f.parts}}
    path=out/'evaluation.json';r=json.loads(path.read_text()) if path.exists() else {'configuration':identity,'results':{},'events':[]}
    if r['configuration']!=identity:raise ValueError('Changed configuration; cannot resume')
    r['status']='running';save(path,r);pacer=GroqPacer(out/'rate-limits.jsonl')
    try:
        for variant,model in models.items():
            if variant in r['results']:continue
            os.environ['P2_ANOMALY_MODEL']=str(model);output=out/variant
            args=SimpleNamespace(provider='groq',llm=MODEL,reviewer='llm',reviewer_model=MODEL,policy='anomaly',benchmark_version='v1.2',suite='slack',attack='important_instructions',user_tasks=['user_task_13'],injection_tasks=['injection_task_1','injection_task_3'],split_file=str(ROOT/'splits/slack_v1.2.json'),split='dev',outdir=str(output),force=False,shadow_audit=False)
            print('START',variant,flush=True)
            with paced_clients(pacer):runner.run_one(args,2)
            r['results'][variant]=summarize(output,'slack','important_instructions',2);save(path,r)
            print('DONE',variant,r['results'][variant]['completed'],'/2',flush=True)
    except (InfrastructureStop,Exception,KeyboardInterrupt) as error:
        r['status']='stopped; completed cases retained';r['events'].append({'variant':variant,'type':type(error).__name__,'reason':str(error)[:160] if isinstance(error,InfrastructureStop) else type(error).__name__});save(path,r);print(r['events'][-1],flush=True);return 2
    r['status']='completed';save(path,r);return 0


if __name__=='__main__':raise SystemExit(main())
