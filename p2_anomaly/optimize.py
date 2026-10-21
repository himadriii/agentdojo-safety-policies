"""Matched DEV diagnostics and a versioned recovery candidate, never held-out."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

from dotenv import load_dotenv
import openai
from openai.resources.chat.completions import Completions

from p2_anomaly.experiments import CODE_PATHS, digest, save
from p2_anomaly.hosted20 import MODEL, HostedStop, hosted_factories, metrics
from p2_anomaly.recovery import PROMPT_VERSION, agent_variant
from p2_anomaly.shared_summary import load_summary


def jobs(phases, budgets):
    result=[]
    for phase in phases:
        attacks=['none','important_instructions'] if phase=='candidate' else ['none']
        for attack in attacks:
            for k in budgets if attack!='none' else [2]:
                for suite in ('banking','slack','travel'):
                    result.append(dict(phase=phase,attack=attack,k=k,suite=suite))
    return result


@contextmanager
def error_status():
    original=Completions.create
    state={}
    def create(self,*args,**kwargs):
        try:
            return original(self,*args,**kwargs)
        except openai.APIError as exc:
            state['status']=getattr(exc,'status_code',None)
            raise
    Completions.create=create
    try:
        yield state
    finally:
        Completions.create=original


def main():
    parser=argparse.ArgumentParser(__doc__)
    parser.add_argument('--artifact',type=Path,required=True)
    parser.add_argument('--outdir',type=Path,required=True)
    parser.add_argument('--phases',nargs='+',choices=['baseline','recovery_baseline','candidate'],
                        default=['baseline','recovery_baseline','candidate'])
    parser.add_argument('--budgets',nargs='+',type=int,choices=[2,5],default=[2])
    parser.add_argument('--suites',nargs='+',choices=['banking','slack','travel'],default=['banking','slack','travel'])
    parser.add_argument('--user-tasks',nargs='+')
    args=parser.parse_args()
    load_dotenv('.env',override=True)
    for prefix in ('LMSTUDIO','INFERENCE'):
        if not os.getenv(prefix+'_BASE_URL') or not os.getenv(prefix+'_API_KEY'):
            parser.error('Configure hosted endpoint credentials locally')
        os.environ[prefix+'_MAX_RETRIES']='0'
        os.environ[prefix+'_TIMEOUT']='180'
        os.environ[prefix+'_MAX_TOKENS']='4096'
    os.environ.update(REVIEWER_PROVIDER='compatible',REVIEWER_MODEL=MODEL,
                      P2_ANOMALY_MODEL=str(args.artifact.resolve()))
    from agent_framework.policies.anomaly import AnomalyPolicy
    if AnomalyPolicy(args.artifact).artifact is None:
        parser.error('Invalid explicit gate artifact')
    if args.user_tasks and len(args.suites)!=1:
        parser.error('Task selection requires one suite')
    plan=[j for j in jobs(args.phases,args.budgets) if j['suite'] in args.suites]
    splits={s:json.loads(Path(f'splits/{s}_v1.2.json').read_text())['dev'] for s in args.suites}
    if args.user_tasks and not set(args.user_tasks)<=set(splits[args.suites[0]]['user_tasks']):
        parser.error('Only published DEV task IDs are allowed')
    files=set(CODE_PATHS)|{'p2_anomaly/optimize.py','p2_anomaly/recovery.py',
        'p2_anomaly/hosted20.py','agent_framework/policies/anomaly_authorization.py'}
    identity={'scope':'DEV only; matched agent/policy diagnostic; not a held-out score',
        'agent':MODEL,'reviewer':MODEL,'reviewer_prompt':'v2','agent_prompt_variant':PROMPT_VERSION,
        'artifact_sha256':digest(args.artifact),'source_sha256':{p:digest(p) for p in sorted(files)},
        'endpoint_hashes':{p:hashlib.sha256(os.environ[p+'_BASE_URL'].encode()).hexdigest() for p in ('LMSTUDIO','INFERENCE')},
        'split_sha256':{s:digest(f'splits/{s}_v1.2.json') for s in args.suites},
        'jobs':plan,'pilot_tasks':args.user_tasks,'temperature':0,'agent_max_tokens':4096,
        'reviewer_max_tokens':1024,'api_retries':0,'max_503_resumes_per_job':3}
    args.outdir.mkdir(parents=True,exist_ok=True)
    report_file=args.outdir/'evaluation.json'
    report=json.loads(report_file.read_text()) if report_file.exists() else dict(configuration=identity,results={},events=[])
    if report['configuration']!=identity:
        parser.error('Configuration changed; use a new output directory')
    report['status']='running';save(report_file,report)
    from agent_framework import runner
    for job in plan:
        name='{phase}-{suite}-{attack}-k{k}'.format(**job)
        if report['results'].get(name,{}).get('status')=='completed':
            continue
        selected=dict(splits[job['suite']])
        if args.user_tasks:selected['user_tasks']=args.user_tasks
        exposure=Path('p2_anomaly/task_exposure.json');exposed=json.loads(exposure.read_text())
        exposed.setdefault('optimization_dev_tasks',{})[job['suite']]=selected;save(exposure,exposed)
        output=args.outdir/name
        runtime=SimpleNamespace(provider='lmstudio',llm=MODEL,reviewer='llm',reviewer_model=MODEL,
            policy='anomaly' if job['phase']=='candidate' else 'full_approve',benchmark_version='v1.2',
            suite=job['suite'],attack=job['attack'],user_tasks=selected['user_tasks'],
            injection_tasks=selected['injection_tasks'] if job['attack']!='none' else None,
            split_file=f"splits/{job['suite']}_v1.2.json",split='dev',outdir=str(output),force=False)
        print('Starting '+name,flush=True)
        for attempt in range(4):
            with error_status() as status:
                try:
                    with hosted_factories(),agent_variant(job['phase']!='baseline'):
                        returned=runner.run_one(runtime,job['k'])
                    summary=load_summary(output,returned,{'suite':job['suite'],'benchmark_version':'v1.2'},job)
                    expected=len(selected['user_tasks'])*(len(selected['injection_tasks']) if job['attack']!='none' else 1)
                    result=metrics(summary,expected)
                    if subprocess.run([sys.executable,'scripts/verify_traces.py',str(output)]).returncode:
                        raise HostedStop('Trace verification failed')
                    report['results'][name]=dict(job,status='completed',**result)
                    save(report_file,report)
                    break
                except (Exception,KeyboardInterrupt) as exc:
                    event=dict(job=job,error_type=type(exc).__name__,http_status=status.get('status'),attempt=attempt)
                    report['events'].append(event)
                    if status.get('status')==503 and attempt<3:
                        save(report_file,report)
                        print('503 service failure; resuming saved tasks after 30 seconds.',flush=True)
                        time.sleep(30)
                        continue
                    report['status']='stopped; completed results retained'
                    report['results'][name]=dict(job,status='stopped',**{k:v for k,v in event.items() if k!='job'})
                    save(report_file,report)
                    print('Stopped '+name+': '+type(exc).__name__,flush=True)
                    return 2
    report['status']='completed DEV diagnostics; not held-out'
    save(report_file,report)
    return 0


if __name__=='__main__':raise SystemExit(main())
