# Dashboard

Streamlit dashboard for FR-8. Full design, measured load times and deploy steps are in
[`docs/architecture/dashboard.md`](../docs/architecture/dashboard.md).

```bash
source .venv/bin/activate
streamlit run app/streamlit_app.py                       # live database (data/vsia.db or DATABASE_URL)
VSIA_READONLY=1 streamlit run app/streamlit_app.py       # disable review writes
VSIA_DEMO_SNAPSHOT=1 streamlit run app/streamlit_app.py  # read app/demo_data/ (public deploy mode)
python scripts/export_demo_snapshot.py                   # refresh the demo snapshot from the live database
pytest tests/test_app_data.py
```

| File | Purpose |
|---|---|
| `streamlit_app.py` | Entrypoint: page config, `st.navigation`, sidebar status |
| `views/*.py` | One script per page: overview, triage, review, trends, evaluation, about |
| `data.py` | Cached, read-only queries (SQLAlchemy Core) and the demo-snapshot reader; the only write is `submit_review()` |
| `ui.py` | Shared helpers: data-source sidebar, empty states, Plotly styling |
| `demo_data/` | Redacted parquet snapshot for Streamlit Community Cloud (generated) |
| `requirements.txt` | Copy of `../requirements-streamlit.txt`; Community Cloud reads this one |

The page folder is `views/`, not `pages/`. A `pages/` folder would turn on Streamlit's legacy multipage
mode next to `st.navigation`.
