"""Matched anomaly/provenance composition study, published DEV cases only."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from urllib.parse import urlparse

import openai
import httpx
from dotenv import dotenv_values

from p2_anomaly.experiments import CODE_PATHS, digest, save
from p2_anomaly.local20 import local_factories, runtime_identity
from p2_anomaly.hosted20 import MODEL, HostedStop, hosted_factories, metrics
from p2_anomaly.recovery import agent_variant
from p2_anomaly.review_protocol import reviewer_json_variant
from p2_anomaly.banking_review import banking_review_variant
from p2_anomaly.shared_summary import load_summary
from p2_anomaly.optimize import error_status

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ('anomaly_provenance', 'anomaly', 'provenance')


@contextmanager
def groq_clients(clock):
    from agent_framework import runner, inference
    from p2_anomaly import hosted20
    originals = runner.make_inference_client, hosted20.make_inference_client
    clients = []
    def factory(provider, **kwargs):
        if provider != 'groq':
            raise ValueError('Matched Groq runs cannot change provider')
        client = inference.make_inference_client('groq', **kwargs)
        clients.append(client)
        return client
    runner.make_inference_client = hosted20.make_inference_client = factory
    try:
        with error_status(groq=True, clock_state=clock):
            yield
    finally:
        runner.make_inference_client, hosted20.make_inference_client = originals
        for client in clients:
            client.close()


@contextmanager
def hosted_clients(base_url):
    """Pin every inference role to one explicit LM Studio host, without retries."""
    from agent_framework import runner
    from agent_framework.inference import _make_compatible
    from p2_anomaly import hosted20
    originals = runner.make_inference_client, hosted20.make_inference_client
    clients = []
    def factory(provider, **kwargs):
        if provider != 'compatible':
            raise ValueError('Matched hosted runs cannot change provider')
        client = openai.OpenAI(base_url=base_url,
            api_key=os.getenv('INFERENCE_API_KEY') or 'local-inference',
            max_retries=0,timeout=300,
            default_headers={'ngrok-skip-browser-warning':'1'})
        client = _make_compatible(client, 'lmstudio', kwargs.get('response_schema'))
        clients.append(client)
        return client
    runner.make_inference_client = hosted20.make_inference_client = factory
    try:
        yield
    finally:
        runner.make_inference_client, hosted20.make_inference_client = originals
        for client in clients:
            client.close()


def hosted_identity(base_url):
    parsed = urlparse(base_url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Supply a credential-free HTTPS endpoint URL')
    with httpx.Client(timeout=20,trust_env=False) as client:
        response = client.get(base_url.rstrip('/')+'/models',headers={
            'Authorization':'Bearer '+(os.getenv('INFERENCE_API_KEY') or 'local-inference'),
            'ngrok-skip-browser-warning':'1'})
        response.raise_for_status()
        models = [m['id'] for m in response.json()['data']]
    if MODEL not in models:
        raise ValueError('The hosted endpoint must provide the agreed 20B model')
    return {'provider':'lmstudio','base_url':base_url.rstrip('/'),'model':MODEL,
            'server_model_digest':'not exposed by endpoint','api_retries':0,
            'agent_max_tokens':4096,'policy_max_tokens':2048,'reviewer_max_tokens':2048,
            'effective_reasoning_effort':'server configured; compatible transport omits flag',
            'no_cloud_fallback':True}


class EvaluationStop(BaseException):
    """Do not let policy/executor error fallbacks score API outages as decisions."""


@contextmanager
def policy_clients():
    from agent_framework import runner
    from agent_framework.policies import anomaly_provenance
    from agent_framework.policies.provenance_gate.extractor import PROVENANCE_SCHEMA
    original_runner = runner.make_inference_client
    original_combo = anomaly_provenance.make_inference_client

    def factory(provider, **kwargs):
        client = original_runner(provider, **kwargs)
        if kwargs.get('response_schema') is not None:
            original = client.chat.completions.create
            def create(*args, **options):
                completion_tokens = options.pop('max_completion_tokens', None)
                if completion_tokens is not None:
                    options['max_tokens'] = completion_tokens
                if options.get('response_format') == {'type':'json_object'}:
                    options['response_format'] = {'type':'json_schema', 'json_schema':{
                        'name':'policy_evidence','schema':PROVENANCE_SCHEMA}}
                try:
                    return original(*args, **options)
                except (openai.APIError, HostedStop) as error:
                    raise EvaluationStop(type(error).__name__) from None
            client.chat.completions.create = create
        return client
    runner.make_inference_client = anomaly_provenance.make_inference_client = factory
    try:
        yield
    finally:
        runner.make_inference_client = original_runner
        anomaly_provenance.make_inference_client = original_combo


def main():
    p = argparse.ArgumentParser(__doc__)
    p.add_argument('--artifact', type=Path, required=True)
    p.add_argument('--outdir', type=Path, required=True)
    p.add_argument('--policies', nargs='+', choices=POLICIES, default=list(POLICIES))
    p.add_argument('--suites', nargs='+', choices=('banking','slack','travel'), default=['slack','banking','travel'])
    p.add_argument('--attack', choices=('none','important_instructions'), default='important_instructions')
    p.add_argument('--user-tasks', nargs='+')
    p.add_argument('--provider', choices=('ollama','lmstudio','groq'), default='ollama')
    p.add_argument('--base-url', help='Explicit HTTPS LM Studio /v1 endpoint')
    p.add_argument('--env-file', type=Path, help='Read credentials privately; never copy into results')
    args = p.parse_args()
    if args.env_file:
        private = dotenv_values(args.env_file)
        if private.get('GROQ_API_KEY'):
            os.environ['GROQ_API_KEY'] = private['GROQ_API_KEY']
        key = private.get('LMSTUDIO_API_KEY') or private.get('INFERENCE_API_KEY')
        if key:
            os.environ['INFERENCE_API_KEY'] = key
    if args.provider == 'lmstudio' and not args.base_url:
        p.error('Hosted evaluation needs --base-url')
    if args.provider == 'groq' and not os.getenv('GROQ_API_KEY'):
        p.error('Configure the private GROQ_API_KEY in the selected .env file')
    if args.provider == 'groq':
        os.environ.update(GROQ_MAX_RETRIES='0', GROQ_TIMEOUT='180')
    if args.user_tasks and len(args.suites) != 1:
        p.error('DEV task selection requires one suite')
    splits = {s:json.loads((ROOT/f'splits/{s}_v1.2.json').read_text())['dev'] for s in args.suites}
    if args.user_tasks and not set(args.user_tasks) <= set(splits[args.suites[0]]['user_tasks']):
        p.error('Only published DEV tasks are allowed')
    artifact = args.artifact.resolve()
    provider = 'groq' if args.provider == 'groq' else 'compatible'
    os.environ.update(LLM_PROVIDER=provider, LLM_MODEL=MODEL,
        PROVENANCE_PROVIDER=provider, PROVENANCE_MODEL=MODEL,
        REVIEWER_PROVIDER=provider, REVIEWER_MODEL=MODEL, P2_ANOMALY_MODEL=str(artifact))
    from agent_framework import runner
    from agent_framework.policies.anomaly import AnomalyPolicy
    if AnomalyPolicy(artifact).artifact is None:
        p.error('A valid explicit anomaly artifact is required')
    runtime = (runtime_identity() if args.provider == 'ollama' else
               {'provider':'groq','base_url':'https://api.groq.com/openai/v1','model':MODEL,
                'api_retries':0,'request_interval_seconds':65,'agent_max_tokens':4096,
                'policy_max_tokens':2048,'reviewer_max_tokens':2048,'temperature':0,
                'no_cloud_fallback':True,'quota_policy':'free tier only; stop on quota'}
               if args.provider == 'groq' else hosted_identity(args.base_url))
    sources = set(CODE_PATHS) | {str(x.relative_to(ROOT)) for folder in ('agent_framework','p2_anomaly')
                              for x in (ROOT/folder).rglob('*.py') if 'artifacts' not in x.parts}
    plan = [{'policy':policy,'suite':suite,'attack':args.attack,'k':2}
            for suite in args.suites for policy in args.policies]
    identity = {'scope':'DEV composition study only; no held-out selection',
        'jobs':plan,'splits':splits,'user_tasks':args.user_tasks,'model':MODEL,
        'provider':args.provider,'runtime':runtime,'artifact_sha256':digest(artifact),
        'source_sha256':{s:digest(ROOT/s) for s in sorted(sources)},
        'agent_recovery':True,'reviewer_json':True,'banking_review_guidance':True,
        'provenance_response_schema':'structured schema from merged main',
        'provenance_max_tokens':2048,'review_budget':2}
    outdir = args.outdir.resolve(); outdir.mkdir(parents=True,exist_ok=True)
    report_path = outdir/'evaluation.json'
    report = json.loads(report_path.read_text()) if report_path.exists() else {
        'configuration':identity,'results':{},'events':[]}
    if report['configuration'] != identity:
        p.error('Configuration changed; keep the original run separate')
    report['status'] = 'running matched DEV comparison'; save(report_path,report)
    clock = [None]
    try:
        for job in plan:
            name = '{policy}-{suite}-{attack}-k{k}'.format(**job)
            if report['results'].get(name,{}).get('status') == 'completed':
                continue
            selected = splits[job['suite']]
            users = args.user_tasks or selected['user_tasks']
            output = outdir/name
            run_args = SimpleNamespace(provider=provider,llm=MODEL,reviewer='llm',
                reviewer_model=MODEL,policy=job['policy'],benchmark_version='v1.2',
                suite=job['suite'],attack=job['attack'],user_tasks=users,
                injection_tasks=selected['injection_tasks'] if job['attack']!='none' else None,
                split_file=str(ROOT/f"splits/{job['suite']}_v1.2.json"),split='dev',
                outdir=str(output),force=False,shadow_audit=False)
            print('Starting matched DEV '+name,flush=True)
            backend = (local_factories(True,outdir,runtime) if args.provider == 'ollama'
                       else groq_clients(clock) if args.provider == 'groq' else hosted_clients(args.base_url))
            with backend, policy_clients(), reviewer_json_variant(True,allowed_base_url=args.base_url if args.provider=='lmstudio' else None), banking_review_variant(True), hosted_factories(provider), agent_variant(True):
                result = runner.run_one(run_args,2)
            summary = load_summary(output,result,{'suite':job['suite'],'benchmark_version':'v1.2'},job)
            expected = len(users)*(len(selected['injection_tasks']) if job['attack']!='none' else 1)
            measured = metrics(summary,expected)
            if subprocess.run([sys.executable,str(ROOT/'scripts/verify_traces.py'),str(output)]).returncode:
                raise HostedStop('Trace verification failed')
            report['results'][name] = dict(job,status='completed',**measured)
            save(report_path,report)
    except (Exception,EvaluationStop,KeyboardInterrupt) as error:
        report['status'] = 'stopped; completed DEV results retained'
        report['events'].append({'job':job,'type':type(error).__name__,
            'reason':str(error)[:100] if isinstance(error,(HostedStop,EvaluationStop)) else type(error).__name__})
        save(report_path,report)
        print(report['events'][-1],flush=True)
        return 2
    finally:
        # Release this study's model copy on success, protocol failure or interruption.
        if args.provider == 'ollama':
            subprocess.run(['/opt/homebrew/bin/ollama','stop','gpt-oss:20b'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    report['status'] = 'completed matched DEV comparison'; save(report_path,report)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
