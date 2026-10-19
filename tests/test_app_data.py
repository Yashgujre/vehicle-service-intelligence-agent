"""Dashboard data layer (app/data.py) against a temporary SQLite database. No network, no API keys."""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from sqlalchemy import create_engine, insert, select

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "app"))

import data as app_data
from vsia import db, observability
from vsia.schemas import ReviewDecision

MONDAY = date(2026, 6, 1)  # a Monday


def _complaint(odi, make, comp, day_offset, year=2023, summary="Car lost power on the highway."):
    return dict(odi_number=odi, make=make, model="MODEL X", model_year=year,
                date_filed=MONDAY + timedelta(days=day_offset), component_primary=comp, summary=summary,
                crash=False, fire=False, injuries=0, deaths=0)


@pytest.fixture()
def eng(tmp_path, monkeypatch):
    e = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    db.metadata.create_all(e)
    now = datetime(2026, 7, 1, 12, 0)
    with e.begin() as c:
        c.execute(insert(db.complaints), [
            _complaint(1, "FORD", "ELECTRICAL SYSTEM", 0,
                       summary="Call me at 555-123-4567 or jane.doe@example.com, the screen went black."),
            _complaint(2, "FORD", "ELECTRICAL SYSTEM", 1),
            _complaint(3, "KIA", "STEERING", 8, year=2024),
            _complaint(4, "KIA", "ELECTRICAL SYSTEM", 9, year=2024),
            _complaint(5, "TESLA", None, 15),  # partial third week (only one day of it in the data)
        ])
        c.execute(insert(db.recalls), [dict(campaign_number="24V123000", make="FORD", model="MODEL X",
                                            model_year=2023, component_raw="ELECTRICAL SYSTEM",
                                            component_primary="ELECTRICAL SYSTEM", summary="Display may fail.")])
        signals = {"candidates": ["24V123000", "24V999000"], "review_reasons": ["confidence 0.40 below threshold 0.70"],
                   "llm_confidence": 0.6, "llm_error": "upstream said: contact jane.doe@example.com"}
        c.execute(insert(db.triage_records), [
            dict(id=10, odi_number=1, run_id="r1", component="STEERING", severity="S3", recall_campaigns=[],
                 confidence=0.9, confidence_signals={}, route="auto", output={}, cited_sources=[],
                 provider="heuristic", model="tfidf-logreg", cost_usd=0.0, created_at=now - timedelta(days=1)),
            dict(id=11, odi_number=1, run_id="r2", component="ELECTRICAL SYSTEM", severity="S2",
                 recall_campaigns=["24V123000"], confidence=0.4, confidence_signals=signals, route="review",
                 output={"component": "ELECTRICAL SYSTEM",
                         "extracted": {"symptom": "Owner jane.doe@example.com says screen went black"}},
                 cited_sources=["recall:24V123000", "complaint:1"], provider="anthropic",
                 model="claude-haiku-5-5", cost_usd=0.002, created_at=now),
            dict(id=12, odi_number=3, run_id="r2", component="STEERING", severity="S1", recall_campaigns=[],
                 confidence=0.95, confidence_signals={}, route="auto", output={}, cited_sources=[],
                 provider="anthropic", model="claude-haiku-5-5", cost_usd=0.001, created_at=now),
        ])
        c.execute(insert(db.review_queue), [
            dict(odi_number=1, triage_record_id=11, status="pending", reason="low confidence", created_at=now),
            dict(odi_number=2, triage_record_id=None, status="accepted", reason="x", created_at=now),
        ])
        c.execute(insert(db.llm_calls), [
            dict(provider="anthropic", model="claude-haiku-5-5", purpose="triage", input_tokens=1000,
                 output_tokens=200, cost_usd=0.002, latency_ms=800, ok=True, created_at=now),
            dict(provider="anthropic", model="claude-haiku-5-5", purpose="triage", input_tokens=1000,
                 output_tokens=0, cost_usd=0.001, latency_ms=1200, ok=False, error="timeout", created_at=now),
        ])
        c.execute(insert(db.ingestion_runs), [
            dict(kind="recalls", started_at=now - timedelta(hours=2), finished_at=now - timedelta(hours=2),
                 rows_fetched=10, rows_inserted=10, ok=True),
            dict(kind="complaints_api", started_at=now - timedelta(hours=1), finished_at=now,
                 rows_fetched=100, rows_inserted=5, rows_skipped_duplicate=95, ok=True),
        ])
        old, new = now - timedelta(days=7), now
        c.execute(insert(db.forecasts), [
            dict(run_id="old", component="STEERING", week=date(2026, 6, 1), actual=1, forecast=1, lower=0,
                 upper=2, model_name="m@v1", is_holdout=True, created_at=old),
            *[dict(run_id="new", component="STEERING", week=date(2026, 5, 4) + timedelta(weeks=i),
                   actual=None if i >= 6 else 2.0, forecast=2.0, lower=1.0, upper=3.0, model_name="m@v2",
                   is_holdout=i < 6, created_at=new) for i in range(8)],
        ])
        c.execute(insert(db.spike_alerts), [
            dict(run_id="new", component="STEERING", week=date(2026, 6, 8), actual=9, upper=3, ratio=3.0),
            dict(run_id="new", component="STEERING", week=date(2026, 5, 4), actual=6, upper=3, ratio=2.0),
        ])
        c.execute(insert(db.eval_runs), [
            dict(run_id="e1", provider="ollama", model="qwen2.5:3b", created_at=now - timedelta(days=2),
                 metrics={"provider": "ollama", "split": "gold", "metrics": {"n": 300,
                                                                             "component_accuracy_primary": 0.5}}),
            dict(run_id="e2", provider="ollama", model="qwen2.5:3b", created_at=now,
                 metrics={"provider": "ollama", "split": "gold", "metrics": {"n": 300,
                                                                             "component_accuracy_primary": 0.6}}),
            dict(run_id="e3", provider="heuristic", model="tfidf-logreg", created_at=now,
                 metrics={"n": 300, "component_accuracy_primary": 0.55}),
        ])
    monkeypatch.setattr(db, "engine", lambda: e)
    monkeypatch.setattr(observability, "engine", lambda: e)
    return e


