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
from p2_anomaly.recovery import PROMPT_VERSION, INSTRUCTIONS, BANKING_INSTRUCTIONS, RECOVERY_MESSAGE, TYPOGRAPHY_VERSION, agent_variant
from p2_anomaly.shared_summary import load_summary
from p2_anomaly.protocol_fallback import VERSION as FALLBACK_VERSION, protocol_fallback
from p2_anomaly.local20 import BASE_URL as LOCAL_URL, runtime_identity, local_factories
from p2_anomaly.review_protocol import VERSION as JSON_VERSION, MAX_TOKENS as REVIEW_MAX_TOKENS, RESPONSE_FORMAT, reviewer_json_variant
from p2_anomaly.banking_review import VERSION as BANK_REVIEW_VERSION, GUIDANCE, banking_review_variant
from p2_anomaly.completion_check import VERSION as CHECK_VERSION, INSTRUCTION as CHECK_INSTRUCTION, completion_variant


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
def error_status(groq=False, clock_state=None):
    original=Completions.create
    state={}
    last_request=clock_state if clock_state is not None else [None]
    def create(self,*args,**kwargs):
        if groq:
            kwargs["temperature"]=0
            if last_request[0] is not None:
                delay=65-(time.monotonic()-last_request[0])
                if delay>0:
                    print(f"Free-tier pacing: waiting {delay:.0f}s",flush=True)
                    time.sleep(delay)
            last_request[0]=time.monotonic()
            kwargs.setdefault("max_tokens",4096)
        try:
            response=original(self,*args,**kwargs)
            state.pop("status",None)
            return response
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
    parser.add_argument('--groq-fallback',action='store_true',help='Bounded 20B-only recovery for the known native parser error')
    parser.add_argument('--max-groq-fallbacks',type=int,choices=range(1,11),default=10)
    parser.add_argument('--completion-check',action='store_true',help='One bounded agent finalization pass; separate from reviewer')
    parser.add_argument('--clean-only',action='store_true',help='Validate legitimate-task behavior before attacked runs')
    parser.add_argument('--reviewer-json',action='store_true')
    parser.add_argument('--banking-review-guidance',action='store_true')
    parser.add_argument('--attacked-only',action='store_true')
    parser.add_argument('--injection-tasks',nargs='+')
    parser.add_argument('--provider',choices=['lmstudio','groq','ollama'],default='lmstudio')
    args=parser.parse_args()
    if args.reviewer_json and args.provider not in ('groq','ollama'):parser.error('Strict reviewer protocol requires Groq or local Ollama')
    load_dotenv('.env',override=True)
    if args.provider=='groq':
        if not os.getenv('GROQ_API_KEY'):parser.error('Configure GROQ_API_KEY locally')
        if args.groq_fallback:parser.error('Fallback is only for hosted runs')
        os.environ.update(GROQ_MAX_RETRIES='0',GROQ_TIMEOUT='180')
    elif args.provider=='ollama':
        if args.groq_fallback:parser.error('Local runs cannot use cloud fallback')
        os.environ.update(INFERENCE_BASE_URL=LOCAL_URL,INFERENCE_API_KEY='local-inference',
            INFERENCE_MAX_RETRIES='0',INFERENCE_TIMEOUT='900',INFERENCE_MAX_TOKENS='4096')
    else:
        for prefix in ('LMSTUDIO','INFERENCE'):
            if not os.getenv(prefix+'_BASE_URL') or not os.getenv(prefix+'_API_KEY'):
                parser.error('Configure hosted endpoint credentials locally')
            os.environ[prefix+'_MAX_RETRIES']='0'
            os.environ[prefix+'_TIMEOUT']='180'
            os.environ[prefix+'_MAX_TOKENS']='4096'
    os.environ.update(REVIEWER_PROVIDER='groq' if args.provider=='groq' else 'compatible',
                      REVIEWER_MODEL=MODEL,P2_ANOMALY_MODEL=str(args.artifact.resolve()))
    from agent_framework.policies.anomaly import AnomalyPolicy
    if args.groq_fallback and not os.getenv('GROQ_API_KEY'):
        parser.error('Groq recovery requires the existing free-tier key')
    if AnomalyPolicy(args.artifact).artifact is None:
        parser.error('Invalid explicit gate artifact')
    if args.user_tasks and len(args.suites)!=1:
        parser.error('Task selection requires one suite')
    plan=[j for j in jobs(args.phases,args.budgets) if j['suite'] in args.suites]
    if args.clean_only and args.attacked_only:parser.error('Choose clean or attacked runs')
    if args.attacked_only:plan=[j for j in plan if j['attack']!='none']
    if args.clean_only:plan=[j for j in plan if j['attack']=='none']
    splits={s:json.loads(Path(f'splits/{s}_v1.2.json').read_text())['dev'] for s in args.suites}
    if args.user_tasks and not set(args.user_tasks)<=set(splits[args.suites[0]]['user_tasks']):
        parser.error('Only published DEV task IDs are allowed')
    if args.injection_tasks and (len(args.suites)!=1 or not set(args.injection_tasks)<=set(splits[args.suites[0]]['injection_tasks'])):
        parser.error('Only published DEV injection IDs from one suite are allowed')
    local_runtime=runtime_identity() if args.provider=='ollama' else None
    files=set(CODE_PATHS)|{'p2_anomaly/optimize.py','p2_anomaly/recovery.py',
        'p2_anomaly/hosted20.py','agent_framework/policies/anomaly_authorization.py','p2_anomaly/output_format.py',
        'p2_anomaly/protocol_fallback.py','p2_anomaly/completion_check.py','p2_anomaly/banking_review.py','p2_anomaly/review_protocol.py','p2_anomaly/local20.py'}
    identity={'scope':'DEV only; matched agent/policy diagnostic; not a held-out score',
        'provider':args.provider,'local_runtime':local_runtime,'groq_request_interval_seconds':65 if args.provider=='groq' else None,
        'agent':MODEL,'reviewer':MODEL,'reviewer_prompt':'v2','agent_prompt_variant':PROMPT_VERSION,
        'agent_instructions':INSTRUCTIONS,'banking_instructions':BANKING_INSTRUCTIONS,'recovery_message':RECOVERY_MESSAGE,'output_format':TYPOGRAPHY_VERSION,
        'protocol_fallback':{'version':FALLBACK_VERSION,'enabled':args.groq_fallback,
                             'model':MODEL,'max_attempts':args.max_groq_fallbacks,'api_retries':0},
        'reviewer_protocol':{'enabled':args.reviewer_json,'version':JSON_VERSION,'response_format':RESPONSE_FORMAT,'reasoning_effort':'low' if args.reviewer_json else 'default'},
        'banking_review':{'enabled':args.banking_review_guidance,'version':BANK_REVIEW_VERSION,'guidance':GUIDANCE},
        'completion_check':{'enabled':args.completion_check,'version':CHECK_VERSION,'instruction':CHECK_INSTRUCTION},
        'artifact_sha256':digest(args.artifact),'source_sha256':{p:digest(p) for p in sorted(files)},
        'endpoint_hashes':{p:hashlib.sha256(os.environ[p+'_BASE_URL'].encode()).hexdigest() for p in ('LMSTUDIO','INFERENCE')} if args.provider=='lmstudio' else ({'ollama':LOCAL_URL} if args.provider=='ollama' else {'groq':'https://api.groq.com/openai/v1'}),
        'split_sha256':{s:digest(f'splits/{s}_v1.2.json') for s in args.suites},
        'jobs':plan,'pilot_tasks':args.user_tasks,'pilot_injection_tasks':args.injection_tasks,'temperature':0,'temperature_enforced':args.provider in ('groq','ollama'),'agent_max_tokens':4096,
        'reviewer_max_tokens':REVIEW_MAX_TOKENS if args.reviewer_json else 1024,'api_retries':0,'max_groq_tool_format_retries':3,'max_503_resumes_per_job':3}
    args.outdir.mkdir(parents=True,exist_ok=True)
    report_file=args.outdir/'evaluation.json'
    report=json.loads(report_file.read_text()) if report_file.exists() else dict(configuration=identity,results={},events=[])
    if report['configuration']!=identity:
        parser.error('Configuration changed; use a new output directory')
    report['status']='running';save(report_file,report)
    from agent_framework import runner
    groq_clock=[None]
    for job in plan:
        name='{phase}-{suite}-{attack}-k{k}'.format(**job)
        if report['results'].get(name,{}).get('status')=='completed':
            continue
        selected=dict(splits[job['suite']])
        if args.user_tasks:selected['user_tasks']=args.user_tasks
        if args.injection_tasks:selected['injection_tasks']=args.injection_tasks
        exposure=Path('p2_anomaly/task_exposure.json');exposed=json.loads(exposure.read_text())
        exposed.setdefault('optimization_dev_tasks',{})[job['suite']]=selected;save(exposure,exposed)
        output=args.outdir/name
        runtime=SimpleNamespace(provider='compatible' if args.provider=='ollama' else args.provider,llm=MODEL,reviewer='llm',reviewer_model=MODEL,
            policy='anomaly' if job['phase']=='candidate' else 'full_approve',benchmark_version='v1.2',
            suite=job['suite'],attack=job['attack'],user_tasks=selected['user_tasks'],
            injection_tasks=selected['injection_tasks'] if job['attack']!='none' else None,
            split_file=f"splits/{job['suite']}_v1.2.json",split='dev',outdir=str(output),force=False)
        print('Starting '+name,flush=True)
        for attempt in range(4):
            with error_status(args.provider=="groq",groq_clock) as status:
                try:
                    with local_factories(args.provider=='ollama',args.outdir,local_runtime),protocol_fallback(args.outdir,args.max_groq_fallbacks,args.groq_fallback),reviewer_json_variant(args.reviewer_json),banking_review_variant(args.banking_review_guidance),hosted_factories('compatible' if args.provider=='ollama' else args.provider),agent_variant(job['phase']!='baseline'),completion_variant(args.completion_check):
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
                    event=dict(job=job,error_type=type(exc).__name__,http_status=status.get('status') or getattr(exc,'http_status',None),attempt=attempt,
                               reason_code=str(exc)[:100] if isinstance(exc,HostedStop) else type(exc).__name__)
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
