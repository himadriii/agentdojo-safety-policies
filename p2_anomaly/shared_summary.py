"""Adapt shared runner output for P2 diagnostics without editing shared files."""
import json
from pathlib import Path


def load_summary(output, returned, plan, job):
    output = Path(output)
    if returned is None:
        files = list(output.glob(f'*/summary_{plan["suite"]}_{job["attack"]}.json'))
        if len(files) != 1:
            raise ValueError('Shared runner must produce exactly one summary for this job')
        summary = json.loads(files[0].read_text())
        summary['pipeline_name'] = files[0].parent.name
    else:
        summary = returned
    for key, row in summary.get('rows', {}).items():
        uid, _, injection = key.partition('|')
        path = (output / summary['pipeline_name'] / plan['suite'] / uid /
                job['attack'] / f'{injection if job["attack"] != "none" else "none"}.json')
        trace = json.loads(path.read_text()) if path.exists() else {}
        decisions = trace.get('approval_decisions', [])
        row['error'] = trace.get('error') or (None if trace else 'missing_trace')
        row['completed_safely'] = bool(row['utility'] and not row['attack_succeeded'] and not row['error'])
        row.update(proposed_calls=len(decisions),
                   flagged_calls=sum(d['decision'] != 'approve' for d in decisions),
                   policy_latency_s=sum(d.get('policy_latency_s', 0) for d in decisions),
                   reviewer_errors=sum(str(d.get('reviewer_reason') or '').startswith('REVIEWER_ERROR') for d in decisions),
                   reviewer_parse_failures=sum(str(d.get('reviewer_reason') or '').startswith('REVIEWER_PARSE_FAILURE') for d in decisions))
    rows = list(summary.get('rows', {}).values())
    summary['tasks_with_errors'] = sum(r['error'] is not None for r in rows)
    summary['tasks_with_reviewer_errors'] = sum(bool(r['reviewer_errors'] or r['reviewer_parse_failures']) for r in rows)
    summary['benchmark_version'] = plan['benchmark_version']
    # Preserve the official shared summary file unchanged; this is additional P2 data.
    return summary
