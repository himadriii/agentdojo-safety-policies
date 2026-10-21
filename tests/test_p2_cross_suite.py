import numpy as np
from agentdojo.functions_runtime import FunctionCall
from agent_framework.policies.anomaly import AnomalyPolicy
from p2_anomaly.cross_suite import category, qualified


def test_shared_tool_categories_preserve_workspace_and_cover_banking():
    assert category('send_money') == 'external'
    assert category('get_balance') == 'read'
    assert category('update_password') == 'destructive'
    assert category('update_user_info') == 'write'
    assert category('cancel_calendar_event') == 'destructive'


def test_suite_names_prevent_task_id_collisions():
    rows = [{'user_task': 'user_task_4', 'group_id': 'family'}]
    assert qualified(rows, 'banking')[0]['user_task'] != qualified(rows, 'slack')[0]['user_task']
    assert qualified(rows, 'banking')[0]['group_id'] != qualified(rows, 'slack')[0]['group_id']
    assert rows[0]['user_task'] == 'user_task_4'


def test_sensitive_action_keeps_review_even_when_statistically_normal():
    class Normal:
        def score_samples(self, vectors):
            return np.array([-0.1] * len(vectors))
    policy = AnomalyPolicy('/nonexistent-model')
    policy.artifact = {'tool_table': {'send_money': 'external', 'get_balance': 'read'},
                       'trained_tools': ['send_money', 'get_balance'],
                       'threshold': 0.5, 'model': Normal(), 'review_required_tools': ['send_money']}
    context = {'task': 'Refund the sender', 'trajectory': [],
               'proposed_call': FunctionCall(function='send_money', args={'amount': 10, 'recipient': 'x'})}
    assert policy.evaluate(context, {})[0] == 'escalate'
    context['proposed_call'] = FunctionCall(function='get_balance', args={})
    assert policy.evaluate(context, {})[0] == 'approve'
    context['proposed_call'] = FunctionCall(function='unknown', args={})
    result = policy.evaluate(context, {})
    assert result[0] == 'escalate' and result[2]['reason'] == 'anomaly coverage: unknown_tool'
