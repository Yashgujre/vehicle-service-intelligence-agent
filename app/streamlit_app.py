"""Vehicle Service Intelligence dashboard (FR-8). Run from the repo root:

    streamlit run app/streamlit_app.py

Data source: the project database (vsia.db.engine()), or the demo snapshot in app/demo_data/ when
VSIA_DEMO_SNAPSHOT=1 or no database is reachable. VSIA_READONLY=1 disables review writes.
"""

from __future__ import annotations

import sys
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
for p in (APP_DIR, APP_DIR.parent / "src"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import streamlit as st
import ui

st.set_page_config(page_title="Vehicle Service Intelligence", layout="wide", initial_sidebar_state="expanded")

pages = [
    st.Page(APP_DIR / "views" / "overview.py", title="Overview", url_path="overview", default=True),
    st.Page(APP_DIR / "views" / "triage.py", title="Triage queue", url_path="triage"),
    st.Page(APP_DIR / "views" / "review.py", title="Human review", url_path="review"),
    st.Page(APP_DIR / "views" / "trends.py", title="Trends and spikes", url_path="trends"),
    st.Page(APP_DIR / "views" / "evaluation.py", title="Evaluation and cost", url_path="evaluation"),
    st.Page(APP_DIR / "views" / "about.py", title="About", url_path="about"),
]
nav = st.navigation(pages)
with st.sidebar:
    st.markdown("### Vehicle Service Intelligence")
    st.caption("Defect intelligence for vehicle quality and service teams, on public NHTSA data.")
ui.sidebar_status(ui.source())
nav.run()
