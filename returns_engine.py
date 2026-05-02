#!/usr/bin/env python3
"""Return engine with explicit methodology for holdings-based analytics."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from portfolio_core import MXN_CURRENCY, USD_CURRENCY, normalize_to_growth_of_one


@dataclass
class ReturnDiagnostics:
    methodology: dict[str, str]
    warnings: list[str]


def _convert_snapshot_value(value: float, base_currency: str, fx_spot: float | None) -> float:
    if base_currency == USD_CURRENCY and fx_spot and not np.isclose(fx_spot, 0.0):
        return float(value) / float(fx_spot)
    return float(value)


def compute_snapshot_cost_metrics(
    holdings: pd.DataFrame,
    base_currency: str,
    fx_spot: float | None,
) -> dict[str, float]:
    enriched = holdings.copy()
    enriched["cost_basis_value_mxn"] = enriched["quantity"].fillna(0.0) * enriched["average_cost"].fillna(0.0)
    total_market_value = _convert_snapshot_value(enriched["market_value"].fillna(0.0).sum(), base_currency, fx_spot)
    total_cost_basis = _convert_snapshot_value(enriched["cost_basis_value_mxn"].sum(), base_currency, fx_spot)
    unrealized_pnl = total_market_value - total_cost_basis
    absolute_return = np.nan
    if total_cost_basis and not np.isclose(total_cost_basis, 0.0):
        absolute_return = total_market_value / total_cost_basis - 1.0
    return {
        "snapshot_total_value": total_market_value,
        "snapshot_total_cost_basis": total_cost_basis,
        "snapshot_unrealized_pnl": unrealized_pnl,
        "snapshot_absolute_return": absolute_return,
    }


def compute_portfolio_value_series(
    holdings: pd.DataFrame,
    converted_prices: pd.DataFrame,
    base_currency: str,
    fx_series: pd.Series | None,
) -> pd.Series:
    market_assets = holdings[holdings["is_market_asset"] & holdings["has_price_history"]].copy()
    market_assets = market_assets[market_assets["ticker"].isin(converted_prices.columns)]
    if market_assets.empty:
        raise ValueError("No assets with market history are available for this portfolio.")

    asset_frame = converted_prices[sorted(market_assets["ticker"].unique())].copy()
    asset_frame = asset_frame.dropna(how="any")
    if asset_frame.empty:
        raise ValueError("No overlapping market history is available across the selected holdings.")

    quantity_map = market_assets.groupby("ticker")["quantity"].sum()
    holdings_matrix = asset_frame.mul(quantity_map, axis=1)
    portfolio_value = holdings_matrix.sum(axis=1)

    static_value_mxn = holdings.loc[~holdings["has_price_history"], "market_value"].fillna(0.0).sum()
    if static_value_mxn:
        static_series = pd.Series(static_value_mxn, index=portfolio_value.index, dtype=float)
        if base_currency == USD_CURRENCY and fx_series is not None:
            aligned_fx = fx_series.reindex(portfolio_value.index).ffill().bfill()
            static_series = static_series / aligned_fx
        portfolio_value = portfolio_value + static_series

    return portfolio_value.rename(holdings["portfolio_name"].iat[0]).dropna()


def compute_daily_returns(values: pd.Series) -> pd.Series:
    return values.pct_change().replace([np.inf, -np.inf], np.nan).dropna()


def compute_cagr(values: pd.Series, trading_days: int = 252) -> float:
    returns = compute_daily_returns(values)
    if returns.empty:
        return np.nan
    total_return = values.iloc[-1] / values.iloc[0] - 1.0
    return (1.0 + total_return) ** (trading_days / len(returns)) - 1.0


def compute_drawdown(values: pd.Series) -> pd.Series:
    running_max = values.cummax()
    return values / running_max - 1.0


def compute_reconstructed_return_metrics(values: pd.Series, trading_days: int = 252) -> dict[str, float]:
    returns = compute_daily_returns(values)
    cumulative_return = values.iloc[-1] / values.iloc[0] - 1.0 if len(values) else np.nan
    return {
        "daily_return_mean": returns.mean() if not returns.empty else np.nan,
        "cumulative_return": cumulative_return,
        "cagr": compute_cagr(values, trading_days=trading_days),
        "start_date": values.index.min().date().isoformat(),
        "end_date": values.index.max().date().isoformat(),
    }


def compute_xirr(
    cash_flows: list[tuple[pd.Timestamp, float]],
    guess: float = 0.1,
    max_iterations: int = 100,
    tolerance: float = 1e-6,
) -> float:
    if len(cash_flows) < 2:
        return np.nan
    dates = [pd.Timestamp(date).normalize() for date, _ in cash_flows]
    amounts = [float(amount) for _, amount in cash_flows]
    if not any(amount < 0 for amount in amounts) or not any(amount > 0 for amount in amounts):
        return np.nan
    t0 = dates[0]

    def npv(rate: float) -> float:
        return sum(amount / ((1.0 + rate) ** (((date - t0).days) / 365.25)) for date, amount in zip(dates, amounts, strict=False))

    rate = guess
    for _ in range(max_iterations):
        value = npv(rate)
        derivative = sum(
            -(((date - t0).days) / 365.25) * amount / ((1.0 + rate) ** ((((date - t0).days) / 365.25) + 1.0))
            for date, amount in zip(dates, amounts, strict=False)
        )
        if abs(derivative) < tolerance:
            break
        new_rate = rate - value / derivative
        if abs(new_rate - rate) < tolerance:
            return float(new_rate)
        rate = new_rate
    return np.nan


def build_synthetic_money_weighted_return(
    holdings: pd.DataFrame,
    value_series: pd.Series,
    base_currency: str,
    fx_spot: float | None,
) -> float:
    """
    Synthetic IRR only.
    This is not account-level MWR because GBM exports do not include dated cash flows.
    """
    snapshot = compute_snapshot_cost_metrics(holdings, base_currency=base_currency, fx_spot=fx_spot)
    total_cost_basis = snapshot["snapshot_total_cost_basis"]
    if not total_cost_basis or np.isclose(total_cost_basis, 0.0):
        return np.nan
    cash_flows = [
        (value_series.index.min(), -total_cost_basis),
        (value_series.index.max(), float(value_series.iloc[-1])),
    ]
    return compute_xirr(cash_flows)


def build_performance_attribution(
    holdings: pd.DataFrame,
    base_currency: str,
    fx_spot: float | None,
) -> pd.DataFrame:
    attribution = holdings.copy()
    attribution["cost_basis_value"] = attribution["quantity"].fillna(0.0) * attribution["average_cost"].fillna(0.0)
    if base_currency == USD_CURRENCY and fx_spot and not np.isclose(fx_spot, 0.0):
        attribution["cost_basis_value"] = attribution["cost_basis_value"] / fx_spot
        attribution["market_value"] = attribution["market_value"] / fx_spot
    attribution["pnl"] = attribution["market_value"] - attribution["cost_basis_value"]
    total_cost = attribution["cost_basis_value"].sum()
    attribution["contribution_to_return"] = np.where(
        total_cost > 0,
        attribution["pnl"] / total_cost,
        np.nan,
    )
    return attribution.sort_values("contribution_to_return", ascending=False)


def build_returns_diagnostics(has_real_cash_flows: bool = False) -> ReturnDiagnostics:
    methodology = {
        "absolute_return": "Current broker market value divided by current broker cost basis minus 1.",
        "daily_return": "Percentage change of reconstructed portfolio market value based on current holdings and adjusted close prices.",
        "cumulative_return": "Ending reconstructed value divided by starting reconstructed value minus 1.",
        "cagr": "Annualized geometric return from reconstructed daily holdings path.",
        "twr": "Holdings-based approximation only. True account-level TWR requires dated external cash flows.",
        "mwr_xirr": "Reported only as a synthetic buy-and-hold IRR when real dated cash flows are unavailable.",
    }
    warnings = []
    if not has_real_cash_flows:
        warnings.append(
            "GBM holdings exports do not include dated deposits, withdrawals, or trades, so account-level TWR and true MWR/XIRR cannot be computed exactly."
        )
        warnings.append(
            "Reconstructed returns represent the historical path of today's holdings, not the exact path of the brokerage account."
        )
        warnings.append(
            "Dividend and split adjustments are handled through adjusted market data from the price provider."
        )
    return ReturnDiagnostics(methodology=methodology, warnings=warnings)


def normalize_comparison_frame(series_map: dict[str, pd.Series]) -> pd.DataFrame:
    frame = pd.DataFrame(series_map).sort_index()
    return normalize_to_growth_of_one(frame).dropna(how="all")
