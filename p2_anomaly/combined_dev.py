"""Matched anomaly/provenance composition study, published DEV cases only."""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import openai

from p2_anomaly.experiments import CODE_PATHS, digest, save
from p2_anomaly.local20 import local_factories, runtime_identity
from p2_anomaly.hosted20 import MODEL, HostedStop, hosted_factories, metrics
from p2_anomaly.recovery import agent_variant
from p2_anomaly.review_protocol import reviewer_json_variant
from p2_anomaly.banking_review import banking_review_variant
from p2_anomaly.shared_summary import load_summary

ROOT = Path(__file__).resolve().parents[1]
POLICIES = ('anomaly_provenance', 'anomaly', 'provenance')


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
    args = p.parse_args()
    if args.user_tasks and len(args.suites) != 1:
        p.error('DEV task selection requires one suite')
    splits = {s:json.loads((ROOT/f'splits/{s}_v1.2.json').read_text())['dev'] for s in args.suites}
    if args.user_tasks and not set(args.user_tasks) <= set(splits[args.suites[0]]['user_tasks']):
        p.error('Only published DEV tasks are allowed')
    artifact = args.artifact.resolve()
    os.environ.update(LLM_PROVIDER='compatible', LLM_MODEL=MODEL,
        PROVENANCE_PROVIDER='compatible', PROVENANCE_MODEL=MODEL,
        REVIEWER_PROVIDER='compatible', REVIEWER_MODEL=MODEL, P2_ANOMALY_MODEL=str(artifact))
    from agent_framework import runner
    from agent_framework.policies.anomaly import AnomalyPolicy
    if AnomalyPolicy(artifact).artifact is None:
        p.error('A valid explicit anomaly artifact is required')
    runtime = runtime_identity()
    sources = set(CODE_PATHS) | {str(x.relative_to(ROOT)) for folder in ('agent_framework','p2_anomaly')
                              for x in (ROOT/folder).rglob('*.py') if 'artifacts' not in x.parts}
    plan = [{'policy':policy,'suite':suite,'attack':args.attack,'k':2}
            for suite in args.suites for policy in args.policies]
    identity = {'scope':'DEV composition study only; no held-out selection',
        'jobs':plan,'splits':splits,'user_tasks':args.user_tasks,'model':MODEL,
        'runtime':runtime,'artifact_sha256':digest(artifact),
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
    try:
        for job in plan:
            name = '{policy}-{suite}-{attack}-k{k}'.format(**job)
            if report['results'].get(name,{}).get('status') == 'completed':
                continue
            selected = splits[job['suite']]
            users = args.user_tasks or selected['user_tasks']
            output = outdir/name
            run_args = SimpleNamespace(provider='compatible',llm=MODEL,reviewer='llm',
                reviewer_model=MODEL,policy=job['policy'],benchmark_version='v1.2',
                suite=job['suite'],attack=job['attack'],user_tasks=users,
                injection_tasks=selected['injection_tasks'] if job['attack']!='none' else None,
                split_file=str(ROOT/f"splits/{job['suite']}_v1.2.json"),split='dev',
                outdir=str(output),force=False,shadow_audit=False)
            print('Starting matched DEV '+name,flush=True)
            with local_factories(True,outdir,runtime), policy_clients(), reviewer_json_variant(True), banking_review_variant(True), hosted_factories('compatible'), agent_variant(True):
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
        subprocess.run(['/opt/homebrew/bin/ollama','stop','gpt-oss:20b'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    report['status'] = 'completed matched DEV comparison'; save(report_path,report)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
