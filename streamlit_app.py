#!/usr/bin/env python3
"""Premium institutional Streamlit UI for portfolio analytics."""

from __future__ import annotations

import math
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
from portfolio_registry import load_portfolio_registry
from transaction_parser import parse_portfolio_transactions, parsed_positions_to_holdings
from transaction_returns_engine import build_transaction_analytics
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
from theme_engine import PRODUCT_NAME, PRODUCT_TAGLINE, inject_global_styles
from ui_components import (
    apply_plotly_theme,
    dataframe_toolbar,
    filter_dataframe,
    paginate_dataframe,
    render_kpi_card,
    render_method_note,
    render_market_tape,
    render_shell_topbar,
    tone_from_value,
)


st.set_page_config(page_title=PRODUCT_NAME, page_icon=":chart_with_upwards_trend:", layout="wide")


def to_csv_bytes(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=True).encode("utf-8")


@st.cache_data(show_spinner=False)
def load_portfolio_datasets_cached(files: tuple[tuple[str, str, bytes], ...]) -> dict[str, dict[str, object]]:
    portfolios: dict[str, dict[str, object]] = {}
    for display_name, file_name, content in files:
        suffix = Path(file_name).suffix.lower()
        if suffix == ".csv":
            parsed = parse_portfolio_transactions(BytesIO(content), source_name=file_name)
            holdings = parsed_positions_to_holdings(parsed)
            parsed.ledger["portfolio_name"] = display_name
            holdings["portfolio_name"] = display_name
            portfolios[display_name] = {
                "holdings": holdings,
                "source_type": "transaction_csv",
                "parsed": parsed,
            }
        else:
            holdings = read_gbm_holdings(BytesIO(content), source_name=file_name)
            holdings["portfolio_name"] = display_name
            portfolios[display_name] = {
                "holdings": holdings,
                "source_type": "gbm_snapshot_excel",
                "parsed": None,
            }
    return portfolios


@st.cache_data(show_spinner=True, ttl=60 * 60 * 4)
def load_market_bundle_cached(
    portfolio_cache_key: tuple[tuple[str, bytes], ...],
    benchmark_map: tuple[tuple[str, str], ...],
    start_date: str,
) -> tuple[pd.DataFrame, pd.Series]:
    datasets = load_portfolio_datasets_cached(portfolio_cache_key)
    portfolios = {name: data["holdings"] for name, data in datasets.items()}
    return fetch_market_bundle(
        portfolio_frames=portfolios,
        benchmark_map=dict(benchmark_map),
        start_date=pd.Timestamp(start_date),
    )


@st.cache_data(show_spinner=True, ttl=60 * 30)
def load_market_snapshot_cached(as_of: str) -> dict[str, object]:
    return build_market_snapshot(pd.Timestamp(as_of))


def format_pct(value: float) -> str:
    return "N/A" if pd.isna(value) else f"{value:.2%}"


def format_num(value: float, digits: int = 2) -> str:
    return "N/A" if pd.isna(value) else f"{value:,.{digits}f}"


def format_currency(value: float) -> str:
    return "N/A" if pd.isna(value) else f"{value:,.2f}"


def format_timestamp_label(value: str | None) -> str:
    if not value:
        return "N/A"
    stamp = pd.Timestamp(value)
    if pd.isna(stamp):
        return "N/A"
    return stamp.tz_convert("America/Monterrey").strftime("%Y-%m-%d %H:%M %Z") if stamp.tzinfo else stamp.strftime("%Y-%m-%d %H:%M")


def slice_by_timeframe(frame: pd.DataFrame | pd.Series, timeframe: str) -> pd.DataFrame | pd.Series:
    if frame is None or len(frame) == 0:
        return frame
    end = frame.index.max()
    if timeframe == "1D":
        start = end - pd.DateOffset(days=2)
    elif timeframe == "1W":
        start = end - pd.DateOffset(weeks=1)
    elif timeframe == "1M":
        start = end - pd.DateOffset(months=1)
    elif timeframe == "3M":
        start = end - pd.DateOffset(months=3)
    elif timeframe == "YTD":
        start = pd.Timestamp(year=end.year, month=1, day=1)
    elif timeframe == "1Y":
        start = end - pd.DateOffset(years=1)
    else:
        return frame
    return frame.loc[frame.index >= start]


