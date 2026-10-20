"""Evaluation runner (FR-12). One command per step; every number in docs/evaluation comes from here.

  python -m eval.run_eval predict  --provider ollama --split calibration   # run triage, save predictions
  python -m eval.run_eval calibrate --provider ollama                       # fit confidence + threshold
  python -m eval.run_eval predict  --provider ollama --split gold
  python -m eval.run_eval score    --provider ollama                        # metrics -> MLflow + report
  python -m eval.run_eval all      --provider ollama                        # the four steps above
  python -m eval.run_eval compare                                           # model comparison table

Predictions are stored as JSONL (data/eval/<split>_<provider>.jsonl) so metrics can be recomputed from
stored signals after the calibrator changes, without paying for LLM calls again.
"""

from __future__ import annotations

import argparse
import json
import logging
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from vsia import agent, confidence, config, db
from vsia.schemas import Complaint
from vsia.tools import model_family

GOLD_DIR = config.DATA_DIR / "gold"
EVAL_DIR = config.DATA_DIR / "eval"
REPORT_DIR = config.REPO_ROOT / "docs" / "evaluation" / "reports"
TARGET_AUTO_ACCURACY = 0.90  # accuracy required inside the auto-routed share when choosing the threshold
log = logging.getLogger("eval")


def load_split(split: str) -> list[dict]:
    path = GOLD_DIR / ("gold_set.jsonl" if split == "gold" else "calibration_set.jsonl")
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def pred_path(split: str, provider: str) -> Path:
    return EVAL_DIR / f"{split}_{provider}.jsonl"


def predict(split: str, provider: str, limit: int | None = None, min_interval_s: float = 0.0) -> Path:
    """Append one prediction per complaint, resuming after the last one written. Stops at the first rate-limit
    error (HTTP 429) instead of recording the offline fallback as the provider's answer."""
    rows = load_split(split)[: limit or None]
    out = pred_path(split, provider)
    out.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out.exists():
        done = {json.loads(line)["odi_number"] for line in out.read_text().splitlines() if line.strip()}
    run_id = agent.new_run_id(f"eval-{split}-{provider}")
    with out.open("a") as f:
        for i, g in enumerate(rows):
            if g["odi_number"] in done:
                continue
            started = time.monotonic()
            c: Complaint = agent.load_complaint(g["odi_number"])
            rec = agent.triage(c, provider=provider, run_id=run_id, persist=False, enqueue=False)
            if rec.confidence_signals.get("llm_status") == 429:
                log.warning("rate limited at %s/%s %s %s; stopping, rerun to resume", i + 1, len(rows), split,
                            provider)
                raise SystemExit(3)
            agent.save(rec, run_id=run_id, enqueue=False)
            f.write(json.dumps({"odi_number": g["odi_number"], "record": rec.model_dump(mode="json")}) + "\n")
            f.flush()
            if (i + 1) % 10 == 0:
                log.info("%s/%s %s %s", i + 1, len(rows), split, provider)
            time.sleep(max(0.0, min_interval_s - (time.monotonic() - started)))
    return out


def load_preds(split: str, provider: str) -> dict[int, dict]:
    p = pred_path(split, provider)
    if not p.exists():
        return {}
    preds = {}
    for line in p.read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            preds[d["odi_number"]] = d["record"]
    return preds


def _correct(rec: dict, g: dict) -> int:
    return int(rec["output"]["component"] in set(g["components_all"] or [g["component_primary"]]))


