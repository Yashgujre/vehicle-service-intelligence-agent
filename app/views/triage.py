"""Triage queue: latest triage records joined to complaints, with filters and a detail panel."""

import pandas as pd
import streamlit as st
import ui

import data

src = ui.source()
st.title("Triage queue")
st.caption("Each complaint is triaged by the agent: component, severity, linked recalls, calibrated confidence "
           "and a route (auto or human review).")

tr = data.cached(data.triage_table, src, True)
latest_only = True
if tr.empty:
    ui.no_data("triage_records", "triage")
    st.stop()

with st.container(border=True):
    f = st.columns([2, 2, 1.4, 1.4, 1.6, 2])
    makes = f[0].multiselect("Make", sorted(tr["make"].dropna().unique()), placeholder="All")
    comps = f[1].multiselect("Component", sorted(tr["component"].dropna().unique()), placeholder="All")
    sevs = f[2].multiselect("Severity", ["S1", "S2", "S3", "S4"], placeholder="All")
    routes = f[3].multiselect("Route", ["auto", "review"], placeholder="All")
    provs = f[4].multiselect("Provider", sorted(tr["provider"].dropna().unique()), placeholder="All")
    conf = f[5].slider("Confidence", 0.0, 1.0, (0.0, 1.0), step=0.05)
    latest_only = st.toggle("Latest record per complaint only", value=True,
                            help="Off shows every triage run, including evaluation runs and re-triages")

if not latest_only:
    tr = data.cached(data.triage_table, src, False)

m = tr["confidence"].between(conf[0], conf[1]) | tr["confidence"].isna()
for col, sel in (("make", makes), ("component", comps), ("severity", sevs), ("route", routes),
                 ("provider", provs)):
    if sel:
        m &= tr[col].isin(sel)
view = tr[m].copy()
st.caption(f"{len(view):,} triage records shown.")
if view.empty:
    st.warning("No triage records match these filters.")
    st.stop()

def _text(col: str):
    return view[col].astype(object).where(view[col].notna(), "").astype(str)


view["vehicle"] = (view["model_year"].astype("Int64").astype(str).replace("<NA>", "") + " " + _text("make") + " "
                   + _text("vehicle_model")).str.strip()
view["recalls"] = view["recall_campaigns"].map(lambda xs: ", ".join(xs) if xs is not None and len(xs) else "")
view["provider_model"] = _text("provider") + " / " + _text("model")
cols = ["odi_number", "vehicle", "component", "severity", "confidence", "route", "recalls", "provider_model",
        "created_at"]
event = st.dataframe(
    view[cols], width="stretch", hide_index=True, height=360, on_select="rerun", selection_mode="single-row",
    key="triage_table",
    column_config={
        "odi_number": st.column_config.NumberColumn("ODI", format="%d"),
        "vehicle": "Vehicle",
        "component": "Component",
        "severity": "Severity",
        "confidence": st.column_config.ProgressColumn("Confidence", min_value=0.0, max_value=1.0, format="%.2f"),
        "route": "Route",
        "recalls": "Recall campaigns",
        "provider_model": "Provider / model",
        "created_at": st.column_config.DatetimeColumn("Triaged (UTC)", format="YYYY-MM-DD HH:mm"),
    },
)
rows = event.selection.rows if event and event.selection else []
sel = view.iloc[rows[0]] if rows else view.iloc[0]
if not rows:
    st.caption("Select a row to see its details. Showing the first record.")

rec = data.cached(data.triage_detail, src, int(sel["id"]))
if rec is None:
    st.error("This triage record is not available in the current data source.")
    st.stop()

st.subheader(f"Complaint {int(rec['odi_number'])}: {sel['vehicle']}")
d1, d2, d3, d4 = st.columns(4)
d1.metric("Component", rec["component"] or "n/a")
d2.metric("Severity", rec["severity"] or "n/a")
d3.metric("Confidence", f"{rec['confidence']:.2f}" if pd.notna(rec["confidence"]) else "n/a")
d4.metric("Route", rec["route"] or "n/a")

left, right = st.columns([3, 2])
with left:
    st.markdown("**Complaint text** (PII redacted)")
    with st.container(border=True):
        text = rec.get("complaint_text")
        st.markdown(ui.escape_md(text) if text else "_Complaint text is not available in this data source._")
    st.markdown("**Structured output**")
    st.json(rec["output"], expanded=1)
with right:
    sig = rec["confidence_signals"] or {}
    st.markdown("**Confidence signals**")
    keys = [("confidence_method", "Method"), ("llm_confidence", "LLM self-reported confidence"),
            ("clf_max_prob", "Baseline classifier max probability"),
            ("clf_prob_of_llm_label", "Classifier probability of LLM label"), ("agree", "LLM and classifier agree"),
            ("retrieval_top_score", "Top retrieval score"), ("n_candidates", "Recall candidates"),
            ("injection_score", "Injection score"), ("pii_redactions", "PII redactions"),
            ("citations_dropped", "Citations dropped by grounding"),
            ("severity_rule_override", "Severity rule override")]
    tbl = pd.DataFrame([{"signal": label, "value": str(sig[k_])} for k_, label in keys if k_ in sig])
    if not tbl.empty:
        st.dataframe(tbl, hide_index=True, width="stretch")
    reasons = sig.get("review_reasons") or []
    if reasons:
        st.markdown("**Review reasons:** " + "; ".join(ui.escape_md(r) for r in reasons))
    with st.expander("All signals (JSON)"):
        st.json(sig)

    st.markdown("**Cited sources**")
    camps = rec["recall_campaigns"]
    if camps:
        rc = data.cached(data.recalls_for, src, tuple(camps))
        info = {r.campaign_number: r for r in rc.itertuples()}
        for c in camps:
            r = info.get(c)
            line = f"- [Recall {c}]({data.recall_url(c)})"
            if r is not None:
                line += f": {ui.escape_md(str(r.component_raw or ''))}"
            st.markdown(line)
            if r is not None and r.summary:
                st.caption(str(r.summary)[:400])
    else:
        st.caption("No recall campaign was linked to this complaint.")
    others = [s for s in rec["cited_sources"] if not str(s).startswith("recall:")]
    if others:
        st.caption("Other sources: " + ", ".join(map(str, others)))
    st.caption(f"Provider {rec['provider']} / model {rec['model']}, prompt {rec['prompt_version']}, "
               f"latency {rec['latency_ms']} ms, cost {ui.money(rec['cost_usd'], 6)}, run {rec['run_id']}.")
