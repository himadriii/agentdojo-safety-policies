"""P3: supervised risk-model approval policy.

A classifier trained offline on labeled tool calls scores each proposed call from the
visible context only. Two calibrated thresholds map the score to a decision:
    risk <  escalate_at            -> approve
    escalate_at <= risk < deny_at  -> escalate
    risk >= deny_at                -> deny
Training, thresholds and limitations: docs/policies/p3_supervised_risk.md.
"""
import json
import logging
from pathlib import Path

import joblib

from agent_framework.policy import Policy
from agent_framework.policies.risk_features import FEATURE_NAMES, explain, extract_features

log = logging.getLogger(__name__)

ARTIFACT_DIR = Path(__file__).resolve().parents[2] / "p3_risk" / "artifacts"


class SupervisedRiskPolicy(Policy):
    name = "supervised_risk"

    def __init__(self, artifact_dir=None, escalate_at=None, deny_at=None):
        d = Path(artifact_dir) if artifact_dir else ARTIFACT_DIR
        model_path, thr_path = d / "risk_model.joblib", d / "thresholds.json"
        if not model_path.exists():
            raise FileNotFoundError(
                f"{model_path} not found. Train it with: python -m p3_risk.train")
        self.model = joblib.load(model_path)
        if list(self.model.feature_names) != list(FEATURE_NAMES):
            raise ValueError("Model was trained with a different feature set; retrain with p3_risk.train.")
        thr = json.loads(thr_path.read_text())
        self.escalate_at = thr["escalate_at"] if escalate_at is None else escalate_at
        self.deny_at = thr["deny_at"] if deny_at is None else deny_at

    def decide(self, risk):
        if risk >= self.deny_at:
            return "deny"
        if risk >= self.escalate_at:
            return "escalate"
        return "approve"

    def evaluate(self, context, state):
        try:
            feats = extract_features(context)
            risk = float(self.model.predict_risk([[feats[n] for n in FEATURE_NAMES]])[0])
        except Exception as e:  # never crash the task run
            log.warning("[supervised_risk] scoring failed: %r", e)
            return "escalate", state, {"reason": f"risk scoring failed ({type(e).__name__})"}
        decision = self.decide(risk)
        notes = explain(feats)
        reason = f"risk score {risk:.2f}" + (f"; {notes}" if notes else "")
        return decision, state, {"reason": reason, "scores": {"risk": risk}}
