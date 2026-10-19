"""Overview: headline KPIs, weekly complaint volume and top components, with make / model year / date filters."""

import pandas as pd
import plotly.express as px
import streamlit as st
import ui

import data

src = ui.source()
st.title("Overview")
st.caption("Owner defect complaints from NHTSA, AI triage, human review and spike alerts in one view.")

k = data.cached(data.kpis, src)
ing = k["last_ingestion"]

finished = pd.Timestamp(ing["finished_at"]) if ing and ing.get("finished_at") is not None else None
r1 = st.columns(5, border=True)
r1[0].metric("Complaints", f"{k['complaints']:,}", help="Complaints stored in the database")
r1[1].metric("Last ingestion (UTC)", finished.strftime("%b %d %H:%M") if finished is not None else "none",
             help=(f"{finished:%Y-%m-%d %H:%M} UTC, run kind {ing['kind']}, ok {bool(ing['ok'])}"
                   if finished is not None else f"Run `{data.COMMANDS['ingestion_runs']}`"))
r1[2].metric("Rows inserted", f"{int(ing['rows_inserted'] or 0):,}" if ing else "n/a",
             help=(f"Last run: fetched {int(ing['rows_fetched'] or 0):,}, skipped as duplicates "
                   f"{int(ing['rows_skipped_duplicate'] or 0):,}") if ing else None)
r1[3].metric("Triaged", f"{k['triaged']:,}",
             help=f"Distinct complaints with a triage record ({k['triage_runs']:,} triage runs in total)")
r1[4].metric("Auto-routed", ui.pct(k["auto_routed_pct"]),
             help="Share of triaged complaints (latest record each) routed without human review")

r2 = st.columns(5, border=True)
r2[0].metric("Pending reviews", f"{k['pending_reviews']:,}")
r2[1].metric("Active spike alerts", f"{k['active_spike_alerts']:,}",
             help=f"Alerts in the last {data.RECENT_ALERT_WEEKS} weeks of the latest forecast window "
                  f"({k['spike_alerts_total']:,} alerts in total)")
r2[2].metric("LLM calls", f"{k['llm_calls']:,}", help="Rows in the LLM gateway call log")
r2[3].metric("LLM cost to date", ui.money(k["llm_cost_usd"], 2) if k["llm_calls"] else "n/a",
             help=f"Exact: {ui.money(k['llm_cost_usd'], 6)}" if k["llm_calls"] else "Not yet measured")
cpk = k["cost_per_1000_triaged_usd"]
r2[4].metric("Cost / 1,000 triaged", ui.money(cpk, 2) if cpk is not None else "n/a",
             help="Sum of triage_records.cost_usd divided by the number of triage runs, times 1,000"
                  + ("" if cpk is not None else ". Not yet measured."))

if k["triaged"] == 0:
    ui.no_data("triage_records", "triage")

st.divider()
comp = data.cached(data.complaints, src)
if comp.empty:
    ui.no_data("complaints")
    st.stop()

f1, f2, f3 = st.columns([2, 2, 3])
makes = f1.multiselect("Make", sorted(comp["make"].dropna().unique()), placeholder="All makes")
years = f2.multiselect("Model year", sorted(comp["model_year"].dropna().unique().tolist()),
                       placeholder="All model years")
dmin, dmax = comp["date_filed"].min().date(), comp["date_filed"].max().date()
rng = f3.date_input("Date filed", value=(dmin, dmax), min_value=dmin, max_value=dmax)
d_from, d_to = (rng if isinstance(rng, tuple) and len(rng) == 2 else (dmin, dmax))

view = data.filter_complaints(comp, makes, years, d_from, d_to)
st.caption(f"{len(view):,} complaints match the filters.")
if view.empty:
    st.warning("No complaints match these filters.")
    st.stop()

c1, c2 = st.columns([3, 2])
with c1:
    wk = data.weekly_counts(view)
    fig = px.area(wk, x="week", y="count", title="Complaints per week (week starting Monday)",
                  labels={"week": "", "count": "Complaints"})
    fig.update_traces(line_color=ui.PRIMARY, fillcolor=ui.BAND)
    ui.chart(ui.style(fig, legend=False))
with c2:
    top = data.top_components(view, 12).sort_values("count")
    fig = px.bar(top, x="count", y="component", orientation="h", title="Top components (NHTSA-coded)",
                 labels={"count": "Complaints", "component": ""})
    fig.update_traces(marker_color=ui.PRIMARY)
    ui.chart(ui.style(fig, legend=False))

with st.expander("Complaints by make and model year"):
    pivot = view.pivot_table(index="make", columns="model_year", values="odi_number", aggfunc="count",
                             fill_value=0)
    st.dataframe(pivot, width="stretch")

with st.expander("Ingestion runs"):
    runs = data.cached(data.ingestion_runs, src)
    if runs.empty:
        ui.no_data("ingestion_runs", "ingestion runs")
    else:
        st.dataframe(runs, width="stretch", hide_index=True)
