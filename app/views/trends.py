"""Trends and spikes: weekly complaints by component, champion forecasts with prediction bands, spike alerts."""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st
import ui

import data

src = ui.source()
st.title("Trends and spikes")
st.caption("Weekly complaint volume per component, the forecasting champion's predictions with prediction "
           "intervals, and spike alerts where actual volume exceeded the upper bound.")

comp = data.cached(data.complaints, src)
if comp.empty:
    ui.no_data("complaints")
else:
    st.subheader("Complaints per week by component")
    ranked = data.top_components(comp, 50)["component"].tolist()
    chosen = st.multiselect("Components (NHTSA-coded)", ranked, default=ranked[:5])
    if chosen:
        wk = data.weekly_counts(comp, by="component_primary", components=chosen)
        fig = px.line(wk, x="week", y="count", color="component_primary",
                      color_discrete_sequence=ui.SEQUENCE, labels={"week": "", "count": "Complaints", "component_primary": "Component"})
        ui.chart(ui.style(fig, height=380))
    else:
        st.caption("Select at least one component.")

st.divider()
st.subheader("Forecast versus actual")
fc = data.cached(data.latest_forecasts, src)
if fc.empty:
    ui.no_data("forecasts")
else:
    run_id, model_name = fc["run_id"].iloc[0], fc["model_name"].iloc[0]
    st.caption(f"Latest forecast run `{run_id}` ({model_name}). Holdout weeks have actuals; future weeks do not.")
    comps = sorted(fc["component"].unique())
    pick = st.selectbox("Component", comps)
    g = fc[fc["component"] == pick].sort_values("week")
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=g["week"], y=g["upper"], mode="lines", line=dict(width=0), showlegend=False,
                             hoverinfo="skip"))
    fig.add_trace(go.Scatter(x=g["week"], y=g["lower"], mode="lines", line=dict(width=0), fill="tonexty",
                             fillcolor=ui.BAND, name="Prediction interval"))
    fig.add_trace(go.Scatter(x=g["week"], y=g["forecast"], mode="lines+markers", name="Forecast",
                             line=dict(color=ui.PRIMARY, dash="dash")))
    fig.add_trace(go.Scatter(x=g["week"], y=g["actual"], mode="lines+markers", name="Actual",
                             line=dict(color=ui.ACCENT)))
    fut = g[~g["is_holdout"]]
    if not fut.empty:
        fig.add_vrect(x0=fut["week"].min() - pd.Timedelta(days=3), x1=fut["week"].max() + pd.Timedelta(days=3),
                      fillcolor="#F3F5F8", line_width=0, layer="below", annotation_text="future",
                      annotation_position="top left")
    fig.update_layout(yaxis_title="Complaints per week")
    ui.chart(ui.style(fig, height=380))
    with st.expander("Forecast table"):
        st.dataframe(g[["week", "actual", "forecast", "lower", "upper", "is_holdout"]]
                     .round({"actual": 2, "forecast": 2, "lower": 2, "upper": 2}),
                     hide_index=True, width="stretch",
                     column_config={"week": st.column_config.DateColumn("Week starting", format="YYYY-MM-DD"),
                                    "is_holdout": "Holdout week"})

st.divider()
st.subheader("Spike alerts")
alerts = data.cached(data.spike_alerts, src)
if alerts.empty:
    if fc.empty:
        ui.no_data("spike_alerts", "spike alerts")
    else:
        st.info("The latest forecast run raised no spike alerts.")
else:
    n_active = int(alerts["active"].sum())
    st.caption(f"{len(alerts):,} alerts; {n_active} active (in the last {data.RECENT_ALERT_WEEKS} weeks of the "
               "latest forecast window). Ratio is actual weekly complaints divided by the interval upper bound.")
    st.dataframe(alerts[["component", "week", "actual", "upper", "ratio", "active", "run_id"]]
                 .round({"actual": 2, "upper": 2, "ratio": 2}),
                 hide_index=True, width="stretch",
                 column_config={"week": st.column_config.DateColumn("Week starting", format="YYYY-MM-DD"),
                                "ratio": st.column_config.NumberColumn("Ratio", format="%.2f"),
                                "active": "Active"})
