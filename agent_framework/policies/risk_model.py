"""Picklable wrapper: base classifier + Platt calibration -> calibrated risk probability."""
import numpy as np


class RiskModel:
    def __init__(self, base, calibrator, feature_names):
        self.base = base
        self.calibrator = calibrator
        self.feature_names = list(feature_names)

    @staticmethod
    def _logit(p):
        p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p)).reshape(-1, 1)

    def predict_risk(self, X):
        """Calibrated probability that each row is an unsafe call."""
        raw = self.base.predict_proba(np.asarray(X, dtype=float))[:, 1]
        return self.calibrator.predict_proba(self._logit(raw))[:, 1]
