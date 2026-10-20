"""Generate clean development references and fit/calibrate the anomaly gate.

Run: python -m p2_anomaly.train
No API calls; final held-out user tasks are never replayed or used for fitting.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import joblib
import numpy as np
from sklearn.ensemble import IsolationForest

from agentdojo.agent_pipeline.ground_truth_pipeline import GroundTruthPipeline
from agentdojo.functions_runtime import FunctionsRuntime
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.types import text_content_block_from_string
from agent_framework.policies.anomaly_features import EFFECTS, FEATURE_NAMES, SCHEMA_VERSION, extract_features
from agent_framework.policies.anomaly_support import SHAPE_FEATURES, unsupported_reason
from p2_anomaly.diagnostics import coverage, clustered_flag_interval
from p2_anomaly.splits import FIT, CALIBRATE, TEST, group_id, audit

ROOT = Path(__file__).resolve().parent
READ_TOOLS = {
    'get_current_day', 'get_current_date', 'get_current_time', 'get_unread_emails',
    'get_sent_emails', 'get_received_emails', 'get_draft_emails', 'search_emails',
    'search_contacts_by_name', 'search_contacts_by_email', 'get_file_by_id',
    'list_files', 'search_files', 'search_files_by_filename', 'get_calendar_events',
    'search_calendar_events', 'get_day_calendar_events', 'get_current_user_email',
}


def collect(suite, ids, tool_table):
    rows, failures = [], []
    for number in ids:
        uid = f'user_task_{number}'
        task = suite.user_tasks[uid]
        try:
            env = suite.load_and_inject_default_environment({})
            if hasattr(task, 'init_environment'):
                env = task.init_environment(env)
            start = [{'role': 'system', 'content': [text_content_block_from_string('You are a helpful assistant.')]},
                     {'role': 'user', 'content': [text_content_block_from_string(task.PROMPT)]}]
            _, _, _, messages, _ = GroundTruthPipeline(task).query(
                task.PROMPT, FunctionsRuntime(suite.tools), env, start)
            task_rows = []
            for i, message in enumerate(messages):
                if message['role'] != 'assistant':
                    continue
                for call in message.get('tool_calls') or []:
                    ctx = {'task': task.PROMPT, 'proposed_call': call, 'trajectory': messages[:i + 1]}
                    task_rows.append({'user_task': uid, 'group_id': group_id(uid), 'tool': call.function,
                                      'features': extract_features(ctx, tool_table)})
            if not task_rows:
                raise ValueError('no reference calls')
            rows.extend(task_rows)
        except Exception as exc:
            failures.append({'user_task': uid, 'error': f'{type(exc).__name__}: {exc}'})
    return rows, failures


def fit_artifact(fit_rows, calibration_rows, tool_table, review_rate=0.1, support_mode='strict'):
    if not fit_rows or not calibration_rows:
        raise ValueError('fit and calibration calls are both required')
    if not 0 < review_rate < 1:
        raise ValueError('review rate must be between zero and one')
    if support_mode not in ('strict', 'category'):
        raise ValueError('unknown support mode')
    for row in fit_rows + calibration_rows:
        vector = row['features']
        if len(vector) != len(FEATURE_NAMES) or not np.isfinite(vector).all():
            raise ValueError('invalid training vector')
        if row['tool'] not in tool_table:
            raise ValueError('unknown training tool')
    fit_tasks = {r['user_task'] for r in fit_rows}
    if fit_tasks & {r['user_task'] for r in calibration_rows}:
        raise ValueError('fit/calibration task leakage')
    if {r.get('group_id', r['user_task']) for r in fit_rows} & {r.get('group_id', r['user_task']) for r in calibration_rows}:
        raise ValueError('fit/calibration family leakage')
    model = IsolationForest(n_estimators=200, random_state=42, n_jobs=1,
                            contamination='auto').fit([r['features'] for r in fit_rows])
    scores = -model.score_samples([r['features'] for r in calibration_rows])
    # Strictly above this observed quantile: ties must not inflate the review rate.
    threshold = float(np.nextafter(np.quantile(scores, 1 - review_rate, method='higher'), np.inf))
    supported = {r['tool'] for r in fit_rows}
    category_support = {}
    for category in sorted(set(tool_table.values())):
        members = [r for r in fit_rows if tool_table[r['tool']] == category]
        category_support[category] = {
            'calls': len(members), 'tasks': len({r.get('group_id',r['user_task']) for r in members}),
            'bounds': {name: [min(r['features'][FEATURE_NAMES.index(name)] for r in members),
                              max(r['features'][FEATURE_NAMES.index(name)] for r in members)]
                       for name in SHAPE_FEATURES} if members else {}}
    artifact = {'model': model, 'threshold': threshold, 'schema_version': SCHEMA_VERSION,
                'features': FEATURE_NAMES,
                'tool_table': dict(sorted(tool_table.items())),
                'trained_tools': sorted(supported), 'support_mode': support_mode,
                'category_support': category_support}
    fallbacks = [bool(unsupported_reason(artifact, r['tool'], r['features'])) for r in calibration_rows]
    flags = [bool(s >= threshold or f) for s, f in zip(scores, fallbacks)]
    report = {'fit_calls': len(fit_rows), 'calibration_calls': len(calibration_rows),
              'fit_tasks': sorted(fit_tasks),
              'calibration_tasks': sorted({r['user_task'] for r in calibration_rows}),
              'target_review_rate': review_rate,
              'calibration_score_flag_rate': float(np.mean(scores >= threshold)),
              'calibration_unsupported_calls': sum(fallbacks),
              'calibration_gate_flag_rate': float(np.mean(flags)),
              'calibration_uncertainty': clustered_flag_interval(calibration_rows, flags),
              'support_mode': support_mode,
              'fit_coverage': coverage(fit_rows, tool_table),
              'calibration_coverage': coverage(calibration_rows, tool_table),
              'category_support': category_support,
              'threshold': threshold, 'supported_tools': sorted(supported)}
    return artifact, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--outdir', type=Path, default=ROOT / 'artifacts')
    parser.add_argument('--review-rate', type=float, default=0.1)
    parser.add_argument('--audit-manifest', type=Path,
                        help='Optional hash-checked, manually audited clean real traces')
    parser.add_argument('--support-mode', choices=['strict', 'category'], default='strict')
    parser.add_argument('--calibration-source', choices=['reference', 'mixed', 'real'])
    args = parser.parse_args()
    suite = get_suite('v1.2', 'workspace')
    split_audit = audit(suite)
    names = set(FunctionsRuntime(suite.tools).functions)
    unknown = names - READ_TOOLS - set(EFFECTS)
    if unknown:
        raise ValueError(f'Classify suite tools explicitly first: {sorted(unknown)}')
    table = {name: EFFECTS.get(name, 'read') for name in names}
    fit_rows, fit_errors = collect(suite, FIT, table)
    cal_rows, cal_errors = collect(suite, CALIBRATE, table)
    calibration_source = args.calibration_source or ('real' if args.audit_manifest else 'reference')
    if calibration_source != 'reference' and not args.audit_manifest:
        raise ValueError('live calibration requires an audit manifest')
    if args.audit_manifest:
        from p2_anomaly.traces import extract_audited
        real_fit, real_cal = extract_audited(
            args.audit_manifest, {f'user_task_{i}' for i in FIT},
            {f'user_task_{i}' for i in CALIBRATE}, table)
        fit_rows += real_fit
        if calibration_source == 'real':
            cal_rows = real_cal
        elif calibration_source == 'mixed':
            cal_rows += real_cal
    artifact, report = fit_artifact(fit_rows, cal_rows, table, args.review_rate, args.support_mode)
    report.update({'status': 'development prototype; no held-out evaluation',
                   'split_audit': split_audit,
                   'fit_audited_real_calls': sum(r.get('source') == 'audited_real' for r in fit_rows),
                   'calibration_audited_real_calls': sum(r.get('source') == 'audited_real' for r in cal_rows),
                   'calibration_source': calibration_source,
                   'calibration_agent_profiles': sorted({r.get('agent_configuration','reference') for r in cal_rows}),
                   'fit_agent_profiles': sorted({r.get('agent_configuration','reference') for r in fit_rows}),
                   'fit_partial_episode_calls': sum(r.get('partial_episode', False) for r in fit_rows),
                   'calibration_partial_episode_calls': sum(r.get('partial_episode', False) for r in cal_rows),
                   'created_utc': datetime.now(timezone.utc).isoformat(),
                   'benchmark': 'v1.2', 'suite': 'workspace',
                   'versions': {p: version(p) for p in ('agentdojo', 'scikit-learn', 'joblib', 'numpy')},
                   'excluded_test_user_tasks': [f'user_task_{i}' for i in TEST],
                   'collection_errors': fit_errors + cal_errors})
    report['schema_version'] = SCHEMA_VERSION
    report['features'] = list(FEATURE_NAMES)
    report['tool_table'] = table
    report['intended_fit_tasks'] = [f'user_task_{i}' for i in FIT]
    report['intended_calibration_tasks'] = [f'user_task_{i}' for i in CALIBRATE]
    repo = ROOT.parent
    report['source_sha256'] = {
        name: hashlib.sha256((repo / name).read_bytes()).hexdigest()
        for name in ('p2_anomaly/train.py', 'p2_anomaly/traces.py',
                     'agent_framework/policies/anomaly.py',
                     'agent_framework/policies/anomaly_features.py',
                     'agent_framework/policies/anomaly_support.py', 'p2_anomaly/diagnostics.py',
                     'p2_anomaly/splits.py')}
    args.outdir.mkdir(parents=True, exist_ok=True)
    if (args.outdir / 'freeze.json').exists():
        raise ValueError('refusing to overwrite frozen artifacts')
    data = json.dumps({'fit': fit_rows, 'calibration': cal_rows}, sort_keys=True, indent=2)
    report['data_sha256'] = hashlib.sha256(data.encode()).hexdigest()
    (args.outdir / 'reference_features.json').write_text(data + '\n')
    joblib.dump(artifact, args.outdir / 'model.joblib')
    report['model_sha256'] = hashlib.sha256((args.outdir / 'model.joblib').read_bytes()).hexdigest()
    (args.outdir / 'manifest.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
