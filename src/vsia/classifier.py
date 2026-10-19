"""Baseline component classifier (FR-12 groundwork): TF-IDF word 1-2 grams + char 3-5 grams into a
class-balanced logistic regression, with probability calibration chosen on a dev slice of TRAIN.

It is a benchmark for the LLM and a confidence signal for the triage agent. Input is the redacted
complaint summary only; NHTSA's coded components are training labels and never model input (ADR-0005).

  python -m vsia.classifier train            # select config, fit on TRAIN, evaluate, save, write report
  python -m vsia.classifier predict "text"   # top label and probability
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score, log_loss
from sklearn.pipeline import FeatureUnion, Pipeline

from vsia.config import DATA_DIR, REPO_ROOT, confidence_threshold
from vsia.guardrails import redact

MODEL_PATH = DATA_DIR / "models" / "component_clf.joblib"
METRICS_PATH = DATA_DIR / "models" / "component_clf_metrics.json"
SPLITS_FILE = DATA_DIR / "gold" / "splits.json"
GOLD_FILE = DATA_DIR / "gold" / "gold_set.jsonl"
CALIB_FILE = DATA_DIR / "gold" / "calibration_set.jsonl"
REPORT_PATH = REPO_ROOT / "docs" / "evaluation" / "baseline-classifier.md"
MODEL_VERSION = "tfidf-logreg-v1"
SEED = 42
MIN_TRAIN_PER_CLASS = 3  # needed for 3-fold calibration; rarer classes cannot be predicted
C_GRID = (1.0, 4.0, 16.0)
CALIBRATION_METHODS = ("none", "sigmoid", "temperature")
THRESHOLDS = [round(t, 2) for t in np.arange(0.30, 0.901, 0.05)]
TARGET_ACCURACY = 0.85


def _redacted(texts) -> list[str]:
    out = []
    for t in texts:
        r = redact(t or "")
        out.append(r.text if hasattr(r, "text") else str(r))
    return out


def _features(small: bool = False) -> FeatureUnion:
    min_df = 1 if small else 2
    return FeatureUnion([
        ("word", TfidfVectorizer(ngram_range=(1, 2), min_df=min_df, max_df=0.9, sublinear_tf=True,
                                 strip_accents="unicode", max_features=60000)),
        ("char", TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), min_df=min_df, sublinear_tf=True,
                                 strip_accents="unicode", max_features=120000)),
    ])


def _lr(C: float) -> LogisticRegression:
    return LogisticRegression(C=C, class_weight="balanced", max_iter=3000, random_state=SEED)


def _head(C: float, method: str, cv: int = 3):
    if method == "none":
        return _lr(C)
    return CalibratedClassifierCV(_lr(C), method=method, cv=cv, ensemble=False, n_jobs=cv)


def _drop_rare(texts: list[str], labels: list[str], min_count: int) -> tuple[list[str], list[str], list[str]]:
    counts = pd.Series(labels).value_counts()
    keep = set(counts[counts >= min_count].index)
    dropped = sorted(set(counts.index) - keep)
    pairs = [(t, y) for t, y in zip(texts, labels) if y in keep]
    return [p[0] for p in pairs], [p[1] for p in pairs], dropped


def fit_pipeline(texts: list[str], labels: list[str], C: float = 4.0, method: str = "temperature",
                 cv: int = 3, small: bool = False) -> tuple[Pipeline, list[str]]:
    """Fit features + head on redacted texts. Returns (pipeline, classes dropped as too rare)."""
    texts, labels, dropped = _drop_rare(_redacted(texts), list(labels), max(cv, MIN_TRAIN_PER_CLASS)
                                        if method != "none" else 1)
    pipe = Pipeline([("features", _features(small)), ("clf", _head(C, method, cv))])
    pipe.fit(texts, labels)
    return pipe, dropped


def top_label_ece(conf: np.ndarray, correct: np.ndarray, bins: int = 10) -> float:
    edges = np.linspace(0, 1, bins + 1)
    ece = 0.0
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi) if lo > 0 else (conf >= lo) & (conf <= hi)
        if m.any():
            ece += m.mean() * abs(conf[m].mean() - correct[m].mean())
    return float(ece)


class ComponentClassifier:
    def __init__(self, pipeline: Pipeline, meta: dict):
        self.pipeline = pipeline
        self.meta = meta
        self.labels = [str(c) for c in pipeline.classes_]

    def predict_proba(self, texts: list[str]) -> list[dict[str, float]]:
        if not texts:
            return []
        probs = self.pipeline.predict_proba(_redacted(texts))
        return [{lab: float(p) for lab, p in zip(self.labels, row)} for row in probs]

    def predict(self, texts: list[str]) -> list[tuple[str, float]]:
        out = []
        for d in self.predict_proba(texts):
            lab = max(d, key=d.get)
            out.append((lab, d[lab]))
        return out


@lru_cache
def load(path: str | None = None) -> ComponentClassifier:
    obj = joblib.load(path or MODEL_PATH)
    return ComponentClassifier(obj["pipeline"], obj["meta"])


def predict_proba(texts: list[str]) -> list[dict[str, float]]:
    return load().predict_proba(texts)


def predict(texts: list[str]) -> list[tuple[str, float]]:
    return load().predict(texts)


# ---------------------------------------------------------------------------------------------------
# Training and evaluation on the real splits
# ---------------------------------------------------------------------------------------------------


def _load_data() -> tuple[pd.DataFrame, list[dict], list[dict], dict]:
    from sqlalchemy import select

    from vsia import db

    splits = json.loads(SPLITS_FILE.read_text())
    with db.engine().begin() as conn:
        df = pd.DataFrame(conn.execute(select(db.complaints.c.odi_number, db.complaints.c.summary,
                                              db.complaints.c.component_primary,
                                              db.complaints.c.date_filed)).mappings().all())
    gold = [json.loads(x) for x in GOLD_FILE.read_text().splitlines() if x.strip()]
    calib = [json.loads(x) for x in CALIB_FILE.read_text().splitlines() if x.strip()]
    return df.set_index("odi_number"), gold, calib, splits


def _select_config(texts: list[str], labels: list[str]) -> dict:
    """Choose C (macro-F1) and the calibration method (top-label ECE, then log loss) on an 85/15 random
    dev split of TRAIN. GOLD and CALIBRATION are never touched here."""
    rng = np.random.default_rng(SEED)
    idx = rng.permutation(len(texts))
    n_dev = int(0.15 * len(texts))
    dev_i, tr_i = idx[:n_dev], idx[n_dev:]
    tr_t, tr_y, _ = _drop_rare([texts[i] for i in tr_i], [labels[i] for i in tr_i], MIN_TRAIN_PER_CLASS)
    keep = set(tr_y)
    dv = [(texts[i], labels[i]) for i in dev_i if labels[i] in keep]
    dv_t, dv_y = [d[0] for d in dv], [d[1] for d in dv]
    feats = _features()
    Xtr = feats.fit_transform(_redacted(tr_t))
    Xdv = feats.transform(_redacted(dv_t))
    c_results = {}
    for C in C_GRID:
        t0 = time.time()
        m = _lr(C).fit(Xtr, tr_y)
        pred = m.predict(Xdv)
        c_results[str(C)] = {"accuracy": round(accuracy_score(dv_y, pred), 4),
                             "macro_f1": round(f1_score(dv_y, pred, average="macro", zero_division=0), 4),
                             "fit_seconds": round(time.time() - t0, 1)}
    best_c = max(C_GRID, key=lambda c: (c_results[str(c)]["macro_f1"], -c))
    cal_results = {}
    for method in CALIBRATION_METHODS:
        t0 = time.time()
        m = _head(best_c, method).fit(Xtr, tr_y)
        P = m.predict_proba(Xdv)
        classes = list(m.classes_)
        pred = np.array(classes)[P.argmax(1)]
        correct = (pred == np.array(dv_y)).astype(float)
        cal_results[method] = {
            "accuracy": round(float(correct.mean()), 4),
            "macro_f1": round(f1_score(dv_y, pred, average="macro", zero_division=0), 4),
            "ece_top_label": round(top_label_ece(P.max(1), correct), 4),
            "log_loss": round(log_loss(dv_y, P, labels=classes), 4),
            "mean_confidence": round(float(P.max(1).mean()), 4),
            "fit_seconds": round(time.time() - t0, 1),
        }
    best_method = min(CALIBRATION_METHODS,
                      key=lambda k: (cal_results[k]["ece_top_label"], cal_results[k]["log_loss"]))
    return {"dev_size": len(dv_y), "dev_train_size": len(tr_y), "C_grid": c_results, "C": best_c,
            "calibration_methods": cal_results, "calibration": best_method,
            "selection_rule": "C by dev macro-F1; calibration by dev top-label ECE then log loss"}


def _gold_metrics(clf: ComponentClassifier, rows: list[dict], texts: list[str], pop_share: dict) -> dict:
    preds = clf.predict(texts)
    y = [r["component_primary"] for r in rows]
    yhat = [p[0] for p in preds]
    any_hit = [p in r["components_all"] or p == r["component_primary"] for p, r in zip(yhat, rows)]
    labels = sorted(set(y))
    rep = classification_report(y, yhat, labels=labels, output_dict=True, zero_division=0)
    per_class = {lab: {"precision": round(rep[lab]["precision"], 3), "recall": round(rep[lab]["recall"], 3),
                       "f1": round(rep[lab]["f1-score"], 3), "support": int(rep[lab]["support"])}
                 for lab in labels}
    w = {lab: pop_share.get(lab, 0.0) for lab in labels}
    wsum = sum(w.values()) or 1.0
    pop_weighted = sum(w[lab] * per_class[lab]["recall"] for lab in labels) / wsum

    def acc(mask):
        idx = [i for i, m in enumerate(mask) if m]
        if not idx:
            return {"n": 0}
        return {"n": len(idx), "primary_accuracy": round(np.mean([y[i] == yhat[i] for i in idx]), 4),
                "any_label_accuracy": round(np.mean([any_hit[i] for i in idx]), 4)}

    conf = pd.Series([f"{a} -> {b}" for a, b in zip(y, yhat) if a != b]).value_counts().head(10).to_dict()
    return {
        "n": len(rows),
        "primary_accuracy": round(accuracy_score(y, yhat), 4),
        "any_label_accuracy": round(float(np.mean(any_hit)), 4),
        "macro_f1": round(f1_score(y, yhat, labels=labels, average="macro", zero_division=0), 4),
        "weighted_f1": round(f1_score(y, yhat, labels=labels, average="weighted", zero_division=0), 4),
        "population_weighted_primary_accuracy": round(pop_weighted, 4),
        "per_class": per_class,
        "slices": {
            "s1_nhtsa_flags": acc([r["severity_source"] == "nhtsa_flags" for r in rows]),
            "with_known_recall_silver": acc([bool(r["known_recalls_silver"]) for r in rows]),
            "multilabel": acc([len(r["components_all"]) > 1 for r in rows]),
            "single_label": acc([len(r["components_all"]) <= 1 for r in rows]),
        },
        "top_confusions": conf,
        "mean_confidence": round(float(np.mean([p[1] for p in preds])), 4),
    }


def _calibration_metrics(clf: ComponentClassifier, rows: list[dict], texts: list[str]) -> dict:
    preds = clf.predict(texts)
    conf = np.array([p[1] for p in preds])
    prim = np.array([p[0] == r["component_primary"] for p, r in zip(preds, rows)], dtype=float)
    anyl = np.array([p[0] in r["components_all"] or p[0] == r["component_primary"]
                     for p, r in zip(preds, rows)], dtype=float)
    edges = np.linspace(0, 1, 11)
    reliability = []
    for lo, hi in zip(edges[:-1], edges[1:]):
        m = (conf > lo) & (conf <= hi) if lo > 0 else (conf >= lo) & (conf <= hi)
        reliability.append({"bin": f"{lo:.1f}-{hi:.1f}", "n": int(m.sum()),
                            "mean_confidence": round(float(conf[m].mean()), 3) if m.any() else None,
                            "primary_accuracy": round(float(prim[m].mean()), 3) if m.any() else None,
                            "any_label_accuracy": round(float(anyl[m].mean()), 3) if m.any() else None})
    curve = []
    for t in THRESHOLDS:
        m = conf >= t
        curve.append({"threshold": t, "coverage": round(float(m.mean()), 3), "n_auto": int(m.sum()),
                      "primary_accuracy": round(float(prim[m].mean()), 3) if m.any() else None,
                      "any_label_accuracy": round(float(anyl[m].mean()), 3) if m.any() else None})

    def first_meeting(key):
        for row in curve:
            if row[key] is not None and row[key] >= TARGET_ACCURACY:
                return {"threshold": row["threshold"], "coverage": row["coverage"], "accuracy": row[key]}
        return None

    cfg_t = confidence_threshold()
    m = conf >= cfg_t
    return {
        "n": len(rows),
        "primary_accuracy": round(float(prim.mean()), 4),
        "any_label_accuracy": round(float(anyl.mean()), 4),
        "ece_top_label_primary": round(top_label_ece(conf, prim), 4),
        "mean_confidence": round(float(conf.mean()), 4),
        "reliability": reliability,
        "coverage_curve": curve,
        "lowest_threshold_primary_ge_85": first_meeting("primary_accuracy"),
        "lowest_threshold_any_label_ge_85": first_meeting("any_label_accuracy"),
        "at_configured_threshold": {"threshold": cfg_t, "coverage": round(float(m.mean()), 3),
                                    "primary_accuracy": round(float(prim[m].mean()), 3) if m.any() else None,
                                    "any_label_accuracy": round(float(anyl[m].mean()), 3) if m.any() else None},
    }


def _temporal_check(df_train: pd.DataFrame, C: float) -> dict:
    """Within TRAIN only: fit on the earliest 80% by filing date, test on the latest 20%; compare with a
    random 80/20 split of the same pool. Uncalibrated LR (calibration does not change the argmax much)."""
    d = df_train.sort_values("date_filed")
    cut = int(0.8 * len(d))
    early, late = d.iloc[:cut], d.iloc[cut:]
    out = {"cutoff_date": str(late.date_filed.iloc[0]), "n_train": len(early), "n_test": len(late)}
    pipe, _ = fit_pipeline(early.summary.tolist(), early.component_primary.tolist(), C=C, method="none")
    out["temporal_accuracy"] = round(accuracy_score(late.component_primary, pipe.predict(_redacted(late.summary))), 4)
    shuffled = d.sample(frac=1.0, random_state=SEED)
    a, b = shuffled.iloc[:cut], shuffled.iloc[cut:]
    pipe, _ = fit_pipeline(a.summary.tolist(), a.component_primary.tolist(), C=C, method="none")
    out["random_accuracy"] = round(accuracy_score(b.component_primary, pipe.predict(_redacted(b.summary))), 4)
    return out


def train(save: bool = True, select: bool = True, temporal: bool = True, report: bool = True) -> dict:
    t_start = time.time()
    df, gold, calib, splits = _load_data()
    train_df = df.loc[splits["train"]].reset_index()
    texts, labels = train_df.summary.tolist(), train_df.component_primary.tolist()
    selection = _select_config(texts, labels) if select else {"C": 4.0, "calibration": "temperature"}
    C, method = selection["C"], selection["calibration"]
    t0 = time.time()
    pipe, dropped = fit_pipeline(texts, labels, C=C, method=method)
    fit_seconds = round(time.time() - t0, 1)
    meta = {"version": MODEL_VERSION, "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "C": C, "calibration": method, "n_train": len(texts), "classes": [str(c) for c in pipe.classes_],
            "classes_dropped_too_rare": dropped, "splits_version": splits.get("meta", {}).get("version"),
            "input": "redacted complaint summary only"}
    clf = ComponentClassifier(pipe, meta)
    pop_share = (df.component_primary.value_counts(normalize=True)).to_dict()
    gold_texts = df.loc[[r["odi_number"] for r in gold], "summary"].tolist()
    calib_texts = df.loc[[r["odi_number"] for r in calib], "summary"].tolist()
    t0 = time.time()
    gm = _gold_metrics(clf, gold, gold_texts, pop_share)
    latency_ms = (time.time() - t0) / max(1, len(gold)) * 1000
    cm = _calibration_metrics(clf, calib, calib_texts)
    metrics = {
        "model": meta, "selection": selection, "fit_seconds": fit_seconds,
        "predict_ms_per_complaint_batch": round(latency_ms, 2),
        "label_source": "gold_silver (NHTSA coded components); not hand-verified",
        "gold": gm, "calibration": cm,
        "temporal_check": _temporal_check(train_df, C) if temporal else None,
        "train_label_counts": pd.Series(labels).value_counts().to_dict(),
        "total_seconds": round(time.time() - t_start, 1),
    }
    if save:
        MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"pipeline": pipe, "meta": meta}, MODEL_PATH, compress=3)
        METRICS_PATH.write_text(json.dumps(metrics, indent=1, default=str))
        load.cache_clear()
    if report:
        write_report(metrics, REPORT_PATH)
    return metrics


# ---------------------------------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------------------------------


def _pct(x) -> str:
    return "n/a" if x is None else f"{100 * x:.1f}%"


def write_report(m: dict, path: Path) -> None:
    g, c, s = m["gold"], m["calibration"], m["selection"]
    L = []
    L.append("# Baseline component classifier: results")
    L.append("")
    L.append(f"- **Generated:** {m['model']['trained_at']} by `python -m vsia.classifier train` "
             f"(source: `src/vsia/classifier.py`; full metrics JSON in `data/models/component_clf_metrics.json`, "
             "gitignored).")
    L.append(f"- **Model:** `{m['model']['version']}`: TF-IDF word 1-2 grams + char_wb 3-5 grams, "
             f"LogisticRegression (C={m['model']['C']}, class_weight=balanced), calibration = "
             f"`{m['model']['calibration']}` (ADR-0043, ADR-0046).")
    L.append(f"- **Input:** redacted complaint summary only. **Train:** {m['model']['n_train']} complaints "
             f"(TRAIN split, `data/gold/splits.json`). Fit time {m['fit_seconds']} s; prediction "
             f"{m['predict_ms_per_complaint_batch']} ms per complaint in a batch of 200 on the dev laptop.")
    L.append(f"- **Labels:** SILVER. Ground truth is NHTSA's coded component (`gold_silver`), not hand labels "
             "(ADR-0040). Treat every number below as agreement with NHTSA intake coding.")
    if m["model"]["classes_dropped_too_rare"]:
        L.append(f"- **Classes the model cannot predict** (fewer than {MIN_TRAIN_PER_CLASS} training rows): "
                 f"{', '.join(m['model']['classes_dropped_too_rare'])}.")
    L.append("")
    L.append("## Headline (GOLD, n=%d, class-stratified, silver labels)" % g["n"])
    L.append("")
    L.append("| Metric | Value |")
    L.append("|---|---|")
    L.append(f"| Primary-label accuracy | {_pct(g['primary_accuracy'])} |")
    L.append(f"| Any-label accuracy (prediction in components_all) | {_pct(g['any_label_accuracy'])} |")
    L.append(f"| Macro-F1 (over the {len(g['per_class'])} classes present in GOLD) | {g['macro_f1']:.3f} |")
    L.append(f"| Weighted-F1 | {g['weighted_f1']:.3f} |")
    L.append(f"| Population-weighted primary accuracy (per-class recall weighted by corpus class share) | "
             f"{_pct(g['population_weighted_primary_accuracy'])} |")
    L.append("")
    L.append("GOLD is capped at 20 per class, so plain accuracy over-weights rare classes compared with live "
             "traffic. The population-weighted figure re-weights per-class recall by the corpus class mix "
             "and is the better estimate of production accuracy (ADR-0041).")
    L.append("")
    L.append("### Slices")
    L.append("")
    L.append("| Slice | n | Primary accuracy | Any-label accuracy |")
    L.append("|---|---|---|---|")
    for k, v in g["slices"].items():
        L.append(f"| {k} | {v['n']} | {_pct(v.get('primary_accuracy'))} | {_pct(v.get('any_label_accuracy'))} |")
    L.append("")
    L.append("### Per-class report (GOLD)")
    L.append("")
    L.append("| Class | Precision | Recall | F1 | Support |")
    L.append("|---|---|---|---|---|")
    for lab, v in sorted(g["per_class"].items(), key=lambda kv: -kv[1]["support"]):
        L.append(f"| {lab} | {v['precision']:.2f} | {v['recall']:.2f} | {v['f1']:.2f} | {v['support']} |")
    L.append("")
    L.append("### Most frequent confusions (true -> predicted)")
    L.append("")
    for k, v in g["top_confusions"].items():
        L.append(f"- {k}: {v}")
    L.append("")
    L.append("## Confidence on CALIBRATION (n=%d, proportional to the corpus class mix)" % c["n"])
    L.append("")
    L.append(f"Overall primary accuracy {_pct(c['primary_accuracy'])}, any-label accuracy "
             f"{_pct(c['any_label_accuracy'])}, mean top-label confidence {c['mean_confidence']:.3f}, "
             f"top-label expected calibration error (10 bins) {c['ece_top_label_primary']:.3f}.")
    L.append("")
    L.append("### Reliability table")
    L.append("")
    L.append("| Confidence bin | n | Mean confidence | Primary accuracy | Any-label accuracy |")
    L.append("|---|---|---|---|---|")
    for r in c["reliability"]:
        mc = "" if r["mean_confidence"] is None else f"{r['mean_confidence']:.3f}"
        L.append(f"| {r['bin']} | {r['n']} | {mc} | {_pct(r['primary_accuracy'])} | {_pct(r['any_label_accuracy'])} |")
    L.append("")
    L.append("### Coverage and accuracy by auto-route threshold")
    L.append("")
    L.append("| Threshold | Coverage (share auto-routed) | n auto | Primary accuracy | Any-label accuracy |")
    L.append("|---|---|---|---|---|")
    for r in c["coverage_curve"]:
        L.append(f"| {r['threshold']:.2f} | {_pct(r['coverage'])} | {r['n_auto']} | {_pct(r['primary_accuracy'])} "
                 f"| {_pct(r['any_label_accuracy'])} |")
    L.append("")
    p85, a85, at = c["lowest_threshold_primary_ge_85"], c["lowest_threshold_any_label_ge_85"], c["at_configured_threshold"]
    L.append("**Reading:**")
    L.append("")
    if p85:
        L.append(f"- Primary accuracy first reaches {int(TARGET_ACCURACY * 100)}% at threshold {p85['threshold']:.2f}, "
                 f"where {_pct(p85['coverage'])} of complaints would be auto-routed (accuracy {_pct(p85['accuracy'])}).")
    else:
        L.append(f"- Primary accuracy never reaches {int(TARGET_ACCURACY * 100)}% at any threshold from 0.30 to 0.90.")
    if a85:
        L.append(f"- Any-label accuracy first reaches {int(TARGET_ACCURACY * 100)}% at threshold {a85['threshold']:.2f}, "
                 f"coverage {_pct(a85['coverage'])} (accuracy {_pct(a85['accuracy'])}).")
    else:
        L.append(f"- Any-label accuracy never reaches {int(TARGET_ACCURACY * 100)}% in the 0.30 to 0.90 range.")
    L.append(f"- At the configured routing threshold ({at['threshold']}, `config/settings.yaml`), this classifier "
             f"alone would auto-route {_pct(at['coverage'])} with primary accuracy {_pct(at['primary_accuracy'])} "
             f"and any-label accuracy {_pct(at['any_label_accuracy'])}. The agent's threshold applies to its own "
             "combined confidence, not to this classifier alone.")
    L.append("- With n=300, each coverage cell has a binomial standard error of up to about 2.9 percentage points, "
             "and accuracy cells at high thresholds rest on fewer rows; read differences under 5 points as noise.")
    L.append("")
    L.append("## Model selection (dev slice of TRAIN; GOLD and CALIBRATION untouched)")
    L.append("")
    if "C_grid" in s:
        L.append(f"Dev slice: {s['dev_size']} complaints held out from TRAIN (random 15%, seed {SEED}); "
                 f"models fit on the other {s['dev_train_size']}. Rule: {s['selection_rule']}.")
        L.append("")
        L.append("| C | Dev accuracy | Dev macro-F1 | Fit seconds |")
        L.append("|---|---|---|---|")
        for k, v in s["C_grid"].items():
            L.append(f"| {k} | {_pct(v['accuracy'])} | {v['macro_f1']:.3f} | {v['fit_seconds']} |")
        L.append("")
        L.append("| Calibration | Dev accuracy | Dev macro-F1 | Top-label ECE | Log loss | Mean confidence |")
        L.append("|---|---|---|---|---|---|")
        for k, v in s["calibration_methods"].items():
            L.append(f"| {k} | {_pct(v['accuracy'])} | {v['macro_f1']:.3f} | {v['ece_top_label']:.3f} | "
                     f"{v['log_loss']:.3f} | {v['mean_confidence']:.3f} |")
        L.append("")
    t = m.get("temporal_check")
    if t:
        L.append("## Temporal check (within TRAIN)")
        L.append("")
        L.append(f"Fit on the earliest {t['n_train']} TRAIN complaints, tested on the latest {t['n_test']} "
                 f"(filed on or after {t['cutoff_date']}): primary accuracy {_pct(t['temporal_accuracy'])}. "
                 f"A random 80/20 split of the same pool gives {_pct(t['random_accuracy'])}. The gap is the "
                 "measured cost of drift for this baseline (ADR-0042). Uncalibrated LR, same C.")
        L.append("")
    L.append("## Limitations")
    L.append("")
    L.append("- Labels are NHTSA intake codes (silver). Intake coding is itself noisy and multi-label; the "
             "any-label metric exists because many complaints legitimately carry two or three components.")
    L.append("- `OTHER` (NHTSA 'UNKNOWN OR OTHER') is a catch-all with no consistent vocabulary, so it is hard "
             "for any text model.")
    L.append("- GOLD has 200 rows; per-class numbers for classes with 3 to 7 rows are anecdotal.")
    L.append("- Not yet measured: agreement with hand labels (needs the hand review in "
             "`docs/evaluation/labeling-guide.md`).")
    L.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L))


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Baseline component classifier")
    sub = ap.add_subparsers(dest="cmd", required=True)
    tr = sub.add_parser("train")
    tr.add_argument("--no-select", action="store_true", help="Skip dev selection (C=4, temperature)")
    tr.add_argument("--no-temporal", action="store_true")
    pr = sub.add_parser("predict")
    pr.add_argument("text", nargs="+")
    args = ap.parse_args(argv)
    if args.cmd == "train":
        m = train(select=not args.no_select, temporal=not args.no_temporal)
        g, c = m["gold"], m["calibration"]
        print(json.dumps({"gold": {k: g[k] for k in ("primary_accuracy", "any_label_accuracy", "macro_f1",
                                                     "population_weighted_primary_accuracy")},
                          "calibration": {k: c[k] for k in ("primary_accuracy", "ece_top_label_primary",
                                                            "lowest_threshold_primary_ge_85",
                                                            "lowest_threshold_any_label_ge_85")},
                          "selection": {k: m["selection"].get(k) for k in ("C", "calibration")},
                          "temporal_check": m["temporal_check"], "total_seconds": m["total_seconds"]}, indent=1))
    else:
        for lab, p in predict(args.text):
            print(f"{lab}\t{p:.3f}")


if __name__ == "__main__":
    main(sys.argv[1:])
