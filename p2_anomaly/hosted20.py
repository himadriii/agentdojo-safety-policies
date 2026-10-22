"""Primary 20B/20B DEV evaluation on two explicitly configured hosted endpoints.

Preserves the shared reviewer v2 and executor. No Groq fallback or automatic retries.
"""
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
from dotenv import load_dotenv
from agentdojo.agent_pipeline.llms.openai_llm import (
    OpenAILLM, chat_completion_request, _message_to_openai,
    _function_to_openai, _openai_to_assistant_message,
)
from agentdojo.functions_runtime import EmptyEnv
from agentdojo.models import MODEL_NAMES
from agentdojo.logging import Logger
from agentdojo.types import get_text_content_as_str
from agent_framework.inference import make_inference_client
from agent_framework.llm_reviewer import LLMReviewer
from p2_anomaly.experiments import CODE_PATHS, digest, save
from p2_anomaly.shared_summary import load_summary

MODEL = 'openai/gpt-oss-20b'


class HostedStop(RuntimeError):
    """Escape shared provider retry loops and swallowed reviewer failures."""


class HostedAgent(OpenAILLM):
    max_reasoning_continuations = 2

    def query(self, query, runtime, env=EmptyEnv(), messages=(), extra_args=None):
        working = list(messages)
        for continuation in range(self.max_reasoning_continuations + 1):
            payload = []
            for message in working:
                encoded = _message_to_openai(message, self.model)
                if message['role'] == 'assistant':
                    for key in ('reasoning', 'reasoning_content'):
                        if isinstance(message.get(key), str):
                            encoded[key] = message[key]
                payload.append(encoded)
            try:
                response = chat_completion_request.__wrapped__(self.client, self.model,
                    payload, [_function_to_openai(f) for f in runtime.functions.values()],
                    self.reasoning_effort, self.temperature)
            except openai.APIError as exc:
                raise HostedStop(type(exc).__name__) from None
            if not response.choices:
                raise HostedStop('EMPTY_AGENT_CHOICES')
            raw = response.choices[0].message
            parsed = _openai_to_assistant_message(raw)
            reasoning = {key: value for key in ('reasoning', 'reasoning_content')
                         if isinstance(value := (raw.model_extra or {}).get(key), str) and value}
            parsed.update(reasoning)
            if parsed.get('tool_calls') or get_text_content_as_str(parsed.get('content') or []).strip():
                return query, runtime, env, [*working, parsed], extra_args or {}
            if not reasoning or continuation == self.max_reasoning_continuations:
                raise HostedStop('EMPTY_OR_REASONING_ONLY_AGENT_RESPONSE')
            # Continue the model's assistant state, never promote reasoning to a user answer.
            working.append(parsed)
            trace = Logger.get()
            if hasattr(trace, 'set_contextarg'):
                trace.set_contextarg('hosted_reasoning_only_continuations',
                    trace.context.get('hosted_reasoning_only_continuations', 0) + 1)
        raise HostedStop('AGENT_CONTINUATION_LIMIT')


class HostedReviewer(LLMReviewer):
    def review(self, context):
        result = super().review(context)
        if not self.last_reason or str(self.last_reason).startswith(('REVIEWER_ERROR', 'REVIEWER_PARSE_FAILURE')):
            raise HostedStop(self.last_reason or 'REVIEWER_REASON_MISSING')
        return result


@contextmanager
def hosted_factories(provider="lmstudio"):
    from agent_framework import runner
    original_agent, original_reviewer = runner.make_inference_llm, runner.REVIEWERS['llm']
    original_groq = runner.make_groq_llm
    def make_agent(provider, model):
        if provider not in ('lmstudio', 'groq') or model != MODEL:
            raise ValueError('Hosted20 agent configuration changed')
        MODEL_NAMES.setdefault(model, 'AI assistant')
        MODEL_NAMES.setdefault(model.replace('/', '_'), 'AI assistant')
        return HostedAgent(make_inference_client(provider), model)
    runner.make_inference_llm, runner.REVIEWERS['llm'] = make_agent, HostedReviewer
    runner.make_groq_llm = lambda model: make_agent('groq', model)
    try:
        yield
    finally:
        runner.make_inference_llm, runner.REVIEWERS['llm'] = original_agent, original_reviewer
        runner.make_groq_llm = original_groq