@pytest.fixture()
def src(eng, tmp_path):
    return app_data.Source("live", "test", readonly=False, engine=eng, demo_dir=tmp_path / "demo")


def test_complaints_filter_and_top_components(src):
    df = app_data.complaints(src)
    assert len(df) == 5
    assert df.loc[df.odi_number == 5, "component_primary"].item() == "OTHER"
    assert len(app_data.filter_complaints(df, makes=["KIA"])) == 2
    assert len(app_data.filter_complaints(df, model_years=[2024])) == 2
    assert len(app_data.filter_complaints(df, date_from=MONDAY + timedelta(days=8))) == 3
    top = app_data.top_components(df, 2)
    assert top.iloc[0].to_dict() == {"component": "ELECTRICAL SYSTEM", "count": 3}


def test_weekly_counts_drops_partial_week_and_zero_fills(src):
    df = app_data.complaints(src)
    wk = app_data.weekly_counts(df)
    assert wk["week"].dt.weekday.eq(0).all()
    assert wk["count"].tolist() == [2, 2]  # the third week is incomplete in the data and is dropped
    by = app_data.weekly_counts(df, by="component_primary", components=["STEERING"])
    assert by["count"].tolist() == [0, 1]
    assert app_data.weekly_counts(df.iloc[0:0]).empty


def test_triage_table_latest_only_and_join(src):
    latest = app_data.triage_table(src, latest_only=True)
    assert sorted(latest["id"]) == [11, 12]
    row = latest[latest.odi_number == 1].iloc[0]
    assert row["make"] == "FORD" and row["recall_campaigns"] == ["24V123000"]
    assert len(app_data.triage_table(src, latest_only=False)) == 3


