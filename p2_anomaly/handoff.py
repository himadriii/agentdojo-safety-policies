"""Portable course-project runs. Preparation and packaging never call an API."""
import argparse
from importlib.metadata import version
import json
from pathlib import Path
import zipfile

from dotenv import load_dotenv

from p2_anomaly.experiments import ROOT, digest, make_plan, run_plan, save, summarize, validate_plan
from p2_anomaly.reproduce import reproduce
from p2_anomaly.splits import CALIBRATE

DEFAULT_CANDIDATE = ROOT / 'p2_anomaly/artifacts/development/family-v3-category'


def prepare(directory, candidate=DEFAULT_CANDIDATE):
    directory, candidate = Path(directory).resolve(), Path(candidate).resolve()
    if directory.exists():
        raise ValueError('Choose a new output directory; existing experiments must not be overwritten')
    lock = ROOT / 'p2_anomaly/artifacts/development/environment-lock.txt'
    expected = dict(line.split('==', 1) for line in lock.read_text().splitlines() if '==' in line)
    for package in ('agentdojo', 'pydantic', 'openai', 'scikit-learn', 'numpy', 'joblib', 'scipy'):
        if version(package) != expected[package]:
            raise ValueError(f'{package} version mismatch; install the P2 environment-lock.txt')
    verified = reproduce(candidate)
    development = make_plan('development')
    development['jobs'] = [j for j in development['jobs'] if j['k'] == 2]
    order = {'anomaly': 0, 'full_approve': 1, 'full_escalate': 2}
    development['jobs'].sort(key=lambda j: (j['user_task'], j['attack'], order[j['policy']]))
    development['note'] = ('Development evidence only, not held-out results. Gate-first matched '
                           'triplets with real reviewer and k=2; do not tune on final tasks.')
    collection = make_plan('collect', repeats=1)
    collection['jobs'] = [j for j in collection['jobs']
                          if j['user_task'] in {f'user_task_{i}' for i in CALIBRATE}]
    for name, plan in [('development', development), ('calibration', collection)]:
        validate_plan(plan)
        save(directory / name / 'plan.json', plan)
    # Store a repository-relative artifact location so the setup can be moved between machines.
    relative = candidate.relative_to(ROOT)
    save(directory / 'setup.json', {'candidate': relative.as_posix(),
         'candidate_sha256': digest(candidate / 'model.joblib'), 'offline_verification': verified,
         'phases': {'development': len(development['jobs']), 'calibration': len(collection['jobs'])}})
    return {'directory': str(directory), 'development_episodes': 12, 'calibration_episodes': 8,
            'api_calls': 0, 'next': 'Run development first; stop on quota, return the bundle.'}


def run(directory, phase, max_jobs, resume_after_quota=False):
    directory = Path(directory).resolve()
    if not resume_after_quota:
        for name in ('development', 'calibration'):
            ledger = directory / name / 'ledger.json'
            if ledger.exists() and any(r.get('error_type') == 'RateLimitError'
                                      for r in json.loads(ledger.read_text()).values()):
                raise ValueError('A handoff phase hit quota; stop all live phases until reset, then resume explicitly')
    setup = json.loads((directory / 'setup.json').read_text())
    candidate = ROOT / setup['candidate']
    if digest(candidate / 'model.joblib') != setup['candidate_sha256']:
        raise ValueError('candidate changed since preparation; use a fresh output directory')
    reproduce(candidate)
    return run_plan(directory / phase / 'plan.json', max_jobs,
                    candidate / 'model.joblib' if phase == 'development' else None,
                    resume_after_quota)


def bundle(directory, output):
    directory, output = Path(directory).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('Choose a new bundle filename')
    for phase in ('development', 'calibration'):
        plan = directory / phase / 'plan.json'
        if plan.exists():
            save(plan.parent / 'comparison.json', summarize(plan))
    # Explicit allowlist: never sweep the repository, .env, credentials or unrelated files.
    files = [directory / 'setup.json']
    for phase in ('development', 'calibration'):
        base = directory / phase
        for name in ('plan.json', 'ledger.json', 'execution.json', 'comparison.json', 'audit.json'):
            if (base / name).is_file():
                files.append(base / name)
        files.extend((base / 'runs').rglob('*.json'))
        files.extend(p for p in (base / 'source_snapshot').rglob('*') if p.is_file())
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in files:
            archive.write(path, path.relative_to(directory))
    return {'bundle': str(output), 'files': len(files),
            'note': 'Contains benchmark traces and results, not .env. Share within the project team.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    prepare_parser = sub.add_parser('prepare')
    prepare_parser.add_argument('--out', type=Path, required=True)
    prepare_parser.add_argument('--candidate', type=Path, default=DEFAULT_CANDIDATE)
    run_parser = sub.add_parser('run')
    run_parser.add_argument('--directory', type=Path, required=True)
    run_parser.add_argument('--phase', choices=['development', 'calibration'], default='development')
    run_parser.add_argument('--max-jobs', type=int, default=1)
    run_parser.add_argument('--resume-after-quota', action='store_true')
    bundle_parser = sub.add_parser('bundle')
    bundle_parser.add_argument('--directory', type=Path, required=True)
    bundle_parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'prepare':
        result = prepare(args.out, args.candidate)
    elif args.command == 'run':
        load_dotenv(ROOT / '.env')
        result = run(args.directory, args.phase, args.max_jobs, args.resume_after_quota)
    else:
        result = bundle(args.directory, args.out)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
