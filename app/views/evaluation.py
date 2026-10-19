"""Evaluation and cost: latest eval metrics per provider, routing threshold curves, LLM cost and latency."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import ui

import data

src = ui.source()
st.title("Evaluation and cost")
st.caption("Metrics on the gold split come from `eval/run_eval.py`; labels are silver (derived from NHTSA "
           "structured fields). Cost and latency come from the LLM gateway's call log.")

KEY_METRICS = ["n", "component_accuracy_primary", "component_accuracy_any_label", "component_macro_f1_primary",
               "severity_within_one_vs_silver", "s1_recall_llm_raw", "auto_route_rate",
               "auto_route_accuracy_any_label", "recall_at_5_retrieval_silver", "llm_failure_rate",
               "latency_median_s", "latency_p95_s", "cost_per_1000_usd"]

st.subheader("Latest evaluation runs")
ev = data.cached(data.eval_table, src)
if ev.empty:
    ui.no_data("eval_runs", "evaluation runs")
else:
    latest = ev[ev["is_latest"]]
    cols = ["provider", "model", "split", "created_at"] + [m for m in KEY_METRICS if m in latest.columns]
    st.dataframe(latest[cols], hide_index=True, width="stretch",
                 column_config={"created_at": st.column_config.DatetimeColumn("Run (UTC)",
                                                                              format="YYYY-MM-DD HH:mm")})
    gold = latest[latest["split"] == "gold"]
    if gold["provider"].nunique() > 1:
        rate_metrics = [m for m in KEY_METRICS if m in gold.columns and m not in
                        ("n", "latency_median_s", "latency_p95_s", "cost_per_1000_usd")]
        pick = st.multiselect("Compare providers on", rate_metrics, default=rate_metrics[:4])
        if pick:
            long = gold.melt(id_vars=["provider", "model"], value_vars=pick, var_name="metric",
                             value_name="value")
            long["system"] = long["provider"] + " / " + long["model"]
            fig = px.bar(long, x="metric", y="value", color="system", barmode="group",
                         color_discrete_sequence=ui.SEQUENCE, labels={"metric": "", "value": ""}, title="Provider comparison (gold split)")
            fig.update_yaxes(range=[0, 1])
            ui.chart(ui.style(fig, height=380))
    with st.expander("All evaluation runs"):
        st.dataframe(ev, hide_index=True, width="stretch")

st.divider()
st.subheader("Routing threshold curve")
curves = data.cached(data.routing_curves, src)
if not curves:
    ui.no_data("routing", "routing calibration")
else:
    st.caption("Each point is a confidence threshold on the calibration split: coverage is the share of "
               "complaints auto-routed, accuracy is component accuracy inside that auto-routed share.")
    fig = go.Figure()
    for i, c in enumerate(curves):
        pts = pd.DataFrame(c.get("curve") or [])
        if pts.empty:
            continue
        color = ui.SEQUENCE[i % len(ui.SEQUENCE)]
        fig.add_trace(go.Scatter(x=pts["coverage"], y=pts["accuracy_auto"], mode="lines+markers",
                                 name=c["provider"], line=dict(color=color),
                                 customdata=pts["threshold"],
                                 hovertemplate="threshold %{customdata:.3f}<br>coverage %{x:.3f}"
                                               "<br>accuracy %{y:.3f}<extra></extra>"))
        if c.get("coverage") is not None and c.get("accuracy_auto") is not None:
            fig.add_trace(go.Scatter(x=[c["coverage"]], y=[c["accuracy_auto"]], mode="markers",
                                     marker=dict(size=13, symbol="diamond", color=color),
                                     name=f"{c['provider']} chosen threshold {c['threshold']:.3f}"))
    target = next((c.get("target_auto_accuracy") for c in curves if c.get("target_auto_accuracy")), None)
    if target:
        fig.add_hline(y=target, line_dash="dot", line_color=ui.NEUTRAL,
                      annotation_text=f"target auto-routed accuracy {target:.0%}")
    fig.update_layout(xaxis_title="Coverage (auto-routed share)", yaxis_title="Accuracy of auto-routed")
    ui.chart(ui.style(fig, height=400))
    st.dataframe(pd.DataFrame([{k: c.get(k) for k in ("provider", "threshold", "coverage", "accuracy_auto",
                                                       "fitted_at", "note")} for c in curves]),
                 hide_index=True, width="stretch")

st.divider()
st.subheader("LLM cost and latency")
llm = data.cached(data.llm_summary, src)
if llm.empty:
    ui.no_data("llm_calls", "LLM calls")
else:
    calls = int(llm["calls"].sum())
    errs = int(llm["errors"].sum())
    m = st.columns(4)
    m[0].metric("LLM calls", f"{calls:,}")
    m[1].metric("Error rate", f"{errs / calls * 100:.1f}%" if calls else "n/a")
    m[2].metric("Total cost", ui.money(float(llm["total_cost_usd"].sum())))
    m[3].metric("Max p95 latency", f"{llm['p95_latency_ms'].max():,.0f} ms")
    st.dataframe(llm, hide_index=True, width="stretch",
                 column_config={"error_rate": st.column_config.NumberColumn("error_rate", format="%.3f"),
                                "cost_per_1k_calls_usd": st.column_config.NumberColumn("cost per 1,000 calls (USD)",
                                                                                       format="%.4f")})
    llm = llm.assign(system=llm["provider"] + " / " + llm["model"] + " / " + llm["purpose"])
    a, b = st.columns(2)
    with a:
        fig = px.bar(llm, x="system", y="cost_per_1k_calls_usd", title="Cost per 1,000 calls (USD)",
                     labels={"system": "", "cost_per_1k_calls_usd": "USD"})
        fig.update_traces(marker_color=ui.PRIMARY)
        ui.chart(ui.style(fig, legend=False))
    with b:
        lat = llm.melt(id_vars="system", value_vars=["p50_latency_ms", "p95_latency_ms"], var_name="percentile",
                       value_name="ms")
        lat["percentile"] = lat["percentile"].str.replace("_latency_ms", "")
        fig = px.bar(lat, x="system", y="ms", color="percentile", barmode="group", title="Latency (ms)",
                     labels={"system": "", "ms": "ms"}, color_discrete_sequence=ui.SEQUENCE)
        ui.chart(ui.style(fig))
