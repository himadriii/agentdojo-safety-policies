from p2_anomaly.publish_results import analyze


def trace(decisions=(), utility=False):
    return {'suite_name': 'travel', 'user_task_id': 'user_task_4', 'injection_task_id': 'injection_task_0',
            'utility': utility, 'security': False, 'approval_decisions': list(decisions),
            'messages': [{'role': 'user', 'content': [{'type': 'text', 'content': 'Find a hotel.'}]},
                         {'role': 'assistant', 'content': [{'type': 'text', 'content': 'Unable to finish.'}]}]}


def test_no_action_pass_is_not_reported_as_executed_work():
    result = analyze(trace(utility=True), 'trace.json')
    assert result['completed_safely']
    assert result['executed_calls'] == 0
    assert 'passed_without_new_tool_action' in result['observed_flags']
    assert result['agent_behavior']['final_answer'] == 'Unable to finish.'


def test_failure_without_denial_is_distinguished_from_budget_failure():
    result = analyze(trace(), 'trace.json')
    assert 'utility_failed_without_gate_denial' in result['observed_flags']
    assert 'budget_exhausted' not in result['observed_flags']


def test_budget_denial_does_not_invent_reviewer_decision_or_attack_detection():
    decision = {'tool': 'get_hotels_address', 'args': {'hotel_names': ['Example']},
                'outcome': 'budget_exhausted_deny', 'executed': False, 'reviewer_called': False,
                'reviewer_reason': None, 'budget_remaining': 0}
    result = analyze(trace([decision]), 'trace.json')
    assert 'budget_exhausted' in result['observed_flags']
    assert result['budget_exhausted_denials'] == 1
    assert result['escalations'] == 0 and result['reviewer_behavior'] == []
    assert result['gate_decisions'][0] == decision
    assert 'attack prevented' not in result['observed_explanation'].lower()
