#!/usr/bin/env python3
"""Core analytics for GBM portfolio analysis and dashboarding."""

from __future__ import annotations

import math
import os
import re
import sys
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
LOCAL_LIBS = ROOT / ".pythonlibs"
if LOCAL_LIBS.exists():
    sys.path.insert(0, str(LOCAL_LIBS))
os.environ.setdefault("MPLCONFIGDIR", str(ROOT / ".mplconfig"))

import yfinance as yf


DEFAULT_BENCHMARKS = {
    "SPY": "SPY",
    "QQQ": "QQQ",
    "VT": "VT",
    "^MXX": "^MXX",
}
DEFAULT_BASE_CURRENCY = "MXN"
FX_TICKER = "MXN=X"
USD_CURRENCY = "USD"
MXN_CURRENCY = "MXN"

HEADER_ALIASES = {
    "emisora/fondo": "ticker",
    "ticker": "ticker",
    "títulos": "quantity",
    "titulos": "quantity",
    "cantidad": "quantity",
    "costo promedio": "average_cost",
    "precio promedio": "average_cost",
    "precio mercado": "market_price",
    "valor mercado": "market_value",
    "valor de mercado": "market_value",
    "p / m": "profit_loss",
    "% cartera": "portfolio_weight_reported",
    "asset name": "asset_name",
    "nombre": "asset_name",
}

SECTION_STOP_WORDS = {
    "",
    "emisora/fondo",
}

GBM_TO_YFINANCE = {
    "BRKB": "BRK-B",
    "ASURB": "ASURB.MX",
    "BOLSAA": "BOLSAA.MX",
    "CHDRAUIB": "CHDRAUIB.MX",
    "GAPB": "GAPB.MX",
    "OMAB": "OMAB.MX",
    "SIGMAFA": "SIGMAFA.MX",
    "WALMEX": "WALMEX.MX",
    "GBMALFABO": "GBMALFABO.MX",
    "GBMF2BF": "GBMF2BF.MX",
}

NON_MARKET_SECTIONS = {"efectivo"}


@dataclass
class PortfolioResult:
    name: str
    holdings: pd.DataFrame
    value_series: pd.Series
    return_series: pd.Series
    metrics: pd.Series
    allocation: pd.DataFrame
    comparison: pd.DataFrame
    drawdown_series: pd.Series


def slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def clean_label(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def normalize_header(value: object) -> str:
    key = clean_label(value).lower()
    return HEADER_ALIASES.get(key, slugify(key))


def parse_number(value: object, percent: bool = False) -> float:
    if pd.isna(value):
        return np.nan
    text = str(value).strip()
    if not text or text == "-":
        return np.nan
    negative = text.startswith("-") or text.startswith("(")
    text = (
        text.replace("$", "")
        .replace(",", "")
        .replace("%", "")
        .replace("(", "")
        .replace(")", "")
        .replace(" ", "")
    )
    if not text:
        return np.nan
    number = float(text)
    if negative and number > 0:
        number *= -1
    if percent:
        number /= 100.0
    return number


def normalize_gbm_ticker(raw_ticker: object, section: str) -> str:
    ticker = clean_label(raw_ticker)
    ticker = ticker.replace("*", "").replace(".", "").replace("-", " ").strip()
    ticker = re.sub(r"\s+", " ", ticker)
    compact = ticker.replace(" ", "").upper()
    if compact in GBM_TO_YFINANCE:
        return GBM_TO_YFINANCE[compact]
    if compact.startswith("BI"):
        return compact
    if "nacional" in section.lower():
        return f"{compact}.MX"
    return compact


def infer_ticker_currency(ticker: str) -> str:
    if ticker.endswith(".MX") or ticker == "^MXX" or ticker.startswith("BI"):
        return MXN_CURRENCY
    return USD_CURRENCY


def read_gbm_holdings(source: Path | BytesIO, source_name: str | None = None) -> pd.DataFrame:
    raw = pd.read_excel(source, sheet_name=0, header=None)
    if source_name is not None:
        file_name = source_name
    elif isinstance(source, Path):
        file_name = source.name
    else:
        file_name = getattr(source, "name", "uploaded_portfolio.xlsx")
    portfolio_name = Path(file_name).stem
    records: list[dict[str, object]] = []
    current_section = "Unclassified"
    current_headers: list[str] | None = None

    for row in raw.itertuples(index=False, name=None):
        values = [clean_label(cell) for cell in row]
        non_empty = [value for value in values if value]
        if not non_empty:
            continue

        first = non_empty[0]
        if first.lower() == "emisora/fondo":
            current_headers = [normalize_header(cell) for cell in values]
            continue

        if len(non_empty) == 1 and first.lower() not in SECTION_STOP_WORDS:
            current_section = first
            continue

        if not current_headers:
            continue

        row_data = {
            current_headers[idx] if idx < len(current_headers) else f"col_{idx}": values[idx]
            for idx in range(len(values))
            if idx < len(current_headers) and current_headers[idx]
        }
        ticker = clean_label(row_data.get("ticker"))
        if not ticker:
            continue
        row_data["section"] = current_section
        row_data["source_file"] = file_name
        row_data["portfolio_name"] = portfolio_name
        records.append(row_data)

    df = pd.DataFrame(records)
    if df.empty:
        raise ValueError(f"No holdings detected in {file_name}")

    if "asset_name" not in df.columns:
        df["asset_name"] = df["ticker"]

    numeric_columns = {
        "quantity": False,
        "average_cost": False,
        "market_price": False,
        "market_value": False,
        "profit_loss": False,
        "portfolio_weight_reported": True,
    }
    for column, percent in numeric_columns.items():
        if column in df.columns:
            df[column] = df[column].map(lambda value: parse_number(value, percent=percent))

    df["original_ticker"] = df["ticker"]
    df["ticker"] = [
        normalize_gbm_ticker(raw_ticker=value, section=section)
        for value, section in zip(df["ticker"], df["section"], strict=False)
    ]
    lower_original = df["original_ticker"].str.replace(" ", "", regex=False).str.upper()
    df["is_market_asset"] = ~df["section"].str.lower().isin(NON_MARKET_SECTIONS)
    df["has_price_history"] = (
        df["is_market_asset"]
        & ~df["ticker"].str.startswith("BI")
        & ~lower_original.str.startswith("EFEC")
    )
    df["currency"] = df["ticker"].map(infer_ticker_currency)
    df["market_value"] = df["market_value"].fillna(0.0)
    df["quantity"] = df["quantity"].fillna(0.0)
    return df


def aggregate_portfolios(files: Iterable[Path]) -> dict[str, pd.DataFrame]:
    return {file_path.stem: read_gbm_holdings(file_path) for file_path in files}


def available_portfolio_files(search_dir: Path | None = None) -> list[Path]:
    base = search_dir or ROOT
    local = sorted(base.glob("*.xlsx"))
    downloads = sorted((Path.home() / "Downloads").glob("App_GBM_Detalle_Portafolio__*.xlsx"))
    seen: set[Path] = set()
    ordered: list[Path] = []
    for file_path in local + downloads:
        resolved = file_path.resolve()
        if resolved not in seen:
            seen.add(resolved)
            ordered.append(resolved)
    return ordered


def download_single_ticker(
    ticker: str,
    start: str | pd.Timestamp,
    end: str | pd.Timestamp | None = None,
    interval: str = "1d",
) -> pd.Series | None:
    for _ in range(3):
        try:
            history = yf.download(
                tickers=ticker,
                start=start,
                end=end,
                interval=interval,
                auto_adjust=True,
                progress=False,
                group_by="column",
                threads=False,
            )
        except Exception:
            continue
        if history.empty or "Close" not in history.columns:
            continue
        series = history["Close"].copy()
        if isinstance(series, pd.DataFrame):
            series = series.iloc[:, 0]
        if series.empty:
            continue
        series.index = pd.to_datetime(series.index).tz_localize(None)
        return series.rename(ticker)
    return None


def fetch_price_history(
    tickers: Iterable[str],
    start: str | pd.Timestamp,
    end: str | pd.Timestamp | None = None,
    interval: str = "1d",
) -> pd.DataFrame:
    closes: dict[str, pd.Series] = {}
    for ticker in sorted({ticker for ticker in tickers if ticker}):
        series = download_single_ticker(ticker, start=start, end=end, interval=interval)
        if series is not None:
            closes[ticker] = series
    if not closes:
        return pd.DataFrame()
    return pd.DataFrame(closes).sort_index().dropna(how="all")


def convert_price_frame(
    prices: pd.DataFrame,
    base_currency: str,
    fx_series: pd.Series | None,
) -> pd.DataFrame:
    if prices.empty:
        return prices
    converted = prices.copy()
    if base_currency == USD_CURRENCY:
        for column in converted.columns:
            if infer_ticker_currency(column) == MXN_CURRENCY and fx_series is not None:
                converted[column] = converted[column] / fx_series
    else:
        for column in converted.columns:
            if infer_ticker_currency(column) == USD_CURRENCY and fx_series is not None:
                converted[column] = converted[column] * fx_series
    return converted


def normalize_to_growth_of_one(frame_or_series: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    if isinstance(frame_or_series, pd.Series):
        valid = frame_or_series.dropna()
        return frame_or_series if valid.empty else frame_or_series / valid.iloc[0]
    return frame_or_series.apply(
        lambda series: series if series.dropna().empty else series / series.dropna().iloc[0]
    )


def calculate_drawdown(values: pd.Series) -> pd.Series:
    running_max = values.cummax()
    return values / running_max - 1.0


def compute_metrics(
    values: pd.Series,
    risk_free_rate: float = 0.0,
    trading_days: int = 252,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    values = values.dropna()
    returns = values.pct_change().dropna()
    if returns.empty:
        raise ValueError(f"Not enough history to compute returns for {values.name}.")
    total_return = values.iloc[-1] / values.iloc[0] - 1.0
    annualized_return = (1.0 + total_return) ** (trading_days / len(returns)) - 1.0
    volatility = returns.std(ddof=1) * math.sqrt(trading_days)
    sharpe_ratio = np.nan
    if volatility and not np.isclose(volatility, 0.0):
        sharpe_ratio = (annualized_return - risk_free_rate) / volatility
    drawdown = calculate_drawdown(values)
    metrics = pd.Series(
        {
            "start_date": values.index.min().date().isoformat(),
            "end_date": values.index.max().date().isoformat(),
            "total_value": float(values.iloc[-1]),
            "cumulative_return": float(total_return),
            "annualized_return": float(annualized_return),
            "volatility": float(volatility),
            "sharpe_ratio": float(sharpe_ratio) if not pd.isna(sharpe_ratio) else np.nan,
            "max_drawdown": float(drawdown.min()),
        },
        name=values.name,
    )
    return metrics, returns, drawdown


def compute_portfolio_value_series(
    holdings: pd.DataFrame,
    close_prices: pd.DataFrame,
    base_currency: str,
    fx_series: pd.Series | None,
) -> pd.Series:
    market_assets = holdings[holdings["is_market_asset"] & holdings["has_price_history"]].copy()
    if market_assets.empty:
        raise ValueError("No market assets with price history were found in the portfolio.")
    market_assets = market_assets[market_assets["ticker"].isin(close_prices.columns)]
    if market_assets.empty:
        raise ValueError("Price history could not be loaded for any market asset in the portfolio.")
    matrix = pd.DataFrame(index=close_prices.index)
    for row in market_assets.itertuples(index=False):
        matrix[row.ticker] = close_prices[row.ticker] * float(row.quantity)
    portfolio_value = matrix.sum(axis=1)
    static_holdings = holdings.loc[~holdings["has_price_history"], ["market_value", "currency"]]
    if not static_holdings.empty:
        static_series = pd.Series(0.0, index=close_prices.index)
        for row in static_holdings.itertuples(index=False):
            row_series = pd.Series(float(row.market_value), index=close_prices.index)
            if fx_series is not None:
                aligned_fx = fx_series.reindex(close_prices.index).ffill().bfill()
                if base_currency == USD_CURRENCY and row.currency == MXN_CURRENCY:
                    row_series = row_series / aligned_fx
                elif base_currency == MXN_CURRENCY and row.currency == USD_CURRENCY:
                    row_series = row_series * aligned_fx
            static_series = static_series + row_series
        portfolio_value = portfolio_value + static_series
    return portfolio_value.rename(holdings["portfolio_name"].iat[0])


def build_allocation_table(
    holdings: pd.DataFrame,
    base_currency: str,
    fx_spot: float | None,
) -> pd.DataFrame:
    allocation = holdings.copy()
    allocation["market_value_native"] = allocation["market_value"]
    if fx_spot and not np.isclose(fx_spot, 0.0):
        is_mxn = allocation["currency"] == MXN_CURRENCY
        price_columns = ["average_cost", "market_price", "market_value"]
        if base_currency == USD_CURRENCY:
            for column in price_columns:
                allocation.loc[is_mxn, column] = allocation.loc[is_mxn, column] / fx_spot
        else:
            for column in price_columns:
                allocation.loc[~is_mxn, column] = allocation.loc[~is_mxn, column] * fx_spot
    total_value = allocation["market_value"].sum()
    allocation["weight"] = np.where(total_value > 0, allocation["market_value"] / total_value, np.nan)
    allocation["display_currency"] = base_currency
    return allocation[
        [
            "section",
            "original_ticker",
            "ticker",
            "asset_name",
            "currency",
            "quantity",
            "average_cost",
            "market_price",
            "market_value",
            "weight",
        ]
    ].sort_values("market_value", ascending=False)


def compare_to_benchmarks(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.DataFrame,
    trading_days: int = 252,
) -> pd.DataFrame:
    rows = []
    for benchmark in benchmark_returns.columns:
        aligned = pd.concat(
            [portfolio_returns.rename("portfolio"), benchmark_returns[benchmark].rename("benchmark")],
            axis=1,
            join="inner",
        ).dropna()
        if aligned.empty:
            continue
        active = aligned["portfolio"] - aligned["benchmark"]
        benchmark_cumulative = (1.0 + aligned["benchmark"]).prod() - 1.0
        portfolio_cumulative = (1.0 + aligned["portfolio"]).prod() - 1.0
        tracking_error = active.std(ddof=1) * math.sqrt(trading_days)
        information_ratio = np.nan
        if tracking_error and not np.isclose(tracking_error, 0.0):
            information_ratio = (active.mean() * trading_days) / tracking_error
        rows.append(
            {
                "benchmark": benchmark,
                "excess_return": portfolio_cumulative - benchmark_cumulative,
                "tracking_error": tracking_error,
                "information_ratio": information_ratio,
                "correlation": aligned["portfolio"].corr(aligned["benchmark"]),
            }
        )
    return pd.DataFrame(rows).set_index("benchmark") if rows else pd.DataFrame()


def format_display_table(table: pd.DataFrame | pd.Series) -> pd.DataFrame:
    if isinstance(table, pd.Series):
        display = table.to_frame("value")
    else:
        display = table.copy()
    percent_like = {
        "cumulative_return",
        "annualized_return",
        "volatility",
        "max_drawdown",
        "excess_return",
        "tracking_error",
        "weight",
        "portfolio_weight_reported",
        "correlation",
    }
    currency_like = {"total_value", "average_cost", "market_price", "market_value"}
    for column in display.columns:
        if column in percent_like:
            display[column] = display[column].map(lambda value: f"{value:.2%}" if pd.notna(value) else "")
        elif column in currency_like:
            display[column] = display[column].map(lambda value: f"{value:,.2f}" if pd.notna(value) else "")
        elif pd.api.types.is_numeric_dtype(display[column]):
            display[column] = display[column].map(lambda value: f"{value:,.4f}" if pd.notna(value) else "")
    return display


def prepare_analysis(
    portfolio_frames: dict[str, pd.DataFrame],
    benchmark_map: dict[str, str],
    base_currency: str = DEFAULT_BASE_CURRENCY,
    risk_free_rate: float = 0.0,
    start_date: str | pd.Timestamp | None = None,
    end_date: str | pd.Timestamp | None = None,
    price_history: pd.DataFrame | None = None,
    fx_history: pd.Series | None = None,
) -> dict[str, object]:
    if not portfolio_frames:
        raise ValueError("No portfolio files were provided.")
    selected_benchmarks = benchmark_map or DEFAULT_BENCHMARKS
    asset_tickers = {
        ticker
        for holdings in portfolio_frames.values()
        for ticker in holdings.loc[holdings["is_market_asset"] & holdings["has_price_history"], "ticker"].tolist()
    }
    requested_tickers = asset_tickers | set(selected_benchmarks.values())
    if price_history is None:
        if start_date is None:
            start_date = pd.Timestamp.today().normalize() - pd.DateOffset(years=5)
        price_history = fetch_price_history(requested_tickers, start=start_date, end=end_date)
    if price_history.empty:
        raise RuntimeError("Price download failed; no market data was returned.")
    if fx_history is None:
        if start_date is None:
            start_date = price_history.index.min()
        fx_history = download_single_ticker(FX_TICKER, start=start_date, end=end_date)

    fx_series = None
    if fx_history is not None and not fx_history.empty:
        fx_series = fx_history.reindex(price_history.index).ffill().bfill()

    converted_prices = (
        convert_price_frame(price_history, base_currency=base_currency, fx_series=fx_series)
        .sort_index()
        .ffill()
    )
    benchmark_prices = converted_prices.rename(columns={value: key for key, value in selected_benchmarks.items()})
    benchmark_prices = benchmark_prices[[label for label in selected_benchmarks if label in benchmark_prices.columns]]

    benchmark_values = normalize_to_growth_of_one(benchmark_prices)
    benchmark_metrics: dict[str, pd.Series] = {}
    benchmark_returns: dict[str, pd.Series] = {}
    benchmark_drawdowns: dict[str, pd.Series] = {}
    for benchmark in benchmark_values.columns:
        metrics, returns, drawdown = compute_metrics(benchmark_values[benchmark], risk_free_rate=risk_free_rate)
        benchmark_metrics[benchmark] = metrics
        benchmark_returns[benchmark] = returns
        benchmark_drawdowns[benchmark] = drawdown

    benchmark_metrics_df = pd.DataFrame(benchmark_metrics).T if benchmark_metrics else pd.DataFrame()
    benchmark_returns_df = pd.DataFrame(benchmark_returns).dropna(how="all") if benchmark_returns else pd.DataFrame()
    benchmark_drawdown_df = pd.DataFrame(benchmark_drawdowns).dropna(how="all") if benchmark_drawdowns else pd.DataFrame()

    results: dict[str, PortfolioResult] = {}
    summary_rows = []
    normalized_series = benchmark_values.copy()
    drawdown_frame = benchmark_drawdown_df.copy()
    fx_spot = float(fx_series.dropna().iloc[-1]) if fx_series is not None and not fx_series.dropna().empty else None

    asset_price_frame = converted_prices[[column for column in asset_tickers if column in converted_prices.columns]]
    for portfolio_name, holdings in portfolio_frames.items():
        value_series = compute_portfolio_value_series(
            holdings=holdings,
            close_prices=asset_price_frame,
            base_currency=base_currency,
            fx_series=fx_series,
        ).dropna()
        metrics, returns, drawdown = compute_metrics(value_series, risk_free_rate=risk_free_rate)
        comparison = compare_to_benchmarks(returns, benchmark_returns_df)
        allocation = build_allocation_table(holdings, base_currency=base_currency, fx_spot=fx_spot)
        results[portfolio_name] = PortfolioResult(
            name=portfolio_name,
            holdings=holdings,
            value_series=value_series,
            return_series=returns,
            metrics=metrics,
            allocation=allocation,
            comparison=comparison,
            drawdown_series=drawdown,
        )
        normalized_series[portfolio_name] = normalize_to_growth_of_one(value_series)
        drawdown_frame[portfolio_name] = drawdown
        row = metrics.to_dict()
        for benchmark, values in comparison.iterrows():
            row[f"excess_return_vs_{benchmark}"] = values["excess_return"]
            row[f"tracking_error_vs_{benchmark}"] = values["tracking_error"]
            row[f"information_ratio_vs_{benchmark}"] = values["information_ratio"]
            row[f"correlation_vs_{benchmark}"] = values["correlation"]
        summary_rows.append(pd.Series(row, name=portfolio_name))

    summary_df = pd.DataFrame(summary_rows)
    return {
        "portfolio_results": results,
        "summary": summary_df,
        "benchmark_metrics": benchmark_metrics_df,
        "benchmark_returns": benchmark_returns_df,
        "benchmark_drawdowns": drawdown_frame,
        "cumulative_returns": normalized_series,
        "fx_history": fx_series.rename(FX_TICKER) if fx_series is not None else pd.Series(dtype=float),
        "base_currency": base_currency,
        "fx_spot": fx_spot,
    }


def export_analysis_to_excel(analysis: dict[str, object]) -> bytes:
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        format_display_table(analysis["summary"]).to_excel(writer, sheet_name="Portfolio Summary")
        format_display_table(analysis["benchmark_metrics"]).to_excel(writer, sheet_name="Benchmarks")
        portfolio_results: dict[str, PortfolioResult] = analysis["portfolio_results"]
        for name, result in portfolio_results.items():
            sheet_base = slugify(name)[:20] or "portfolio"
            format_display_table(result.metrics).to_excel(writer, sheet_name=f"{sheet_base}_metrics")
            format_display_table(result.comparison).to_excel(writer, sheet_name=f"{sheet_base}_compare")
            format_display_table(result.allocation).to_excel(writer, sheet_name=f"{sheet_base}_alloc", index=False)
            result.value_series.to_frame("value").to_excel(writer, sheet_name=f"{sheet_base}_value")
            result.return_series.to_frame("return").to_excel(writer, sheet_name=f"{sheet_base}_returns")
    output.seek(0)
    return output.read()
