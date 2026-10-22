"""Offline DEV-only candidate: shared tool metadata, references and audited calls.

Does not run benchmark evaluators, attacks, held-out prompts, or API requests.
"""
import argparse
import hashlib
import json
from pathlib import Path

import joblib
from agentdojo.functions_runtime import FunctionCall, FunctionsRuntime
from agentdojo.task_suite.load_suites import get_suite
from agentdojo.types import get_text_content_as_str
from agent_framework.tool_meta import get_tool_meta
from agent_framework.policies.anomaly_features import EFFECTS, extract_features
from p2_anomaly.train import collect, fit_artifact
from p2_anomaly.splits import leaves

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'p2_anomaly/artifacts/development'


def category(name):
    # Preserve the original workspace representation for existing feature rows.
    if name in EFFECTS:
        return EFFECTS[name]
    meta = get_tool_meta(name)
    if not meta['known']:
        raise ValueError(f'Unclassified tool: {name}')
    if meta['read_only']:
        return 'read'
    if meta['external_side_effect']:
        return 'external'
    return 'destructive' if meta['irreversible'] else 'write'


def qualified(rows, suite):
    return [dict(r, suite=suite, user_task=f"{suite}:{r['user_task']}",
                 group_id=f"{suite}:{r.get('group_id', r['user_task'])}") for r in rows]


def audited_banking(table):
    audit = json.loads((BASE / 'shared-banking-audit.json').read_text())
    fit, calibration = [], []
    partition = json.loads((BASE / 'shared-inner-plan.json').read_text())['suites']['banking']
    for entry in audit['rows']:
        uid = entry['user_task']
        if uid not in partition[entry['partition']]:
            raise ValueError('Audited call violates declared partition')
        matches = list((ROOT / 'results/p2-shared-v01/banking/runs').glob(f'*/*/banking/{uid}/none/none.json'))
        if len(matches) != 1:
            raise ValueError(f'Missing/ambiguous audited trace: {uid}')
        raw = matches[0].read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry['trace_sha256']:
            raise ValueError('Audit trace changed')
        trace = json.loads(raw)
        if (trace['suite_name'] != 'banking' or trace['user_task_id'] != uid
                or trace.get('attack_type') not in (None, 'none')
                or trace.get('injection_task_id') or trace.get('injections') or trace.get('error')):
            raise ValueError('Only clean audited banking traces are accepted')
        task = next(get_text_content_as_str(m['content']) for m in trace['messages'] if m['role'] == 'user')
        wanted = set(entry['approved_call_indices'])
        found, index = set(), 0
        for position, message in enumerate(trace['messages']):
            for raw_call in (message.get('tool_calls') or []) if message['role'] == 'assistant' else []:
                if index in wanted:
                    call = FunctionCall.model_validate(raw_call)
                    row = {'user_task': uid, 'tool': call.function, 'source': 'audited_real',
                           'trace_sha256': entry['trace_sha256'], 'call_index': index,
                           'audit_kind': entry['audit_kind'],
                           'features': extract_features({'task': task, 'proposed_call': call,
                               'trajectory': trace['messages'][:position + 1]}, table)}
                    (fit if entry['partition'] == 'fit' else calibration).append(row)
                    found.add(index)
                index += 1
        if found != wanted:
            raise ValueError('Invalid audited call indices')
    return qualified(fit, 'banking'), qualified(calibration, 'banking')


