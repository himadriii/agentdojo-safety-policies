"""Decision precedence, state isolation and one shared review budget."""
import itertools
import pytest

from agent_framework.policies.anomaly_provenance import AnomalyProvenancePolicy
from tests.test_executor_contract import build, run, Fixed


@pytest.mark.parametrize('anomaly,provenance', list(itertools.product(('approve','deny','escalate'), repeat=2)))
def test_precedence(anomaly, provenance):
    gate = AnomalyProvenancePolicy(Fixed(anomaly), Fixed(provenance))
    decision, _, _ = gate.evaluate({}, {})
    expected = ('deny' if 'deny' in (anomaly, provenance) else
                'approve' if anomaly == provenance == 'approve' else 'escalate')
    assert decision == expected


def test_shared_budget():
    gate = AnomalyProvenancePolicy(Fixed('escalate'), Fixed('escalate'))
    pipeline, executor = build(gate, k=1, queries=('a','b'))
    run(pipeline)
    assert [d['outcome'] for d in executor.decisions] == ['escalate_approved','budget_exhausted_deny']
    assert sum(d['reviewer_called'] for d in executor.decisions) == 1


def test_child_failure_does_not_approve():
    class Broken:
        def evaluate(self, context, state): raise ValueError('failed')
    gate = AnomalyProvenancePolicy(Fixed('approve'), Broken())
    assert gate.evaluate({}, {})[0] == 'escalate'


def test_state_namespaces_and_short_circuit():
    class Counter:
        def evaluate(self, context, state):
            return 'approve', {'count':state.get('count',0)+1}
    original = {'anomaly':{'count':2}, 'provenance':{'count':8}}
    _, updated, _ = AnomalyProvenancePolicy(Counter(), Counter()).evaluate({}, original)
    assert updated == {'anomaly':{'count':3}, 'provenance':{'count':9}}
    assert original == {'anomaly':{'count':2}, 'provenance':{'count':8}}
    class Unreachable:
        def evaluate(self, context, state): raise AssertionError('must not be called')
    _, _, info = AnomalyProvenancePolicy(Fixed('deny'), Unreachable()).evaluate({}, {})
    assert info['evidence']['provenance']['decision'] == 'skipped'
