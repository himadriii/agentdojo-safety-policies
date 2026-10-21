"""Run the team's compatibility/DEV commands with immediate free-quota stop."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

from dotenv import load_dotenv


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('stage', choices=['compat', 'dev'])
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--outdir', type=Path, required=True)
    parser.add_argument('--resume-after-quota', action='store_true')
    options = parser.parse_args()
    load_dotenv()
    from agent_framework.policies.anomaly import AnomalyPolicy
    from agent_framework.runner import run_one
    from p2_anomaly.quota_adapter import QuotaStop, quota_safe_shared_runner

    artifact = options.artifact.resolve()
    policy = AnomalyPolicy(artifact)
    if policy.artifact is None:
        parser.error('Explicit valid model artifact required')
    os.environ.update(P2_ANOMALY_MODEL=str(artifact), REVIEWER_PROVIDER='groq',
                      GROQ_MAX_RETRIES='0', GROQ_TIMEOUT='45',
                      GROQ_REQUEST_INTERVAL_SECONDS='20')
    options.outdir.mkdir(parents=True, exist_ok=True)
    identity = {'stage': options.stage, 'artifact_sha256': hashlib.sha256(artifact.read_bytes()).hexdigest(),
                'agent': 'openai/gpt-oss-20b', 'reviewer': 'openai/gpt-oss-120b',
                'benchmark': 'v1.2', 'attack': 'important_instructions', 'k': 2}
    from p2_anomaly.experiments import CODE_PATHS, digest
    identity['source_sha256'] = {name: digest(name) for name in [*CODE_PATHS, 'p2_anomaly/shared_run.py']}
    if options.stage == 'dev':
        identity['split_sha256'] = {suite: digest(f'splits/{suite}_v1.2.json')
                                   for suite in ('banking', 'slack', 'travel')}
    identity_file = options.outdir / 'p2-run-identity.json'
    if identity_file.exists() and json.loads(identity_file.read_text()) != identity:
        parser.error('Run configuration changed; choose a new output directory')
    identity_file.write_text(json.dumps(identity, indent=2) + '\n')
    marker = options.outdir / 'quota-stop.json'
    if marker.exists() and not options.resume_after_quota:
        parser.error('Quota stop retained; use --resume-after-quota after reset')
    suites = ['workspace'] if options.stage == 'compat' else ['banking', 'slack', 'travel']
    try:
        with quota_safe_shared_runner():
            for suite in suites:
                split_file = None
                users = [f'user_task_{i}' for i in range(3)]
                injections = ['injection_task_0']
                if options.stage == 'dev':
                    split_file = f'splits/{suite}_v1.2.json'
                    split = json.loads(Path(split_file).read_text())['dev']
                    users, injections = split['user_tasks'], split['injection_tasks']
                exposure_path = Path('p2_anomaly/task_exposure.json')
                exposure = json.loads(exposure_path.read_text())
                exposure.setdefault('shared_v01_selected_for_evaluation', {})[suite] = {
                    'user_tasks': users, 'injection_tasks': injections,
                    'note': 'Conservatively reserve every selected task as exposed; completion requires saved trace evidence.'}
                exposure_path.write_text(json.dumps(exposure, indent=2, sort_keys=True) + '\n')
                args = SimpleNamespace(provider='groq', llm='openai/gpt-oss-20b',
                    reviewer='llm', reviewer_model='openai/gpt-oss-120b', policy='anomaly',
                    benchmark_version='v1.2', suite=suite, attack='important_instructions',
                    user_tasks=users, injection_tasks=injections, split_file=split_file,
                    split='dev', outdir=str(options.outdir), force=False)
                run_one(args, 2)
    except QuotaStop:
        marker.write_text(json.dumps({'status': 'quota_stop', 'suite': suite}) + '\n')
        print('Quota reached. Stopped; completed traces remain cached.', flush=True)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
