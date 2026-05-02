#!/bin/zsh
set -euo pipefail

ROOT="/Users/chemaar/Documents/Codex/2026-04-24-files-mentioned-by-the-user-app"
PYTHON_BIN="/Users/chemaar/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"

export PYTHONPATH="$ROOT/.pythonlibs"

exec "$PYTHON_BIN" -m streamlit run \
  "$ROOT/streamlit_app.py" \
  --global.developmentMode false \
  --server.headless false
