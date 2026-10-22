"""Freeze a completed local DEV configuration; evaluate held-out only after team agreement."""
import argparse
from datetime import datetime,timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace

from p2_anomaly.experiments import digest,save
from p2_anomaly.hosted20 import MODEL,HostedStop,hosted_factories,metrics
from p2_anomaly.local20 import runtime_identity,local_factories
from p2_anomaly.recovery import agent_variant
from p2_anomaly.review_protocol import reviewer_json_variant
from p2_anomaly.banking_review import banking_review_variant
from p2_anomaly.shared_summary import load_summary

ROOT=Path(__file__).resolve().parents[1]
SUITES=('banking','slack','travel')
BUDGETS=(0,1,2,3,5)


def dataset_groups(data):
    def groups(part):
        return {r.get('group_id',f"{r.get('suite','workspace')}:{r['user_task']}") for r in data[part]}
    fit,cal=groups('fit'),groups('calibration')
    if fit & cal:raise ValueError('Fitting and calibration task families overlap')
    if not data['calibration'] or any(r.get('source')!='audited_real' for r in data['calibration']):
        raise ValueError('Independent audited live calibration is required')
    return {'fitting_calls':len(data['fit']),'calibration_calls':len(data['calibration']),
            'fitting_families':len(fit),'calibration_families':len(cal)}


def validate_dev(report):
    if report.get('status')!='completed DEV diagnostics; not held-out':raise ValueError('Complete DEV evaluation first')
    config=report['configuration']
    if config.get('provider')!='ollama' or not config.get('temperature_enforced'):
        raise ValueError('Requires the explicit-temperature local configuration')
    if config['agent']!=MODEL or config['reviewer']!=MODEL:raise ValueError('Both models must be 20B')
    if not config['reviewer_protocol']['enabled'] or not config['banking_review']['enabled']:
        raise ValueError('Expected validated reviewer configuration')
    if config['completion_check']['enabled']:raise ValueError('Rejected completion-check profile cannot be frozen here')
    expected={(p,a,s,2) for p,a in [('candidate','none'),('candidate','important_instructions'),
                                 ('recovery_baseline','none')] for s in SUITES}
    actual={(j['phase'],j['attack'],j['suite'],j['k']) for j in config['jobs']}
    if actual!=expected:raise ValueError('Full candidate and matched clean baseline are required')
    for j in config['jobs']:
        key='{phase}-{suite}-{attack}-k{k}'.format(**j);r=report['results'].get(key,{})
        if r.get('status')!='completed':raise ValueError('DEV job remains incomplete')
        split=json.loads((ROOT/f"splits/{j['suite']}_v1.2.json").read_text())['dev']
        n=len(split['user_tasks'])*(len(split['injection_tasks']) if j['attack']!='none' else 1)
        if r['n']!=n:raise ValueError('DEV task selection is incomplete')
    for suite,expected_hash in config['split_sha256'].items():
        if digest(ROOT/f'splits/{suite}_v1.2.json')!=expected_hash:
            raise ValueError('Published task split changed since DEV')
    for name,expected_hash in config['source_sha256'].items():
        if digest(ROOT/name)!=expected_hash:raise ValueError(f'DEV source changed: {name}')
    return config


