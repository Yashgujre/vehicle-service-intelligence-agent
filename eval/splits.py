"""Deterministic GOLD / CALIBRATION / TRAIN splits (PRD Weekend 3, FR-12).

Strategy (ADR-0042):
  GOLD (200): stratified by component_primary with a per-class floor and cap, so rare classes appear and
    large classes do not dominate. After sampling, within-class swaps raise the number of S1 incidents
    and recall-linked complaints to their minimums without changing the class quotas.
  CALIBRATION (300): proportional stratified sample of what is left, so it mirrors the production class
    mix. It is used to tune the routing confidence threshold.
  TRAIN: everything else. The baseline classifier never sees GOLD or CALIBRATION rows.

Input is a DataFrame with columns odi_number, component_primary, is_s1 (bool), has_recall (bool).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 42
SPLITS_VERSION = "splits-v1"


@dataclass
class SplitConfig:
    n_gold: int = 200
    n_calibration: int = 300
    cap_per_class: int = 20
    floor_per_class: int = 3
    min_class_size_for_gold: int = 2  # a class with one complaint stays in TRAIN
    min_s1: int = 20
    min_with_recall: int = 25
    seed: int = SEED


@dataclass
class Splits:
    gold: list[int]
    calibration: list[int]
    train: list[int]
    meta: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"meta": self.meta, "gold": self.gold, "calibration": self.calibration, "train": self.train}


def gold_quotas(class_counts: dict[str, int], cfg: SplitConfig) -> dict[str, int]:
    """Water-filling allocation: quota_c = clip(k * n_c, floor_c, ceil_c) with k chosen so quotas sum to
    n_gold. floor_c = min(floor, n_c // 2); ceil_c = min(cap, n_c // 2) so every class keeps at least half
    its rows for training. Integer rounding uses largest remainder."""
    eligible = {c: n for c, n in class_counts.items() if n >= cfg.min_class_size_for_gold}
    lo = {c: min(cfg.floor_per_class, n // 2) for c, n in eligible.items()}
    hi = {c: max(lo[c], min(cfg.cap_per_class, n // 2)) for c, n in eligible.items()}
    target = min(cfg.n_gold, sum(hi.values()))

    def alloc(k: float) -> dict[str, float]:
        return {c: float(np.clip(k * n, lo[c], hi[c])) for c, n in eligible.items()}

    a, b = 0.0, 1.0
    for _ in range(100):
        mid = (a + b) / 2
        if sum(alloc(mid).values()) < target:
            a = mid
        else:
            b = mid
    raw = alloc(b)
    quotas = {c: int(np.floor(v)) for c, v in raw.items()}
    short = target - sum(quotas.values())
    order = sorted(raw, key=lambda c: (-(raw[c] - quotas[c]), c))
    for c in order:
        if short <= 0:
            break
        if quotas[c] < hi[c]:
            quotas[c] += 1
            short -= 1
    return {c: q for c, q in sorted(quotas.items()) if q > 0}


def _enforce_minimum(df: pd.DataFrame, chosen: set[int], attr: str, minimum: int,
                     protected: list[str], rng: np.random.Generator) -> int:
    """Swap selected rows without `attr` for unselected rows with `attr` from the same class until the
    minimum is met. Rows carrying any protected attribute are never swapped out. Returns swaps made."""
    swaps = 0
    have = int(df[df.odi_number.isin(chosen)][attr].sum())
    classes = sorted(df.component_primary.unique())
    rng.shuffle(classes)
    while have < minimum:
        progressed = False
        for cls in classes:
            if have >= minimum:
                break
            sub = df[df.component_primary == cls]
            sel = sub[sub.odi_number.isin(chosen)]
            out_cand = sel[~sel[attr]]
            for p in protected:
                out_cand = out_cand[~out_cand[p]]
            in_cand = sub[(~sub.odi_number.isin(chosen)) & sub[attr]]
            if out_cand.empty or in_cand.empty:
                continue
            out_id = int(out_cand.odi_number.iloc[rng.integers(len(out_cand))])
            in_id = int(in_cand.odi_number.iloc[rng.integers(len(in_cand))])
            chosen.discard(out_id)
            chosen.add(in_id)
            have += 1
            swaps += 1
            progressed = True
        if not progressed:
            break
    return swaps


def make_splits(df: pd.DataFrame, cfg: SplitConfig | None = None) -> Splits:
    cfg = cfg or SplitConfig()
    df = df.sort_values("odi_number").reset_index(drop=True).copy()
    df["is_s1"] = df["is_s1"].astype(bool)
    df["has_recall"] = df["has_recall"].astype(bool)
    rng = np.random.default_rng(cfg.seed)

    counts = df.component_primary.value_counts().to_dict()
    quotas = gold_quotas(counts, cfg)
    chosen: set[int] = set()
    for cls, q in quotas.items():
        ids = df.loc[df.component_primary == cls, "odi_number"].to_numpy()
        chosen.update(int(i) for i in rng.choice(ids, size=q, replace=False))

    swaps_s1 = _enforce_minimum(df, chosen, "is_s1", cfg.min_s1, ["has_recall"], rng)
    swaps_recall = _enforce_minimum(df, chosen, "has_recall", cfg.min_with_recall, ["is_s1"], rng)

    rest = df[~df.odi_number.isin(chosen)]
    rest_counts = rest.component_primary.value_counts()
    raw = rest_counts / rest_counts.sum() * cfg.n_calibration
    calib_q = np.floor(raw).astype(int)
    short = cfg.n_calibration - int(calib_q.sum())
    for cls in sorted(raw.index, key=lambda c: (-(raw[c] - calib_q[c]), c))[:short]:
        calib_q[cls] += 1
    calibration: set[int] = set()
    for cls in sorted(calib_q.index):
        q = int(calib_q[cls])
        if q <= 0:
            continue
        ids = rest.loc[rest.component_primary == cls, "odi_number"].to_numpy()
        calibration.update(int(i) for i in rng.choice(ids, size=min(q, len(ids)), replace=False))

    train = sorted(set(df.odi_number.astype(int)) - chosen - calibration)
    gold_df = df[df.odi_number.isin(chosen)]
    meta = {
        "version": SPLITS_VERSION,
        "strategy": "random_stratified",
        "temporal": False,
        "temporal_note": "Gold and calibration are random (not time-based) samples across the whole filing "
                         "window; see ADR-0042. The classifier report adds a separate temporal check.",
        "seed": cfg.seed,
        "config": cfg.__dict__,
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_total": int(len(df)),
        "sizes": {"gold": len(chosen), "calibration": len(calibration), "train": len(train)},
        "gold_quotas": quotas,
        "gold_s1": int(gold_df.is_s1.sum()),
        "gold_with_recall": int(gold_df.has_recall.sum()),
        "swaps": {"s1": swaps_s1, "with_recall": swaps_recall},
        "classes_excluded_from_gold": sorted(set(counts) - set(quotas)),
    }
    return Splits(gold=sorted(chosen), calibration=sorted(calibration), train=train, meta=meta)


def save_splits(splits: Splits, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(splits.to_json(), indent=1))


def load_splits(path: Path) -> Splits:
    d = json.loads(Path(path).read_text())
    return Splits(gold=d["gold"], calibration=d["calibration"], train=d["train"], meta=d.get("meta", {}))