def test_kpis(src):
    k = app_data.kpis(src)
    assert k["complaints"] == 5
    assert k["triaged"] == 2 and k["triage_runs"] == 3
    assert k["auto_routed_pct"] == pytest.approx(50.0)
    assert k["cost_per_1000_triaged_usd"] == pytest.approx(1.0)  # (0 + 0.002 + 0.001) / 3 * 1000
    assert k["pending_reviews"] == 1
    assert k["last_ingestion"]["kind"] == "complaints_api" and k["last_ingestion"]["rows_inserted"] == 5
    assert k["llm_calls"] == 2 and k["llm_cost_usd"] == pytest.approx(0.003)
    assert k["active_spike_alerts"] == 1 and k["spike_alerts_total"] == 2


def test_triage_detail_redacts_text_and_output(src):
    rec = app_data.triage_detail(src, 11)
    assert "555-123-4567" not in rec["complaint_text"] and "jane.doe@example.com" not in rec["complaint_text"]
    assert "[EMAIL]" in rec["complaint_text"]
    assert "jane.doe" not in json.dumps(rec["output"]) and "jane.doe" not in json.dumps(rec["confidence_signals"])
    assert rec["recall_campaigns"] == ["24V123000"]
    assert app_data.triage_detail(src, 999) is None


def test_recalls_for_builds_nhtsa_links(src):
    rc = app_data.recalls_for(src, ["24V123000", "00V000000"])
    assert rc["campaign_number"].tolist() == ["24V123000"]
    assert rc["url"].item() == "https://www.nhtsa.gov/recalls?nhtsaId=24V123000"


def test_pending_reviews_live_has_candidates_and_redacted_text(src):
    p = app_data.pending_reviews(src, limit=10)
    assert p["odi_number"].tolist() == [1]
    assert p["candidates"].iloc[0] == ["24V123000", "24V999000"]
    assert p["review_reasons"].iloc[0] == ["confidence 0.40 below threshold 0.70"]
    assert "jane.doe" not in p["summary"].iloc[0]
    assert app_data.review_counts(src) == {"pending": 1, "accepted": 1, "corrected": 0}


def test_submit_review_writes_label_and_refuses_when_readonly(src, eng):
    ro = app_data.Source("live", "test", readonly=True, engine=eng)
    d = ReviewDecision(odi_number=1, accepted=False, component="STEERING", severity="S1",
                       recall_campaigns=["24V999000"], note="checked")
    with pytest.raises(app_data.ReadOnlyError):
        app_data.submit_review(ro, d)
    res = app_data.submit_review(src, d)
    assert res["status"] == "corrected" and res["component"] == "STEERING"
    with eng.connect() as c:
        lab = c.execute(select(db.labels)).mappings().one()
    assert lab["source"] == "review" and lab["recall_campaigns"] == ["24V999000"]
    assert app_data.review_counts(src)["corrected"] == 1


def test_forecasts_latest_run_and_active_alerts(src):
    fc = app_data.latest_forecasts(src)
    assert set(fc["run_id"]) == {"new"} and len(fc) == 8
    assert fc["is_holdout"].sum() == 6
    al = app_data.spike_alerts(src)
    assert al["week"].iloc[0] == pd.Timestamp("2026-06-08")  # newest first
    assert al["active"].tolist() == [True, False]  # last holdout week 2026-06-08; window is 4 weeks


def test_eval_table_flattens_nested_and_flat_metrics(src):
    ev = app_data.eval_table(src)
    latest = ev[ev["is_latest"]].set_index("provider")
    assert latest.loc["ollama", "component_accuracy_primary"] == pytest.approx(0.6)
    assert latest.loc["heuristic", "component_accuracy_primary"] == pytest.approx(0.55)
    assert ev["is_latest"].sum() == 2


