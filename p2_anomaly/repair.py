"""Refit the same legitimate data with explicit, versioned context protections."""
import argparse
import copy
import hashlib
import json
from pathlib import Path

import joblib
from agent_framework.policies.anomaly_context import TRANSFORM, transform_features
from p2_anomaly.train import fit_artifact


def build(source, output):
    source, output = Path(source), Path(output)
    if output.exists():
        raise ValueError('Use a new candidate directory')
    manifest = json.loads((source / 'manifest.json').read_text())
    if hashlib.sha256((source / 'model.joblib').read_bytes()).hexdigest() != manifest['model_sha256']:
        raise ValueError('Source artifact checksum mismatch')
    data = json.loads((source / 'reference_features.json').read_text())
    if hashlib.sha256((source / 'reference_features.json').read_text().rstrip('\n').encode()).hexdigest() != manifest['data_sha256']:
        raise ValueError('Source fitting/calibration data checksum mismatch')
    data = copy.deepcopy(data)
    table = manifest['tool_table']
    for rows in data.values():
        for row in rows:
            row['features'] = transform_features(row['features'], table[row['tool']], TRANSFORM)
    artifact, report = fit_artifact(data['fit'], data['calibration'], table, support_mode='category')
    artifact.update(feature_transform=TRANSFORM, context_guards=True,
                    review_required_tools=sorted(name for name, category in table.items() if category != 'read'))
    report.update(status='DEV repair candidate; live performance untested; not frozen',
                  feature_transform=TRANSFORM, context_guards=True, tool_table=table,
                  review_required_tools=artifact['review_required_tools'],
                  source_model_sha256=manifest['model_sha256'],
                  fitting_note='Same 184 legitimate fitting calls and 36 separate calibration calls. No attacked calls added.',
                  calibration_note='Reported flag rate is for the detector/support checks only; source and mandatory-review rules require live evaluation.',
                  limitations=['Slack/travel fitting remains reference-based with no live calibration.',
                    'URL rules recognize explicitly named Slack sources, not complete semantic authorization.',
                    'Links in the requested channel may themselves be attacker-controlled.',
                    'Removing read-history penalties can miss harmful context-dependent reads; other features and source checks remain.',
                    'Reviewer mistakes on other actions and agent recovery failures remain possible.'],
                  source_sha256={p:hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in [
                    'p2_anomaly/repair.py', 'p2_anomaly/train.py', 'agent_framework/policies/anomaly.py',
                    'agent_framework/policies/anomaly_context.py', 'agent_framework/policies/anomaly_support.py',
                    'agent_framework/policies/anomaly_features.py']})
    output.mkdir(parents=True)
    encoded = json.dumps(data, indent=2, sort_keys=True)
    (output / 'reference_features.json').write_text(encoded + '\n')
    joblib.dump(artifact, output / 'model.joblib')
    report['data_sha256'] = hashlib.sha256(encoded.encode()).hexdigest()
    report['model_sha256'] = hashlib.sha256((output / 'model.joblib').read_bytes()).hexdigest()
    (output / 'manifest.json').write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--outdir', type=Path, required=True)
    args = parser.parse_args()
    report = build(args.source, args.outdir)
    print(json.dumps({k:report[k] for k in ['fit_calls','calibration_calls','threshold','calibration_gate_flag_rate']}))
