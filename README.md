# Aurelia Portfolio OS

Institutional-style portfolio intelligence for GBM holdings with premium Streamlit UX, configurable benchmarking, advanced risk analytics, and a market snapshot layer.

The app now supports two ingestion modes:

- GBM holdings snapshot exports (`.xlsx`)
- Transaction-ledger portfolio exports (`.csv`) with trade dates, purchase prices, cash flows, and FIFO-derived open positions

Recommended production workflow:

- Store canonical portfolio files in `data/portfolios/`
- Register them in `data/portfolio_registry.json`
- Let GitHub be the source of truth
- Streamlit Cloud will update only when the repository file changes and a new deploy is triggered

This workspace now has two entry points:

- `portfolio_core.py`: reusable analytics module for loading GBM exports, normalizing holdings, downloading market and FX data, computing metrics, and exporting Excel.
- `returns_engine.py`: holdings-based return reconstruction, absolute return vs cost basis, synthetic XIRR, and attribution.
- `transaction_returns_engine.py`: transaction-ledger NAV reconstruction, daily TWR, true XIRR from external cash flows, and realized vs unrealized P&L analytics.
- `benchmark_engine.py`: benchmark selection, date alignment, and period-return comparison tables.
- `risk_engine.py`: institutional risk metrics such as beta, alpha, Sortino, VaR, CVaR, tracking error, and rolling measures.
- `market_snapshot.py`: daily market snapshot with major indices, ETFs, and top movers.
- `transaction_parser.py`: robust transaction-ledger parser for CSV portfolio exports with trade normalization, cash-flow classification, FIFO open lots, and position reconstruction.
- `theme_engine.py`: design tokens, dark/light theming, shell styling, and premium visual system.
- `ui_components.py`: reusable UI primitives for KPI cards, shell top bar, data grid helpers, and chart theming.
- `portfolio_analysis.py`: CLI wrapper for batch CSV and Excel exports.
- `streamlit_app.py`: premium command center UI with executive navigation, KPI surfaces, benchmark overlays, risk dashboard, holdings explorer, and market snapshot.

## Recommended Deployment

Best option:

- Put the code in a GitHub repository.
- Deploy the app from that repo with Streamlit Community Cloud.

Why:

- `GitHub Pages` is for static sites and is not a good fit for this Python Streamlit app.
- `Streamlit Community Cloud` is designed for Streamlit apps and connects directly to GitHub.

What to upload:

- `streamlit_app.py`
- `portfolio_core.py`
- `portfolio_analysis.py`
- `requirements.txt`
- `README.md`
- `data/portfolios/*.csv` or `data/portfolios/*.xlsx`
- `data/portfolio_registry.json`

Do not upload:

- `.pythonlibs/`
- `outputs/`
- `__pycache__/`

## Portfolio Registry

To move away from manual uploads, create:

- `data/portfolio_registry.json`

You can start from:

- `data/portfolio_registry.example.json`

Suggested setup for your two portfolios:

```json
{
  "portfolios": [
    {
      "name": "MAIN GBM",
      "path": "data/portfolios/main_gbm.csv"
    },
    {
      "name": "LT KIA",
      "path": "data/portfolios/lt_kia.csv"
    }
  ]
}
```

With that setup, the app can auto-load those portfolios directly from the repo without needing a manual upload every time.

## Streamlit Dashboard

Simplest launch:

```bash
/Users/chemaar/Documents/Codex/2026-04-24-files-mentioned-by-the-user-app/run_dashboard.sh
```

Manual launch:

```bash
PYTHONPATH=/Users/chemaar/Documents/Codex/2026-04-24-files-mentioned-by-the-user-app/.pythonlibs \
/Users/chemaar/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
-m streamlit run \
/Users/chemaar/Documents/Codex/2026-04-24-files-mentioned-by-the-user-app/streamlit_app.py \
--global.developmentMode false
```

The app looks for GBM files in:

- `/Users/chemaar/Documents/Codex/2026-04-24-files-mentioned-by-the-user-app`
- `/Users/chemaar/Downloads`

## CLI Export

```bash
PYTHONPATH=/Users/chemaar/Documents/Codex/2026-04-24-files-mentioned-by-the-user-app/.pythonlibs \
/Users/chemaar/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 \
/Users/chemaar/Documents/Codex/2026-04-24-files-mentioned-by-the-user-app/portfolio_analysis.py \
/Users/chemaar/Downloads/App_GBM_Detalle_Portafolio__1777067587722.xlsx \
/Users/chemaar/Downloads/App_GBM_Detalle_Portafolio__1777067580272.xlsx \
--period 2021-01-01 \
--base-currency MXN
```

## Outputs

The CLI writes into `/Users/chemaar/Documents/Codex/2026-04-24-files-mentioned-by-the-user-app/outputs`:

- `portfolio_summary.csv`
- `benchmark_metrics.csv`
- `benchmark_drawdowns.csv`
- `cumulative_returns.csv`
- one cleaned holdings file per portfolio
- one allocation file per portfolio
- one daily value series per portfolio
- one daily returns series per portfolio
- one benchmark comparison file per portfolio
- `portfolio_report.xlsx`

## GitHub to Streamlit Cloud

1. Create a GitHub repo and push these files.
2. Go to [https://share.streamlit.io](https://share.streamlit.io).
3. Sign in with GitHub.
4. Click `Create app`.
5. Select your repository and branch.
6. Set the entrypoint file to `streamlit_app.py`.
7. Deploy.

After that, you will get a public URL like:

- `https://your-app-name.streamlit.app`
