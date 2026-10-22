"""Conservative composition; the shared executor owns the single review budget."""
import os

from agent_framework.policy import Policy
from agent_framework.policies.anomaly import AnomalyPolicy
from agent_framework.policies.provenance_gate import ProvenancePolicy
from agent_framework.policies.provenance_gate.extractor import PROVENANCE_SCHEMA
from agent_framework.inference import component_settings, make_inference_client
from agent_framework.usage import track_openai_client

VERSION = 'anomaly-provenance-v1'


class AnomalyProvenancePolicy(Policy):
    name = 'anomaly_provenance'

    def __init__(self, anomaly=None, provenance=None):
        self.anomaly = anomaly if anomaly is not None else AnomalyPolicy()
        if provenance is None:
            provider, model = component_settings(
                'PROVENANCE', os.getenv('LLM_PROVIDER', 'groq'),
                os.getenv('LLM_MODEL', 'openai/gpt-oss-20b'))
            provenance = ProvenancePolicy(client_factory=lambda: track_openai_client(
                make_inference_client(provider, response_schema=PROVENANCE_SCHEMA), 'policy'),
                model=model)
        self.provenance = provenance

    @staticmethod
    def _evaluate(policy, context, state):
        try:
            result = policy.evaluate(context, state)
            decision, updated = result[:2]
            info = result[2] if len(result) == 3 else {}
            if decision not in ('approve', 'deny', 'escalate') or not isinstance(updated, dict):
                raise ValueError('invalid child policy result')
            return decision, updated, info
        except Exception as error:
            return 'escalate', state, {'reason': 'child policy failed: '+type(error).__name__}

    def evaluate(self, context, state):
        anomaly, astate, ainfo = self._evaluate(self.anomaly, context, state.get('anomaly', {}))
        evidence = {'combination_version': VERSION,
                    'anomaly': {'decision': anomaly, **ainfo}}
        updated = dict(state, anomaly=astate)
        if anomaly == 'deny':
            evidence['provenance'] = {'decision': 'skipped', 'reason': 'anomaly already denied'}
            return 'deny', updated, {'reason': 'anomaly denied; provenance not called', 'evidence': evidence}
        provenance, pstate, pinfo = self._evaluate(self.provenance, context, state.get('provenance', {}))
        updated['provenance'] = pstate
        evidence['provenance'] = {'decision': provenance, **pinfo}
        decision = ('deny' if provenance == 'deny' else
                    'approve' if anomaly == provenance == 'approve' else 'escalate')
        scores = {f'{child}_{key}': value for child, info in (('anomaly', ainfo), ('provenance', pinfo))
                  for key, value in info.get('scores', {}).items()}
        return decision, updated, {'reason': f'anomaly={anomaly}; provenance={provenance}',
                                  'scores': scores, 'evidence': evidence}
