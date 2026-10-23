"""Shared-prompt DEV ablation. No P2 agent/reviewer prompt patches or held-out runs."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import openai
from dotenv import dotenv_values
from agentdojo.agent_pipeline.agent_pipeline import load_system_message
from agent_framework import runner, inference
from agent_framework.llm_reviewer import SYSTEM_PROMPT, REVIEWER_PROMPT_VERSION
from p2_anomaly.disjoint_train import VARIANTS

MODEL='openai/gpt-oss-20b'
ROOT=Path(__file__).resolve().parents[1]


class InfrastructureStop(BaseException):
    """Keep API failures out of scored denials without changing shared prompts."""


def save(path, value):
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n');temp.replace(path)


@contextmanager
def guarded_clients():
    original=inference.make_inference_client
    previous=runner.make_inference_client
    clients=[]
    def factory(provider,**kwargs):
        client=original(provider,**kwargs);clients.append(client)
        create=client.chat.completions.create
        def guarded(*args,**options):
            try:return create(*args,**options)
            except openai.APIError as error:
                status=getattr(error,'status_code',None)
                raise InfrastructureStop(f'{type(error).__name__}; HTTP {status}') from None
        client.chat.completions.create=guarded
        return client
    inference.make_inference_client=runner.make_inference_client=factory
    try:yield
    finally:
        inference.make_inference_client=original;runner.make_inference_client=previous
        for client in clients:client.close()


def summarize(output,suite,attack,expected):
    paths=list(output.glob(f'*/{suite}/user_task_*/{attack}/*.json'))
    traces=[json.loads(p.read_text()) for p in paths]
    if len(traces)!=expected or any(not isinstance(d.get('utility'),bool) or d.get('error') for d in traces):
        raise InfrastructureStop('Incomplete or errored task traces; no final score')
    cases=[]
    for d in traces:
        decisions=d.get('approval_decisions',[])
        if any(str(a.get('reviewer_reason','')).startswith(('REVIEWER_ERROR','REVIEWER_PARSE_FAILURE')) for a in decisions):
            raise InfrastructureStop('Reviewer error/parse failure; no final score')
        attacked=attack!='none'
        if attacked and not isinstance(d.get('security'),bool):raise InfrastructureStop('Missing security result')
        cases.append({'user_task_id':d['user_task_id'],'injection_task_id':d['injection_task_id'],
            'utility':d['utility'],'attack_succeeded':d['security'] if attacked else None,
            'completed':bool(d['utility'] and (not d['security'] if attacked else True)),
            'reviews':sum(bool(a.get('reviewer_called')) for a in decisions),
            'auto_denials':sum(a['outcome']=='auto_deny' for a in decisions),
            'budget_exhausted_denials':sum(a['outcome']=='budget_exhausted_deny' for a in decisions)})
    return {'n':expected,'completed':sum(c['completed'] for c in cases),
        'tcr':sum(c['completed'] for c in cases)/expected,
        'hitl_load_completed':sum(c['reviews'] for c in cases if c['completed']),
        'total_reviews':sum(c['reviews'] for c in cases),
        'attack_successes':sum(c['attack_succeeded'] for c in cases) if attack!='none' else None,
        'auto_denials':sum(c['auto_denials'] for c in cases),
        'budget_exhausted_denials':sum(c['budget_exhausted_denials'] for c in cases),
        'cases':sorted(cases,key=lambda c:(c['user_task_id'],c['injection_task_id'] or ''))}


def main():
    p=argparse.ArgumentParser(__doc__)
    p.add_argument('--artifacts',type=Path,required=True);p.add_argument('--outdir',type=Path,required=True)
    p.add_argument('--base-url',required=True);p.add_argument('--env-file',type=Path,required=True)
    p.add_argument('--variants',nargs='+',choices=VARIANTS,default=['detector_generic','generic_rules_only','detector_only'])
    p.add_argument('--suites',nargs='+',choices=('slack','banking','travel'),default=['slack','banking','travel'])
    p.add_argument('--attack',choices=('important_instructions','none'),default='important_instructions')
    a=p.parse_args();private=dotenv_values(a.env_file)
    os.environ.update(LLM_PROVIDER='lmstudio',LLM_MODEL=MODEL,LMSTUDIO_MODEL=MODEL,
        LMSTUDIO_BASE_URL=a.base_url,LMSTUDIO_API_KEY=private.get('LMSTUDIO_API_KEY') or private.get('INFERENCE_API_KEY') or 'aarav_ntu',
        LMSTUDIO_MAX_RETRIES='0',LMSTUDIO_TIMEOUT='90',REVIEWER_PROVIDER='lmstudio',REVIEWER_MODEL=MODEL)
    artifacts=a.artifacts.resolve();out=a.outdir.resolve();out.mkdir(parents=True,exist_ok=True)
    sources={str(x.relative_to(ROOT)):hashlib.sha256(x.read_bytes()).hexdigest()
             for folder in ('agent_framework','p2_anomaly') for x in (ROOT/folder).rglob('*.py') if 'artifacts' not in x.parts}
    identity={'scope':'Task-disjoint DEV, previously exposed during development; not held-out',
        'variants':a.variants,'suites':a.suites,'attack':a.attack,'k':2,'endpoint':a.base_url,
        'agent_model':MODEL,'reviewer_model':MODEL,'reviewer_prompt_version':REVIEWER_PROMPT_VERSION,
        'shared_system_prompt_sha256':hashlib.sha256(load_system_message(None).encode()).hexdigest(),
        'shared_reviewer_prompt_sha256':hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest(),
        'source_sha256':sources,'custom_prompt_guidance':False,
        'artifact_sha256':{v:hashlib.sha256((artifacts/v/'model.joblib').read_bytes()).hexdigest() for v in a.variants}}
    path=out/'evaluation.json';r=json.loads(path.read_text()) if path.exists() else {'configuration':identity,'results':{},'events':[]}
    if r['configuration']!=identity:raise ValueError('Configuration changed; start a distinct study')
    r['status']='running';save(path,r)
    try:
        for variant in a.variants:
            os.environ['P2_ANOMALY_MODEL']=str(artifacts/variant/'model.joblib')
            for suite in a.suites:
                job=f'{variant}-{suite}-{a.attack}'
                if job in r['results']:continue
                split=json.loads((ROOT/f'splits/{suite}_v1.2.json').read_text())['dev'];output=out/job
                print('START',job,flush=True)
                args=SimpleNamespace(provider='lmstudio',llm=MODEL,reviewer='llm',reviewer_model=MODEL,
                    policy='anomaly',benchmark_version='v1.2',suite=suite,attack=a.attack,
                    user_tasks=split['user_tasks'],injection_tasks=split['injection_tasks'] if a.attack!='none' else None,
                    split_file=str(ROOT/f'splits/{suite}_v1.2.json'),split='dev',outdir=str(output),force=False,shadow_audit=False)
                with guarded_clients():runner.run_one(args,2)
                measured=summarize(output,suite,a.attack,len(split['user_tasks'])*(len(split['injection_tasks']) if a.attack!='none' else 1))
                if subprocess.run([sys.executable,str(ROOT/'scripts/verify_traces.py'),str(output)]).returncode:
                    raise InfrastructureStop('Trace verification failed')
                r['results'][job]=measured;save(path,r);print('DONE',job,measured['completed'],measured['n'],flush=True)
    except (InfrastructureStop,Exception,KeyboardInterrupt) as error:
        r['status']='stopped; completed results retained'
        r['events'].append({'job':job,'type':type(error).__name__,'reason':str(error)[:160] if isinstance(error,InfrastructureStop) else type(error).__name__})
        save(path,r);print(r['events'][-1],flush=True);return 2
    r['status']='completed';save(path,r);return 0


if __name__=='__main__':raise SystemExit(main())
