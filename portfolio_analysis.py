#!/usr/bin/env python3
"""CLI wrapper for GBM portfolio analysis."""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from portfolio_core import (
    DEFAULT_BASE_CURRENCY,
    DEFAULT_BENCHMARKS,
    aggregate_portfolios,
    export_analysis_to_excel,
    format_display_table,
    prepare_analysis,
    slugify,
)


ROOT = Path(__file__).resolve().parent


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Analyze GBM portfolio exports against selected benchmarks."
    )
    parser.add_argument(
        "files",
        nargs="+",
        type=Path,
        help="One or more GBM Excel exports.",
    )
    parser.add_argument(
        "--period",
        default="2021-01-01",
        help="Start date for market history, for example 2021-01-01.",
    )
    parser.add_argument(
        "--risk-free-rate",
        type=float,
        default=0.0,
        help="Annual risk-free rate as a decimal, for example 0.03 for 3%%.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs",
        help="Directory for CSV and Excel exports.",
    )
    parser.add_argument(
        "--base-currency",
        choices=["MXN", "USD"],
        default=DEFAULT_BASE_CURRENCY,
        help="Presentation currency for market values and benchmark series.",
    )
    return parser


def ensure_output_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def export_tables(analysis: dict[str, object], output_dir: Path) -> None:
    summary = analysis["summary"]
    benchmark_metrics = analysis["benchmark_metrics"]
    summary.to_csv(output_dir / "portfolio_summary.csv")
    benchmark_metrics.to_csv(output_dir / "benchmark_metrics.csv")
    benchmark_drawdowns = analysis["benchmark_drawdowns"]
    benchmark_drawdowns.to_csv(output_dir / "benchmark_drawdowns.csv")
    cumulative_returns = analysis["cumulative_returns"]
    cumulative_returns.to_csv(output_dir / "cumulative_returns.csv")

    portfolio_results = analysis["portfolio_results"]
    for name, result in portfolio_results.items():
        slug = slugify(name)
        result.holdings.to_csv(output_dir / f"{slug}_holdings_clean.csv", index=False)
        result.allocation.to_csv(output_dir / f"{slug}_allocation.csv", index=False)
        result.value_series.to_csv(output_dir / f"{slug}_daily_value.csv", header=["value"])
        result.return_series.to_csv(output_dir / f"{slug}_daily_returns.csv", header=["return"])
        result.comparison.to_csv(output_dir / f"{slug}_benchmark_comparison.csv")
    (output_dir / "portfolio_report.xlsx").write_bytes(export_analysis_to_excel(analysis))


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()

    files = [file_path.expanduser().resolve() for file_path in args.files]
    output_dir = ensure_output_dir(args.output_dir.expanduser().resolve())

    benchmarks = DEFAULT_BENCHMARKS.copy()

    pd.set_option("display.width", 180)
    pd.set_option("display.max_columns", 50)
    pd.set_option("display.float_format", lambda value: f"{value:,.6f}")

    portfolios = aggregate_portfolios(files)
    analysis = prepare_analysis(
        portfolio_frames=portfolios,
        benchmark_map=benchmarks,
        start_date=pd.Timestamp(args.period),
        risk_free_rate=args.risk_free_rate,
        base_currency=args.base_currency,
    )
    export_tables(analysis, output_dir)

    print("\nPortfolio Summary")
    print(format_display_table(analysis["summary"]).to_string())
    print("\nBenchmark Metrics")
    print(format_display_table(analysis["benchmark_metrics"]).to_string())

    portfolio_results = analysis["portfolio_results"]
    for name, result in portfolio_results.items():
        print(f"\n{name} Metrics")
        print(format_display_table(result.metrics).to_string())
        print(f"\n{name} Allocation")
        print(format_display_table(result.allocation.head(15)).to_string(index=False))
        print(f"\n{name} vs Benchmarks")
        print(format_display_table(result.comparison).to_string())

    print(f"Artifacts saved to: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
