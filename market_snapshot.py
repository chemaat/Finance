#!/usr/bin/env python3
"""Daily market snapshot with graceful fallbacks."""

from __future__ import annotations

import datetime as dt

import numpy as np
import pandas as pd

from portfolio_core import fetch_price_history


SNAPSHOT_TICKERS = {
    "S&P 500": "SPY",
    "Nasdaq 100": "QQQ",
    "Dow Jones": "DIA",
    "Russell 2000": "IWM",
    "VIX": "^VIX",
    "IPC Mexico": "^MXX",
    "USD/MXN": "MXN=X",
    "Treasury 10Y": "^TNX",
}

ETF_WATCHLIST = {
    "XLK": "XLK",
    "XLF": "XLF",
    "XLE": "XLE",
    "XLI": "XLI",
    "XLV": "XLV",
    "XLP": "XLP",
    "EEM": "EEM",
    "BND": "BND",
    "AGG": "AGG",
}

EQUITY_WATCHLIST = {
    "AAPL": "AAPL",
    "MSFT": "MSFT",
    "NVDA": "NVDA",
    "AMZN": "AMZN",
    "META": "META",
    "GOOGL": "GOOGL",
    "TSLA": "TSLA",
    "JPM": "JPM",
    "BRK-B": "BRK-B",
    "NFLX": "NFLX",
    "AMD": "AMD",
    "AVGO": "AVGO",
    "WMT": "WMT",
    "COST": "COST",
    "ASURB.MX": "ASURB.MX",
    "WALMEX.MX": "WALMEX.MX",
}


def _build_daily_change_table(frame: pd.DataFrame, label_map: dict[str, str]) -> pd.DataFrame:
    rows = []
    for label, ticker in label_map.items():
        if ticker not in frame.columns:
            continue
        series = frame[ticker].dropna()
        if len(series) < 2:
            continue
        last = series.iloc[-1]
        prev = series.iloc[-2]
        rows.append(
            {
                "asset": label,
                "ticker": ticker,
                "last": float(last),
                "change_points": float(last - prev),
                "change_pct": float(last / prev - 1.0),
                "last_date": series.index[-1],
            }
        )
    return pd.DataFrame(rows)


def build_market_snapshot(end_date: pd.Timestamp | None = None) -> dict[str, object]:
    end = pd.Timestamp(end_date).normalize() if end_date is not None else pd.Timestamp.today().normalize()
    start = end - pd.DateOffset(days=14)
    universe = set(SNAPSHOT_TICKERS.values()) | set(ETF_WATCHLIST.values()) | set(EQUITY_WATCHLIST.values())
    history = fetch_price_history(universe, start=start, end=end + pd.Timedelta(days=1))
    if history.empty:
        return {
            "indices": pd.DataFrame(),
            "top_gainers": pd.DataFrame(),
            "top_losers": pd.DataFrame(),
            "etfs": pd.DataFrame(),
            "last_updated": None,
            "warnings": ["Market snapshot data provider returned no results."],
        }

    index_table = _build_daily_change_table(history, SNAPSHOT_TICKERS)
    etf_table = _build_daily_change_table(history, ETF_WATCHLIST)
    movers_table = _build_daily_change_table(history, EQUITY_WATCHLIST)
    movers_table = movers_table.sort_values("change_pct", ascending=False)
    last_updated = None
    if not index_table.empty:
        last_updated = index_table["last_date"].max()
    elif not history.empty:
        last_updated = history.dropna(how="all").index.max()

    return {
        "indices": index_table,
        "top_gainers": movers_table.head(5),
        "top_losers": movers_table.tail(5).sort_values("change_pct", ascending=True),
        "etfs": etf_table.sort_values("change_pct", ascending=False),
        "last_updated": last_updated,
        "warnings": [],
    }


def format_last_updated(last_updated: pd.Timestamp | None) -> str:
    if last_updated is None or pd.isna(last_updated):
        return "Unavailable"
    return pd.Timestamp(last_updated).strftime("%Y-%m-%d %H:%M UTC")
