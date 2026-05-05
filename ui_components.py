#!/usr/bin/env python3
"""Reusable premium UI components for Streamlit."""

from __future__ import annotations

import math

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

from theme_engine import PRODUCT_NAME, PRODUCT_TAGLINE


def render_shell_topbar(last_updated: str, benchmark_label: str, portfolio_label: str) -> None:
    st.markdown(
        f"""
        <div class="shell-topbar">
          <div style="display:flex; align-items:center; justify-content:space-between; gap:1rem; flex-wrap:wrap;">
            <div class="brand-lockup">
              <div class="brand-mark">AP</div>
              <div>
                <p class="brand-title">{PRODUCT_NAME}</p>
                <p class="brand-subtitle">{PRODUCT_TAGLINE}</p>
              </div>
            </div>
            <div style="display:flex; gap:0.6rem; flex-wrap:wrap;">
              <span class="nav-chip">Portfolio: {portfolio_label}</span>
              <span class="nav-chip">Benchmark: {benchmark_label}</span>
              <span class="nav-chip">Last Updated: {last_updated}</span>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _sparkline_svg(points: list[float], tone: str, theme: dict[str, str]) -> str:
    if not points:
        return ""
    color = {
        "up": theme["success"],
        "down": theme["danger"],
        "flat": theme["accent"],
    }.get(tone, theme["accent"])
    width = 140.0
    height = 36.0
    min_v = min(points)
    max_v = max(points)
    spread = max(max_v - min_v, 1e-9)
    coords = []
    for idx, value in enumerate(points):
        x = (idx / max(len(points) - 1, 1)) * width
        y = height - ((value - min_v) / spread) * (height - 2.0) - 1.0
        coords.append(f"{x:.2f},{y:.2f}")
    return (
        f'<svg class="tape-sparkline" viewBox="0 0 {width:.0f} {height:.0f}" preserveAspectRatio="none">'
        f'<polyline fill="none" stroke="{color}" stroke-width="2.4" points="{" ".join(coords)}" />'
        "</svg>"
    )


def render_market_tape(frame: pd.DataFrame, theme: dict[str, str]) -> None:
    if frame.empty:
        return
    cards: list[str] = []
    for row in frame.itertuples(index=False):
        tone = tone_from_value(getattr(row, "change_pct", 0.0))
        tone_class = {
            "up": "value-up",
            "down": "value-down",
            "flat": "value-flat",
        }.get(tone, "value-flat")
        sparkline = _sparkline_svg(getattr(row, "sparkline", []) or [], tone, theme)
        cards.append(
            f"""
            <div class="tape-card">
              <div class="tape-label">{row.asset}</div>
              <div class="tape-price">{row.last:,.2f}</div>
              <div class="tape-change {tone_class}">{row.change_points:+,.2f} · {row.change_pct:+.2%}</div>
              {sparkline}
            </div>
            """
        )
    components.html(
        f"""
        <style>
          body {{
            margin: 0;
            background: transparent;
            color: {theme["text"]};
            font-family: "Inter", "SF Pro Display", "IBM Plex Sans", system-ui, sans-serif;
          }}
          .market-tape {{
            background: linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.018));
            border: 1px solid {theme["border"]};
            box-shadow: {theme["shadow"]};
            border-radius: 18px;
            padding: 0.9rem 1rem;
            overflow-x: auto;
            white-space: nowrap;
            box-sizing: border-box;
          }}
          .market-tape-track {{
            display: flex;
            gap: 0.8rem;
            min-width: max-content;
          }}
          .tape-card {{
            min-width: 184px;
            border: 1px solid {theme["border"]};
            border-radius: 16px;
            padding: 0.8rem 0.85rem;
            background: rgba(255,255,255,0.035);
            box-sizing: border-box;
          }}
          .tape-label {{
            font-size: 0.78rem;
            font-weight: 700;
            color: {theme["accent"]};
            margin-bottom: 0.3rem;
          }}
          .tape-price {{
            font-size: 1.15rem;
            font-weight: 700;
            color: {theme["text"]};
            line-height: 1.1;
          }}
          .tape-change {{
            font-size: 0.82rem;
            margin-top: 0.2rem;
          }}
          .value-up {{
            color: {theme["success"]};
          }}
          .value-down {{
            color: {theme["danger"]};
          }}
          .value-flat {{
            color: {theme["text"]};
          }}
          .tape-sparkline {{
            width: 100%;
            height: 36px;
            margin-top: 0.45rem;
          }}
        </style>
        <div class="market-tape">
          <div class="market-tape-track">
            {''.join(cards)}
          </div>
        </div>
        """,
        height=126,
    )


def render_kpi_card(label: str, value: str, footnote: str = "", tone: str = "flat") -> None:
    tone_class = {
        "up": "value-up",
        "down": "value-down",
        "flat": "value-flat",
    }.get(tone, "value-flat")
    st.markdown(
        f"""
        <div class="kpi-card">
          <div class="kpi-label">{label}</div>
          <div class="kpi-value {tone_class}">{value}</div>
          <div class="kpi-foot">{footnote}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_panel_header(title: str, subtitle: str = "") -> None:
    st.markdown(
        f"""
        <div class="panel-card">
          <div class="section-title">{title}</div>
          <div class="section-subtitle">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_method_note(text: str) -> None:
    st.markdown(f'<div class="method-note">{text}</div>', unsafe_allow_html=True)


def tone_from_value(value: float) -> str:
    if pd.isna(value):
        return "flat"
    if value > 0:
        return "up"
    if value < 0:
        return "down"
    return "flat"


def dataframe_toolbar(title: str, subtitle: str = "") -> None:
    st.markdown(
        f"""
        <div class="toolbar-card">
          <div class="section-title">{title}</div>
          <div class="section-subtitle">{subtitle}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def filter_dataframe(frame: pd.DataFrame, query: str) -> pd.DataFrame:
    if not query.strip():
        return frame
    mask = pd.Series(False, index=frame.index)
    q = query.lower().strip()
    for column in frame.columns:
        mask = mask | frame[column].astype(str).str.lower().str.contains(q, na=False)
    return frame.loc[mask]


def paginate_dataframe(frame: pd.DataFrame, page_size: int, page_number: int) -> pd.DataFrame:
    start = page_size * max(page_number, 0)
    end = start + page_size
    return frame.iloc[start:end]


def apply_plotly_theme(fig: go.Figure, theme: dict[str, str]) -> go.Figure:
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=theme["text"], family='"Inter", "IBM Plex Sans", system-ui'),
        margin=dict(l=24, r=24, t=58, b=24),
        hoverlabel=dict(
            bgcolor=theme["panel_strong"],
            font=dict(color=theme["text"]),
            bordercolor=theme["border"],
        ),
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            borderwidth=0,
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
    )
    fig.update_xaxes(showgrid=False, zeroline=False)
    fig.update_yaxes(showgrid=True, gridcolor=theme["grid"], zeroline=False)
    return fig
