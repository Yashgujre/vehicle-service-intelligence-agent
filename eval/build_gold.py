"""Build the SILVER gold set, the calibration set and the train split (PRD Weekend 3, FR-12).

No human labeler was available at build time, so labels are derived from structured NHTSA fields
(ADR-0040). Every output says "silver": label_source = "gold_silver" in files and in the labels table.
A review CSV lets the owner hand-verify gold rows later and promote them to "gold_hand".

Usage:
  python eval/build_gold.py                      # build splits, silver labels, review CSV, labels rows
  python eval/build_gold.py --promote data/gold/gold_set_review.csv   # write hand labels as gold_hand
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pandas as pd
from sqlalchemy import delete, insert, select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "eval"))

from splits import SplitConfig, make_splits, save_splits  # noqa: E402

from vsia import db  # noqa: E402
from vsia.guardrails import redact  # noqa: E402
from vsia.taxonomy import split_components  # noqa: E402

GOLD_DIR = ROOT / "data" / "gold"
SPLITS_FILE = GOLD_DIR / "splits.json"
GOLD_FILE = GOLD_DIR / "gold_set.jsonl"
CALIB_FILE = GOLD_DIR / "calibration_set.jsonl"
REVIEW_FILE = GOLD_DIR / "gold_set_review.csv"
SILVER_RULES_VERSION = "silver-v1"
LABEL_SOURCE = "gold_silver"

# ---------------------------------------------------------------------------------------------------
# Model family key (ADR-0045). Complaint and recall model strings differ in punctuation and suffixes:
# "MUSTANG MACH-E" vs "MUSTANG MACH E", "F-150 LIGHTNING" vs "F-150 LIGHTNING BEV", "ID.4" vs "ID 4".
# Rule: upper-case; "-", "." and "/" become spaces; "PLUG-IN HYBRID" -> "PHEV"; "HEV" -> "HYBRID";
# a trailing "BEV" token is dropped; whitespace collapsed. Distinct vehicles stay distinct
# (ESCAPE HYBRID vs ESCAPE PHEV, IONIQ 5 vs IONIQ 5 N, RAV4 PRIME vs RAV4 PHEV).
# ---------------------------------------------------------------------------------------------------


def model_family_key(model: str | None) -> str:
    s = (model or "").upper()
    s = re.sub(r"[-./]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\bPLUG IN HYBRID\b", "PHEV", s)
    s = re.sub(r"\bHEV\b", "HYBRID", s)
    s = re.sub(r"\s+BEV$", "", s)
    return s


# ---------------------------------------------------------------------------------------------------
# Severity silver rubric (ADR-0044). S1 from NHTSA incident flags is high precision. Everything else
# comes from keyword rules and is low confidence: needs_hand_review = True.
# Order: S1 flags > S1 keywords > S2 > S3 > S4 > default S3.
# ---------------------------------------------------------------------------------------------------

_MOVING = re.compile(r"\b(while driving|driving (on|down|at)|highway|freeway|interstate|\d+\s?mph|at speed|"
                     r"in traffic|while moving|on the road|merging|intersection)\b")

SEVERITY_RULES: list[tuple[str, str, re.Pattern, bool]] = [
    # (severity, rule id, pattern, requires moving context)
    ("S1", "s1_total_loss", re.compile(
        r"\b(complete|total)\s+(loss\s+of\s+)?(motive\s+)?(power|propulsion|braking|brakes|steering)\b"
        r"(?!\s+steering)|\blost\s+all\s+(motive\s+)?(power|propulsion|braking|brakes|steering)\b"
        r"|\b(brakes?|steering)\s+(completely\s+)?(failed|went out|stopped working|did not work)\b"
        r"|\bno\s+(brakes|steering)\b"), True),
    ("S2", "s2_phantom_or_sudden_braking", re.compile(
        r"phantom\s+br[ae]a?k|\b(sudden|unexpected|random|abrupt|violent)(ly)?\s+(hard\s+)?(br[ae]a?k|slow|decelerat)"
        r"|\bbr[ae]a?k(ed|es|ing|s)?\s+(very\s+)?(hard|suddenly|abruptly|violently|on its own|by itself"
        r"|for no (apparent )?reason|without (any )?(reason|warning))"
        r"|slow(ed|s|ing)? down\s+(\w+\s+)?(abruptly|suddenly|rapidly)"
        r"|automatic emergency br[ae]a?k|\baeb\b|forward collision (warning|avoidance)"), False),
    ("S2", "s2_unintended_acceleration", re.compile(
        r"unintended accel|accelerat\w*\s+(on its own|by itself|unexpectedly|without)|sudden(ly)? accelerat"),
        False),
    ("S2", "s2_loss_of_power", re.compile(
        r"\b(loss|lost|losing|lose)\s+(of\s+)?(all\s+)?(motive\s+)?(power|propulsion)\b(?!\s+steering)"
        r"|reduced power|power (was )?(limited|reduced)|turtle mode|limp mode|stop vehicle|\biccu\b"
        r"|would not go (any )?faster|failed to (respond|accelerate)|(no|lack of|delayed) (acceleration|response)"
        r"|hesitat"
        r"|\b(shut (down|off)|stalled|died)\b.{0,40}\b(while driving|on the (highway|freeway|road))"), False),
    ("S2", "s2_steering_or_adas", re.compile(
        r"(lane keep\w*|lane assist|lane centering|autopilot|auto ?steer|adaptive cruise|super cruise|"
        r"blue ?cruise|cruise control)\b.{0,80}\b(jerk|swerv|veer|yank|pull|disengag)"
        r"|\b(steering( wheel)?|wheel)\s+(jerk|swerv|veer|yank)|loss of (power )?steering"
        r"|steering (assist )?(fault|failure|warning|reduced|lost)"), False),
    ("S2", "s2_brake_warning_or_restraints", re.compile(
        r"\bbrak\w*\s+(system\s+)?(warning|fault|failure|failed)"
        r"|\bair ?bags?\b.{0,40}\b(light|warning|deploy|fault)|seat ?belts?\b.{0,40}\b(not|won'?t|fail|latch|retract)"
        r"|wipers?\b.{0,30}\b(stop|stopped|fail|quit|freeze|froze|not work|does not work|do not work)"),
        False),
    ("S3", "s3_charging_or_battery", re.compile(
        r"\b(not|won'?t|wouldn'?t|will not|unable to|stopped|fail\w*( to)?)\s+charg"
        r"|charg\w*\s+(fail|error|fault|issue|problem|port)|\b12 ?v(olt)?\b|(dead|drained) battery"
        r"|battery (died|drain|dead)"), False),
    ("S3", "s3_no_start_or_shift", re.compile(
        r"(won'?t|wouldn'?t|will not|would not|did not|does not|failed to|unable to)\s+"
        r"(start|turn on|power on|go into (drive|gear|reverse)|shift)|\bno start\b"), False),
    ("S3", "s3_camera_display_hvac", re.compile(
        r"(backup|back-up|rear|reverse|rearview|rear view|360) camera"
        r"|(screen|display|monitor|infotainment)\s+(went |goes |is |was )?(black|blank|dark|froze|frozen|reboot)"
        r"|heat pump|\bhvac\b|air condition|\ba/?c\b|heater|defrost|water (leak|intrusion)|\bleak"), False),
    ("S3", "s3_doors_lights", re.compile(
        r"(door|window|liftgate|trunk|tailgate|frunk)\b.{0,40}\b(won'?t|will not|stuck|fail|not open|not close)"
        r"|(head ?lights?|tail ?lights?|turn signal)\b.{0,40}\b(out|fail|not work|flicker)"
        r"|key ?fob|fail\w* to (un)?lock"), False),
    ("S3", "s3_mechanical_or_recall_remedy", re.compile(
        r"vibrat|\bcrack|glass roof|panoramic|sunroof|bolts? (sheared|broke)"
        r"|recall (repair|remedy|part)|parts? (are |is |were |was )?(not )?(yet )?(available|on backorder|back ?order)"),
        False),
    ("S4", "s4_comfort_cosmetic_infotainment", re.compile(
        r"\b(rattl|squeak|creak|buzz)|\bnoise\b|\b(trim|paint|cosmetic|scratch|rust|panel gap)"
        r"|\b(radio|bluetooth|carplay|android auto|speaker|audio|navigation|phone key|browser|video)\b"), False),
]


def is_s1_flag(crash, fire, injuries, deaths) -> bool:
    return bool(crash) or bool(fire) or int(injuries or 0) > 0 or int(deaths or 0) > 0


def silver_severity(summary: str, crash=False, fire=False, injuries=0, deaths=0) -> dict:
    """Return {severity_silver, severity_source, severity_rule, needs_hand_review}."""
    if is_s1_flag(crash, fire, injuries, deaths):
        fired = [n for n, v in (("crash", crash), ("fire", fire), ("injuries", int(injuries or 0) > 0),
                                ("deaths", int(deaths or 0) > 0)) if v]
        return {"severity_silver": "S1", "severity_source": "nhtsa_flags",
                "severity_rule": "flags:" + "+".join(fired), "needs_hand_review": False}
    text = (summary or "").lower()
    moving = bool(_MOVING.search(text))
    for sev, rule_id, pat, needs_moving in SEVERITY_RULES:
        if needs_moving and not moving:
            continue
        if pat.search(text):
            return {"severity_silver": sev, "severity_source": "rule_keywords", "severity_rule": rule_id,
                    "needs_hand_review": True}
    return {"severity_silver": "S3", "severity_source": "rule_default", "severity_rule": "default_s3",
            "needs_hand_review": True}


# ---------------------------------------------------------------------------------------------------
# Recall silver rule (ADR-0045).
#   candidate_recalls: same make, model family key and model year, report_date <= date_filed.
#   known_recalls_silver: candidates whose component_primary is in the complaint's components_all
#     (OTHER never matches: it is not a component).
#   later_recalls_same_component: same vehicle and component, report_date > date_filed (the complaint
#     preceded the recall; useful for early-warning analysis, not a triage target).
# ---------------------------------------------------------------------------------------------------

RECALL_RULE = ("same make + model_family_key + model_year; recall.component_primary in "
               "complaint.components_all (excluding OTHER); recall.report_date <= complaint.date_filed + 0 days")


def _as_date(v) -> date | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v)[:10])
    except ValueError:
        return None


def index_recalls(recalls: list[dict]) -> dict[tuple, list[dict]]:
    idx: dict[tuple, list[dict]] = {}
    for r in recalls:
        key = (str(r["make"]).upper(), model_family_key(r["model"]), int(r["model_year"]))
        idx.setdefault(key, []).append(r)
    return idx


def match_recalls(complaint: dict, recall_index: dict[tuple, list[dict]]) -> dict:
    key = (str(complaint["make"]).upper(), model_family_key(complaint["model"]), int(complaint["model_year"]))
    filed = _as_date(complaint.get("date_filed"))
    comps = set(complaint.get("components_all") or []) - {"OTHER"}
    candidate, known, later = set(), set(), set()
    for r in recall_index.get(key, []):
        rdate = _as_date(r.get("report_date"))
        same_comp = r.get("component_primary") in comps
        if rdate is not None and filed is not None and rdate <= filed:
            candidate.add(r["campaign_number"])
            if same_comp:
                known.add(r["campaign_number"])
        elif same_comp:
            later.add(r["campaign_number"])
    return {"known_recalls_silver": sorted(known), "candidate_recalls": sorted(candidate),
            "later_recalls_same_component": sorted(later)}


# ---------------------------------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------------------------------


def load_frames() -> tuple[pd.DataFrame, list[dict]]:
    eng = db.engine()
    with eng.begin() as conn:
        comp = pd.DataFrame(conn.execute(select(db.complaints)).mappings().all())
        rec = [dict(r) for r in conn.execute(select(db.recalls)).mappings().all()]
    return comp, rec


def silver_row(c: dict, recall_index: dict) -> dict:
    comps_all = split_components(c.get("components_raw"))
    base = {"make": c["make"], "model": c["model"], "model_year": int(c["model_year"]),
            "date_filed": c.get("date_filed"), "components_all": comps_all}
    rec = match_recalls(base, recall_index)
    sev = silver_severity(c.get("summary", ""), c.get("crash"), c.get("fire"), c.get("injuries"), c.get("deaths"))
    return {
        "odi_number": int(c["odi_number"]),
        "label_source": LABEL_SOURCE,
        "silver_rules_version": SILVER_RULES_VERSION,
        "make": c["make"],
        "model": c["model"],
        "model_family": model_family_key(c["model"]),
        "model_year": int(c["model_year"]),
        "date_filed": str(_as_date(c.get("date_filed")) or ""),
        "date_incident": str(_as_date(c.get("date_incident")) or ""),
        "summary_redacted": redact(c.get("summary") or "").text,
        "components_raw": c.get("components_raw"),
        "component_primary": c.get("component_primary"),
        "components_all": comps_all,
        "flags": {"crash": bool(c.get("crash")), "fire": bool(c.get("fire")),
                  "injuries": int(c.get("injuries") or 0), "deaths": int(c.get("deaths") or 0)},
        **sev,
        **rec,
        "recall_rule": RECALL_RULE,
    }


def add_recall_similarity(rows: list[dict], recalls: list[dict]) -> None:
    """Attach TF-IDF cosine similarity between the complaint text and each matched recall's summary plus
    consequence. Review aid only: it is not part of the silver rule and is not a label."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    texts: dict[str, str] = {}
    for r in recalls:
        texts.setdefault(r["campaign_number"], f"{r.get('summary') or ''} {r.get('consequence') or ''}")
    camps = sorted(texts)
    if not rows or not camps:
        return
    vec = TfidfVectorizer(stop_words="english", sublinear_tf=True, min_df=1)
    vec.fit([texts[c] for c in camps] + [r["summary_redacted"] for r in rows])
    rmat = vec.transform([texts[c] for c in camps])
    pos = {c: i for i, c in enumerate(camps)}
    cmat = vec.transform([r["summary_redacted"] for r in rows])
    for i, r in enumerate(rows):
        ids = sorted(set(r["known_recalls_silver"]) | set(r["candidate_recalls"]))
        sims = {}
        for c in ids:
            if c in pos:
                sims[c] = round(float(cmat[i].multiply(rmat[pos[c]]).sum()), 3)
        r["recall_text_similarity"] = sims


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w") as f:
        for r in rows:
            f.write(json.dumps(r, default=str) + "\n")


