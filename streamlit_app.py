#!/usr/bin/env python3
"""Interactive Streamlit dashboard for GBM portfolio analysis."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
LOCAL_LIBS = ROOT / ".pythonlibs"
if LOCAL_LIBS.exists():
    sys.path.insert(0, str(LOCAL_LIBS))

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from portfolio_core import (
    DEFAULT_BASE_CURRENCY,
    DEFAULT_BENCHMARKS,
    FX_TICKER,
    aggregate_portfolios,
    available_portfolio_files,
    export_analysis_to_excel,
    fetch_price_history,
    format_display_table,
    prepare_analysis,
)


st.set_page_config(page_title="Portfolio Monitor", page_icon=":bar_chart:", layout="wide")


def to_csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=True).encode("utf-8")


@st.cache_data(show_spinner=False)
def load_portfolios_cached(file_paths: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    return aggregate_portfolios([Path(path) for path in file_paths])


@st.cache_data(show_spinner=True, ttl=60 * 60 * 4)
def load_market_data_cached(
    file_paths: tuple[str, ...],
    benchmark_labels: tuple[str, ...],
    start_date: str,
) -> tuple[pd.DataFrame, pd.Series]:
    portfolios = load_portfolios_cached(file_paths)
    asset_tickers = {
        ticker
        for holdings in portfolios.values()
        for ticker in holdings.loc[holdings["is_market_asset"] & holdings["has_price_history"], "ticker"].tolist()
    }
    requested = asset_tickers | {DEFAULT_BENCHMARKS[label] for label in benchmark_labels}
    price_history = fetch_price_history(requested, start=start_date)
    fx_frame = fetch_price_history([FX_TICKER], start=start_date)
    fx_series = fx_frame[FX_TICKER] if FX_TICKER in fx_frame.columns else pd.Series(dtype=float)
    return price_history, fx_series


def build_line_chart(frame: pd.DataFrame, title: str, yaxis_title: str, percent: bool = False) -> go.Figure:
    plot_frame = frame.reset_index().rename(columns={"index": "Date"})
    plot_frame = plot_frame.melt(id_vars="Date", var_name="Series", value_name="Value").dropna()
    fig = px.line(plot_frame, x="Date", y="Value", color="Series", title=title)
    fig.update_layout(
        margin=dict(l=20, r=20, t=60, b=20),
        legend_title_text="Series",
        hovermode="x unified",
    )
    fig.update_yaxes(title_text=yaxis_title, tickformat=".1%" if percent else None)
    return fig


def build_allocation_chart(allocation: pd.DataFrame) -> go.Figure:
    top = allocation.head(12).copy()
    fig = px.bar(
        top.sort_values("weight"),
        x="weight",
        y="original_ticker",
        orientation="h",
        color="section",
        title="Allocation Breakdown",
    )
    fig.update_layout(margin=dict(l=20, r=20, t=60, b=20), legend_title_text="Section")
    fig.update_xaxes(tickformat=".1%")
    fig.update_yaxes(title_text="")
    return fig


st.title("Portfolio Monitoring Dashboard")
st.caption("Interactive benchmark comparison for GBM portfolio exports with currency-aware return series.")

candidate_files = available_portfolio_files()
if not candidate_files:
    st.error("No GBM Excel exports were found in this workspace or Downloads.")
    st.stop()

default_paths = tuple(str(path) for path in candidate_files[: min(5, len(candidate_files))])

with st.sidebar:
    st.header("Controls")
    selected_files = st.multiselect(
        "Portfolio files",
        options=[str(path) for path in candidate_files],
        default=list(default_paths),
        format_func=lambda value: Path(value).name,
    )
    if not selected_files:
        st.warning("Select at least one portfolio file.")
        st.stop()

    benchmark_options = list(DEFAULT_BENCHMARKS.keys())
    selected_benchmarks = st.multiselect(
        "Benchmarks",
        options=benchmark_options,
        default=benchmark_options,
        help="Use ^MXX as the IPC benchmark.",
    )
    if not selected_benchmarks:
        st.warning("Select at least one benchmark.")
        st.stop()

    base_currency = st.selectbox("Display currency", options=["MXN", "USD"], index=0)
    risk_free_rate_pct = st.number_input("Risk-free rate (%)", min_value=0.0, max_value=20.0, value=0.0, step=0.25)
    lookback_years = st.selectbox("Max history", options=[1, 2, 3, 5], index=3)

portfolio_frames = load_portfolios_cached(tuple(selected_files))
history_start = (pd.Timestamp.today().normalize() - pd.DateOffset(years=lookback_years)).date().isoformat()
price_history, fx_series = load_market_data_cached(tuple(selected_files), tuple(selected_benchmarks), history_start)
if price_history.empty:
    st.error("No market data was returned. Try again later.")
    st.stop()

available_start = price_history.index.min().date()
available_end = price_history.index.max().date()
selected_range = st.sidebar.date_input(
    "Date range",
    value=(available_start, available_end),
    min_value=available_start,
    max_value=available_end,
)
if isinstance(selected_range, tuple) and len(selected_range) == 2:
    start_date = pd.Timestamp(selected_range[0])
    end_date = pd.Timestamp(selected_range[1])
else:
    start_date = pd.Timestamp(available_start)
    end_date = pd.Timestamp(available_end)
if start_date >= end_date:
    st.error("Choose a valid date range.")
    st.stop()

filtered_prices = price_history.loc[(price_history.index >= start_date) & (price_history.index <= end_date)]
filtered_fx = fx_series.loc[(fx_series.index >= start_date) & (fx_series.index <= end_date)] if not fx_series.empty else fx_series
analysis = prepare_analysis(
    portfolio_frames=portfolio_frames,
    benchmark_map={label: DEFAULT_BENCHMARKS[label] for label in selected_benchmarks},
    base_currency=base_currency,
    risk_free_rate=risk_free_rate_pct / 100.0,
    start_date=start_date,
    end_date=end_date,
    price_history=filtered_prices,
    fx_history=filtered_fx,
)

portfolio_names = list(analysis["portfolio_results"].keys())
selected_portfolio = st.selectbox("Portfolio", options=portfolio_names)
portfolio_result = analysis["portfolio_results"][selected_portfolio]

summary_display = format_display_table(analysis["summary"])
comparison_display = format_display_table(portfolio_result.comparison)
allocation_display = format_display_table(portfolio_result.allocation)

metric_cols = st.columns(5)
metric_cols[0].metric("Total Return", f"{portfolio_result.metrics['cumulative_return']:.2%}")
metric_cols[1].metric("Annualized Return", f"{portfolio_result.metrics['annualized_return']:.2%}")
metric_cols[2].metric("Volatility", f"{portfolio_result.metrics['volatility']:.2%}")
metric_cols[3].metric("Sharpe Ratio", f"{portfolio_result.metrics['sharpe_ratio']:.2f}")
metric_cols[4].metric("Max Drawdown", f"{portfolio_result.metrics['max_drawdown']:.2%}")

chart_left, chart_right = st.columns((2, 1))
with chart_left:
    cumulative_subset = analysis["cumulative_returns"][selected_benchmarks + [selected_portfolio]]
    st.plotly_chart(
        build_line_chart(cumulative_subset, "Cumulative Returns", "Growth of 1.0"),
        use_container_width=True,
    )
with chart_right:
    st.plotly_chart(build_allocation_chart(portfolio_result.allocation), use_container_width=True)

drawdown_subset = analysis["benchmark_drawdowns"][selected_benchmarks + [selected_portfolio]]
st.plotly_chart(
    build_line_chart(drawdown_subset, "Drawdown", "Drawdown", percent=True),
    use_container_width=True,
)

tab1, tab2, tab3 = st.tabs(["Summary", "Benchmark Comparison", "Downloads"])
with tab1:
    st.subheader("Portfolio Summary")
    st.dataframe(summary_display, use_container_width=True)
    st.subheader("Allocation Detail")
    st.dataframe(allocation_display, use_container_width=True, hide_index=True)

with tab2:
    st.subheader(f"{selected_portfolio} vs Benchmarks")
    st.dataframe(comparison_display, use_container_width=True)
    st.subheader("Benchmark Metrics")
    st.dataframe(format_display_table(analysis["benchmark_metrics"]), use_container_width=True)

with tab3:
    st.subheader("Exports")
    c1, c2, c3 = st.columns(3)
    c1.download_button(
        "Download portfolio summary CSV",
        data=to_csv_bytes(analysis["summary"]),
        file_name="portfolio_summary.csv",
        mime="text/csv",
    )
    c2.download_button(
        "Download comparison CSV",
        data=to_csv_bytes(portfolio_result.comparison),
        file_name=f"{selected_portfolio}_comparison.csv",
        mime="text/csv",
    )
    c3.download_button(
        "Download Excel report",
        data=export_analysis_to_excel(analysis),
        file_name="portfolio_dashboard_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    st.caption(
        f"Display currency: {analysis['base_currency']}. "
        f"Latest MXN/USD rate used: {analysis['fx_spot']:.4f}" if analysis["fx_spot"] else f"Display currency: {analysis['base_currency']}."
    )
