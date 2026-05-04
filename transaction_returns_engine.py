#!/usr/bin/env python3
"""Transaction-ledger NAV, TWR, and MWR analytics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from returns_engine import compute_reconstructed_return_metrics, compute_xirr
from risk_engine import drawdown_series
from transaction_parser import ParsedPortfolioLedger


@dataclass
class TransactionAnalytics:
    nav_series: pd.Series
    twr_returns: pd.Series
    twr_index: pd.Series
    external_cash_flows: pd.Series
    position_matrix: pd.DataFrame
    asset_value_matrix: pd.DataFrame
    realized_lots: pd.DataFrame
    realized_summary: pd.DataFrame
    metrics: dict[str, float | str]
    warnings: list[str]


def _convert_cash_series(series: pd.Series, base_currency: str, fx_series: pd.Series | None) -> pd.Series:
    converted = series.astype(float).copy()
    if base_currency == "USD" and fx_series is not None and not fx_series.empty:
        aligned_fx = fx_series.reindex(converted.index).ffill().bfill()
        converted = converted / aligned_fx
    return converted


def _build_external_cash_flow_series(
    parsed: ParsedPortfolioLedger,
    index: pd.DatetimeIndex,
    base_currency: str,
    fx_series: pd.Series | None,
) -> pd.Series:
    cash = parsed.cash_flows[parsed.cash_flows["cash_flow_scope"] == "external"].copy()
    if cash.empty:
        return pd.Series(0.0, index=index, name="external_cash_flow")
    cash = cash.dropna(subset=["trade_date"])
    grouped = cash.groupby("trade_date")["cash_amount_mxn"].sum()
    grouped.index = pd.to_datetime(grouped.index)
    aligned = grouped.reindex(index, fill_value=0.0)
    return _convert_cash_series(aligned, base_currency=base_currency, fx_series=fx_series).rename("external_cash_flow")


def _build_position_matrix(parsed: ParsedPortfolioLedger, index: pd.DatetimeIndex) -> pd.DataFrame:
    trades = parsed.trades.dropna(subset=["trade_date"]).copy()
    if trades.empty:
        return pd.DataFrame(index=index)
    signed = (
        trades.groupby(["trade_date", "symbol"])["signed_quantity"]
        .sum()
        .unstack(fill_value=0.0)
        .sort_index()
    )
    signed.index = pd.to_datetime(signed.index)
    signed = signed.reindex(index, fill_value=0.0)
    return signed.cumsum().rename_axis(index="date")


def _build_asset_value_matrix(position_matrix: pd.DataFrame, price_frame: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    if position_matrix.empty:
        return pd.DataFrame(index=price_frame.index), []
    symbols = [column for column in position_matrix.columns if column in price_frame.columns]
    missing = sorted(set(position_matrix.columns) - set(symbols))
    if not symbols:
        return pd.DataFrame(index=price_frame.index), missing
    aligned_prices = price_frame[symbols].sort_index().ffill()
    aligned_positions = position_matrix[symbols].reindex(aligned_prices.index).ffill().fillna(0.0)
    return aligned_positions.mul(aligned_prices), missing


def _build_twr_returns(nav_series: pd.Series, external_cash_flows: pd.Series) -> pd.Series:
    if len(nav_series) < 2:
        return pd.Series(dtype=float, name=nav_series.name)
    prior_nav = nav_series.shift(1)
    twr = (nav_series - prior_nav - external_cash_flows) / prior_nav
    twr = twr.replace([np.inf, -np.inf], np.nan)
    # External flows on the first tracked date establish capital but do not define a return.
    return twr.iloc[1:].dropna().rename(nav_series.name)


def _build_twr_index(nav_series: pd.Series, twr_returns: pd.Series) -> pd.Series:
    if nav_series.empty:
        return nav_series
    growth = (1.0 + twr_returns).cumprod()
    growth = pd.concat([pd.Series([1.0], index=[nav_series.index[0]]), growth])
    growth = growth[~growth.index.duplicated(keep="last")]
    return growth.reindex(nav_series.index).ffill().rename(nav_series.name)


def _build_money_weighted_return(
    external_cash_flows: pd.Series,
    nav_series: pd.Series,
) -> float:
    dated_flows: list[tuple[pd.Timestamp, float]] = []
    for date, amount in external_cash_flows.items():
        if np.isclose(amount, 0.0):
            continue
        # Investor perspective: deposits into the brokerage are negative cash flows.
        dated_flows.append((pd.Timestamp(date), -float(amount)))
    if nav_series.empty:
        return np.nan
    dated_flows.append((pd.Timestamp(nav_series.index[-1]), float(nav_series.iloc[-1])))
    return compute_xirr(dated_flows)


def _build_realized_summary(closed_lots: pd.DataFrame) -> pd.DataFrame:
    if closed_lots.empty:
        return pd.DataFrame(columns=["symbol", "realized_pnl_mxn", "proceeds_mxn", "cost_basis_mxn", "matched_quantity"])
    return (
        closed_lots.groupby("symbol", as_index=False)
        .agg(
            realized_pnl_mxn=("realized_pnl_mxn", "sum"),
            proceeds_mxn=("proceeds_mxn", "sum"),
            cost_basis_mxn=("cost_basis_mxn", "sum"),
            matched_quantity=("matched_quantity", "sum"),
        )
        .sort_values("realized_pnl_mxn", ascending=False)
        .reset_index(drop=True)
    )


def build_transaction_analytics(
    parsed: ParsedPortfolioLedger,
    converted_prices: pd.DataFrame,
    base_currency: str,
    fx_series: pd.Series | None,
) -> TransactionAnalytics:
    warnings = list(parsed.diagnostics.get("warnings", []))
    incomplete_history = any("Sell quantity exceeds accumulated open lots" in warning for warning in warnings)
    trade_dates = parsed.trades["trade_date"].dropna()
    if trade_dates.empty:
        raise ValueError("The transaction ledger does not contain dated trades.")
    if converted_prices.empty:
        raise ValueError("No market history is available for the transaction ledger.")

    start_date = max(pd.Timestamp(trade_dates.min()).normalize(), pd.Timestamp(converted_prices.index.min()).normalize())
    price_frame = converted_prices.loc[converted_prices.index >= start_date].copy()
    if price_frame.empty:
        raise ValueError("Price history starts after the transaction ledger window.")

    position_matrix = _build_position_matrix(parsed, price_frame.index)
    asset_value_matrix, missing_symbols = _build_asset_value_matrix(position_matrix, price_frame)
    if missing_symbols:
        warnings.append(
            "No provider history was available for: " + ", ".join(missing_symbols) + ". They were excluded from reconstructed NAV."
        )
    if asset_value_matrix.empty:
        raise ValueError("No priced assets were available to reconstruct daily NAV from the transaction ledger.")

    nav_series = asset_value_matrix.sum(axis=1).rename(parsed.ledger["portfolio_name"].iat[0])
    external_cash_flows = _build_external_cash_flow_series(parsed, nav_series.index, base_currency=base_currency, fx_series=fx_series)
    twr_returns = _build_twr_returns(nav_series, external_cash_flows)
    twr_index = _build_twr_index(nav_series, twr_returns)
    drawdown = drawdown_series(twr_index)
    realized_summary = _build_realized_summary(parsed.closed_lots)

    reconstructed = compute_reconstructed_return_metrics(twr_index)
    net_external_capital = float(external_cash_flows.sum()) if not external_cash_flows.empty else 0.0
    ending_nav = float(nav_series.iloc[-1])
    realized_total = float(parsed.closed_lots["realized_pnl_mxn"].sum()) if not parsed.closed_lots.empty else 0.0
    unrealized_total = float(parsed.positions["unrealized_pnl_mxn"].sum()) if not parsed.positions.empty else 0.0
    mwr = np.nan if incomplete_history else _build_money_weighted_return(external_cash_flows, nav_series)

    metrics = {
        "start_date": nav_series.index.min().date().isoformat(),
        "end_date": nav_series.index.max().date().isoformat(),
        "ending_nav": ending_nav,
        "net_external_capital": net_external_capital,
        "twr_cumulative_return": reconstructed["cumulative_return"],
        "twr_cagr": reconstructed["cagr"],
        "mwr_xirr": mwr,
        "realized_pnl": realized_total,
        "unrealized_pnl": unrealized_total,
        "total_pnl": realized_total + unrealized_total,
        "max_drawdown_twr": float(drawdown.min()) if not drawdown.empty else np.nan,
        "ledger_history_complete": not incomplete_history,
    }

    if incomplete_history:
        warnings.append(
            "The transaction ledger appears incomplete because at least one sell predates the visible buy history. TWR is shown as a partial reconstructed series and XIRR is withheld."
        )

    return TransactionAnalytics(
        nav_series=nav_series,
        twr_returns=twr_returns,
        twr_index=twr_index,
        external_cash_flows=external_cash_flows,
        position_matrix=position_matrix,
        asset_value_matrix=asset_value_matrix,
        realized_lots=parsed.closed_lots.copy(),
        realized_summary=realized_summary,
        metrics=metrics,
        warnings=warnings,
    )