def _review_has_hand_labels(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open() as f:
        for r in csv.DictReader(f):
            if any((r.get(k) or "").strip() for k in ("hand_component", "hand_severity", "hand_recall")):
                return True
    return False


def write_review_csv(rows: list[dict], path: Path) -> Path:
    if _review_has_hand_labels(path):
        path = path.with_name(path.stem + ".new.csv")
    cols = ["odi_number", "split", "vehicle", "date_filed", "summary_redacted", "silver_component_primary",
            "silver_components_all", "silver_severity", "severity_source", "severity_rule",
            "needs_hand_review", "silver_known_recalls", "known_recall_similarity", "candidate_recalls",
            "hand_component", "hand_severity", "hand_recall", "reviewer_note"]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({
                "odi_number": r["odi_number"], "split": "gold",
                "vehicle": f"{r['model_year']} {r['make']} {r['model']}",
                "date_filed": r["date_filed"], "summary_redacted": r["summary_redacted"],
                "silver_component_primary": r["component_primary"],
                "silver_components_all": "|".join(r["components_all"]),
                "silver_severity": r["severity_silver"], "severity_source": r["severity_source"],
                "severity_rule": r["severity_rule"], "needs_hand_review": r["needs_hand_review"],
                "silver_known_recalls": "|".join(r["known_recalls_silver"]),
                "known_recall_similarity": "|".join(
                    str(r.get("recall_text_similarity", {}).get(c, "")) for c in r["known_recalls_silver"]),
                "candidate_recalls": "|".join(r["candidate_recalls"]),
                "hand_component": "", "hand_severity": "", "hand_recall": "", "reviewer_note": "",
            })
    return path


def write_labels_table(rows_by_split: dict[str, list[dict]]) -> int:
    ids = [r["odi_number"] for rows in rows_by_split.values() for r in rows]
    now = datetime.utcnow()
    with db.engine().begin() as conn:
        conn.execute(delete(db.labels).where(db.labels.c.source == LABEL_SOURCE))
        payload = []
        for split, rows in rows_by_split.items():
            for r in rows:
                payload.append({
                    "odi_number": r["odi_number"], "component": r["component_primary"],
                    "severity": r["severity_silver"], "recall_campaigns": r["known_recalls_silver"],
                    "source": LABEL_SOURCE, "reviewer": f"rules:{SILVER_RULES_VERSION}",
                    "note": json.dumps({"split": split, "components_all": r["components_all"],
                                        "severity_source": r["severity_source"],
                                        "needs_hand_review": r["needs_hand_review"],
                                        "candidate_recalls": r["candidate_recalls"]}),
                    "created_at": now,
                })
        if payload:
            conn.execute(insert(db.labels), payload)
    return len(ids)


def build(write_db: bool = True, cfg: SplitConfig | None = None) -> dict:
    comp, recalls = load_frames()
    recall_index = index_recalls(recalls)
    records = comp.to_dict("records")
    silver = {int(c["odi_number"]): silver_row(c, recall_index) for c in records}

    feat = pd.DataFrame({
        "odi_number": list(silver),
        "component_primary": [s["component_primary"] for s in silver.values()],
        "is_s1": [s["severity_source"] == "nhtsa_flags" for s in silver.values()],
        "has_recall": [bool(s["known_recalls_silver"]) for s in silver.values()],
    })
    splits = make_splits(feat, cfg)
    splits.meta["silver_rules_version"] = SILVER_RULES_VERSION
    splits.meta["population_with_known_recall"] = int(feat.has_recall.sum())
    splits.meta["population_s1_flags"] = int(feat.is_s1.sum())
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    save_splits(splits, SPLITS_FILE)

    gold_rows = [dict(silver[i], split="gold") for i in splits.gold]
    calib_rows = [dict(silver[i], split="calibration") for i in splits.calibration]
    add_recall_similarity(gold_rows + calib_rows, recalls)
    _write_jsonl(GOLD_FILE, gold_rows)
    _write_jsonl(CALIB_FILE, calib_rows)
    review_path = write_review_csv(gold_rows, REVIEW_FILE)
    n_labels = write_labels_table({"gold": gold_rows, "calibration": calib_rows}) if write_db else 0

    def comp_counts(rows):
        return pd.Series([r["component_primary"] for r in rows]).value_counts().to_dict()

    def sev_counts(rows):
        return pd.Series([f"{r['severity_silver']}:{r['severity_source']}" for r in rows]).value_counts().to_dict()

    summary = {
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sizes": splits.meta["sizes"],
        "gold_components": comp_counts(gold_rows),
        "gold_s1_flags": sum(r["severity_source"] == "nhtsa_flags" for r in gold_rows),
        "gold_with_known_recall": sum(bool(r["known_recalls_silver"]) for r in gold_rows),
        "gold_with_candidate_recall": sum(bool(r["candidate_recalls"]) for r in gold_rows),
        "gold_multilabel": sum(len(r["components_all"]) > 1 for r in gold_rows),
        "gold_severity": sev_counts(gold_rows),
        "calibration_components": comp_counts(calib_rows),
        "calibration_severity": sev_counts(calib_rows),
        "population_with_known_recall": splits.meta["population_with_known_recall"],
        "population_s1_flags": splits.meta["population_s1_flags"],
        "labels_rows_written": n_labels,
        "review_csv": str(review_path.relative_to(ROOT)),
        "swaps": splits.meta["swaps"],
        "classes_excluded_from_gold": splits.meta["classes_excluded_from_gold"],
    }
    (GOLD_DIR / "build_summary.json").write_text(json.dumps(summary, indent=1))
    return summary


# ---------------------------------------------------------------------------------------------------
# Promotion of hand labels (see docs/evaluation/labeling-guide.md)
# ---------------------------------------------------------------------------------------------------


def promote(review_csv: Path, reviewer: str) -> int:
    """Write every reviewed row (hand_component and hand_severity filled) to labels as source='gold_hand'
    and add hand fields to gold_set.jsonl. Re-running replaces earlier gold_hand rows for the same ids."""
    valid_sev = {"S1", "S2", "S3", "S4"}
    from vsia.config import components
    valid_comp = set(components())
    reviewed: dict[int, dict] = {}
    with Path(review_csv).open() as f:
        for r in csv.DictReader(f):
            hc, hs = (r.get("hand_component") or "").strip().upper(), (r.get("hand_severity") or "").strip().upper()
            if not hc or not hs:
                continue
            if hc not in valid_comp or hs not in valid_sev:
                raise ValueError(f"odi {r['odi_number']}: invalid hand label {hc!r} / {hs!r}")
            hr = (r.get("hand_recall") or "").strip().upper()
            recalls = [] if hr in {"", "NONE"} else [x.strip() for x in re.split(r"[|;, ]+", hr) if x.strip()]
            reviewed[int(r["odi_number"])] = {"hand_component": hc, "hand_severity": hs, "hand_recalls": recalls,
                                              "reviewer_note": (r.get("reviewer_note") or "").strip()}
    if not reviewed:
        return 0
    now = datetime.utcnow()
    with db.engine().begin() as conn:
        conn.execute(delete(db.labels).where((db.labels.c.source == "gold_hand")
                                             & db.labels.c.odi_number.in_(list(reviewed))))
        conn.execute(insert(db.labels), [
            {"odi_number": i, "component": v["hand_component"], "severity": v["hand_severity"],
             "recall_campaigns": v["hand_recalls"], "source": "gold_hand", "reviewer": reviewer,
             "note": v["reviewer_note"] or None, "created_at": now}
            for i, v in reviewed.items()])
    rows = [json.loads(line) for line in GOLD_FILE.read_text().splitlines() if line.strip()]
    for r in rows:
        if r["odi_number"] in reviewed:
            r.update(reviewed[r["odi_number"]], hand_reviewer=reviewer, label_source_hand="gold_hand")
    _write_jsonl(GOLD_FILE, rows)
    return len(reviewed)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--promote", type=Path, help="Filled review CSV to promote to gold_hand labels")
    ap.add_argument("--reviewer", default="owner")
    ap.add_argument("--no-db", action="store_true", help="Do not write rows to the labels table")
    args = ap.parse_args()
    if args.promote:
        n = promote(args.promote, args.reviewer)
        print(f"promoted {n} rows to gold_hand")
        return
    print(json.dumps(build(write_db=not args.no_db), indent=1))


if __name__ == "__main__":
    main()
