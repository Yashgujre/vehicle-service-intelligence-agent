"""Shared Streamlit helpers: source resolution, status sidebar, empty states and chart styling."""

from __future__ import annotations

import re

import plotly.graph_objects as go
import streamlit as st

import data

PRIMARY = "#1F4E79"
ACCENT = "#C8553D"
BAND = "rgba(31, 78, 121, 0.15)"
SEQUENCE = ["#1F4E79", "#C8553D", "#2E8B57", "#8E6C8A", "#D4A017", "#4F9FBF", "#7A7A7A", "#A23B72"]


@st.cache_resource(ttl=data.CACHE_TTL_S, show_spinner=False)
def _source() -> data.Source:
    return data.resolve_source()


def source() -> data.Source:
    return _source()


def sidebar_status(src: data.Source) -> None:
    with st.sidebar:
        st.markdown("**Data source**")
        if src.mode == "live":
            st.caption(src.reason)
        elif src.mode == "demo":
            m = data.snapshot_manifest(src) or {}
            st.caption(f"{src.reason}. Snapshot exported {m.get('exported_at', 'n/a')}.")
        else:
            st.caption(src.reason)
        if src.readonly:
            st.caption("Read-only: review decisions are disabled.")
        st.caption(f"Queries are cached for {data.CACHE_TTL_S // 60} minutes.")
        if st.button("Refresh data", width="stretch"):
            data.clear_cache()
            _source.clear()
            st.rerun()


def no_data(table: str, what: str | None = None) -> None:
    cmd = data.COMMANDS.get(table, "")
    label = what or table.replace("_", " ")
    st.info(f"No data yet for {label}: run `{cmd}`." if cmd else f"No data yet for {label}.")


_MD_SPECIAL = re.compile(r"([\\`*_{}\[\]()#+\-.!|>~<$])")


def escape_md(text: str) -> str:
    return _MD_SPECIAL.sub(r"\\\1", text)


def style(fig: go.Figure, height: int = 360, legend: bool = True) -> go.Figure:
    fig.update_layout(height=height, margin=dict(l=60, r=20, t=60, b=50), colorway=SEQUENCE,
                      plot_bgcolor="white", paper_bgcolor="white", showlegend=legend,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title=None),
                      font=dict(size=12), title=dict(x=0, xanchor="left", font=dict(size=15)))
    fig.update_xaxes(showgrid=False, linecolor="#D0D4DA", automargin=True)
    fig.update_yaxes(gridcolor="#ECEFF3", zeroline=False, automargin=True)
    return fig


def chart(fig: go.Figure, key: str | None = None) -> None:
    st.plotly_chart(fig, width="stretch", theme=None, key=key,
                    config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})


def money(v: float | None, digits: int = 4) -> str:
    return "not yet measured" if v is None else f"${v:,.{digits}f}"


def pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1f}%"