def build_line_chart(frame: pd.DataFrame, title: str, yaxis_title: str, theme: dict[str, str], percent: bool = False) -> go.Figure:
    plot_frame = frame.reset_index().rename(columns={"index": "Date"})
    plot_frame = plot_frame.melt(id_vars="Date", var_name="Series", value_name="Value").dropna()
    fig = px.line(plot_frame, x="Date", y="Value", color="Series", title=title)
    fig.update_traces(line=dict(width=2.4))
    fig.update_yaxes(title_text=yaxis_title, tickformat=".1%" if percent else None)
    fig.update_layout(hovermode="x unified")
    return apply_plotly_theme(fig, theme)


def build_area_chart(series: pd.Series, title: str, theme: dict[str, str], percent: bool = False) -> go.Figure:
    frame = series.dropna().reset_index()
    frame.columns = ["Date", "Value"]
    fig = px.area(frame, x="Date", y="Value", title=title)
    fig.update_traces(line=dict(width=2.4), fillcolor="rgba(77,163,255,0.20)")
    fig.update_yaxes(tickformat=".1%" if percent else None)
    return apply_plotly_theme(fig, theme)


def build_donut_chart(frame: pd.DataFrame, theme: dict[str, str]) -> go.Figure:
    fig = px.pie(
        frame.sort_values("weight", ascending=False).head(10),
        values="weight",
        names="original_ticker",
        hole=0.68,
        title="Allocation by Asset",
    )
    fig.update_traces(textinfo="label+percent", pull=[0.02] * min(len(frame), 10))
    return apply_plotly_theme(fig, theme)


def build_treemap(frame: pd.DataFrame, theme: dict[str, str]) -> go.Figure:
    local = frame.copy()
    local["label"] = local["original_ticker"]
    fig = px.treemap(
        local,
        path=[px.Constant("Portfolio"), "section", "label"],
        values="market_value",
        color="contribution_to_return",
        color_continuous_scale="RdYlGn",
        title="Holdings Heatmap",
    )
    return apply_plotly_theme(fig, theme)


def build_attribution_chart(frame: pd.DataFrame, theme: dict[str, str]) -> go.Figure:
    fig = px.bar(
        frame.sort_values("contribution_to_return", ascending=False),
        x="original_ticker",
        y="contribution_to_return",
        color="section",
        title="Performance Attribution",
    )
    fig.update_yaxes(tickformat=".1%")
    return apply_plotly_theme(fig, theme)


def build_correlation_heatmap(frame: pd.DataFrame, theme: dict[str, str]) -> go.Figure:
    corr = frame.corr()
    fig = px.imshow(
        corr,
        text_auto=".2f",
        color_continuous_scale="RdBu",
        zmin=-1,
        zmax=1,
        title="Correlation Matrix",
    )
    return apply_plotly_theme(fig, theme)


