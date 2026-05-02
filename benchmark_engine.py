#!/usr/bin/env python3
"""Benchmark selection and comparative performance engine."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from portfolio_core import DEFAULT_BASE_CURRENCY, FX_TICKER, fetch_price_history


DEFAULT_BENCHMARKS = {
    "S&P 500": "SPY",
    "Nasdaq 100": "QQQ",
    "Total World": "VT",
    "IPC Mexico": "^MXX",
    "Dow Jones": "DIA",
    "US Bonds": "BND",
    "Core Bonds": "AGG",
}

PERIOD_LABELS = {
    "YTD": lambda end: pd.Timestamp(year=end.year, month=1, day=1),
    "1M": lambda end: end - pd.DateOffset(months=1),
    "3M": lambda end: end - pd.DateOffset(months=3),
    "6M": lambda end: end - pd.DateOffset(months=6),
    "1Y": lambda end: end - pd.DateOffset(years=1),
}


@dataclass
class BenchmarkSelection:
    primary_label: str
    primary_ticker: str
    comparison_map: dict[str, str]


def build_benchmark_selection(primary_label: str, peer_labels: list[str], custom_ticker: str | None = None) -> BenchmarkSelection:
    selection_map = {label: DEFAULT_BENCHMARKS[label] for label in peer_labels if label in DEFAULT_BENCHMARKS}
    if primary_label in DEFAULT_BENCHMARKS:
        primary_ticker = DEFAULT_BENCHMARKS[primary_label]
        selection_map[primary_label] = primary_ticker
    else:
        primary_ticker = (custom_ticker or "").strip().upper()
        if not primary_ticker:
            raise ValueError("A custom benchmark ticker is required when selecting a custom benchmark.")
        selection_map[primary_label] = primary_ticker
    return BenchmarkSelection(primary_label=primary_label, primary_ticker=primary_ticker, comparison_map=selection_map)


def last_valid_date(series: pd.Series) -> pd.Timestamp | None:
    valid = series.dropna()
    return valid.index.max() if not valid.empty else None


def compute_period_return(values: pd.Series, start_date: pd.Timestamp, end_date: pd.Timestamp | None = None) -> float:
    if values.empty:
        return np.nan
    end = pd.Timestamp(end_date) if end_date is not None else values.dropna().index.max()
    if pd.isna(end):
        return np.nan
    subset = values.loc[:end].dropna()
    if subset.empty:
        return np.nan
    valid_start = subset.loc[subset.index >= start_date]
    if valid_start.empty:
        return np.nan
    start_value = valid_start.iloc[0]
    end_value = subset.iloc[-1]
    if not start_value or np.isclose(start_value, 0.0):
        return np.nan
    return float(end_value / start_value - 1.0)


def build_period_return_table(series_map: dict[str, pd.Series]) -> pd.DataFrame:
    rows = []
    for name, series in series_map.items():
        clean = series.dropna()
        if clean.empty:
            continue
        end = clean.index.max()
        row = {"series": name}
        for label, start_fn in PERIOD_LABELS.items():
            row[label] = compute_period_return(clean, start_fn(end), end)
        row["Since Inception"] = float(clean.iloc[-1] / clean.iloc[0] - 1.0)
        rows.append(row)
    return pd.DataFrame(rows).set_index("series") if rows else pd.DataFrame()


def build_benchmark_comparison_table(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.DataFrame,
    benchmark_ticker_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    from risk_engine import beta_alpha, information_ratio, tracking_error

    rows = []
    for label in benchmark_returns.columns:
        aligned = pd.concat(
            [portfolio_returns.rename("portfolio"), benchmark_returns[label].rename("benchmark")],
            axis=1,
            join="inner",
        ).dropna()
        if aligned.empty:
            continue
        port = aligned["portfolio"]
        bench = aligned["benchmark"]
        beta, alpha = beta_alpha(port, bench)
        portfolio_total = (1.0 + port).prod() - 1.0
        benchmark_total = (1.0 + bench).prod() - 1.0
        rows.append(
            {
                "benchmark": label,
                "benchmark_ticker": benchmark_ticker_map.get(label, label) if benchmark_ticker_map else label,
                "portfolio_return": portfolio_total,
                "benchmark_return": benchmark_total,
                "excess_return": portfolio_total - benchmark_total,
                "alpha": alpha,
                "beta": beta,
                "correlation": port.corr(bench),
                "tracking_error": tracking_error(port, bench),
                "information_ratio": information_ratio(port, bench),
            }
        )
    return pd.DataFrame(rows).set_index("benchmark") if rows else pd.DataFrame()


def build_requested_market_universe(
    portfolio_frames: dict[str, pd.DataFrame],
    benchmark_map: dict[str, str],
) -> set[str]:
    asset_tickers = {
        ticker
        for holdings in portfolio_frames.values()
        for ticker in holdings.loc[holdings["is_market_asset"] & holdings["has_price_history"], "ticker"].tolist()
    }
    return asset_tickers | set(benchmark_map.values())


def fetch_market_bundle(
    portfolio_frames: dict[str, pd.DataFrame],
    benchmark_map: dict[str, str],
    start_date: pd.Timestamp,
    end_date: pd.Timestamp | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    requested = build_requested_market_universe(portfolio_frames, benchmark_map)
    price_history = fetch_price_history(requested, start=start_date, end=end_date)
    fx_frame = fetch_price_history([FX_TICKER], start=start_date, end=end_date)
    fx_series = fx_frame[FX_TICKER] if FX_TICKER in fx_frame.columns else pd.Series(dtype=float)
    return price_history, fx_series