def schedule(budgets):
    if not budgets or any(k not in (0, 2, 5) for k in budgets) or len(set(budgets)) != len(budgets):
        raise ValueError('Choose distinct DEV budgets from 0,2,5')
    return [{'suite': suite, 'attack': attack, 'k': k}
        for attack, ks in [('important_instructions', budgets), ('none', [2])]
        for k in ks for suite in ('banking', 'slack', 'travel')]


def metrics(summary, expected):
    rows = list(summary['rows'].values())
    if summary['n'] != expected or len(rows) != expected:
        raise ValueError('Incomplete planned run')
    if summary['tasks_with_errors'] or summary['tasks_with_reviewer_errors']:
        raise HostedStop('Completed summary contains backend/reviewer failures')
    safe = [r for r in rows if r['completed_safely']]
    return {'n': expected, 'safe_completions': len(safe), 'tcr': len(safe) / expected,
            'hitl_load_completed': sum(r['escalations'] for r in safe),
            'hitl_load_all': sum(r['escalations'] for r in rows),
            'attack_successes': sum(r['attack_succeeded'] for r in rows),
            'budget_exhausted_denials': sum(r['budget_exhausted_denials'] for r in rows),
            'agent_episodes_without_proposed_calls': sum(r['proposed_calls'] == 0 for r in rows),
            'token_usage': summary.get('token_usage', {})}


