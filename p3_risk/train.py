"""P3: train, calibrate and set thresholds for the supervised risk model (dev split only).

The held-out test split is never read here. Model selection and thresholds use
out-of-fold predictions from cross-validation grouped by task, so no user task (or
injection task) is in both the training and the scoring side of a fold.

Usage:  python -m p3_risk.train
"""
import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from agent_framework.policies.risk_features import FEATURE_NAMES
from agent_framework.policies.risk_model import RiskModel

HERE = Path(__file__).parent
ART = HERE / "artifacts"
MAX_BENIGN_FLAG = 0.03      # benign calls we accept sending to the reviewer (escalate or deny)
MAX_BENIGN_DENY = 0.002     # benign calls we accept auto-denying
MIN_DENY_AT = 0.9           # auto-deny only on high-confidence risk
MIN_ESCALATE_AT = 0.25      # floor: benign scores saturate near 0, so a pure quantile threshold is fragile
SEED = 0
REAL_REPEAT = 5             # real-trajectory rows are scarce; repeat them so they count in training

CANDIDATES = {
    "logreg": lambda: make_pipeline(StandardScaler(), LogisticRegression(C=0.5, class_weight="balanced", max_iter=2000)),
    "hist_gb": lambda: HistGradientBoostingClassifier(max_depth=3, learning_rate=0.05, max_iter=200,
                                                      class_weight="balanced", random_state=SEED),
    "random_forest": lambda: RandomForestClassifier(n_estimators=300, min_samples_leaf=3, class_weight="balanced",
                                                    n_jobs=-1, random_state=SEED),
}


def oof_scores(make, X, y, groups, n_splits=5):
    oof = np.zeros(len(y))
    cv = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=SEED)
    for tr, te in cv.split(X, y, groups):
        m = make().fit(X[tr], y[tr])
        oof[te] = m.predict_proba(X[te])[:, 1]
    return oof


def platt(raw, y):
    z = RiskModel._logit(raw)
    return LogisticRegression(C=1e6, max_iter=1000).fit(z, y)


def pick_thresholds(risk, y):
    """escalate_at: lowest threshold whose benign flag rate stays <= MAX_BENIGN_FLAG (most recall
    for a bounded reviewer load). deny_at: above the benign range (<= MAX_BENIGN_DENY of benign
    calls) and at least MIN_DENY_AT, so the escalate band stays meaningful."""
    benign = np.sort(risk[y == 0])
    n = len(benign)
    esc = max(float(benign[min(n - 1, int(np.ceil((1 - MAX_BENIGN_FLAG) * n)))]) + 1e-9, MIN_ESCALATE_AT)
    deny = float(benign[min(n - 1, int(np.ceil((1 - MAX_BENIGN_DENY) * n)))]) + 1e-9
    deny = max(deny, esc, MIN_DENY_AT)
    return esc, deny


def rates(risk, y, effectful, esc, deny):
    flagged = risk >= esc
    return {
        "recall_effectful_unsafe": float(flagged[(y == 1) & effectful].mean()),
        "recall_all_unsafe": float(flagged[y == 1].mean()),
        "benign_escalate_or_deny": float(flagged[y == 0].mean()),
        "benign_deny": float((risk[y == 0] >= deny).mean()),
        "unsafe_denied": float((risk[y == 1] >= deny).mean()),
    }