def test_llm_summary_uses_observability(src):
    s = app_data.llm_summary(src)
    row = s.iloc[0]
    assert row["calls"] == 2 and row["errors"] == 1 and row["error_rate"] == pytest.approx(0.5)


def test_routing_curves_from_demo_dir(tmp_path):
    d = tmp_path / "demo"
    d.mkdir()
    (d / "routing_ollama.json").write_text(json.dumps({
        "provider": "ollama", "threshold": 0.7, "coverage": 0.5, "accuracy_auto": 0.91,
        "curve": [{"threshold": 0.5, "coverage": 0.8, "accuracy_auto": 0.8}]}))
    s = app_data.Source("demo", "test", readonly=True, demo_dir=d)
    curves = app_data.routing_curves(s)
    assert curves[0]["provider"] == "ollama" and len(curves[0]["curve"]) == 1


def test_empty_database_degrades_gracefully(tmp_path):
    e = create_engine(f"sqlite:///{tmp_path / 'empty.db'}", future=True)
    db.metadata.create_all(e)
    s = app_data.Source("live", "test", readonly=False, engine=e)
    assert app_data.triage_table(s).empty
    assert app_data.latest_forecasts(s).empty and app_data.spike_alerts(s).empty
    assert app_data.eval_table(s).empty
    assert app_data.weekly_counts(app_data.complaints(s)).empty
    k = app_data.triage_summary(s)
    assert k["triaged"] == 0 and k["auto_routed_pct"] is None and k["cost_per_1000_triaged_usd"] is None
    empty = app_data.Source("empty", "nothing", readonly=True, demo_dir=tmp_path / "none")
    assert app_data.pending_reviews(empty).empty and app_data.llm_summary(empty).empty
    assert app_data.complaint_text(empty, 1) is None


def test_resolve_source_modes(tmp_path, monkeypatch):
    from vsia import config as vconfig
    monkeypatch.setenv("VSIA_DEMO_SNAPSHOT", "1")
    assert app_data.resolve_source(demo_dir=tmp_path / "none").mode == "empty"
    monkeypatch.delenv("VSIA_DEMO_SNAPSHOT")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'missing.db'}")
    vconfig.env.cache_clear()
    try:
        s = app_data.resolve_source(demo_dir=tmp_path / "none")
        assert s.mode == "empty" and s.readonly
        assert not (tmp_path / "missing.db").exists()  # resolution never creates a database file
    finally:
        monkeypatch.delenv("DATABASE_URL")
        vconfig.env.cache_clear()