def aggregates(ledger, plan):
    totals = {}
    for attack, k in {(j['attack'], j['k']) for j in plan}:
        wanted = [j for j in plan if j['attack'] == attack and j['k'] == k]
        rows = [ledger.get(f"{j['suite']}-{attack}-k{k}", {}) for j in wanted]
        if not all(r.get('status') == 'completed' for r in rows):
            continue
        n = sum(r['n'] for r in rows)
        totals[f'{attack}@{k}'] = {
            'n': n, 'safe_completions': sum(r['safe_completions'] for r in rows),
            'tcr': sum(r['safe_completions'] for r in rows) / n,
            'hitl_load_completed': sum(r['hitl_load_completed'] for r in rows),
            'hitl_load_all': sum(r['hitl_load_all'] for r in rows)}
    return totals


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--outdir', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--budgets', nargs='+', type=int, default=[2])
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--suites', nargs='+', choices=['banking','slack','travel'],
                        default=['banking','slack','travel'])
    parser.add_argument('--user-tasks', nargs='+', help='Optional DEV-only pilot; requires exactly one suite')
    parser.add_argument('--clean-first', action='store_true')
    args = parser.parse_args()
    load_dotenv(Path(__file__).resolve().parents[1] / '.env', override=True)
    for prefix in ('LMSTUDIO', 'INFERENCE'):
        if not os.getenv(prefix + '_BASE_URL') or not os.getenv(prefix + '_API_KEY'):
            parser.error(f'Configure {prefix} endpoint credentials locally')
        os.environ[prefix + '_MAX_RETRIES'] = '0'
        os.environ[prefix + '_TIMEOUT'] = '180'
        os.environ[prefix + '_MAX_TOKENS'] = '4096'
    os.environ.update(REVIEWER_PROVIDER='compatible', REVIEWER_MODEL=MODEL,
                      P2_ANOMALY_MODEL=str(args.artifact.resolve()))
    from agent_framework.policies.anomaly import AnomalyPolicy
    if AnomalyPolicy(args.artifact).artifact is None:
        parser.error('Valid explicit gate artifact required')
    plan = schedule(args.budgets)
    plan = [j for j in plan if j['suite'] in args.suites]
    if args.user_tasks and len(args.suites) != 1:
        parser.error('A pilot task selection requires exactly one suite')
    if args.user_tasks:
        allowed = json.loads(Path(f'splits/{args.suites[0]}_v1.2.json').read_text())['dev']['user_tasks']
        if not set(args.user_tasks) <= set(allowed) or len(set(args.user_tasks)) != len(args.user_tasks):
            parser.error('Pilot tasks must be distinct published DEV IDs')
    if args.clean_first:
        plan.sort(key=lambda j:j['attack']!='none')
    identity = {'scope': ('DEV regression pilot; not full-suite or final evaluation' if args.user_tasks
                         else 'DEV only; primary hosted 20B/20B evaluation; separate from Groq 20B/120B'),
        'artifact_sha256': digest(args.artifact), 'agent': MODEL, 'reviewer': MODEL,
        'agent_provider': 'lmstudio', 'reviewer_provider': 'compatible', 'reviewer_prompt': 'v2',
        'agent_max_tokens': 4096, 'reviewer_max_tokens': 1024, 'temperature': 0, 'retries': 0,
        'agent_response_mode': 'preserve-reasoning-v1', 'max_reasoning_only_continuations': 2,
        'endpoint_hashes': {p: hashlib.sha256(os.environ[p + '_BASE_URL'].encode()).hexdigest()
                            for p in ('LMSTUDIO', 'INFERENCE')},
        'source_sha256': {p: digest(p) for p in [*CODE_PATHS, 'p2_anomaly/hosted20.py']},
        'split_sha256': {s: digest(f'splits/{s}_v1.2.json') for s in ('banking', 'slack', 'travel')},
        'jobs': plan, 'pilot_user_tasks': args.user_tasks}
    args.outdir.mkdir(parents=True, exist_ok=True)
    identity_file = args.outdir / 'identity.json'
    if identity_file.exists() and json.loads(identity_file.read_text()) != identity:
        parser.error('Source, endpoint, artifact or settings changed; use a new directory')
    save(identity_file, identity)
    stop_file = args.outdir / 'stop.json'
    if stop_file.exists() and not args.resume:
        parser.error('Prior backend failure retained; use --resume after endpoint recovery')
    ledger_file = args.outdir / 'ledger.json'
    ledger = json.loads(ledger_file.read_text()) if ledger_file.exists() else {}
    report = {'configuration': identity, 'status': 'running', 'results': ledger,
              'banking_caveat': 'Task 5 can pass on an existing transaction; task 10 rewards no state change. Official TCR is not proof of executing a requested payment.'}
    save(args.report, report)
    from agent_framework import runner
    with hosted_factories():
        for job in plan:
            name = f"{job['suite']}-{job['attack']}-k{job['k']}"
            if ledger.get(name, {}).get('status') == 'completed':
                continue
            split_file = f"splits/{job['suite']}_v1.2.json"
            split = json.loads(Path(split_file).read_text())['dev']
            if args.user_tasks:
                split = dict(split, user_tasks=args.user_tasks)
            output = args.outdir / name
            runtime = SimpleNamespace(provider='lmstudio', llm=MODEL, reviewer='llm',
                reviewer_model=MODEL, policy='anomaly', benchmark_version='v1.2',
                suite=job['suite'], attack=job['attack'], user_tasks=split['user_tasks'],
                injection_tasks=split['injection_tasks'] if job['attack'] != 'none' else None,
                split_file=split_file, split='dev', outdir=str(output), force=False)
            exposure = Path('p2_anomaly/task_exposure.json')
            exposed = json.loads(exposure.read_text())
            exposed.setdefault('hosted20_selected_dev_tasks', {})[job['suite']] = split
            save(exposure, exposed)
            print(f'Starting {name}', flush=True)
            try:
                returned = runner.run_one(runtime, job['k'])
                summary = load_summary(output, returned, {'suite': job['suite'], 'benchmark_version': 'v1.2'}, job)
                expected = len(split['user_tasks']) * (len(split['injection_tasks']) if job['attack'] != 'none' else 1)
                result = metrics(summary, expected)
                checked = subprocess.run([sys.executable, 'scripts/verify_traces.py', str(output)])
                if checked.returncode:
                    raise HostedStop('Trace verification failed')
                ledger[name] = dict(job, status='completed', **result)
            except (Exception, KeyboardInterrupt) as exc:
                ledger[name] = dict(job, status='stopped', error_type=type(exc).__name__,
                    reason_code=str(exc)[:100] if isinstance(exc, HostedStop) else type(exc).__name__)
                save(stop_file, ledger[name])
                save(ledger_file, ledger)
                report.update(status='stopped; completed results retained', results=ledger)
                save(args.report, report)
                print(f'Stopped {name}: {type(exc).__name__}; no retries or provider fallback.', flush=True)
                return 2
            save(ledger_file, ledger)
            report['aggregate_complete_suites'] = aggregates(ledger, plan)
            save(args.report, report)
    report['status'] = 'completed DEV evaluation; not a held-out final score'
    save(args.report, report)
    stop_file.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
