"""Calibrated confidence for routing (FR-5).

An LLM's self-reported confidence is poorly calibrated, especially on small models. The routing score is a
logistic-regression calibrator over several independent signals, fitted per provider on the calibration
split (`python -m eval.run_eval calibrate --provider <p>`). Until one is fitted, a fixed-weight fallback is used and the record
says so in confidence_signals.confidence_method.
"""

from __future__ import annotations

from pathlib import Path

import joblib
import numpy as np

from vsia.config import DATA_DIR

FEATURES = ["llm_confidence", "clf_prob_of_llm_label", "clf_max_prob", "agree", "retrieval_top_score",
            "schema_retry"]
_FALLBACK_WEIGHTS = {"llm_confidence": 0.25, "clf_prob_of_llm_label": 0.45, "agree": 0.30}
_models: dict[str, object] = {}


def calibrator_path(provider: str) -> Path:
    return DATA_DIR / "models" / f"confidence_calibrator_{provider}.joblib"


def features(signals: dict) -> list[float]:
    return [float(signals.get(f, 0.0) or 0.0) for f in FEATURES]


def fallback_score(signals: dict) -> float:
    s = sum(w * float(signals.get(k, 0.0) or 0.0) for k, w in _FALLBACK_WEIGHTS.items())
    if signals.get("schema_retry"):
        s -= 0.10
    return float(min(max(s, 0.0), 1.0))


def _load(provider: str):
    if provider not in _models and calibrator_path(provider).exists():
        _models[provider] = joblib.load(calibrator_path(provider))
    return _models.get(provider)


def score(signals: dict, provider: str) -> tuple[float, str]:
    """Return (confidence, method). Hard overrides (injection, LLM failure) are applied by the agent."""
    m = _load(provider)
    if m is None:
        return fallback_score(signals), "fallback_weights"
    return float(m.predict_proba(np.array([features(signals)]))[0, 1]), "logreg_calibrator"


def fit(rows: list[dict], correct: list[int], provider: str) -> dict:
    """Fit on calibration-split signals and correctness labels (1 = component correct)."""
    from sklearn.linear_model import LogisticRegression
    from sklearn.model_selection import cross_val_score

    X = np.array([features(r) for r in rows])
    y = np.array(correct)
    model = LogisticRegression(C=1.0, max_iter=1000)
    cv = cross_val_score(model, X, y, cv=5, scoring="roc_auc") if len(set(y)) > 1 and len(y) >= 25 else []
    model.fit(X, y)
    path = calibrator_path(provider)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, path)
    _models[provider] = model
    return {"provider": provider, "n": int(len(y)), "positive_rate": float(y.mean()) if len(y) else 0.0,
            "cv_roc_auc_mean": float(np.mean(cv)) if len(cv) else None,
            "coefficients": dict(zip(FEATURES, map(float, model.coef_[0]))),
            "intercept": float(model.intercept_[0])}
