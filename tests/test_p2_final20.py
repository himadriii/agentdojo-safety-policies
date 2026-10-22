import copy
import json
import pytest
from p2_anomaly import final20


def test_freeze_requires_team_agreement_before_reading_report(tmp_path):
    with pytest.raises(ValueError,match='team agreement'):
        final20.freeze(tmp_path/'missing',tmp_path/'model',tmp_path/'freeze','tag',False)
    assert not (tmp_path/'freeze').exists()


def test_heldout_requires_final_flag_before_verifying_or_reading_tasks(monkeypatch,tmp_path):
    monkeypatch.delenv('FINAL_RUN',raising=False)
    monkeypatch.setattr(final20,'verify_frozen',lambda p:pytest.fail('must not read freeze or held-out selection'))
    with pytest.raises(ValueError,match='FINAL_RUN'):
        final20.run(tmp_path/'missing',tmp_path/'out',[2])
    assert not (tmp_path/'out').exists()


def test_dataset_groups_rejects_training_calibration_overlap_and_reference_calibration():
    data={'fit':[{'user_task':'taskA','group_id':'suite:familyA'}],
          'calibration':[{'user_task':'taskB','group_id':'suite:familyB','source':'audited_real'}]}
    assert final20.dataset_groups(data)['calibration_families']==1
    overlap=copy.deepcopy(data);overlap['calibration'][0]['group_id']='suite:familyA'
    with pytest.raises(ValueError,match='overlap'):final20.dataset_groups(overlap)
    data['calibration'][0]['source']='reference'
    with pytest.raises(ValueError,match='audited live'):final20.dataset_groups(data)


def test_a_pilot_or_interrupted_run_cannot_be_frozen():
    with pytest.raises(ValueError,match='Complete DEV'):final20.validate_dev({'status':'stopped'})
    config={'provider':'ollama','temperature_enforced':True,'agent':final20.MODEL,'reviewer':final20.MODEL,
        'reviewer_protocol':{'enabled':True},'banking_review':{'enabled':True},'completion_check':{'enabled':False},
        'jobs':[{'phase':'candidate','attack':'none','suite':'banking','k':2}]}
    with pytest.raises(ValueError,match='Full candidate'):
        final20.validate_dev({'status':'completed DEV diagnostics; not held-out','configuration':config})


def test_changed_frozen_model_is_rejected_before_git_or_runtime_queries(tmp_path,monkeypatch):
    path=tmp_path/'freeze.json';(tmp_path/'model.joblib').write_bytes(b'changed')
    path.write_text(json.dumps({'team_profile_confirmed':True,'files':{'model.joblib':'original-checksum'}}))
    monkeypatch.setattr(final20,'runtime_identity',lambda:pytest.fail('must reject model before runtime queries'))
    with pytest.raises(ValueError,match='Frozen artifact changed'):final20.verify_frozen(path)
