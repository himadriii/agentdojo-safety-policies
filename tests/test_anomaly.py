import copy
import hashlib
import json

import joblib
import pytest
from agentdojo.functions_runtime import FunctionCall
from agentdojo.types import text_content_block_from_string

from agent_framework.policies.anomaly import AnomalyPolicy
from agent_framework.policies.anomaly_features import FEATURE_NAMES, extract_features
from p2_anomaly.train import FIT, CALIBRATE, TEST, fit_artifact
from p2_anomaly.splits import QUARANTINE
from p2_anomaly.traces import extract_audited
from tests.test_executor_contract import build, run, outcomes, EXECUTED


TABLE = {'search_emails': 'read', 'send_email': 'external'}


def context(tool='search_emails', args=None):
    return {'task': 'Search emails about lunch.',
            'proposed_call': FunctionCall(function=tool, args=args or {'query': 'lunch'}),
            'trajectory': [], 'metadata': {}, 'remaining_budget': 2}


@pytest.fixture
def artifact(tmp_path):
    fit = [{'user_task': f'fit_{i}', 'tool': 'search_emails',
            'features': extract_features(context(args={'query': 'lunch' * (i + 1)}), TABLE)}
           for i in range(10)]
    cal = [{'user_task': 'cal', 'tool': 'search_emails',
            'features': extract_features(context(), TABLE)}]
    a, _ = fit_artifact(fit, cal, TABLE)
    path = tmp_path / 'model.joblib'
    joblib.dump(a, path)
    return path


def test_splits_keep_outer_test_untouched():
    assert not set(FIT) & set(CALIBRATE)
    assert not (set(FIT) | set(CALIBRATE)) & set(TEST)
    assert set(FIT + CALIBRATE + TEST + QUARANTINE) == set(range(40))


def test_normal_add_wording_matches_append_action():
    ctx = context('append_to_file', {'file_id':'3','content':'two more activities'})
    ctx['task'] = 'Please add two more activities to the file.'
    vector = extract_features(ctx, {'append_to_file':'write'})
    assert vector[FEATURE_NAMES.index('action_in_task')] == 1


def test_revoked_artifact_cannot_be_used_or_reuse_its_cache_tag(artifact):
    manifest = {'revoked':True, 'model_sha256':hashlib.sha256(artifact.read_bytes()).hexdigest()}
    (artifact.parent / 'manifest.json').write_text(json.dumps(manifest))
    policy = AnomalyPolicy(artifact)
    assert policy.artifact is None and policy.artifact_hash is None
    assert policy.evaluate(context(), {})[0] == 'escalate'


def test_reload_deterministic_and_no_context_mutation(artifact):
    ctx = context()
    before = copy.deepcopy(ctx)
    state = {'sentinel': 1}
    first = AnomalyPolicy(artifact).evaluate(ctx, state)
    assert first == AnomalyPolicy(artifact).evaluate(ctx, state)
    assert ctx == before and first[1] == state


def test_missing_model_and_unsupported_tool_escalate(artifact, tmp_path):
    assert AnomalyPolicy(tmp_path / 'missing').evaluate(context(), {})[0] == 'escalate'
    assert AnomalyPolicy(artifact).evaluate(context('unknown'), {})[0] == 'escalate'
    # Even a classified tool absent from normal fitting must fall back.
    assert AnomalyPolicy(artifact).evaluate(context('send_email'), {})[2]['scores']['fallback'] == 1


def test_invalid_input_does_not_approve(artifact):
    ctx = context()
    ctx['trajectory'] = [{'role': 'tool', 'content': object()}]
    assert AnomalyPolicy(artifact).evaluate(ctx, {})[0] == 'escalate'


def test_no_environment_metadata_or_budget_leakage():
    ctx = context()
    expected = extract_features(ctx, TABLE)
    ctx.update(environment=object(), metadata={'attack': 'anything'}, remaining_budget=0)
    assert extract_features(ctx, TABLE) == expected


def test_visible_tool_results_affect_history_only_when_present():
    ctx = context(args={'query': 'novel'})
    before = extract_features(ctx, TABLE)
    ctx['trajectory'] = [{'role': 'tool', 'content': [text_content_block_from_string('novel')],
                          'tool_call': FunctionCall(function='search_emails', args={}), 'error': None}]
    after = extract_features(ctx, TABLE)
    assert before[FEATURE_NAMES.index('history_overlap')] == 0
    assert after[FEATURE_NAMES.index('history_overlap')] == 1


def test_training_rejects_task_overlap():
    row = {'user_task': 'same', 'tool': 'search_emails', 'features': extract_features(context(), TABLE)}
    with pytest.raises(ValueError, match='leakage'):
        fit_artifact([row], [row], TABLE)


def test_fallback_obeys_executor_budget_and_blocks_calls(tmp_path):
    policy = AnomalyPolicy(tmp_path / 'missing')
    pipeline, executor = build(policy, k=0, queries=('a', 'b'))
    run(pipeline)
    assert not EXECUTED
    assert outcomes(executor) == ['budget_exhausted_deny'] * 2


def test_schema_mismatch_fails_to_review(artifact):
    a = joblib.load(artifact)
    a['features'] = ['wrong']
    joblib.dump(a, artifact)
    assert AnomalyPolicy(artifact).evaluate(context(), {})[0] == 'escalate'


@pytest.mark.parametrize('threshold,expected', [(2.0, 'auto_approve'), (-2.0, 'budget_exhausted_deny')])
def test_loaded_forest_runs_through_shared_executor(artifact, threshold, expected):
    a = joblib.load(artifact)
    a['threshold'] = threshold
    joblib.dump(a, artifact)
    pipeline, executor = build(AnomalyPolicy(artifact), k=0, queries=('lunch',))
    run(pipeline)
    assert outcomes(executor) == [expected]
    assert bool(EXECUTED) == (expected == 'auto_approve')


def test_audited_real_trace_prefix_and_rejection(tmp_path):
    trace = {'suite_name': 'workspace', 'user_task_id': 'user_task_3',
             'attack_type': None, 'injection_task_id': None, 'injections': {},
             'messages': [
                 {'role': 'user', 'content': [text_content_block_from_string('Search emails')]},
                 {'role': 'assistant', 'tool_calls': [context(args={'query': 'novel'})['proposed_call'].model_dump()]},
                 {'role': 'tool', 'content': [text_content_block_from_string('novel')]}]}
    path = tmp_path / 'trace.json'
    audit = tmp_path / 'audit.json'
    def write():
        path.write_text(json.dumps(trace))
        audit.write_text(json.dumps([{'path': 'trace.json',
                                     'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                                     'approved_call_indices': [0]}]))
    write()
    fit, cal = extract_audited(audit, {'user_task_3'}, {'user_task_30'}, TABLE)
    assert len(fit) == 1 and not cal
    assert fit[0]['features'][FEATURE_NAMES.index('history_overlap')] == 0
    trace['user_task_id'] = 'user_task_0'
    write()
    with pytest.raises(ValueError, match='held-out'):
        extract_audited(audit, {'user_task_3'}, {'user_task_30'}, TABLE)
    trace['user_task_id'] = 'user_task_3'
    trace['attack_type'] = 'important_instructions'
    write()
    with pytest.raises(ValueError, match='clean'):
        extract_audited(audit, {'user_task_3'}, {'user_task_30'}, TABLE)
    path.write_text('{}')
    with pytest.raises(ValueError, match='hash'):
        extract_audited(audit, {'user_task_3'}, {'user_task_30'}, TABLE)
