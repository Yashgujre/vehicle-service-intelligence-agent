"""About: architecture in one paragraph, the reusable pipeline pattern and data attribution."""

import streamlit as st
import ui

import data

src = ui.source()
st.title("About")

st.markdown(
    "**Vehicle Service Intelligence Agent** is an AI workflow system for vehicle quality and service teams, "
    "built on public NHTSA data. A Python service ingests owner defect complaints and recall campaigns into a "
    "SQL database (SQLite on a laptop, Postgres on a server), parses recall documents, and indexes them for "
    "hybrid retrieval. A triage agent redacts personal data, extracts structured fields, classifies the "
    "component and severity, links known recalls through retrieval with citation grounding, and scores a "
    "calibrated confidence: confident records are routed automatically, uncertain ones wait for a human "
    "reviewer whose decisions become new labels. A weekly forecasting pipeline tracked in MLflow predicts "
    "complaint volume per component and raises spike alerts. This dashboard reads the same database."
)

st.subheader("Pipeline pattern")
st.markdown(
    "1. **Ingest** public records on a schedule, idempotently.\n"
    "2. **Extract** structured fields from free text and documents with schema-validated LLM output.\n"
    "3. **Retrieve** related reference records (recalls) with hybrid search and cite them.\n"
    "4. **Agent triage with human review**: classify, score confidence, auto-route or queue for a reviewer.\n"
    "5. **Forecast** volume per category and flag spikes against prediction intervals.\n"
    "6. **Dashboard** for operations, review and evaluation."
)
st.markdown(
    "The pattern is domain-agnostic. Swapping the loaders, the taxonomy in `config/settings.yaml` and the "
    "prompts turns it into triage for insurance claims, customer support tickets or healthcare referrals."
)

st.subheader("Data source and attribution")
st.markdown(
    "Complaint and recall data come from the U.S. National Highway Traffic Safety Administration (NHTSA) "
    "public APIs and datasets ([nhtsa.gov](https://www.nhtsa.gov/)). Complaints are unverified owner reports. "
    "Complaint text shown here passes through PII redaction. This project is not affiliated with or endorsed "
    "by NHTSA."
)

st.subheader("Links")
st.markdown(
    "- Source repository: [github.com/Yashgujre/vehicle-service-intelligence-agent]"
    "(https://github.com/Yashgujre/vehicle-service-intelligence-agent)\n"
    "- Live demo: [Streamlit Community Cloud]"
    "(https://vehicle-service-intelligence-agent-nmwg8thucvttua8xzdtvi6.streamlit.app/)"
)

st.subheader("This deployment")
st.caption(f"Data source: {src.reason}. Read-only: {'yes' if src.readonly else 'no'}. "
           f"Query cache TTL: {data.CACHE_TTL_S} seconds.")
manifest = data.snapshot_manifest(src)
if manifest:
    st.caption(f"Demo snapshot exported {manifest.get('exported_at')}; row counts: "
               + ", ".join(f"{k} {v:,}" for k, v in manifest.get("rows", {}).items()))