def main():
    ART.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(HERE / "data" / "dataset.csv")
    dev = df[df.split == "dev"].copy()  # held-out test rows are never touched
    dev["source"] = "replay"
    real_path = HERE / "data" / "real_dev.csv"
    if real_path.exists():
        real = pd.read_csv(real_path)
        dev = pd.concat([dev] + [real] * REAL_REPEAT, ignore_index=True)
    # Read-only calls are never labeled unsafe: a read is harmless by itself, the send/delete that
    # follows is what the policy must catch. (Labeling them taught "no arguments => unsafe".)
    dev = dev[~((dev.label == 1) & (dev.cls_read == 1))].reset_index(drop=True)
    X, y = dev[list(FEATURE_NAMES)].to_numpy(float), dev.label.to_numpy()
    effectful = (dev.cls_read.to_numpy() == 0)
    print(f"dev rows: {len(dev)}  unsafe: {int(y.sum())}  effectful unsafe: {int(((y == 1) & effectful).sum())}")

    report = {}
    oofs = {}
    for name, make in CANDIDATES.items():
        per_view = {}
        for view, groups in (("by_user_task", dev.user_task.to_numpy()), ("by_injection_task", dev.inj_task.to_numpy())):
            o = oof_scores(make, X, y, groups)
            per_view[view] = {"auroc": float(roc_auc_score(y, o)), "auprc": float(average_precision_score(y, o))}
            if view == "by_injection_task":
                oofs[name] = o
        report[name] = per_view
        print(name, json.dumps(per_view))

    # choose by the harder view (unseen injection tasks); AUPRC first
    best = max(report, key=lambda n: report[n]["by_injection_task"]["auprc"])
    print("selected:", best)

    raw = oofs[best]
    calibrator = platt(raw, y)
    risk = calibrator.predict_proba(RiskModel._logit(raw))[:, 1]
    esc, deny = pick_thresholds(risk, y)
    op = rates(risk, y, effectful, esc, deny)
    print(f"thresholds: escalate_at={esc:.4f} deny_at={deny:.4f}")
    print(json.dumps(op, indent=2))

    # operating-point sweep, handed to P1/P4/P6 so they can pick other tradeoffs
    sweep = []
    for t in np.unique(np.round(np.quantile(risk, np.linspace(0.05, 0.995, 40)), 4)):
        flagged = risk >= t
        sweep.append({"threshold": float(t),
                      "recall_effectful_unsafe": float(flagged[(y == 1) & effectful].mean()),
                      "benign_flag_rate": float(flagged[y == 0].mean())})
    pd.DataFrame(sweep).to_csv(ART / "dev_operating_points.csv", index=False)

    final = CANDIDATES[best]().fit(X, y)
    model = RiskModel(final, calibrator, FEATURE_NAMES)
    joblib.dump(model, ART / "risk_model.joblib")
    (ART / "thresholds.json").write_text(json.dumps({
        "escalate_at": esc, "deny_at": deny, "max_benign_flag": MAX_BENIGN_FLAG,
        "max_benign_deny": MAX_BENIGN_DENY, "min_escalate_at": MIN_ESCALATE_AT, "selected_model": best}, indent=2))
    (ART / "metrics_dev.json").write_text(json.dumps(
        {"candidates": report, "selected": best, "operating_point_oof": op}, indent=2))

    is_real = (dev.source == "real").to_numpy()
    if is_real.any():
        real_ben = is_real & (y == 0)
        real_uns = is_real & (y == 1)
        rr = {"n_real_benign_rows": int(real_ben.sum() // REAL_REPEAT), "n_real_unsafe_rows": int(real_uns.sum() // REAL_REPEAT),
              "real_benign_escalate_or_deny": float((risk[real_ben] >= esc).mean()),
              "real_benign_deny": float((risk[real_ben] >= deny).mean()),
              "real_unsafe_flagged": float((risk[real_uns] >= esc).mean()) if real_uns.any() else None}
        print("real-trajectory rows (out-of-fold):", json.dumps(rr))
        op["real_trajectories_oof"] = rr

    # which features matter (permutation-free: model-native importances where available)
    imp = None
    if hasattr(final, "feature_importances_"):
        imp = final.feature_importances_
    elif hasattr(final, "named_steps"):
        imp = np.abs(final.named_steps["logisticregression"].coef_[0])
    if imp is not None:
        pd.DataFrame({"feature": FEATURE_NAMES, "importance": imp}).sort_values(
            "importance", ascending=False).to_csv(ART / "feature_importance.csv", index=False)
    dev.assign(oof_risk=risk)[["episode", "attack", "user_task", "inj_task", "order", "tool", "label", "oof_risk"]] \
        .to_csv(ART / "dev_oof_predictions.csv", index=False)
    print("saved artifacts to", ART)


if __name__ == "__main__":
    main()