def build(output):
    output = Path(output)
    if output.exists():
        raise ValueError('Use a new candidate directory; never overwrite an evaluated artifact')
    inner = json.loads((BASE / 'shared-inner-plan.json').read_text())['suites']
    suites = {name: get_suite('v1.2', name) for name in ('workspace', 'banking', 'slack', 'travel')}
    table = {name: category(name) for suite in suites.values()
             for name in FunctionsRuntime(suite.tools).functions}
    old = json.loads((BASE / 'lmstudio-v2-category/reference_features.json').read_text())
    original_table = json.loads((BASE / 'lmstudio-v2-category/manifest.json').read_text())['tool_table']
    if any(table[name] != value for name, value in original_table.items()):
        raise ValueError('Existing workspace features require recomputation')
    fit, calibration = qualified(old['fit'], 'workspace'), qualified(old['calibration'], 'workspace')
    errors, excluded = [], {}
    for name, partition in inner.items():
        split_path = ROOT / f'splits/{name}_v1.2.json'
        if hashlib.sha256(split_path.read_bytes()).hexdigest() != partition['shared_split_sha256']:
            raise ValueError('Shared split changed')
        dev = set(json.loads(split_path.read_text())['dev']['user_tasks'])
        if not set(partition['fit'] + partition['calibration']) <= dev:
            raise ValueError('Task outside shared DEV')
        suite = suites[name]
        cal_leaves = set().union(*(leaves(suite.user_tasks[u]) for u in partition['calibration']))
        allowed = [u for u in partition['fit'] if not leaves(suite.user_tasks[u]) & cal_leaves]
        excluded[name] = sorted(set(partition['fit']) - set(allowed))
        rows, failures = collect(suite, [int(u.split('_')[-1]) for u in allowed], table)
        for row in rows:
            row['source'] = 'reference'
            row['group_id'] = row['user_task']  # workspace numeric family labels do not apply
        fit.extend(qualified(rows, name))
        errors.extend(dict(f, suite=name) for f in failures)
    bank_fit, bank_cal = audited_banking(table)
    # A reference task overlapping calibration was excluded above; apply same rule to live fit calls.
    bank_fit = [r for r in bank_fit if r['user_task'].split(':')[1] not in excluded['banking']]
    fit.extend(bank_fit)
    calibration.extend(bank_cal)
    artifact, report = fit_artifact(fit, calibration, table, support_mode='category')
    # Preserve review for banking state changes and URL fetches that can send data out.
    review_required = sorted({'get_webpage'} | {name for name in table
        if get_tool_meta(name)['category'] == 'banking' and not get_tool_meta(name)['read_only']})
    artifact['review_required_tools'] = review_required
    report['review_required_tools'] = review_required
    # fit_artifact reports the statistical detector; report the extra rule separately.
    from agent_framework.policies.anomaly_support import unsupported_reason
    scores = -artifact['model'].score_samples([r['features'] for r in calibration])
    flags = [bool(s >= artifact['threshold'] or r['tool'] in review_required
                  or unsupported_reason(artifact, r['tool'], r['features']))
             for r, s in zip(calibration, scores)]
    report['calibration_hybrid_flag_rate'] = sum(flags) / len(flags)
    report.update(status='DEV candidate; live performance untested; not frozen',
                  calibration_note='Pooled workspace + banking audited clean calls; no live Slack/travel calibration',
                  collection_errors=errors, excluded_fit_calibration_component_overlap=excluded,
                  inner_partition=inner, tool_table=table,
                  source_sha256={name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                      for name in ['p2_anomaly/cross_suite.py', 'p2_anomaly/train.py',
                                   'agent_framework/tool_meta.py', 'agent_framework/policies/anomaly_features.py',
                                   'agent_framework/policies/anomaly.py', 'agent_framework/policies/anomaly_support.py']})
    data = json.dumps({'fit': fit, 'calibration': calibration}, indent=2, sort_keys=True)
    output.mkdir(parents=True)
    (output / 'reference_features.json').write_text(data + '\n')
    joblib.dump(artifact, output / 'model.joblib')
    report['model_sha256'] = hashlib.sha256((output / 'model.joblib').read_bytes()).hexdigest()
    report['data_sha256'] = hashlib.sha256(data.encode()).hexdigest()
    (output / 'manifest.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--outdir', type=Path, required=True)
    print(json.dumps(build(parser.parse_args().outdir), indent=2))
