"""Normal-only approval gate. Budget enforcement belongs to the shared executor."""
import math
import os
import hashlib
import json
from pathlib import Path

import joblib

from agent_framework.policy import Policy
from agent_framework.policies.anomaly_features import FEATURE_NAMES, SCHEMA_VERSION, extract_features
from agent_framework.policies.anomaly_support import unsupported_reason

DEFAULT_ARTIFACT = Path(__file__).resolve().parents[2] / 'p2_anomaly/artifacts/current/model.joblib'


class AnomalyPolicy(Policy):
    name = 'anomaly'

    def __init__(self, artifact_path=None):
        self.artifact = None
        self.load_error = None
        self.artifact_hash = None
        try:
            path = Path(artifact_path or os.environ.get('P2_ANOMALY_MODEL', DEFAULT_ARTIFACT))
            self.artifact_hash = hashlib.sha256(path.read_bytes()).hexdigest()
            manifest_path = path.parent / 'manifest.json'
            if manifest_path.exists():
                manifest = json.loads(manifest_path.read_text())
                if manifest.get('revoked'):
                    raise ValueError('artifact revoked after data audit')
                if manifest['model_sha256'] != self.artifact_hash:
                    raise ValueError('model checksum mismatch')
            # Only load project-produced/trusted joblib files (pickle format).
            artifact = joblib.load(path)
            if artifact['schema_version'] != SCHEMA_VERSION or tuple(artifact['features']) != FEATURE_NAMES:
                raise ValueError('feature schema mismatch')
            if not math.isfinite(artifact['threshold']):
                raise ValueError('invalid threshold')
            self.artifact = artifact
        except Exception as exc:
            self.artifact_hash = None
            self.load_error = type(exc).__name__

    def evaluate(self, context, state):
        if self.artifact is None:
            return 'escalate', state, {'reason': 'anomaly model unavailable', 'scores': {'fallback': 1.0}}
        if context['proposed_call'].function not in self.artifact['tool_table']:
            return 'escalate', state, {'reason': 'anomaly coverage: unknown_tool',
                                      'scores': {'fallback': 1.0}}
        try:
            vector = extract_features(context, self.artifact['tool_table'])
            support_error = unsupported_reason(self.artifact, context['proposed_call'].function, vector)
            if support_error:
                return 'escalate', state, {'reason': f'anomaly coverage: {support_error}',
                                          'scores': {'fallback': 1.0}}
            score = float(-self.artifact['model'].score_samples([vector])[0])
            if not math.isfinite(score):
                raise ValueError('invalid score')
            threshold = self.artifact['threshold']
            if context['proposed_call'].function in self.artifact.get('review_required_tools', ()):
                return 'escalate', state, {
                    'reason': 'sensitive action requires review',
                    'scores': {'anomaly': score, 'threshold': threshold, 'fallback': 0.0}}
            decision = 'escalate' if score >= threshold else 'approve'
            return decision, state, {
                'reason': 'call outside normal calibration range' if decision == 'escalate' else 'call within normal calibration range',
                'scores': {'anomaly': score, 'threshold': threshold, 'fallback': 0.0},
            }
        except Exception:
            return 'escalate', state, {'reason': 'anomaly features or scoring unavailable', 'scores': {'fallback': 1.0}}