def calibrate(provider: str) -> dict:
    gold = {g["odi_number"]: g for g in load_split("calibration")}
    preds = load_preds("calibration", provider)
    keys = [k for k in preds if k in gold]
    sig = [preds[k]["confidence_signals"] for k in keys]
    y = [_correct(preds[k], gold[k]) for k in keys]
    fit = confidence.fit(sig, y, provider)
    scores = np.array([confidence.score(s, provider)[0] for s in sig])
    yy = np.array(y)
    curve = []
    best = None
    for t in np.round(np.arange(0.30, 0.96, 0.025), 3):
        m = scores >= t
        cov = float(m.mean())
        acc = float(yy[m].mean()) if m.any() else None
        curve.append({"threshold": float(t), "coverage": cov, "accuracy_auto": acc})
        if acc is not None and acc >= TARGET_AUTO_ACCURACY and (best is None or cov > best["coverage"]):
            best = {"threshold": float(t), "coverage": cov, "accuracy_auto": acc}
    if best is None:
        best = {"threshold": 0.95, "coverage": float((scores >= 0.95).mean()), "accuracy_auto": None,
                "note": f"no threshold reached {TARGET_AUTO_ACCURACY:.0%} accuracy on calibration"}
    routing = {"provider": provider, "target_auto_accuracy": TARGET_AUTO_ACCURACY, **best,
               "fitted_at": datetime.utcnow().isoformat(), "calibrator": fit, "curve": curve}
    config.routing_file(provider).parent.mkdir(parents=True, exist_ok=True)
    config.routing_file(provider).write_text(json.dumps(routing, indent=1))
    return routing


def _rescore(rec: dict, provider: str, threshold: float) -> tuple[float, str]:
    s = rec["confidence_signals"]
    conf, _ = confidence.score(s, provider)
    hard = [r for r in s.get("review_reasons", []) if not r.startswith("confidence")]
    return conf, ("review" if hard or conf < threshold else "auto")


def score(provider: str, split: str = "gold") -> dict:
    gold = {g["odi_number"]: g for g in load_split(split)}
    preds = load_preds(split, provider)
    keys = [k for k in gold if k in preds]
    if not keys:
        raise SystemExit(f"no predictions for {split}/{provider}; run predict first")
    threshold = config.confidence_threshold(provider)
    with db.engine().begin() as conn:
        from sqlalchemy import select
        comp = {r.odi_number: r for r in conn.execute(select(db.complaints)).all() if r.odi_number in gold}

    n = len(keys)
    prim = anyl = 0
    field_hits = {"make": 0, "model": 0, "model_year": 0}
    sev_exact = sev_within = 0
    s1_tp = s1_fp = s1_fn = 0
    auto = auto_correct = 0
    rec5_n = rec5_hit = match_hit = 0
    match_pred = match_pred_ok = 0
    lat, costs, failed = [], [], 0
    per_class: dict[str, list[int]] = {}
    y_true, y_pred = [], []
    order = {"S1": 1, "S2": 2, "S3": 3, "S4": 4}
    for k in keys:
        g, r = gold[k], preds[k]
        out = r["output"]
        sig = r["confidence_signals"]
        c = comp[k]
        p = out["component"]
        ok_any = p in set(g["components_all"] or [g["component_primary"]])
        prim += p == g["component_primary"]
        anyl += ok_any
        per_class.setdefault(g["component_primary"], []).append(int(ok_any))
        y_true.append(g["component_primary"])
        y_pred.append(p)
        ex = out["extracted"]
        field_hits["make"] += (ex.get("make") or "").upper() == c.make
        field_hits["model"] += bool(ex.get("model")) and model_family(ex["model"]) == model_family(c.model)
        field_hits["model_year"] += ex.get("model_year") == c.model_year
        truth_s1 = bool(c.crash or c.fire or (c.injuries or 0) > 0 or (c.deaths or 0) > 0)
        llm_sev = sig.get("llm_severity", out["severity"])
        s1_tp += truth_s1 and llm_sev == "S1"
        s1_fp += (not truth_s1) and llm_sev == "S1"
        s1_fn += truth_s1 and llm_sev != "S1"
        sev_exact += out["severity"] == g["severity_silver"]
        sev_within += abs(order[out["severity"]] - order[g["severity_silver"]]) <= 1
        conf, route = _rescore(r, provider, threshold)
        if route == "auto":
            auto += 1
            auto_correct += ok_any
        known = set(g.get("known_recalls_silver") or [])
        if known:
            rec5_n += 1
            rec5_hit += bool(known & set((sig.get("retrieval_ranked") or [])[:5]))
            match_hit += bool(known & set(r["output"] and [m["campaign_number"] for m in out["recall_matches"]]))
        for m in out["recall_matches"]:
            match_pred += 1
            match_pred_ok += m["campaign_number"] in set(g.get("candidate_recalls") or []) and \
                m["campaign_number"] in known
        lat.append(r["latency_ms"])
        costs.append(r["cost_usd"])
        failed += bool(sig.get("llm_error"))

    from sklearn.metrics import f1_score
    metrics = {
        "n": n,
        "component_accuracy_primary": prim / n,
        "component_accuracy_any_label": anyl / n,
        "component_macro_f1_primary": float(f1_score(y_true, y_pred, average="macro", zero_division=0)),
        "field_accuracy_make": field_hits["make"] / n,
        "field_accuracy_model": field_hits["model"] / n,
        "field_accuracy_model_year": field_hits["model_year"] / n,
        "severity_exact_vs_silver": sev_exact / n,
        "severity_within_one_vs_silver": sev_within / n,
        "s1_precision_llm_raw": s1_tp / (s1_tp + s1_fp) if (s1_tp + s1_fp) else None,
        "s1_recall_llm_raw": s1_tp / (s1_tp + s1_fn) if (s1_tp + s1_fn) else None,
        "auto_route_rate": auto / n,
        "auto_route_accuracy_any_label": auto_correct / auto if auto else None,
        "threshold": threshold,
        "recall_at_5_retrieval_silver": rec5_hit / rec5_n if rec5_n else None,
        "recall_match_hit_rate_llm_silver": match_hit / rec5_n if rec5_n else None,
        "n_with_known_recall": rec5_n,
        "llm_recall_match_precision_silver": match_pred_ok / match_pred if match_pred else None,
        "llm_failure_rate": failed / n,
        "latency_median_s": statistics.median(lat) / 1000,
        "latency_p95_s": float(np.percentile(lat, 95)) / 1000,
        "cost_per_1000_usd": 1000 * sum(costs) / n,
    }
    model = next(iter(preds.values()))["model"]
    run = {"provider": provider, "model": model, "split": split,
           "prompt_version": agent.PROMPT_VERSION, "metrics": metrics,
           "per_class_any_label_accuracy": {k: {"n": len(v), "acc": sum(v) / len(v)} for k, v in
                                            sorted(per_class.items(), key=lambda kv: -len(kv[1]))}}
    _log_mlflow(run)
    _write_report(run)
    from sqlalchemy import insert
    with db.engine().begin() as conn:
        conn.execute(insert(db.eval_runs).values(run_id=f"eval-{split}-{provider}-{int(time.time())}",
                                                 provider=provider, model=model, metrics=run))
    return run


