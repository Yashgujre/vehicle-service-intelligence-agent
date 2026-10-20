"""Shared Streamlit helpers: source resolution, status sidebar, empty states and chart styling."""

from __future__ import annotations

import re

import plotly.graph_objects as go
import streamlit as st

import data

# Mid-luminance colours stay legible on both the light and the dark theme.
PRIMARY = "#3A7BC8"
ACCENT = "#D9644A"
BAND = "rgba(58, 123, 200, 0.18)"
SHADE = "rgba(128, 128, 128, 0.12)"
NEUTRAL = "#8A8F98"
SEQUENCE = ["#3A7BC8", "#D9644A", "#3BA36B", "#A07CC0", "#D4A017", "#4FB0C6", "#8A8F98", "#C9558F"]


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


_MD_LINK = re.compile(r"([\\\[\]()!<>`])")


def defang_md(text: str) -> str:
    """Model output can be steered by the visitor: block links, images and code spans but keep bold and lists."""
    return _MD_LINK.sub(r"\\\1", text)


def style(fig: go.Figure, height: int = 360, legend: bool = True) -> go.Figure:
    """Layout only: backgrounds, font colour and grid come from the active Streamlit theme (light or dark)."""
    fig.update_layout(height=height, margin=dict(l=60, r=20, t=60, b=50), colorway=SEQUENCE, showlegend=legend,
                      legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0, title=None),
                      font=dict(size=12), title=dict(x=0, xanchor="left", font=dict(size=15)))
    fig.update_xaxes(showgrid=False, automargin=True)
    fig.update_yaxes(zeroline=False, automargin=True)
    return fig


def chart(fig: go.Figure, key: str | None = None) -> None:
    st.plotly_chart(fig, width="stretch", theme="streamlit", key=key,
                    config={"displaylogo": False, "modeBarButtonsToRemove": ["lasso2d", "select2d"]})


def money(v: float | None, digits: int = 4) -> str:
    return "not yet measured" if v is None else f"${v:,.{digits}f}"


def pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.1f}%"
