#!/usr/bin/env python3
"""Institutional-style Streamlit dashboard for GBM portfolio analytics."""

from __future__ import annotations

import sys
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
LOCAL_LIBS = ROOT / ".pythonlibs"
if LOCAL_LIBS.exists():
    sys.path.insert(0, str(LOCAL_LIBS))

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from benchmark_engine import (
    DEFAULT_BENCHMARKS,
    BenchmarkSelection,
    build_benchmark_comparison_table,
    build_benchmark_selection,
    build_period_return_table,
    fetch_market_bundle,
)
from market_snapshot import build_market_snapshot, format_last_updated
from portfolio_core import (
    DEFAULT_BASE_CURRENCY,
    available_portfolio_files,
    convert_price_frame,
    export_analysis_to_excel,
    format_display_table,
    normalize_to_growth_of_one,
    read_gbm_holdings,
)
from returns_engine import (
    build_performance_attribution,
    build_returns_diagnostics,
    build_synthetic_money_weighted_return,
    compute_daily_returns,
    compute_portfolio_value_series,
    compute_reconstructed_return_metrics,
    compute_snapshot_cost_metrics,
)
from risk_engine import build_risk_report, drawdown_series, rolling_beta, rolling_volatility


st.set_page_config(page_title="Portfolio Analytics", page_icon=":bar_chart:", layout="wide")


def to_csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=True).encode("utf-8")


@st.cache_data(show_spinner=False)
def load_uploaded_portfolios_cached(files: tuple[tuple[str, bytes], ...]) -> dict[str, pd.DataFrame]:
    portfolios: dict[str, pd.DataFrame] = {}
    for file_name, content in files:
        portfolios[Path(file_name).stem] = read_gbm_holdings(BytesIO(content), source_name=file_name)
    return portfolios


@st.cache_data(show_spinner=False)
def load_local_portfolios_cached(file_paths: tuple[str, ...]) -> dict[str, pd.DataFrame]:
    portfolios: dict[str, pd.DataFrame] = {}
    for file_path in file_paths:
        path = Path(file_path)
        portfolios[path.stem] = read_gbm_holdings(path)
    return portfolios


@st.cache_data(show_spinner=True, ttl=60 * 60 * 4)
def load_market_bundle_cached(
    portfolio_cache_key: tuple[tuple[str, bytes], ...],
    benchmark_map: tuple[tuple[str, str], ...],
    start_date: str,
) -> tuple[pd.DataFrame, pd.Series]:
    portfolios = load_uploaded_portfolios_cached(portfolio_cache_key)
    return fetch_market_bundle(
        portfolio_frames=portfolios,
        benchmark_map=dict(benchmark_map),
        start_date=pd.Timestamp(start_date),
    )


@st.cache_data(show_spinner=True, ttl=60 * 30)
def load_snapshot_cached(as_of: str) -> dict[str, object]:
    return build_market_snapshot(pd.Timestamp(as_of))


def format_pct(value: float) -> str:
    return "N/A" if pd.isna(value) else f"{value:.2%}"


def format_num(value: float, digits: int = 2) -> str:
    return "N/A" if pd.isna(value) else f"{value:,.{digits}f}"


def build_line_chart(frame: pd.DataFrame, title: str, yaxis_title: str, percent: bool = False) -> go.Figure:
    plot_frame = frame.reset_index().rename(columns={"index": "Date"})
    plot_frame = plot_frame.melt(id_vars="Date", var_name="Series", value_name="Value").dropna()
    fig = px.line(plot_frame, x="Date", y="Value", color="Series", title=title)
    fig.update_layout(margin=dict(l=20, r=20, t=60, b=20), hovermode="x unified")
    fig.update_yaxes(title_text=yaxis_title, tickformat=".1%" if percent else None)
    return fig


def build_treemap(attribution: pd.DataFrame) -> go.Figure:
    frame = attribution.copy()
    frame["label"] = frame["original_ticker"]
    fig = px.treemap(
        frame,
        path=[px.Constant("Portfolio"), "section", "label"],
        values="market_value",
        color="contribution_to_return",
        color_continuous_scale="RdYlGn",
        title="Holdings Heatmap / Attribution",
    )
    fig.update_layout(margin=dict(l=10, r=10, t=50, b=10))
    return fig


