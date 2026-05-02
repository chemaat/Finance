#!/usr/bin/env python3
"""Design tokens and theming helpers for the premium fintech dashboard."""

from __future__ import annotations

import streamlit as st


PRODUCT_NAME = "Aurelia Portfolio OS"
PRODUCT_TAGLINE = "Institutional portfolio intelligence for modern capital allocators."


THEMES = {
    "Dark": {
        "bg": "#08111f",
        "bg_alt": "#0d1728",
        "panel": "rgba(15, 24, 41, 0.82)",
        "panel_strong": "#111c30",
        "text": "#eef4ff",
        "muted": "#95a4bd",
        "border": "rgba(255,255,255,0.09)",
        "accent": "#4da3ff",
        "accent_soft": "rgba(77,163,255,0.14)",
        "success": "#3dd598",
        "danger": "#ff6b6b",
        "warning": "#ffbf69",
        "shadow": "0 24px 60px rgba(3, 12, 24, 0.45)",
        "grid": "rgba(255,255,255,0.06)",
    },
    "Light": {
        "bg": "#f4f7fb",
        "bg_alt": "#eaf0f8",
        "panel": "rgba(255,255,255,0.88)",
        "panel_strong": "#ffffff",
        "text": "#162033",
        "muted": "#607086",
        "border": "rgba(12, 26, 49, 0.08)",
        "accent": "#2667ff",
        "accent_soft": "rgba(38,103,255,0.10)",
        "success": "#0f9f6e",
        "danger": "#cf3648",
        "warning": "#cc8b23",
        "shadow": "0 18px 40px rgba(28, 49, 76, 0.10)",
        "grid": "rgba(12,26,49,0.06)",
    },
}


def get_theme(theme_mode: str) -> dict[str, str]:
    return THEMES.get(theme_mode, THEMES["Dark"])