def _load_export_module():
    spec = importlib.util.spec_from_file_location("export_demo_snapshot",
                                                  REPO / "scripts" / "export_demo_snapshot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_snapshot_round_trip(src, tmp_path):
    out = tmp_path / "demo"
    manifest = _load_export_module().export(src, out, max_triage=100, max_mb=10)
    assert manifest["rows"]["complaints"] == 5 and manifest["rows"]["triage_records"] == 2
    assert manifest["total_bytes"] < 10 * 1024 * 1024
    raw = "".join(p.read_bytes().decode("latin-1") for p in out.glob("*.parquet"))
    assert "jane.doe@example.com" not in raw and "555-123-4567" not in raw

    demo = app_data.Source("demo", "test", readonly=True, demo_dir=out)
    live_k, demo_k = app_data.kpis(src), app_data.kpis(demo)
    for key in ("complaints", "triaged", "auto_routed_pct", "pending_reviews", "active_spike_alerts",
                "llm_calls", "llm_cost_usd"):
        assert demo_k[key] == pytest.approx(live_k[key]), key
    p = app_data.pending_reviews(demo)
    assert p["candidates"].iloc[0] == ["24V123000", "24V999000"]
    assert "[EMAIL]" in app_data.triage_detail(demo, 11)["complaint_text"]
    assert app_data.eval_table(demo)["is_latest"].sum() == 2
    assert len(app_data.latest_forecasts(demo)) == 8
    with pytest.raises(app_data.ReadOnlyError):
        app_data.submit_review(demo, ReviewDecision(odi_number=1, accepted=True))


@pytest.mark.parametrize("page", ["views/overview.py", "views/triage.py", "views/review.py", "views/trends.py",
                                  "views/evaluation.py", "views/about.py"])
@pytest.mark.parametrize("populated", [True, False])
def test_every_page_renders_without_exceptions(page, populated, eng, tmp_path, monkeypatch):
    st_testing = pytest.importorskip("streamlit.testing.v1")
    import streamlit as st
    if not populated:
        empty = create_engine(f"sqlite:///{tmp_path / 'empty.db'}", future=True)
        db.metadata.create_all(empty)
        with empty.begin() as c:  # complaints only: the state before triage, forecasting and eval have run
            c.execute(insert(db.complaints), [_complaint(1, "FORD", "STEERING", 0)])
        monkeypatch.setattr(db, "engine", lambda: empty)
        monkeypatch.setattr(observability, "engine", lambda: empty)
    monkeypatch.delenv("VSIA_DEMO_SNAPSHOT", raising=False)
    monkeypatch.delenv("VSIA_READONLY", raising=False)
    monkeypatch.setattr(app_data, "resolve_source",
                        lambda demo_dir=app_data.DEMO_DIR: app_data.Source("live", "test", False, db.engine()))
    st.cache_data.clear()
    st.cache_resource.clear()
    at = st_testing.AppTest.from_file(str(REPO / "app" / "streamlit_app.py"), default_timeout=30)
    at.run()
    at.switch_page(page)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    shown = " ".join(str(m.value) for m in at.markdown)
    assert "jane.doe@example.com" not in shown and "555-123-4567" not in shown
    if populated and page == "views/triage.py":
        assert at.subheader[0].value.startswith("Complaint 3")  # newest record is selected by default
    if populated and page == "views/review.py":
        assert "EMAIL" in shown  # the pending item's complaint text, redacted


@pytest.mark.parametrize("readonly", [False, True])
def test_review_form_submits_or_is_disabled(readonly, eng, monkeypatch):
    st_testing = pytest.importorskip("streamlit.testing.v1")
    import streamlit as st
    monkeypatch.setattr(app_data, "resolve_source",
                        lambda demo_dir=app_data.DEMO_DIR: app_data.Source("live", "test", readonly, eng))
    st.cache_data.clear()
    st.cache_resource.clear()
    at = st_testing.AppTest.from_file(str(REPO / "app" / "streamlit_app.py"), default_timeout=30)
    at.run()
    at.switch_page("views/review.py")
    at.run()
    submit = next(b for b in at.button if b.label == "Save decision")
    if readonly:
        assert submit.disabled and any("Read-only" in w.value for w in at.warning)
        return
    at.radio(key="dec_1").set_value("Correct")
    at.selectbox(key="comp_1").set_value("STEERING")
    at.selectbox(key="sev_1").set_value("S1")
    at.multiselect(key="camps_1").set_value(["24V999000"])
    next(b for b in at.button if b.label == "Save decision").click()
    at.run()
    assert not at.exception, [e.value for e in at.exception]
    with eng.connect() as c:
        lab = c.execute(select(db.labels)).mappings().one()
        status = c.execute(select(db.review_queue.c.status).where(db.review_queue.c.id == 1)).scalar_one()
    assert (lab["component"], lab["severity"], lab["recall_campaigns"], status) == \
        ("STEERING", "S1", ["24V999000"], "corrected")


def test_streamlit_requirements_files_match():
    a = (REPO / "requirements-streamlit.txt").read_text()
    b = (REPO / "app" / "requirements.txt").read_text()
    assert a == b
    pins = [ln for ln in a.splitlines() if ln and not ln.startswith("#")]
    assert pins and all("==" in ln for ln in pins)