def freeze(dev_report,artifact,outdir,tag,team_confirmed):
    if not team_confirmed:raise ValueError('Obtain team agreement on this exact configuration before freezing')
    subprocess.run(['git','check-ref-format','refs/tags/'+tag],cwd=ROOT,check=True,capture_output=True)
    config=validate_dev(json.loads(Path(dev_report).read_text()))
    if runtime_identity()!=config['local_runtime']:raise ValueError('Local model/runtime changed')
    artifact=Path(artifact)
    if digest(artifact/'model.joblib')!=config['artifact_sha256']:raise ValueError('Model differs from evaluated artifact')
    manifest=json.loads((artifact/'manifest.json').read_text())
    if manifest.get('revoked'):raise ValueError('Revoked artifact')
    if digest(artifact/'model.joblib')!=manifest['model_sha256']:raise ValueError('Model checksum mismatch')
    text=(artifact/'reference_features.json').read_text()
    if hashlib.sha256(text.removesuffix('\n').encode()).hexdigest()!=manifest['data_sha256']:
        raise ValueError('Training/calibration provenance checksum mismatch')
    counts=dataset_groups(json.loads(text))
    exposure=json.loads((ROOT/'p2_anomaly/task_exposure.json').read_text())
    if exposure.get('local20_heldout_run'):raise ValueError('Held-out exposure already started; resume its existing freeze')
    outdir=Path(outdir);outdir.mkdir(parents=True,exist_ok=False)
    files={}
    for name in ('model.joblib','manifest.json','reference_features.json'):
        shutil.copyfile(artifact/name,outdir/name);files[name]=digest(outdir/name)
    source=dict(config['source_sha256'])
    source.update({f'splits/{suite}_v1.2.json':h for suite,h in config['split_sha256'].items()})
    for name in ('p2_anomaly/final20.py','requirements-lock.txt'):
        source[name]=digest(ROOT/name)
    helper=Path(importlib.import_module('agentdojo.agent_pipeline.llms.openai_llm').__file__)
    record={'created_utc':datetime.now(timezone.utc).isoformat(),'status':'frozen local course configuration; held-out not yet run','team_profile_confirmed':True,
        'tag':tag,'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'dev_report_sha256':digest(dev_report),'configuration':config,'files':files,'source':source,
        'agentdojo_helper_sha256':digest(helper),'dataset':counts}
    save(outdir/'freeze.json',record)
    return record


def verify_frozen(path):
    path=Path(path).resolve();record=json.loads(path.read_text())
    if not record.get('team_profile_confirmed'):raise ValueError('Team profile confirmation missing')
    for name,expected in record['files'].items():
        if digest(path.parent/name)!=expected:raise ValueError(f'Frozen artifact changed: {name}')
    for name,expected in record['source'].items():
        if digest(ROOT/name)!=expected:raise ValueError(f'Frozen source changed: {name}')
        tagged=subprocess.check_output(['git','show','refs/tags/'+record['tag']+':'+name],cwd=ROOT)
        if hashlib.sha256(tagged).hexdigest()!=expected:raise ValueError('Freeze tag source differs')
    tagged=subprocess.check_output(['git','show','refs/tags/'+record['tag']+':'+str(path.relative_to(ROOT))],cwd=ROOT)
    if tagged!=path.read_bytes():raise ValueError('Commit freeze.json before creating the freeze tag')
    helper=Path(importlib.import_module('agentdojo.agent_pipeline.llms.openai_llm').__file__)
    if digest(helper)!=record['agentdojo_helper_sha256']:raise ValueError('AgentDojo dependency changed')
    if runtime_identity()!=record['configuration']['local_runtime']:raise ValueError('Local runtime changed')
    return record