def build_snapshot_table(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    display = frame.drop(columns=["sparkline"], errors="ignore").copy()
    display["last"] = display["last"].map(lambda x: f"{x:,.2f}")
    display["change_points"] = display["change_points"].map(lambda x: f"{x:,.2f}")
    display["change_pct"] = display["change_pct"].map(lambda x: f"{x:.2%}")
    display["last_date"] = pd.to_datetime(display["last_date"]).dt.strftime("%Y-%m-%d")
    return display


def build_sector_proxy(frame: pd.DataFrame) -> pd.DataFrame:
    sector = frame.groupby("section", as_index=False)["market_value"].sum()
    sector["weight"] = sector["market_value"] / sector["market_value"].sum()
    return sector.rename(columns={"section": "sector_proxy"})


theme_mode = st.session_state.get("theme_mode", "Dark")
theme = inject_global_styles(theme_mode)

candidate_files = available_portfolio_files()
csv_candidates = sorted((Path.home() / "Downloads").glob("portfolio*.csv"))
registered_sources = load_portfolio_registry()
registry_map = {str(source.file_path): source.display_name for source in registered_sources}
registered_existing_sources = [source for source in registered_sources if source.exists]
candidate_files = list(dict.fromkeys(candidate_files + csv_candidates + [source.file_path for source in registered_existing_sources]))
default_paths = tuple(str(path) for path in candidate_files[: min(5, len(candidate_files))])
if registered_existing_sources:
    default_paths = tuple(str(source.file_path) for source in registered_existing_sources)

with st.sidebar:
    st.markdown("### Aurelia")
    st.caption("Premium multi-asset portfolio analytics")
    st.markdown('<div class="app-divider"></div>', unsafe_allow_html=True)

    nav_section = st.radio(
        "Workspace",
        options=[
            "Dashboard",
            "Portfolio Analytics",
            "Risk Metrics",
            "Benchmarking",
            "Holdings",
            "Market Snapshot",
            "Settings",
        ],
        index=0,
        label_visibility="collapsed",
    )

    st.markdown('<div class="app-divider"></div>', unsafe_allow_html=True)
    uploaded_files = st.file_uploader("Upload portfolio files", type=["xlsx", "csv"], accept_multiple_files=True)
    selected_files: list[str] = []
    if registered_sources:
        st.caption("System portfolios")
        st.markdown(
            "\n".join(
                [
                    f"- `{source.display_name}` {'`READY`' if source.exists else '`MISSING`'}"
                    for source in registered_sources
                ]
            )
        )
    if candidate_files:
        selected_files = st.multiselect(
            "Local portfolio files",
            options=[str(path) for path in candidate_files],
            default=list(default_paths),
            format_func=lambda value: registry_map.get(value, Path(value).name),
        )

    st.markdown('<div class="app-divider"></div>', unsafe_allow_html=True)
    st.caption("Portfolio controls")
    base_currency = st.selectbox("Display currency", options=["MXN", "USD"], index=0 if DEFAULT_BASE_CURRENCY == "MXN" else 1)
    risk_free_rate_pct = st.number_input("Risk-free rate (%)", min_value=0.0, max_value=25.0, value=0.0, step=0.25)
    lookback_years = st.selectbox("Max history", options=[1, 2, 3, 5], index=3)

if uploaded_files:
    portfolio_cache_key = tuple((Path(file.name).stem, file.name, file.getvalue()) for file in uploaded_files)
    portfolio_datasets = load_portfolio_datasets_cached(portfolio_cache_key)
elif selected_files:
    portfolio_cache_key = tuple(
        (
            registry_map.get(path, Path(path).stem),
            path,
            Path(path).read_bytes(),
        )
        for path in selected_files
    )
    portfolio_datasets = load_portfolio_datasets_cached(portfolio_cache_key)
else:
    render_shell_topbar("Unavailable", "Unavailable", "No portfolio loaded")
    st.markdown(
        """
        <div class="panel-card" style="padding:2rem 1.4rem 1.2rem 1.4rem;">
          <div class="section-title">Load a Portfolio</div>
          <div class="section-subtitle">Upload GBM holdings exports to launch the command center. Cloud deployments cannot access your local Downloads folder, so file upload is the preferred workflow.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.stop()

portfolio_names = list(portfolio_datasets.keys())
default_portfolio = portfolio_names[0]

top_left, top_mid, top_right, top_search = st.columns([2.3, 1.1, 1.2, 1.4])
with top_left:
    selected_portfolio = st.selectbox("Portfolio", options=portfolio_names, index=0)
with top_mid:
    primary_options = list(DEFAULT_BENCHMARKS.keys()) + ["Custom"]
    primary_benchmark_label = st.selectbox("Primary benchmark", options=primary_options, index=0)
with top_right:
    peer_labels = st.multiselect(
        "Peer benchmarks",
        options=list(DEFAULT_BENCHMARKS.keys()),
        default=["Nasdaq 100", "Total World", "IPC Mexico"],
    )
with top_search:
    holdings_search = st.text_input("Search ticker / holding", value="")

custom_benchmark_ticker = ""
if primary_benchmark_label == "Custom":
    custom_benchmark_ticker = st.text_input("Custom benchmark ticker", value="SPY").strip().upper()

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
date_col, tf_col = st.columns([2.2, 1.2])
with date_col:
    selected_range = st.date_input(
        "Date range",
        value=(available_start, available_end),
        min_value=available_start,
        max_value=available_end,
    )
with tf_col:
    timeframe = st.radio("Chart timeframe", options=["1M", "3M", "YTD", "1Y", "Max"], horizontal=True, index=3)

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

selected_dataset = portfolio_datasets[selected_portfolio]
holdings = selected_dataset["holdings"]
parsed_ledger = selected_dataset["parsed"]
source_type = selected_dataset["source_type"]
selected_registry_source = next((source for source in registered_sources if source.display_name == selected_portfolio), None)
snapshot_metrics = compute_snapshot_cost_metrics(holdings, base_currency=base_currency, fx_spot=fx_spot)
attribution = build_performance_attribution(holdings, base_currency=base_currency, fx_spot=fx_spot)
attribution["weight"] = attribution["market_value"] / attribution["market_value"].sum() if attribution["market_value"].sum() else 0.0
transaction_analytics = None
performance_series = pd.Series(dtype=float)

if parsed_ledger is not None:
    transaction_analytics = build_transaction_analytics(
        parsed=parsed_ledger,
        converted_prices=converted_prices,
        base_currency=base_currency,
        fx_series=filtered_fx,
    )
    portfolio_value_series = transaction_analytics.nav_series
    portfolio_returns = transaction_analytics.twr_returns
    performance_series = transaction_analytics.twr_index
    portfolio_drawdown = drawdown_series(performance_series)
    reconstructed_metrics = {
        "daily_return_mean": portfolio_returns.mean() if not portfolio_returns.empty else np.nan,
        "cumulative_return": transaction_analytics.metrics["twr_cumulative_return"],
        "cagr": transaction_analytics.metrics["twr_cagr"],
        "start_date": transaction_analytics.metrics["start_date"],
        "end_date": transaction_analytics.metrics["end_date"],
    }
    synthetic_mwr = transaction_analytics.metrics["mwr_xirr"]
else:
    portfolio_value_series = compute_portfolio_value_series(
        holdings=holdings,
        converted_prices=converted_prices,
        base_currency=base_currency,
        fx_series=filtered_fx,
    )
    portfolio_returns = compute_daily_returns(portfolio_value_series)
    performance_series = portfolio_value_series
    portfolio_drawdown = drawdown_series(performance_series)
    reconstructed_metrics = compute_reconstructed_return_metrics(portfolio_value_series)
    synthetic_mwr = build_synthetic_money_weighted_return(holdings, portfolio_value_series, base_currency=base_currency, fx_spot=fx_spot)

benchmark_prices = converted_prices.rename(columns={ticker: label for label, ticker in benchmark_selection.comparison_map.items()})
benchmark_series_map = {
    label: benchmark_prices[label].dropna()
    for label in benchmark_selection.comparison_map
    if label in benchmark_prices.columns
}
primary_benchmark_values = benchmark_series_map.get(benchmark_selection.primary_label, pd.Series(dtype=float))
primary_benchmark_returns = compute_daily_returns(primary_benchmark_values) if not primary_benchmark_values.empty else pd.Series(dtype=float)
risk_report = build_risk_report(
    values=performance_series,
    portfolio_returns=portfolio_returns,
    benchmark_returns=primary_benchmark_returns,
    risk_free_rate=risk_free_rate_pct / 100.0,
)

comparison_series_map = dict(benchmark_series_map)
comparison_series_map[selected_portfolio] = performance_series
normalized_comparison = normalize_to_growth_of_one(pd.DataFrame(comparison_series_map).sort_index()).dropna(how="all")
chart_comparison = slice_by_timeframe(normalized_comparison, timeframe)

benchmark_returns_df = pd.DataFrame({name: compute_daily_returns(series) for name, series in benchmark_series_map.items()}).dropna(how="all")
comparison_table = build_benchmark_comparison_table(
    portfolio_returns,
    benchmark_returns_df,
    benchmark_ticker_map=benchmark_selection.comparison_map,
)
period_table = build_period_return_table(comparison_series_map)
rolling_vol_frame = rolling_volatility(portfolio_returns).rename(selected_portfolio).to_frame()
rolling_vol_frame = slice_by_timeframe(rolling_vol_frame, timeframe)
rolling_beta_frame = pd.DataFrame()
if not primary_benchmark_returns.empty:
    rolling_beta_frame = rolling_beta(portfolio_returns, primary_benchmark_returns).rename(selected_portfolio).to_frame()
    rolling_beta_frame = slice_by_timeframe(rolling_beta_frame, timeframe)

has_real_cash_flows = bool(parsed_ledger is not None and not parsed_ledger.cash_flows.empty)
diagnostics = build_returns_diagnostics(has_real_cash_flows=has_real_cash_flows)
snapshot = load_market_snapshot_cached(end_date.date().isoformat())
last_updated_candidates = [portfolio_value_series.index.max()]
if snapshot["last_updated"] is not None:
    last_updated_candidates.append(pd.Timestamp(snapshot["last_updated"]))
last_updated = max(last_updated_candidates)
last_updated_label = last_updated.strftime("%Y-%m-%d %H:%M America/Monterrey")
render_shell_topbar(last_updated_label, benchmark_selection.primary_label, selected_portfolio)
render_market_tape(snapshot.get("market_tape", pd.DataFrame()), theme)

st.caption(f"Source: `{source_type}`")
if selected_registry_source is not None and selected_registry_source.exists:
    st.caption(
        " | ".join(
            [
                f"Registry file: `{selected_registry_source.file_path.name}`",
                f"Synced: `{format_timestamp_label(selected_registry_source.synced_at)}`",
                f"Source modified: `{format_timestamp_label(selected_registry_source.source_modified_at)}`",
                f"SHA256: `{(selected_registry_source.sha256 or '')[:12]}`",
            ]
        )
    )

daily_pnl = portfolio_value_series.diff().iloc[-1] if len(portfolio_value_series) > 1 else np.nan
daily_return = portfolio_returns.iloc[-1] if not portfolio_returns.empty else np.nan
absolute_return = snapshot_metrics["snapshot_absolute_return"]
holdings_cagr = reconstructed_metrics["cagr"]

kpi_cols = st.columns(6)
with kpi_cols[0]:
    render_kpi_card("Portfolio Value", format_currency(snapshot_metrics["snapshot_total_value"]), base_currency)
with kpi_cols[1]:
    render_kpi_card("Daily P&L", format_currency(daily_pnl), format_pct(daily_return), tone_from_value(daily_pnl))
with kpi_cols[2]:
    render_kpi_card("Absolute Return", format_pct(absolute_return), "vs open-position cost basis", tone_from_value(absolute_return))
with kpi_cols[3]:
    ledger_complete = bool(transaction_analytics is not None and transaction_analytics.metrics.get("ledger_history_complete"))
    label = "True TWR CAGR" if transaction_analytics is not None and ledger_complete else "Partial TWR CAGR" if transaction_analytics is not None else "Holdings CAGR"
    subtitle = "external flows adjusted" if transaction_analytics is not None else "reconstructed holdings path"
    render_kpi_card(label, format_pct(holdings_cagr), subtitle, tone_from_value(holdings_cagr))
with kpi_cols[4]:
    render_kpi_card("Alpha vs Primary", format_pct(risk_report.get("alpha", np.nan)), benchmark_selection.primary_label, tone_from_value(risk_report.get("alpha", np.nan)))
with kpi_cols[5]:
    render_kpi_card("Max Drawdown", format_pct(risk_report.get("max_drawdown", np.nan)), "peak-to-trough", tone_from_value(risk_report.get("max_drawdown", np.nan)))

if nav_section == "Dashboard":
    render_method_note(
        "This command center separates broker snapshot metrics from historical analytics. With a transaction CSV, Aurelia reconstructs daily NAV from dated trades, uses only external cash flows for TWR and XIRR, and keeps open-position cost metrics separate from account-level performance."
    )
    if transaction_analytics is not None:
        render_method_note(
            f"Transaction mode: net external capital {format_currency(transaction_analytics.metrics['net_external_capital'])} {base_currency}, "
            f"realized P&L {format_currency(transaction_analytics.metrics['realized_pnl'])}, "
            f"unrealized P&L {format_currency(transaction_analytics.metrics['unrealized_pnl'])}."
        )

    left, right = st.columns([2.0, 1.1])
    with left:
        st.plotly_chart(
            build_line_chart(chart_comparison, "Relative Performance Command Chart", "Growth of 1.0", theme),
            use_container_width=True,
        )
    with right:
        st.plotly_chart(build_donut_chart(attribution, theme), use_container_width=True)

    lower_left, lower_mid, lower_right = st.columns([1.4, 1.05, 1.05])
    with lower_left:
        drawdown_frame = pd.DataFrame(
            {selected_portfolio: portfolio_drawdown, **{label: drawdown_series(series) for label, series in benchmark_series_map.items()}}
        ).dropna(how="all")
        drawdown_frame = slice_by_timeframe(drawdown_frame, timeframe)
        st.plotly_chart(build_line_chart(drawdown_frame, "Drawdown Overlay", "Drawdown", theme, percent=True), use_container_width=True)
    with lower_mid:
        st.plotly_chart(build_area_chart(rolling_vol_frame.iloc[:, 0], "Rolling Volatility", theme, percent=True), use_container_width=True)
    with lower_right:
        if not rolling_beta_frame.empty:
            st.plotly_chart(build_area_chart(rolling_beta_frame.iloc[:, 0], "Rolling Beta", theme), use_container_width=True)

    movers_left, movers_right = st.columns([1.3, 1])
    with movers_left:
        dataframe_toolbar("Benchmark Intelligence", "Configurable peer set with period returns and relative performance.")
        st.dataframe(format_display_table(period_table), use_container_width=True)
    with movers_right:
        dataframe_toolbar("Market Movers", "Live daily snapshot of major indices and movers.")
        st.dataframe(build_snapshot_table(snapshot["top_gainers"]), use_container_width=True, hide_index=True)
        st.dataframe(build_snapshot_table(snapshot["top_losers"]), use_container_width=True, hide_index=True)

elif nav_section == "Portfolio Analytics":
    tabs = st.tabs(["Performance", "Attribution", "Methodology"])
    with tabs[0]:
        summary_frame = pd.DataFrame(
            [
                {
                    "portfolio": selected_portfolio,
                    "source_type": source_type,
                    "snapshot_total_value": snapshot_metrics["snapshot_total_value"],
                    "snapshot_total_cost_basis": snapshot_metrics["snapshot_total_cost_basis"],
                    "snapshot_unrealized_pnl": snapshot_metrics["snapshot_unrealized_pnl"],
                    "absolute_return": snapshot_metrics["snapshot_absolute_return"],
                    "reconstructed_cumulative_return": reconstructed_metrics["cumulative_return"],
                    "cagr": reconstructed_metrics["cagr"],
                    "xirr": synthetic_mwr,
                    "ledger_history_complete": transaction_analytics.metrics["ledger_history_complete"] if transaction_analytics is not None else np.nan,
                    "net_external_capital": transaction_analytics.metrics["net_external_capital"] if transaction_analytics is not None else np.nan,
                    "realized_pnl": transaction_analytics.metrics["realized_pnl"] if transaction_analytics is not None else np.nan,
                    "unrealized_pnl": transaction_analytics.metrics["unrealized_pnl"] if transaction_analytics is not None else snapshot_metrics["snapshot_unrealized_pnl"],
                }
            ]
        ).set_index("portfolio")
        st.dataframe(format_display_table(summary_frame), use_container_width=True)
        st.plotly_chart(build_line_chart(chart_comparison, "Portfolio vs Benchmark Curve", "Growth of 1.0", theme), use_container_width=True)
    with tabs[1]:
        left, right = st.columns([1.3, 1])
        with left:
            st.plotly_chart(build_treemap(attribution, theme), use_container_width=True)
        with right:
            st.plotly_chart(build_attribution_chart(attribution, theme), use_container_width=True)
    with tabs[2]:
        for warning in diagnostics.warnings:
            render_method_note(warning)
        if parsed_ledger is not None:
            render_method_note(
                f"Transaction parser diagnostics: {parsed_ledger.diagnostics['trade_count']} trades, "
                f"{parsed_ledger.diagnostics['cash_flow_count']} cash rows, "
                f"{parsed_ledger.diagnostics['open_lot_count']} open lots, "
                f"{parsed_ledger.diagnostics['closed_lot_count']} closed lots, "
                f"{parsed_ledger.diagnostics['quote_only_row_count']} quote-only rows."
            )
        if transaction_analytics is not None:
            for warning in transaction_analytics.warnings:
                render_method_note(warning)
        methodology_table = pd.DataFrame(
            [{"Metric": key, "Formula / Interpretation": value} for key, value in diagnostics.methodology.items()]
        )
        st.dataframe(methodology_table, use_container_width=True, hide_index=True)

elif nav_section == "Risk Metrics":
    risk_frame = pd.DataFrame([risk_report], index=[selected_portfolio])
    left, right = st.columns([1.1, 1.1])
    with left:
        dataframe_toolbar("Institutional Risk Panel", "Volatility, downside, drawdown, tail risk and recovery metrics.")
        st.dataframe(format_display_table(risk_frame), use_container_width=True)
    with right:
        corr_frame = pd.DataFrame({selected_portfolio: portfolio_returns, **benchmark_returns_df.to_dict(orient="series")}).dropna(how="all")
        if not corr_frame.empty:
            st.plotly_chart(build_correlation_heatmap(corr_frame, theme), use_container_width=True)
    bottom_left, bottom_right = st.columns(2)
    with bottom_left:
        st.plotly_chart(build_line_chart(slice_by_timeframe(pd.DataFrame({selected_portfolio: portfolio_drawdown}), timeframe), "Current Drawdown", "Drawdown", theme, percent=True), use_container_width=True)
    with bottom_right:
        st.plotly_chart(build_area_chart(rolling_vol_frame.iloc[:, 0], "Rolling Volatility", theme, percent=True), use_container_width=True)

elif nav_section == "Benchmarking":
    st.plotly_chart(build_line_chart(chart_comparison, "Benchmarking Matrix", "Growth of 1.0", theme), use_container_width=True)
    left, right = st.columns([1.2, 1])
    with left:
        dataframe_toolbar("Relative Performance", "Absolute and excess return, alpha, beta, tracking error and information ratio.")
        st.dataframe(format_display_table(comparison_table), use_container_width=True)
    with right:
        dataframe_toolbar("Period Returns", "YTD, trailing periods and since inception.")
        st.dataframe(format_display_table(period_table), use_container_width=True)

elif nav_section == "Holdings":
    filtered_holdings = filter_dataframe(attribution, holdings_search)
    page_size = st.selectbox("Rows per page", options=[10, 20, 50], index=1)
    total_pages = max(1, math.ceil(len(filtered_holdings) / page_size)) if len(filtered_holdings) else 1
    page_number = st.number_input("Page", min_value=1, max_value=total_pages, value=1, step=1)
    page_frame = paginate_dataframe(filtered_holdings, page_size=page_size, page_number=int(page_number) - 1)
    dataframe_toolbar("Holdings Grid", "Searchable holdings ledger with attribution and concentration metrics.")
    st.dataframe(
        format_display_table(
            page_frame[
                [
                    "section",
                    "original_ticker",
                    "ticker",
                    "quantity",
                    "average_cost",
                    "market_value",
                    "pnl",
                    "weight",
                    "contribution_to_return",
                ]
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )
    left, right = st.columns([1.1, 1])
    with left:
        st.plotly_chart(build_treemap(filtered_holdings if not filtered_holdings.empty else attribution, theme), use_container_width=True)
    with right:
        sector_proxy = build_sector_proxy(filtered_holdings if not filtered_holdings.empty else attribution)
        st.dataframe(format_display_table(sector_proxy.set_index("sector_proxy")), use_container_width=True)
    if parsed_ledger is not None:
        st.markdown('<div class="app-divider"></div>', unsafe_allow_html=True)
        ledger_tab, cash_tab, lots_tab, realized_tab = st.tabs(["Trades", "Cash Flows", "Open Lots", "Realized Lots"])
        with ledger_tab:
            trades_display = parsed_ledger.trades[
                [
                    "symbol",
                    "trade_date",
                    "transaction_type",
                    "quantity",
                    "trade_price_mxn",
                    "commission_mxn",
                    "net_cash_impact_mxn",
                ]
            ].copy()
            st.dataframe(format_display_table(trades_display), use_container_width=True, hide_index=True)
        with cash_tab:
            cash_display = parsed_ledger.cash_flows[
                [
                    "trade_date",
                    "transaction_type",
                    "cash_amount_mxn",
                    "cash_flow_scope",
                    "cash_flow_category",
                    "classification_reason",
                    "classification_confidence",
                    "comment",
                ]
            ].copy()
            st.dataframe(format_display_table(cash_display), use_container_width=True, hide_index=True)
        with lots_tab:
            lots_display = parsed_ledger.open_lots.copy()
            st.dataframe(format_display_table(lots_display), use_container_width=True, hide_index=True)
        with realized_tab:
            realized_display = parsed_ledger.closed_lots.copy()
            st.dataframe(format_display_table(realized_display), use_container_width=True, hide_index=True)

elif nav_section == "Market Snapshot":
    left, right = st.columns([1.25, 1])
    with left:
        dataframe_toolbar("Macro & Index Tape", "Last available trading session across US and Mexico instruments.")
        st.dataframe(build_snapshot_table(snapshot["indices"]), use_container_width=True, hide_index=True)
        st.dataframe(build_snapshot_table(snapshot["etfs"]), use_container_width=True, hide_index=True)
    with right:
        dataframe_toolbar("Gainers / Losers", "Cross-watchlist market movers.")
        st.dataframe(build_snapshot_table(snapshot["top_gainers"]), use_container_width=True, hide_index=True)
        st.dataframe(build_snapshot_table(snapshot["top_losers"]), use_container_width=True, hide_index=True)
        st.caption(f"Snapshot stamp: {format_last_updated(snapshot['last_updated'])}")

else:
    with st.sidebar:
        theme_mode = st.selectbox("Theme mode", options=["Dark", "Light"], index=0 if theme_mode == "Dark" else 1)
        st.session_state["theme_mode"] = theme_mode
        st.caption("Apply the theme selector and rerun for full-shell styling.")
    left, right = st.columns([1.1, 1])
    with left:
        dataframe_toolbar("Workspace Settings", "Portfolio analytics assumptions and visual system controls.")
        st.markdown(f"- Product: `{PRODUCT_NAME}`")
        st.markdown(f"- Tagline: `{PRODUCT_TAGLINE}`")
        st.markdown(f"- Base currency: `{base_currency}`")
        st.markdown(f"- Primary benchmark: `{benchmark_selection.primary_label}`")
        st.markdown(f"- Risk-free rate: `{risk_free_rate_pct:.2f}%`")
        st.markdown(f"- Last updated: `{last_updated_label}`")
        st.markdown("- Recommended ingestion: `data/portfolios/*.csv` + `data/portfolio_registry.json` in GitHub")
        if selected_registry_source is not None:
            st.markdown(f"- Registry portfolio: `{selected_registry_source.display_name}`")
            st.markdown(f"- Registry path: `{selected_registry_source.file_path.name}`")
            st.markdown(f"- Registry SHA256: `{selected_registry_source.sha256 or 'N/A'}`")
            st.markdown(f"- Last sync: `{format_timestamp_label(selected_registry_source.synced_at)}`")
    with right:
        export_payload = {
            "summary": pd.DataFrame(
                [
                    {
                        "portfolio": selected_portfolio,
                        "absolute_return": absolute_return,
                        "cagr": holdings_cagr,
                        "xirr": synthetic_mwr,
                        "alpha": risk_report.get("alpha"),
                        "beta": risk_report.get("beta"),
                    }
                ]
            ).set_index("portfolio"),
            "benchmark_metrics": period_table,
            "portfolio_results": {
                selected_portfolio: type(
                    "ExportResult",
                    (),
                    {
                        "metrics": pd.Series({**snapshot_metrics, **reconstructed_metrics, **risk_report}),
                        "comparison": comparison_table,
                        "allocation": attribution,
                        "value_series": performance_series,
                        "return_series": portfolio_returns,
                    },
                )()
            },
        }
        st.download_button(
            "Download Excel report",
            data=export_analysis_to_excel(export_payload),
            file_name="aurelia_portfolio_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        st.download_button(
            "Download holdings CSV",
            data=to_csv_bytes(attribution),
            file_name="aurelia_holdings.csv",
            mime="text/csv",
        )
