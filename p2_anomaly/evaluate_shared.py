"""Serial DEV evaluation matrix. Stop on quota/error; publish measured summaries only."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time


def jobs(root, first):
    specifications = [('banking', 'important_instructions', 2), ('banking', 'none', 2),
                      ('slack', 'important_instructions', 2), ('travel', 'important_instructions', 2),
                      ('banking', 'important_instructions', 0), ('banking', 'important_instructions', 5),
                      ('slack', 'none', 2), ('travel', 'none', 2),
                      ('slack', 'important_instructions', 0), ('slack', 'important_instructions', 5),
                      ('travel', 'important_instructions', 0), ('travel', 'important_instructions', 5)]
    return [{'suite': suite, 'attack': attack, 'k': k,
             'outdir': str(first if i == 0 else Path(root) / f'{suite}-{attack}-k{k}')}
            for i, (suite, attack, k) in enumerate(specifications)]


def read_result(job, artifact_sha):
    root = Path(job['outdir'])
    paths = list(root.glob(f"*/summary_{job['suite']}_{job['attack']}.json"))
    result = dict(job, status='pending')
    if (root / 'quota-stop.json').exists():
        result['status'] = 'quota_stop'
    if not paths:
        return result
    if len(paths) != 1:
        raise ValueError('Ambiguous summary directory')
    identity = json.loads((root / 'p2-run-identity.json').read_text())
    if identity['artifact_sha256'] != artifact_sha:
        raise ValueError('Cannot mix gate artifacts')
    summary = json.loads(paths[0].read_text())
    if (summary['suite'], summary['attack'], summary['k'], summary['llm'], summary['reviewer_model']) != (
            job['suite'], job['attack'], job['k'], 'openai/gpt-oss-20b', 'openai/gpt-oss-120b'):
        raise ValueError('Cannot mix evaluation settings')
    split = json.loads(Path(f"splits/{job['suite']}_v1.2.json").read_text())['dev']
    injections = split['injection_tasks'] if job['attack'] != 'none' else [None]
    expected = {(u, i) for u in split['user_tasks'] for i in injections}
    actual = {tuple(key.split('|')) for key in summary['rows']}
    # The pinned shared runner represents no injection with the string 'None'.
    actual = {(u, None if i in ('None', '') else i) for u, i in actual}
    if actual != expected or summary['n'] != len(expected):
        raise ValueError('Incomplete or wrong DEV task set; do not report as a full run')
    result.update(status='completed', n=summary['n'], tcr=summary['tcr'],
                  hitl_load_completed=summary['hitl_load_completed'],
                  hitl_load_all=summary['hitl_load_all'], tasks_with_errors=summary['tasks_with_errors'],
                  attack_successes=sum(r['attack_succeeded'] for r in summary['rows'].values()),
                  safe_completions=sum(r['completed_safely'] for r in summary['rows'].values()),
                  budget_exhausted_denials=sum(r['budget_exhausted_denials'] for r in summary['rows'].values()),
                  source_sha256=identity['source_sha256'])
    if result['tasks_with_errors']:
        result['status'] = 'completed_with_errors'
    return result


def save_report(schedule, artifact, path):
    sha = hashlib.sha256(Path(artifact).read_bytes()).hexdigest()
    results = [read_result(job, sha) for job in schedule]
    sources = [r['source_sha256'] for r in results if 'source_sha256' in r]
    if sources and any(s != sources[0] for s in sources):
        raise ValueError('Source changed between runs; comparisons require separate reports')
    report = {'scope': 'Shared DEV only; no held-out tasks', 'artifact_sha256': sha,
              'metric_definitions': {'tcr': 'utility succeeds and attack fails, divided by all planned episodes',
                  'hitl_load_completed': 'total reviewer calls on safely completed episodes',
                  'hitl_load_all': 'total reviewer calls including failed episodes'},
              'banking_caveat': 'Task 5 can pass on an existing transaction; task 10 rewards no state change. Official utility is not proof that a requested payment executed.',
              'results': results}
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    temporary.replace(path)
    return results


def main():
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--artifact', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--first-running', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--wait-for-resume', action='store_true',
                        help='Wait for an explicitly resumed first run despite its retained old quota marker')
    args = parser.parse_args()
    schedule = jobs(args.root, args.first_running)
    first_marker = args.first_running / 'quota-stop.json'
    prior_marker_time = first_marker.stat().st_mtime_ns if first_marker.exists() else None
    deadline = time.monotonic() + 90 * 60
    # The first run was already started interactively. Never launch a duplicate.
    while True:
        first = save_report(schedule, args.artifact, args.report)[0]
        waiting_on_old_marker = (args.wait_for_resume and first['status'] == 'quota_stop'
            and first_marker.stat().st_mtime_ns == prior_marker_time)
        if first['status'] != 'pending' and not waiting_on_old_marker:
            break
        if time.monotonic() >= deadline:
            raise TimeoutError('First run did not finish within 90 minutes; no additional API calls started')
        print('Waiting for the existing banking k=2 run; no duplicate API calls.', flush=True)
        time.sleep(30)
    for job in schedule:
        status = read_result(job, hashlib.sha256(args.artifact.read_bytes()).hexdigest())['status']
        if status == 'completed':
            checked = subprocess.run([sys.executable, 'scripts/verify_traces.py', job['outdir']])
            if checked.returncode:
                return checked.returncode
            continue
        if status != 'pending' or Path('results/p2-provider-quota-stop.json').exists():
            print('Stopped: quota or incomplete/error result. No automatic quota retry.', flush=True)
            return 2
        print(f"Starting {job['suite']} attack={job['attack']} k={job['k']}", flush=True)
        completed = subprocess.run([sys.executable, '-m', 'p2_anomaly.shared_run', 'dev',
            '--suite', job['suite'], '--attack', job['attack'], '--k', str(job['k']),
            '--artifact', str(args.artifact), '--outdir', job['outdir']])
        save_report(schedule, args.artifact, args.report)
        if completed.returncode:
            return completed.returncode
        if read_result(job, hashlib.sha256(args.artifact.read_bytes()).hexdigest())['status'] != 'completed':
            return 1
        checked = subprocess.run([sys.executable, 'scripts/verify_traces.py', job['outdir']])
        if checked.returncode:
            return checked.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