def inject_global_styles(theme_mode: str) -> dict[str, str]:
    theme = get_theme(theme_mode)
    st.markdown(
        f"""
        <style>
        :root {{
            --bg: {theme['bg']};
            --bg-alt: {theme['bg_alt']};
            --panel: {theme['panel']};
            --panel-strong: {theme['panel_strong']};
            --text: {theme['text']};
            --muted: {theme['muted']};
            --border: {theme['border']};
            --accent: {theme['accent']};
            --accent-soft: {theme['accent_soft']};
            --success: {theme['success']};
            --danger: {theme['danger']};
            --warning: {theme['warning']};
            --shadow: {theme['shadow']};
            --grid: {theme['grid']};
            --radius-xl: 24px;
            --radius-lg: 18px;
            --radius-md: 14px;
            --font-stack: "Inter", "SF Pro Display", "IBM Plex Sans", system-ui, sans-serif;
        }}

        html, body, [class*="css"] {{
            font-family: var(--font-stack);
        }}

        .stApp {{
            background:
                radial-gradient(circle at top left, rgba(77,163,255,0.16), transparent 28%),
                radial-gradient(circle at top right, rgba(61,213,152,0.10), transparent 24%),
                linear-gradient(180deg, var(--bg-alt) 0%, var(--bg) 100%);
            color: var(--text);
        }}

        [data-testid="stSidebar"] {{
            background: linear-gradient(180deg, rgba(7, 15, 27, 0.94), rgba(10, 19, 33, 0.94));
            border-right: 1px solid var(--border);
        }}

        [data-testid="stSidebar"] * {{
            color: #eff4ff;
        }}

        [data-testid="stHeader"] {{
            background: transparent;
        }}

        section.main > div {{
            padding-top: 1.1rem;
        }}

        .shell-topbar {{
            background: linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
            border: 1px solid var(--border);
            box-shadow: var(--shadow);
            border-radius: var(--radius-xl);
            padding: 1.1rem 1.25rem;
            margin-bottom: 1.2rem;
            backdrop-filter: blur(18px);
        }}

        .brand-lockup {{
            display: flex;
            align-items: center;
            gap: 0.9rem;
        }}

        .brand-mark {{
            width: 44px;
            height: 44px;
            border-radius: 14px;
            background: linear-gradient(135deg, var(--accent), rgba(93, 203, 255, 0.9));
            box-shadow: 0 12px 28px rgba(77,163,255,0.28);
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: 700;
            color: white;
            letter-spacing: 0.08em;
        }}

        .brand-title {{
            font-size: 1.08rem;
            font-weight: 700;
            color: var(--text);
            margin: 0;
        }}

        .brand-subtitle {{
            font-size: 0.83rem;
            color: var(--muted);
            margin: 0.15rem 0 0 0;
        }}

        .nav-chip {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            border-radius: 999px;
            padding: 0.38rem 0.7rem;
            border: 1px solid var(--border);
            background: rgba(255,255,255,0.04);
            color: var(--muted);
            font-size: 0.78rem;
        }}

        .kpi-card {{
            background: linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.015));
            border: 1px solid var(--border);
            box-shadow: var(--shadow);
            border-radius: var(--radius-lg);
            padding: 1rem 1.05rem;
            min-height: 132px;
            backdrop-filter: blur(18px);
        }}

        .kpi-label {{
            color: var(--muted);
            font-size: 0.8rem;
            text-transform: uppercase;
            letter-spacing: 0.08em;
            margin-bottom: 0.8rem;
        }}

        .kpi-value {{
            color: var(--text);
            font-size: 2rem;
            font-weight: 700;
            line-height: 1;
            margin-bottom: 0.55rem;
        }}

        .kpi-foot {{
            color: var(--muted);
            font-size: 0.83rem;
        }}

        .value-up {{
            color: var(--success);
        }}

        .value-down {{
            color: var(--danger);
        }}

        .value-flat {{
            color: var(--text);
        }}

        .panel-card {{
            background: var(--panel);
            border: 1px solid var(--border);
            box-shadow: var(--shadow);
            border-radius: var(--radius-xl);
            padding: 1rem 1rem 0.4rem 1rem;
            backdrop-filter: blur(18px);
            margin-bottom: 1rem;
        }}

        .section-title {{
            font-size: 1.1rem;
            font-weight: 700;
            color: var(--text);
            margin: 0 0 0.15rem 0;
        }}

        .section-subtitle {{
            font-size: 0.85rem;
            color: var(--muted);
            margin: 0 0 0.9rem 0;
        }}

        .method-note {{
            border-left: 3px solid var(--accent);
            background: var(--accent-soft);
            border-radius: 12px;
            padding: 0.9rem 1rem;
            margin-bottom: 0.75rem;
            color: var(--text);
            font-size: 0.9rem;
        }}

        .status-badge {{
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.34rem 0.62rem;
            border-radius: 999px;
            font-size: 0.78rem;
            border: 1px solid var(--border);
            background: rgba(255,255,255,0.04);
            color: var(--muted);
        }}

        .toolbar-card {{
            background: var(--panel);
            border: 1px solid var(--border);
            border-radius: var(--radius-xl);
            padding: 0.85rem 1rem;
            box-shadow: var(--shadow);
            margin-bottom: 1rem;
        }}

        div[data-testid="stMetric"] {{
            background: transparent;
            border: none;
            padding: 0;
        }}

        div[data-testid="stDataFrame"] {{
            border-radius: 18px;
            overflow: hidden;
            border: 1px solid var(--border);
            background: rgba(255,255,255,0.02);
        }}

        div[data-testid="stDataFrame"] thead tr th {{
            position: sticky;
            top: 0;
            z-index: 5;
        }}

        .stTabs [data-baseweb="tab-list"] {{
            gap: 0.5rem;
            background: rgba(255,255,255,0.03);
            border: 1px solid var(--border);
            padding: 0.3rem;
            border-radius: 16px;
        }}

        .stTabs [data-baseweb="tab"] {{
            height: 42px;
            border-radius: 12px;
            color: var(--muted);
            padding-inline: 1rem;
        }}

        .stTabs [aria-selected="true"] {{
            background: linear-gradient(180deg, rgba(77,163,255,0.18), rgba(77,163,255,0.08));
            color: var(--text);
        }}

        .stSelectbox label, .stMultiSelect label, .stTextInput label, .stNumberInput label, .stDateInput label, .stFileUploader label {{
            color: var(--muted);
            font-size: 0.84rem;
            letter-spacing: 0.03em;
        }}

        .stButton button, .stDownloadButton button {{
            border-radius: 14px;
            border: 1px solid var(--border);
            background: linear-gradient(180deg, rgba(77,163,255,0.16), rgba(77,163,255,0.08));
            color: var(--text);
            box-shadow: none;
        }}

        .stButton button:hover, .stDownloadButton button:hover {{
            border-color: rgba(77,163,255,0.45);
            transform: translateY(-1px);
        }}

        .stAlert {{
            border-radius: 16px;
            border: 1px solid var(--border);
        }}

        .app-divider {{
            height: 1px;
            background: linear-gradient(90deg, transparent, var(--border), transparent);
            margin: 0.5rem 0 0.9rem 0;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
    return theme