def build_allocation_bar(attribution: pd.DataFrame) -> go.Figure:
    top = attribution.sort_values("market_value", ascending=False).head(12).iloc[::-1]
    fig = px.bar(
        top,
        x="weight",
        y="original_ticker",
        orientation="h",
        color="section",
        title="Allocation Breakdown",
    )
    fig.update_xaxes(tickformat=".1%")
    fig.update_layout(margin=dict(l=20, r=20, t=60, b=20))
    return fig


def build_attribution_bar(attribution: pd.DataFrame) -> go.Figure:
    top = attribution.sort_values("contribution_to_return", ascending=False)
    fig = px.bar(
        top,
        x="original_ticker",
        y="contribution_to_return",
        color="section",
        title="Performance Attribution",
    )
    fig.update_yaxes(tickformat=".1%")
    fig.update_layout(margin=dict(l=20, r=20, t=60, b=20))
    return fig


def build_snapshot_table(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    display = frame.copy()
    display["last"] = display["last"].map(lambda x: f"{x:,.2f}")
    display["change_points"] = display["change_points"].map(lambda x: f"{x:,.2f}")
    display["change_pct"] = display["change_pct"].map(lambda x: f"{x:.2%}")
    display["last_date"] = pd.to_datetime(display["last_date"]).dt.strftime("%Y-%m-%d")
    return display


st.title("Portfolio Monitoring Dashboard")
st.caption("Institutional analytics for GBM holdings with explicit methodology, benchmarking, and market snapshot.")

candidate_files = available_portfolio_files()
default_paths = tuple(str(path) for path in candidate_files[: min(5, len(candidate_files))])

with st.sidebar:
    st.header("Controls")
    uploaded_files = st.file_uploader(
        "Upload GBM Excel files",
        type=["xlsx"],
        accept_multiple_files=True,
        help="Upload one or more GBM holdings exports.",
    )
    selected_files: list[str] = []
    if candidate_files:
        selected_files = st.multiselect(
            "Or use local files",
            options=[str(path) for path in candidate_files],
            default=list(default_paths),
            format_func=lambda value: Path(value).name,
        )

    primary_options = list(DEFAULT_BENCHMARKS.keys()) + ["Custom"]
    primary_benchmark_label = st.selectbox("Primary benchmark", options=primary_options, index=0)
    custom_benchmark_ticker = ""
    if primary_benchmark_label == "Custom":
        custom_benchmark_ticker = st.text_input("Custom benchmark ticker", value="SPY").strip().upper()

    peer_labels = st.multiselect(
        "Comparison benchmarks",
        options=list(DEFAULT_BENCHMARKS.keys()),
        default=["Nasdaq 100", "Total World", "IPC Mexico"],
    )
    base_currency = st.selectbox("Display currency", options=["MXN", "USD"], index=0 if DEFAULT_BASE_CURRENCY == "MXN" else 1)
    risk_free_rate_pct = st.number_input("Risk-free rate (%)", min_value=0.0, max_value=25.0, value=0.0, step=0.25)
    lookback_years = st.selectbox("Max history", options=[1, 2, 3, 5], index=3)

portfolio_frames: dict[str, pd.DataFrame] = {}
portfolio_cache_key: tuple[tuple[str, bytes], ...]
if uploaded_files:
    portfolio_cache_key = tuple((file.name, file.getvalue()) for file in uploaded_files)
    portfolio_frames = load_uploaded_portfolios_cached(portfolio_cache_key)
elif selected_files:
    portfolio_cache_key = tuple((path, Path(path).read_bytes()) for path in selected_files)
    portfolio_frames = load_local_portfolios_cached(tuple(selected_files))
else:
    st.error("Upload one or more GBM Excel exports to use the dashboard.")
    st.stop()

try:
    benchmark_selection: BenchmarkSelection = build_benchmark_selection(
        primary_label=primary_benchmark_label,
        peer_labels=peer_labels,
        custom_ticker=custom_benchmark_ticker,
    )
except ValueError as error:
    st.error(str(error))
    st.stop()

history_start = (pd.Timestamp.today().normalize() - pd.DateOffset(years=lookback_years)).date().isoformat()
price_history, fx_series = load_market_bundle_cached(
    portfolio_cache_key=portfolio_cache_key,
    benchmark_map=tuple(benchmark_selection.comparison_map.items()),
    start_date=history_start,
)
if price_history.empty:
    st.error("No market data was returned by the provider.")
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

filtered_prices = price_history.loc[(price_history.index >= start_date) & (price_history.index <= end_date)].copy()
filtered_fx = fx_series.loc[(fx_series.index >= start_date) & (fx_series.index <= end_date)].copy() if not fx_series.empty else pd.Series(dtype=float)
converted_prices = convert_price_frame(filtered_prices, base_currency=base_currency, fx_series=filtered_fx).sort_index().ffill()
fx_spot = float(filtered_fx.dropna().iloc[-1]) if not filtered_fx.empty and not filtered_fx.dropna().empty else None

benchmark_prices = converted_prices.rename(columns={ticker: label for label, ticker in benchmark_selection.comparison_map.items()})
benchmark_series_map = {
    label: benchmark_prices[label].dropna()
    for label in benchmark_selection.comparison_map
    if label in benchmark_prices.columns
}

portfolio_names = list(portfolio_frames.keys())
selected_portfolio = st.selectbox("Portfolio", options=portfolio_names)
holdings = portfolio_frames[selected_portfolio]

portfolio_value_series = compute_portfolio_value_series(
    holdings=holdings,
    converted_prices=converted_prices,
    base_currency=base_currency,
    fx_series=filtered_fx,
)
portfolio_returns = compute_daily_returns(portfolio_value_series)
portfolio_drawdown = drawdown_series(portfolio_value_series)
snapshot_metrics = compute_snapshot_cost_metrics(holdings, base_currency=base_currency, fx_spot=fx_spot)
reconstructed_metrics = compute_reconstructed_return_metrics(portfolio_value_series)
synthetic_mwr = build_synthetic_money_weighted_return(holdings, portfolio_value_series, base_currency=base_currency, fx_spot=fx_spot)
attribution = build_performance_attribution(holdings, base_currency=base_currency, fx_spot=fx_spot)
attribution["weight"] = attribution["market_value"] / attribution["market_value"].sum() if attribution["market_value"].sum() else 0.0

primary_benchmark_returns = pd.Series(dtype=float)
if benchmark_selection.primary_label in benchmark_series_map:
    primary_benchmark_values = normalize_to_growth_of_one(benchmark_series_map[benchmark_selection.primary_label]).dropna()
    primary_benchmark_returns = compute_daily_returns(primary_benchmark_values)
else:
    primary_benchmark_values = pd.Series(dtype=float)

risk_report = build_risk_report(
    values=portfolio_value_series,
    portfolio_returns=portfolio_returns,
    benchmark_returns=primary_benchmark_returns,
    risk_free_rate=risk_free_rate_pct / 100.0,
)

comparison_frame = dict(benchmark_series_map)
comparison_frame[selected_portfolio] = portfolio_value_series
normalized_comparison = normalize_to_growth_of_one(pd.DataFrame(comparison_frame).sort_index()).dropna(how="all")

benchmark_returns_df = pd.DataFrame({name: compute_daily_returns(series) for name, series in benchmark_series_map.items()}).dropna(how="all")
comparison_table = build_benchmark_comparison_table(
    portfolio_returns,
    benchmark_returns_df,
    benchmark_ticker_map=benchmark_selection.comparison_map,
)
period_table = build_period_return_table(comparison_frame)
rolling_vol = rolling_volatility(portfolio_returns).rename(selected_portfolio).to_frame()
rolling_beta_frame = pd.DataFrame()
if not primary_benchmark_returns.empty:
    rolling_beta_frame = rolling_beta(portfolio_returns, primary_benchmark_returns).rename(selected_portfolio).to_frame()

diagnostics = build_returns_diagnostics(has_real_cash_flows=False)
missing_tickers = sorted(
    {
        ticker
        for ticker in holdings.loc[holdings["is_market_asset"] & holdings["has_price_history"], "ticker"].tolist()
        if ticker not in converted_prices.columns
    }
)
snapshot = load_snapshot_cached(end_date.date().isoformat())
last_updated_candidates = [portfolio_value_series.index.max()]
if snapshot["last_updated"] is not None:
    last_updated_candidates.append(pd.Timestamp(snapshot["last_updated"]))
last_updated = max(last_updated_candidates)

st.caption(f"Last Updated: {last_updated.strftime('%Y-%m-%d %H:%M')} America/Monterrey")
if missing_tickers:
    st.warning(f"Missing market history for: {', '.join(missing_tickers)}. Metrics exclude those tickers from the reconstructed history.")
for warning in snapshot["warnings"]:
    st.warning(warning)

market_left, market_right = st.columns((2, 1))
with market_left:
    st.subheader("Market Snapshot")
    st.dataframe(build_snapshot_table(snapshot["indices"]), use_container_width=True, hide_index=True)
    st.caption(f"Market snapshot last updated: {format_last_updated(snapshot['last_updated'])}")
with market_right:
    st.subheader("Top Movers")
    gainers = build_snapshot_table(snapshot["top_gainers"])
    losers = build_snapshot_table(snapshot["top_losers"])
    st.markdown("`Top Gainers`")
    st.dataframe(gainers, use_container_width=True, hide_index=True)
    st.markdown("`Top Losers`")
    st.dataframe(losers, use_container_width=True, hide_index=True)

kpi_cols = st.columns(6)
kpi_cols[0].metric("Absolute Return", format_pct(snapshot_metrics["snapshot_absolute_return"]))
kpi_cols[1].metric("Holdings CAGR", format_pct(reconstructed_metrics["cagr"]))
kpi_cols[2].metric("Alpha vs Primary", format_pct(risk_report.get("alpha", np.nan)))
kpi_cols[3].metric("Beta vs Primary", format_num(risk_report.get("beta", np.nan)))
kpi_cols[4].metric("Sharpe Ratio", format_num(risk_report.get("sharpe_ratio", np.nan)))
kpi_cols[5].metric("Max Drawdown", format_pct(risk_report.get("max_drawdown", np.nan)))

with st.expander("Methodology and Assumptions", expanded=False):
    methodology_table = pd.DataFrame(
        [{"metric": key, "definition": value} for key, value in diagnostics.methodology.items()]
    )
    st.dataframe(methodology_table, use_container_width=True, hide_index=True)
    for warning in diagnostics.warnings:
        st.warning(warning)
    st.markdown(
        f"""
        Current dashboard conventions:
        - `Absolute Return` uses broker cost basis from the uploaded GBM file.
        - `Holdings CAGR`, daily return, drawdown, rolling beta and rolling volatility use a reconstructed historical path of today's holdings.
        - `Synthetic MWR/XIRR`: `{format_pct(synthetic_mwr)}`.
        - Dividends and splits are handled through adjusted market prices from the provider when available.
        """
    )

summary_tab, risk_tab, attribution_tab, downloads_tab = st.tabs(
    ["Executive Summary", "Risk & Benchmark", "Attribution", "Downloads"]
)

with summary_tab:
    summary_frame = pd.DataFrame(
        [
            {
                "portfolio": selected_portfolio,
                "last_updated": last_updated.strftime("%Y-%m-%d"),
                "snapshot_total_value": snapshot_metrics["snapshot_total_value"],
                "snapshot_total_cost_basis": snapshot_metrics["snapshot_total_cost_basis"],
                "snapshot_unrealized_pnl": snapshot_metrics["snapshot_unrealized_pnl"],
                "absolute_return": snapshot_metrics["snapshot_absolute_return"],
                "reconstructed_cumulative_return": reconstructed_metrics["cumulative_return"],
                "cagr": reconstructed_metrics["cagr"],
                "volatility": risk_report.get("volatility_annualized"),
                "sharpe_ratio": risk_report.get("sharpe_ratio"),
                "sortino_ratio": risk_report.get("sortino_ratio"),
                "max_drawdown": risk_report.get("max_drawdown"),
            }
        ]
    ).set_index("portfolio")
    st.dataframe(format_display_table(summary_frame), use_container_width=True)

    chart_left, chart_right = st.columns((2, 1))
    with chart_left:
        st.plotly_chart(build_line_chart(normalized_comparison, "Cumulative Returns", "Growth of 1.0"), use_container_width=True)
    with chart_right:
        st.plotly_chart(build_allocation_bar(attribution), use_container_width=True)

    drawdown_frame = pd.DataFrame(
        {selected_portfolio: portfolio_drawdown, **{label: drawdown_series(series) for label, series in benchmark_series_map.items()}}
    ).dropna(how="all")
    st.plotly_chart(build_line_chart(drawdown_frame, "Drawdown Curve", "Drawdown", percent=True), use_container_width=True)

with risk_tab:
    risk_frame = pd.DataFrame([risk_report], index=[selected_portfolio])
    st.subheader("Risk Report")
    st.dataframe(format_display_table(risk_frame), use_container_width=True)

    st.subheader("Performance vs Benchmarks")
    st.dataframe(format_display_table(comparison_table), use_container_width=True)

    st.subheader("Period Returns")
    st.dataframe(format_display_table(period_table), use_container_width=True)

    chart_left, chart_right = st.columns(2)
    with chart_left:
        if not rolling_vol.empty:
            st.plotly_chart(build_line_chart(rolling_vol, "Rolling Volatility (63D)", "Volatility", percent=True), use_container_width=True)
    with chart_right:
        if not rolling_beta_frame.empty:
            st.plotly_chart(build_line_chart(rolling_beta_frame, "Rolling Beta (63D)", "Beta"), use_container_width=True)

with attribution_tab:
    attr_left, attr_right = st.columns((2, 1))
    with attr_left:
        st.plotly_chart(build_treemap(attribution), use_container_width=True)
        st.plotly_chart(build_attribution_bar(attribution), use_container_width=True)
    with attr_right:
        sector_proxy = (
            attribution.groupby("section", as_index=False)["market_value"].sum().rename(columns={"section": "sector_proxy"})
        )
        sector_proxy["weight"] = sector_proxy["market_value"] / sector_proxy["market_value"].sum()
        st.subheader("Sector / Section Allocation")
        st.dataframe(format_display_table(sector_proxy.set_index("sector_proxy")), use_container_width=True)
        st.subheader("Holdings Detail")
        display_attr = attribution[
            [
                "section",
                "original_ticker",
                "quantity",
                "average_cost",
                "market_value",
                "pnl",
                "contribution_to_return",
            ]
        ].copy()
        st.dataframe(format_display_table(display_attr), use_container_width=True, hide_index=True)

with downloads_tab:
    export_payload = {
        "summary": summary_frame,
        "benchmark_metrics": period_table,
        "portfolio_results": {
            selected_portfolio: type(
                "ExportResult",
                (),
                {
                    "metrics": pd.Series({**snapshot_metrics, **reconstructed_metrics, **risk_report}),
                    "comparison": comparison_table,
                    "allocation": attribution,
                    "value_series": portfolio_value_series,
                    "return_series": portfolio_returns,
                },
            )()
        },
    }
    c1, c2, c3 = st.columns(3)
    c1.download_button(
        "Download summary CSV",
        data=to_csv_bytes(summary_frame),
        file_name="portfolio_summary.csv",
        mime="text/csv",
    )
    c2.download_button(
        "Download benchmark comparison CSV",
        data=to_csv_bytes(comparison_table),
        file_name="benchmark_comparison.csv",
        mime="text/csv",
    )
    c3.download_button(
        "Download Excel report",
        data=export_analysis_to_excel(export_payload),
        file_name="portfolio_dashboard_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