def _log_mlflow(run: dict) -> None:
    try:
        import mlflow
        mlflow.set_tracking_uri(config.env().mlflow_tracking_uri)
        mlflow.set_experiment("vsia-triage-eval")
        with mlflow.start_run(run_name=f"{run['provider']}-{run['split']}"):
            mlflow.log_params({"provider": run["provider"], "model": run["model"], "split": run["split"],
                               "prompt_version": run["prompt_version"]})
            mlflow.log_metrics({k: float(v) for k, v in run["metrics"].items() if isinstance(v, (int, float))})
            mlflow.log_dict(run, "eval_run.json")
            run["mlflow_run_id"] = mlflow.active_run().info.run_id
    except Exception as e:  # noqa: BLE001
        log.warning("mlflow logging failed: %s", e)


def _fmt(v) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        return f"{v:.3f}"
    return str(v)


def _write_report(run: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = REPORT_DIR / f"{datetime.utcnow():%Y-%m-%d}-{run['provider']}-{run['split']}.md"
    lines = [f"# Evaluation report: {run['provider']} ({run['model']}) on the {run['split']} split", "",
             f"- Generated: {datetime.utcnow():%Y-%m-%d %H:%M} UTC by `python -m eval.run_eval score "
             f"--provider {run['provider']}`",
             f"- Prompt version: `{run['prompt_version']}`; MLflow run: `{run.get('mlflow_run_id', 'n/a')}`",
             "- Labels are SILVER (derived from NHTSA structured fields); see docs/data/datasheet-gold-set.md.",
             "", "| Metric | Value |", "|---|---|"]
    lines += [f"| {k} | {_fmt(v)} |" for k, v in run["metrics"].items()]
    lines += ["", "## Any-label accuracy by true primary component", "", "| Component | n | Accuracy |",
              "|---|---|---|"]
    lines += [f"| {k} | {v['n']} | {v['acc']:.2f} |" for k, v in run["per_class_any_label_accuracy"].items()]
    path.write_text("\n".join(lines) + "\n")
    (EVAL_DIR / f"score_{run['split']}_{run['provider']}.json").write_text(json.dumps(run, indent=1, default=str))


def compare() -> str:
    rows = []
    for p in sorted(EVAL_DIR.glob("score_gold_*.json")):
        rows.append(json.loads(p.read_text()))
    keys = ["component_accuracy_primary", "component_accuracy_any_label", "component_macro_f1_primary",
            "field_accuracy_model_year", "s1_recall_llm_raw", "severity_within_one_vs_silver",
            "auto_route_rate", "auto_route_accuracy_any_label", "recall_at_5_retrieval_silver",
            "recall_match_hit_rate_llm_silver", "latency_median_s", "cost_per_1000_usd", "llm_failure_rate"]
    head = "| Metric | " + " | ".join(f"{r['provider']} ({r['model']})" for r in rows) + " |"
    sep = "|---|" + "---|" * len(rows)
    body = [f"| {k} | " + " | ".join(_fmt(r["metrics"].get(k)) for r in rows) + " |" for k in keys]
    table = "\n".join([head, sep, *body])
    out = config.REPO_ROOT / "docs" / "evaluation" / "model-comparison.md"
    out.write_text("# Model comparison on the gold split\n\nGenerated by `python -m eval.run_eval compare` on "
                   f"{datetime.utcnow():%Y-%m-%d %H:%M} UTC. Providers without a column have not been run "
                   "(no API key at build time). Labels are silver.\n\n" + table + "\n\n" + COMPARE_NOTES)
    return table


COMPARE_NOTES = """## Reading the table

- `field_accuracy_model_year` compares `extracted.model_year` with the vehicle record. The triage prompt asks
  the model for the year only as stated in the complaint text and null otherwise, and owner narratives rarely
  state it, so a low score for an LLM mostly means "not stated". The heuristic copies the vehicle record, so
  its 1.0 is by construction. The agent itself always has the vehicle record; this field measures extraction
  from text only.
- `s1_recall_llm_raw` is the model's own severity before the business rule. The agent forces S1 whenever the
  owner reports a crash, fire, injury or death (ADR-0062), so the routed severity never misses those.
- `auto_route_accuracy_any_label` is accuracy on the cases the calibrated router sends without human review,
  at the threshold fitted on the calibration split; `auto_route_rate` is the share of cases it auto-routes.
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("step", choices=["predict", "calibrate", "score", "all", "compare"])
    ap.add_argument("--provider", default=None)
    ap.add_argument("--split", default="gold", choices=["gold", "calibration"])
    ap.add_argument("--limit", type=int)
    ap.add_argument("--min-interval", type=float, default=0.0,
                    help="minimum seconds between LLM calls, for free tiers with a per-minute limit")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    provider = a.provider or config.llm_provider()
    if a.step == "predict":
        print(predict(a.split, provider, a.limit, a.min_interval))
    elif a.step == "calibrate":
        r = calibrate(provider)
        print(json.dumps({k: v for k, v in r.items() if k != "curve"}, indent=1))
    elif a.step == "score":
        print(json.dumps(score(provider, a.split)["metrics"], indent=1))
    elif a.step == "all":
        predict("calibration", provider, a.limit, a.min_interval)
        calibrate(provider)
        predict("gold", provider, a.limit, a.min_interval)
        print(json.dumps(score(provider)["metrics"], indent=1))
    elif a.step == "compare":
        print(compare())
    return 0


if __name__ == "__main__":
    sys.exit(main())
