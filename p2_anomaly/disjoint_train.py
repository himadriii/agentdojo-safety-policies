"""Build task-disjoint DEV variants using existing audited workspace rows only."""
import argparse
import hashlib
import json
from pathlib import Path

import joblib
from p2_anomaly.train import fit_artifact
from agent_framework.policies.anomaly_authorization import VERSION

VARIANTS = ('detector_only', 'generic_rules_only', 'detector_generic')


def build(source, destination):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError('Use a fresh destination; never overwrite experiment artifacts')
    manifest = json.loads((source/'manifest.json').read_text())
    for filename, key in [('model.joblib','model_sha256'),('reference_features.json','data_sha256')]:
        value=(source/filename).read_bytes()
        if filename.endswith('.json'):value=value.rstrip(b'\n')
        if hashlib.sha256(value).hexdigest()!=manifest[key]:raise ValueError('Source checksum mismatch')
    data=json.loads((source/'reference_features.json').read_text())
    selected={part:[row for row in data[part] if row['user_task'].startswith('workspace:')]
              for part in ('fit','calibration')}
    scored={f'{suite}:{task}' for suite in ('banking','slack','travel')
            for task in json.loads(Path(f'splits/{suite}_v1.2.json').read_text())['dev']['user_tasks']}
    fit={r['user_task'] for r in selected['fit']};cal={r['user_task'] for r in selected['calibration']}
    assert not fit&cal and not (fit|cal)&scored
    assert not {r['group_id'] for r in selected['fit']}&{r['group_id'] for r in selected['calibration']}
    artifact, report=fit_artifact(selected['fit'],selected['calibration'],manifest['tool_table'],review_rate=0.1,support_mode='category')
    # Source vectors already contain the versioned read-history transform.
    artifact['feature_transform']=manifest['feature_transform']
    encoded=json.dumps(selected,indent=2,sort_keys=True)+'\n'
    destination.mkdir(parents=True)
    (destination/'reference_features.json').write_text(encoded)
    report.update(scope='Task-disjoint cross-suite DEV transfer; tasks previously inspected during development',
        scored_tasks=sorted(scored),fit_score_overlap=[],calibration_score_overlap=[],
        feature_transform=artifact['feature_transform'],tool_table=manifest['tool_table'],
        source_artifact_sha256=manifest['model_sha256'],data_sha256=hashlib.sha256(encoded.rstrip('\n').encode()).hexdigest(),
        limitations=['Workspace-only fit/calibration; weaker cross-suite coverage expected.',
                    'DEV score tasks were previously inspected and used for policy development; not fresh held-out.',
                    'Existing audited normal calls include historical agent profiles; no new calibration on score tasks.',
                    'Generic authorization and URL guards are heuristics, not semantic guarantees.'])
    for variant in VARIANTS:
        current=dict(artifact)
        if variant!='detector_only':
            current.update(authorization_guards=VERSION,context_guards=True,
                review_required_tools=sorted(k for k,v in manifest['tool_table'].items() if v!='read'))
        current['detector_enabled']=variant!='generic_rules_only'
        out=destination/variant;out.mkdir()
        joblib.dump(current,out/'model.joblib')
        m=dict(report,variant=variant,authorization_guards=current.get('authorization_guards'),
            context_guards=current.get('context_guards',False),detector_enabled=current['detector_enabled'],
            review_required_tools=current.get('review_required_tools',[]),
            model_sha256=hashlib.sha256((out/'model.joblib').read_bytes()).hexdigest())
        (out/'manifest.json').write_text(json.dumps(m,indent=2,sort_keys=True)+'\n')
    (destination/'split-audit.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(__doc__);p.add_argument('--source',type=Path,required=True);p.add_argument('--outdir',type=Path,required=True)
    a=p.parse_args();r=build(a.source,a.outdir)
    print(json.dumps({k:r[k] for k in ('fit_calls','calibration_calls','fit_score_overlap','calibration_score_overlap','threshold')},indent=2))