def run(frozen,outdir,budgets):
    if os.getenv('FINAL_RUN')!='1':raise ValueError('Held-out evaluation requires FINAL_RUN=1')
    record=verify_frozen(frozen)  # No held-out task selection is read before this guard.
    budgets=list(budgets)
    if not budgets or len(set(budgets))!=len(budgets) or any(k not in BUDGETS for k in budgets):
        raise ValueError('Choose distinct review budgets from 0,1,2,3,5')
    splits={s:json.loads((ROOT/f'splits/{s}_v1.2.json').read_text())['heldout'] for s in SUITES}
    plan=[{'suite':s,'attack':a,'k':k} for k in budgets for a in ('none','important_instructions') for s in SUITES]
    outdir=Path(outdir);outdir.mkdir(parents=True,exist_ok=True)
    identity={'freeze_sha256':digest(frozen),'budgets':budgets,'jobs':plan,
              'splits':{s:digest(ROOT/f'splits/{s}_v1.2.json') for s in SUITES}}
    path=outdir/'final-evaluation.json'
    report=json.loads(path.read_text()) if path.exists() else {'configuration':identity,'results':{},'events':[]}
    if report['configuration']!=identity:raise ValueError('Final configuration changed; do not overwrite results')
    report['status']='running frozen held-out evaluation';save(path,report)
    exposure=ROOT/'p2_anomaly/task_exposure.json';data=json.loads(exposure.read_text())
    previous=data.get('local20_heldout_run')
    if previous and previous['freeze_sha256']!=identity['freeze_sha256']:raise ValueError('Held-out already exposed under another freeze')
    data['local20_heldout_run']={'freeze_sha256':identity['freeze_sha256'],'tag':record['tag'],
        'source':str(path),'suite_task_ids':splits,'note':'Held-out exposure; never use these tasks for further tuning'}
    save(exposure,data)
    os.environ.update(REVIEWER_PROVIDER='compatible',REVIEWER_MODEL=MODEL,
        P2_ANOMALY_MODEL=str(Path(frozen).resolve().parent/'model.joblib'))
    from agent_framework import runner
    for job in plan:
        key='{suite}-{attack}-k{k}'.format(**job)
        if report['results'].get(key,{}).get('status')=='completed':continue
        selected=splits[job['suite']];output=outdir/key
        args=SimpleNamespace(provider='compatible',llm=MODEL,reviewer='llm',reviewer_model=MODEL,
            policy='anomaly',benchmark_version='v1.2',suite=job['suite'],attack=job['attack'],
            user_tasks=selected['user_tasks'],injection_tasks=selected['injection_tasks'] if job['attack']!='none' else None,
            split_file=str(ROOT/f"splits/{job['suite']}_v1.2.json"),split='heldout',outdir=str(output),force=False)
        print('Starting frozen '+key,flush=True)
        try:
            with local_factories(True,outdir,record['configuration']['local_runtime']),reviewer_json_variant(True),banking_review_variant(True),hosted_factories('compatible'),agent_variant(True):
                result=runner.run_one(args,job['k'])
            summary=load_summary(output,result,{'suite':job['suite'],'benchmark_version':'v1.2'},job)
            expected=len(selected['user_tasks'])*(len(selected['injection_tasks']) if job['attack']!='none' else 1)
            measured=metrics(summary,expected)
            if subprocess.run([sys.executable,str(ROOT/'scripts/verify_traces.py'),str(output)]).returncode:
                raise HostedStop('Trace verification failed')
            report['results'][key]=dict(job,status='completed',**measured);save(path,report)
        except (Exception,KeyboardInterrupt) as exc:
            event={'job':job,'error_type':type(exc).__name__,'http_status':getattr(exc,'http_status',None),
                   'reason':str(exc)[:100] if isinstance(exc,HostedStop) else type(exc).__name__}
            report['events'].append(event);report['status']='stopped; retain and resume completed final results'
            save(path,report);return 2
    report['status']='completed frozen held-out evaluation';save(path,report);return 0


def main():
    parser=argparse.ArgumentParser(__doc__);commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('freeze');p.add_argument('--dev-report',type=Path,required=True)
    p.add_argument('--artifact',type=Path,required=True);p.add_argument('--outdir',type=Path,required=True)
    p.add_argument('--tag',required=True);p.add_argument('--team-profile-confirmed',action='store_true')
    p=commands.add_parser('run');p.add_argument('--frozen',type=Path,required=True);p.add_argument('--outdir',type=Path,required=True)
    p.add_argument('--budgets',nargs='+',type=int,choices=BUDGETS,default=list(BUDGETS))
    args=parser.parse_args()
    if args.command=='freeze':
        freeze(args.dev_report,args.artifact,args.outdir,args.tag,args.team_profile_confirmed);return 0
    return run(args.frozen,args.outdir,args.budgets)


if __name__=='__main__':raise SystemExit(main())
