#!/usr/bin/env python3
"""Robust parser for transaction-based portfolio exports."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from io import BytesIO, StringIO
from pathlib import Path

import numpy as np
import pandas as pd


RAW_COLUMNS = [
    "Symbol",
    "Current Price",
    "Date",
    "Time",
    "Change",
    "Open",
    "High",
    "Low",
    "Volume",
    "Trade Date",
    "Purchase Price",
    "Quantity",
    "Commission",
    "High Limit",
    "Low Limit",
    "Comment",
    "Transaction Type",
]

COLUMN_MAP = {
    "Symbol": "symbol",
    "Current Price": "current_price",
    "Date": "quote_date",
    "Time": "quote_time",
    "Change": "daily_change",
    "Open": "open_price",
    "High": "high_price",
    "Low": "low_price",
    "Volume": "volume",
    "Trade Date": "trade_date",
    "Purchase Price": "trade_price",
    "Quantity": "quantity",
    "Commission": "commission",
    "High Limit": "high_limit",
    "Low Limit": "low_limit",
    "Comment": "comment",
    "Transaction Type": "transaction_type",
}

CASH_SYMBOL = "$$CASH_TX"
BUY = "BUY"
SELL = "SELL"
DEPOSIT = "DEPOSIT"
WITHDRAWAL = "WITHDRAWAL"

INTERNAL_CASH_KEYWORDS = {
    "compra": "trade_funding",
    "venta": "trade_settlement",
    "comision": "trade_fee",
    "commission": "trade_fee",
    "cuadre": "adjustment",
    "fee": "trade_fee",
}


@dataclass
class ParsedPortfolioLedger:
    ledger: pd.DataFrame
    trades: pd.DataFrame
    cash_flows: pd.DataFrame
    open_lots: pd.DataFrame
    positions: pd.DataFrame
    diagnostics: dict[str, object]


def parsed_positions_to_holdings(parsed: ParsedPortfolioLedger) -> pd.DataFrame:
    if parsed.positions.empty:
        return pd.DataFrame(
            columns=[
                "ticker",
                "original_ticker",
                "asset_name",
                "section",
                "quantity",
                "average_cost",
                "market_price",
                "market_value",
                "profit_loss",
                "currency",
                "is_market_asset",
                "has_price_history",
                "source_file",
                "portfolio_name",
            ]
        )

    portfolio_name = parsed.ledger["portfolio_name"].iat[0]
    source_file = parsed.ledger["source_file"].iat[0]
    lot_counts = parsed.open_lots.groupby("symbol").size().rename("open_lot_count")
    holdings = (
        parsed.positions.rename(
            columns={
                "symbol": "ticker",
                "quantity_open": "quantity",
                "avg_cost_mxn": "average_cost",
                "current_price_mxn": "market_price",
                "market_value_mxn": "market_value",
                "unrealized_pnl_mxn": "profit_loss",
            }
        )
        .merge(lot_counts, left_on="ticker", right_index=True, how="left")
        .copy()
    )
    holdings["original_ticker"] = holdings["ticker"]
    holdings["asset_name"] = holdings["ticker"]
    holdings["section"] = np.where(
        holdings["ticker"].eq("MXN=X"),
        "FX Exposure",
        "Transaction Ledger",
    )
    holdings["currency"] = "MXN"
    holdings["is_market_asset"] = True
    holdings["has_price_history"] = holdings["market_price"].notna()
    holdings["source_file"] = source_file
    holdings["portfolio_name"] = portfolio_name
    return holdings[
        [
            "ticker",
            "original_ticker",
            "asset_name",
            "section",
            "quantity",
            "average_cost",
            "market_price",
            "market_value",
            "profit_loss",
            "currency",
            "is_market_asset",
            "has_price_history",
            "source_file",
            "portfolio_name",
            "open_lot_count",
            "cost_basis_mxn",
            "unrealized_return",
            "last_quote_timestamp",
        ]
    ].sort_values("market_value", ascending=False).reset_index(drop=True)


def _read_text(source: Path | BytesIO | str) -> tuple[str, str]:
    if isinstance(source, Path):
        return source.read_text(encoding="utf-8"), source.name
    if isinstance(source, BytesIO):
        name = getattr(source, "name", "uploaded_portfolio.csv")
        return source.getvalue().decode("utf-8"), name
    return str(source), "portfolio.csv"


def _repair_csv_rows(text: str) -> list[list[str]]:
    reader = csv.reader(StringIO(text))
    header = next(reader)
    rows: list[list[str]] = []
    for row in reader:
        if len(row) > len(header):
            row = row[:15] + [",".join(row[15:-1]).strip()] + [row[-1]]
        elif len(row) < len(header):
            row = row + [""] * (len(header) - len(row))
        rows.append(row)
    return [header] + rows


def _to_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors="coerce")


def _parse_trade_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series.astype(str).str.strip(), format="%Y%m%d", errors="coerce")


def _parse_quote_timestamp(date_series: pd.Series, time_series: pd.Series) -> pd.Series:
    cleaned_time = time_series.fillna("").astype(str).str.replace(r"\s+[A-Z]{2,4}$", "", regex=True)
    stamp = (date_series.fillna("").astype(str).str.strip() + " " + cleaned_time.str.strip()).str.strip()
    return pd.to_datetime(stamp, format="%Y/%m/%d %H:%M", errors="coerce")


def _clean_text(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def _classify_row_kind(df: pd.DataFrame) -> pd.Series:
    return np.select(
        [
            df["symbol"].eq(CASH_SYMBOL),
            df["transaction_type"].isin([BUY, SELL]),
        ],
        [
            "cash",
            "trade",
        ],
        default="quote",
    )


def _normalize_transaction_type(series: pd.Series) -> pd.Series:
    return _clean_text(series).str.upper()


def _build_trade_ledger(df: pd.DataFrame) -> pd.DataFrame:
    trades = df[df["row_kind"] == "trade"].copy()
    trades["signed_quantity"] = np.where(trades["transaction_type"].eq(BUY), trades["quantity"], -trades["quantity"])
    trades["gross_trade_value_mxn"] = trades["trade_price"].fillna(0.0) * trades["quantity"].fillna(0.0)
    trades["commission_mxn"] = trades["commission"].fillna(0.0)
    trades["net_cash_impact_mxn"] = np.where(
        trades["transaction_type"].eq(BUY),
        -(trades["gross_trade_value_mxn"] + trades["commission_mxn"]),
        trades["gross_trade_value_mxn"] - trades["commission_mxn"],
    )
    trades["trade_price_mxn"] = trades["trade_price"]
    trades["current_price_mxn"] = trades["current_price"]
    return trades.sort_values(["trade_date", "symbol", "transaction_type", "trade_price_mxn"]).reset_index(drop=True)


def _infer_cash_scope(cash_flows: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    classified = cash_flows.copy()
    trade_totals = (
        trades.groupby("trade_date", dropna=True)["net_cash_impact_mxn"]
        .sum()
        .rename("trade_cash_total_mxn")
        .to_frame()
        .reset_index()
    )
    classified = classified.merge(trade_totals, on="trade_date", how="left")
    classified["trade_cash_total_mxn"] = classified["trade_cash_total_mxn"].fillna(0.0)

    def classify_comment(comment: str) -> tuple[str, str]:
        lowered = str(comment).strip().lower()
        for keyword, category in INTERNAL_CASH_KEYWORDS.items():
            if keyword in lowered:
                return "internal", category
        return "external", "capital_flow"

    scopes = []
    categories = []
    reasons = []
    confidences = []
    for row in classified.itertuples(index=False):
        default_scope, default_category = classify_comment(row.comment)
        signed_amount = row.cash_amount_mxn
        matches_trade_total = (
            pd.notna(row.trade_cash_total_mxn)
            and not np.isclose(row.trade_cash_total_mxn, 0.0)
            and np.isclose(signed_amount, row.trade_cash_total_mxn, atol=5.0)
        )
        matches_trade_abs = (
            pd.notna(row.trade_cash_total_mxn)
            and not np.isclose(row.trade_cash_total_mxn, 0.0)
            and np.isclose(abs(signed_amount), abs(row.trade_cash_total_mxn), atol=5.0)
        )
        if default_scope == "internal" or matches_trade_total or matches_trade_abs:
            scope = "internal"
            if row.transaction_type == WITHDRAWAL:
                category = "trade_funding"
            elif row.transaction_type == DEPOSIT:
                category = "trade_settlement"
            else:
                category = default_category
            if default_category != "capital_flow":
                category = default_category
            if default_scope == "internal":
                reason = f"keyword:{default_category}"
                confidence = "high"
            elif matches_trade_total:
                reason = "matched_trade_cash_total"
                confidence = "high"
            else:
                reason = "matched_trade_cash_absolute"
                confidence = "medium"
        else:
            scope = "external"
            category = "deposit" if row.transaction_type == DEPOSIT else "withdrawal"
            reason = "no_trade_match_and_no_internal_keyword"
            confidence = "medium"
        scopes.append(scope)
        categories.append(category)
        reasons.append(reason)
        confidences.append(confidence)

    classified["cash_flow_scope"] = scopes
    classified["cash_flow_category"] = categories
    classified["classification_reason"] = reasons
    classified["classification_confidence"] = confidences
    return classified.sort_values(["trade_date", "transaction_type"]).reset_index(drop=True)


def _build_cash_ledger(df: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    cash = df[df["row_kind"] == "cash"].copy()
    cash["cash_amount_mxn"] = np.where(
        cash["transaction_type"].eq(DEPOSIT),
        cash["quantity"],
        -cash["quantity"],
    )
    cash["quantity"] = 0.0
    return _infer_cash_scope(cash, trades)


def _build_open_lots_fifo(trades: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    open_lots: list[dict[str, object]] = []
    warnings: list[str] = []

    for symbol, symbol_trades in trades.groupby("symbol"):
        fifo_queue: list[dict[str, object]] = []
        ordered = symbol_trades.sort_values(["trade_date", "transaction_type"]).reset_index(drop=True)

        for trade in ordered.itertuples(index=False):
            if trade.transaction_type == BUY:
                commission_per_share = (trade.commission_mxn / trade.quantity) if trade.quantity else 0.0
                fifo_queue.append(
                    {
                        "symbol": symbol,
                        "lot_open_date": trade.trade_date,
                        "remaining_quantity": float(trade.quantity),
                        "entry_price_mxn": float(trade.trade_price_mxn),
                        "commission_per_share_mxn": float(commission_per_share),
                        "source_row_id": trade.row_id,
                    }
                )
                continue

            remaining_to_sell = float(trade.quantity)
            while remaining_to_sell > 1e-9 and fifo_queue:
                lot = fifo_queue[0]
                matched = min(lot["remaining_quantity"], remaining_to_sell)
                lot["remaining_quantity"] -= matched
                remaining_to_sell -= matched
                if lot["remaining_quantity"] <= 1e-9:
                    fifo_queue.pop(0)
            if remaining_to_sell > 1e-9:
                warnings.append(
                    f"Sell quantity exceeds accumulated open lots for {symbol} on {pd.Timestamp(trade.trade_date).date()}."
                )

        for lot in fifo_queue:
            if lot["remaining_quantity"] > 1e-9:
                open_lots.append(lot)

    return pd.DataFrame(open_lots), warnings


def _build_positions_from_lots(open_lots: pd.DataFrame, ledger: pd.DataFrame) -> pd.DataFrame:
    if open_lots.empty:
        return pd.DataFrame(
            columns=[
                "symbol",
                "quantity_open",
                "avg_cost_mxn",
                "current_price_mxn",
                "market_value_mxn",
                "cost_basis_mxn",
                "unrealized_pnl_mxn",
                "unrealized_return",
                "last_quote_timestamp",
            ]
        )

    latest_quotes = (
        ledger[ledger["symbol"] != CASH_SYMBOL]
        .sort_values("quote_timestamp")
        .groupby("symbol", as_index=False)
        .tail(1)[["symbol", "current_price", "quote_timestamp"]]
        .rename(columns={"current_price": "current_price_mxn", "quote_timestamp": "last_quote_timestamp"})
    )

    open_lots = open_lots.copy()
    open_lots["entry_cost_per_share_mxn"] = open_lots["entry_price_mxn"] + open_lots["commission_per_share_mxn"]
    open_lots["cost_basis_mxn"] = open_lots["remaining_quantity"] * open_lots["entry_cost_per_share_mxn"]

    positions = (
        open_lots.groupby("symbol", as_index=False)
        .agg(
            quantity_open=("remaining_quantity", "sum"),
            cost_basis_mxn=("cost_basis_mxn", "sum"),
        )
        .merge(latest_quotes, on="symbol", how="left")
    )
    positions["avg_cost_mxn"] = np.where(
        positions["quantity_open"] > 0,
        positions["cost_basis_mxn"] / positions["quantity_open"],
        np.nan,
    )
    positions["market_value_mxn"] = positions["quantity_open"] * positions["current_price_mxn"]
    positions["unrealized_pnl_mxn"] = positions["market_value_mxn"] - positions["cost_basis_mxn"]
    positions["unrealized_return"] = np.where(
        positions["cost_basis_mxn"] > 0,
        positions["market_value_mxn"] / positions["cost_basis_mxn"] - 1.0,
        np.nan,
    )
    return positions.sort_values("market_value_mxn", ascending=False).reset_index(drop=True)


def parse_portfolio_transactions(source: Path | BytesIO | str, source_name: str | None = None) -> ParsedPortfolioLedger:
    text, detected_name = _read_text(source)
    file_name = source_name or detected_name
    rows = _repair_csv_rows(text)
    header, data_rows = rows[0], rows[1:]
    if header != RAW_COLUMNS:
        raise ValueError("Unexpected CSV schema; parser expected the standard portfolio export columns.")

    ledger = pd.DataFrame(data_rows, columns=header).rename(columns=COLUMN_MAP)
    ledger["source_file"] = file_name
    ledger["portfolio_name"] = Path(file_name).stem
    ledger["row_id"] = np.arange(1, len(ledger) + 1)

    text_columns = ["symbol", "quote_date", "quote_time", "trade_date", "comment", "transaction_type"]
    for column in text_columns:
        ledger[column] = _clean_text(ledger[column])

    numeric_columns = [
        "current_price",
        "daily_change",
        "open_price",
        "high_price",
        "low_price",
        "volume",
        "trade_price",
        "quantity",
        "commission",
        "high_limit",
        "low_limit",
    ]
    for column in numeric_columns:
        ledger[column] = _to_numeric(ledger[column])

    ledger["transaction_type"] = _normalize_transaction_type(ledger["transaction_type"])
    ledger["trade_date"] = _parse_trade_date(ledger["trade_date"])
    ledger["quote_timestamp"] = _parse_quote_timestamp(ledger["quote_date"], ledger["quote_time"])
    ledger["quote_date"] = pd.to_datetime(ledger["quote_date"], format="%Y/%m/%d", errors="coerce")
    ledger["symbol"] = ledger["symbol"].str.strip().str.upper()
    ledger["row_kind"] = _classify_row_kind(ledger)
    ledger["currency"] = "MXN"

    trades = _build_trade_ledger(ledger)
    cash_flows = _build_cash_ledger(ledger, trades)
    open_lots, fifo_warnings = _build_open_lots_fifo(trades)
    positions = _build_positions_from_lots(open_lots, ledger)

    diagnostics = {
        "row_count": len(ledger),
        "trade_count": len(trades),
        "cash_flow_count": len(cash_flows),
        "quote_only_row_count": int((ledger["row_kind"] == "quote").sum()),
        "open_lot_count": len(open_lots),
        "external_cash_flow_total_mxn": cash_flows.loc[cash_flows["cash_flow_scope"] == "external", "cash_amount_mxn"].sum(),
        "internal_cash_flow_total_mxn": cash_flows.loc[cash_flows["cash_flow_scope"] == "internal", "cash_amount_mxn"].sum(),
        "warnings": fifo_warnings,
    }

    return ParsedPortfolioLedger(
        ledger=ledger,
        trades=trades,
        cash_flows=cash_flows,
        open_lots=open_lots,
        positions=positions,
        diagnostics=diagnostics,
    )
