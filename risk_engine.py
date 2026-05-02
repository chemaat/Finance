#!/usr/bin/env python3
"""Institutional risk metrics for portfolio analytics."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd


TRADING_DAYS = 252


def annualized_volatility(returns: pd.Series, trading_days: int = TRADING_DAYS) -> float:
    return returns.std(ddof=1) * math.sqrt(trading_days) if not returns.empty else np.nan


def downside_deviation(returns: pd.Series, mar_daily: float = 0.0, trading_days: int = TRADING_DAYS) -> float:
    downside = np.minimum(returns - mar_daily, 0.0)
    return float(np.sqrt(np.mean(np.square(downside))) * math.sqrt(trading_days)) if len(downside) else np.nan


def sharpe_ratio(returns: pd.Series, risk_free_rate: float = 0.0, trading_days: int = TRADING_DAYS) -> float:
    vol = annualized_volatility(returns, trading_days=trading_days)
    if not vol or np.isclose(vol, 0.0):
        return np.nan
    return ((returns.mean() * trading_days) - risk_free_rate) / vol


def sortino_ratio(returns: pd.Series, risk_free_rate: float = 0.0, trading_days: int = TRADING_DAYS) -> float:
    mar_daily = risk_free_rate / trading_days
    downside = downside_deviation(returns, mar_daily=mar_daily, trading_days=trading_days)
    if not downside or np.isclose(downside, 0.0):
        return np.nan
    return ((returns.mean() * trading_days) - risk_free_rate) / downside


def drawdown_series(values: pd.Series) -> pd.Series:
    running_max = values.cummax()
    return values / running_max - 1.0


def max_drawdown(values: pd.Series) -> float:
    dd = drawdown_series(values)
    return float(dd.min()) if not dd.empty else np.nan


def current_drawdown(values: pd.Series) -> float:
    dd = drawdown_series(values)
    return float(dd.iloc[-1]) if not dd.empty else np.nan


def var_cvar(returns: pd.Series, confidence: float = 0.95) -> tuple[float, float]:
    if returns.empty:
        return np.nan, np.nan
    threshold = np.quantile(returns, 1.0 - confidence)
    tail = returns[returns <= threshold]
    cvar = tail.mean() if not tail.empty else np.nan
    return float(threshold), float(cvar) if not pd.isna(cvar) else np.nan


def beta_alpha(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
    risk_free_rate: float = 0.0,
    trading_days: int = TRADING_DAYS,
) -> tuple[float, float]:
    aligned = pd.concat([portfolio_returns, benchmark_returns], axis=1, join="inner").dropna()
    if aligned.empty:
        return np.nan, np.nan
    port = aligned.iloc[:, 0]
    bench = aligned.iloc[:, 1]
    variance = bench.var(ddof=1)
    if not variance or np.isclose(variance, 0.0):
        return np.nan, np.nan
    beta = port.cov(bench) / variance
    rf_daily = risk_free_rate / trading_days
    alpha_daily = (port.mean() - rf_daily) - beta * (bench.mean() - rf_daily)
    return float(beta), float(alpha_daily * trading_days)


def tracking_error(portfolio_returns: pd.Series, benchmark_returns: pd.Series, trading_days: int = TRADING_DAYS) -> float:
    aligned = pd.concat([portfolio_returns, benchmark_returns], axis=1, join="inner").dropna()
    if aligned.empty:
        return np.nan
    active = aligned.iloc[:, 0] - aligned.iloc[:, 1]
    return float(active.std(ddof=1) * math.sqrt(trading_days))


def information_ratio(portfolio_returns: pd.Series, benchmark_returns: pd.Series, trading_days: int = TRADING_DAYS) -> float:
    aligned = pd.concat([portfolio_returns, benchmark_returns], axis=1, join="inner").dropna()
    if aligned.empty:
        return np.nan
    active = aligned.iloc[:, 0] - aligned.iloc[:, 1]
    te = active.std(ddof=1) * math.sqrt(trading_days)
    if not te or np.isclose(te, 0.0):
        return np.nan
    return float((active.mean() * trading_days) / te)


def calmar_ratio(values: pd.Series, returns: pd.Series) -> float:
    mdd = abs(max_drawdown(values))
    if not mdd or np.isclose(mdd, 0.0):
        return np.nan
    cagr = (1.0 + returns).prod() ** (TRADING_DAYS / len(returns)) - 1.0 if not returns.empty else np.nan
    return float(cagr / mdd) if not pd.isna(cagr) else np.nan


def best_worst_day(returns: pd.Series) -> tuple[float, float]:
    if returns.empty:
        return np.nan, np.nan
    return float(returns.max()), float(returns.min())


def recovery_time(values: pd.Series) -> float:
    dd = drawdown_series(values)
    if dd.empty:
        return np.nan
    trough_date = dd.idxmin()
    peak_level = values.loc[:trough_date].max()
    recovery = values.loc[trough_date:]
    recovered = recovery[recovery >= peak_level]
    if recovered.empty:
        return np.nan
    return float((recovered.index[0] - trough_date).days)


def rolling_volatility(returns: pd.Series, window: int = 63) -> pd.Series:
    return returns.rolling(window).std(ddof=1) * math.sqrt(TRADING_DAYS)


def rolling_beta(portfolio_returns: pd.Series, benchmark_returns: pd.Series, window: int = 63) -> pd.Series:
    aligned = pd.concat([portfolio_returns.rename("portfolio"), benchmark_returns.rename("benchmark")], axis=1, join="inner").dropna()
    if aligned.empty:
        return pd.Series(dtype=float)
    cov = aligned["portfolio"].rolling(window).cov(aligned["benchmark"])
    var = aligned["benchmark"].rolling(window).var()
    return cov / var.replace(0.0, np.nan)


def build_risk_report(
    values: pd.Series,
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series | None = None,
    risk_free_rate: float = 0.0,
) -> dict[str, float]:
    report = {
        "volatility_annualized": annualized_volatility(portfolio_returns),
        "sharpe_ratio": sharpe_ratio(portfolio_returns, risk_free_rate=risk_free_rate),
        "sortino_ratio": sortino_ratio(portfolio_returns, risk_free_rate=risk_free_rate),
        "max_drawdown": max_drawdown(values),
        "current_drawdown": current_drawdown(values),
        "calmar_ratio": calmar_ratio(values, portfolio_returns),
        "downside_deviation": downside_deviation(portfolio_returns, mar_daily=risk_free_rate / TRADING_DAYS),
        "best_day": best_worst_day(portfolio_returns)[0],
        "worst_day": best_worst_day(portfolio_returns)[1],
        "recovery_time_days": recovery_time(values),
    }
    var95, cvar95 = var_cvar(portfolio_returns, confidence=0.95)
    report["var_95"] = var95
    report["cvar_95"] = cvar95
    if benchmark_returns is not None and not benchmark_returns.empty:
        aligned = pd.concat([portfolio_returns, benchmark_returns], axis=1, join="inner").dropna()
        if not aligned.empty:
            beta, alpha = beta_alpha(aligned.iloc[:, 0], aligned.iloc[:, 1], risk_free_rate=risk_free_rate)
            report.update(
                {
                    "beta": beta,
                    "alpha": alpha,
                    "correlation": aligned.iloc[:, 0].corr(aligned.iloc[:, 1]),
                    "tracking_error": tracking_error(aligned.iloc[:, 0], aligned.iloc[:, 1]),
                    "information_ratio": information_ratio(aligned.iloc[:, 0], aligned.iloc[:, 1]),
                }
            )
    return report
