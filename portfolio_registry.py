#!/usr/bin/env python3
"""Portfolio source registry and friendly naming helpers."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "portfolios"
REGISTRY_PATH = ROOT / "data" / "portfolio_registry.json"


@dataclass(frozen=True)
class PortfolioSource:
    display_name: str
    file_path: Path


def _fallback_label_from_path(path: Path) -> str:
    stem = path.stem.lower()
    if "main" in stem and "gbm" in stem:
        return "MAIN GBM"
    if "lt" in stem and "kia" in stem:
        return "LT KIA"
    return path.stem.replace("_", " ").replace("-", " ").title()


def load_portfolio_registry() -> list[PortfolioSource]:
    sources: list[PortfolioSource] = []
    if REGISTRY_PATH.exists():
        payload = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        for item in payload.get("portfolios", []):
            relative = item.get("path", "")
            if not relative:
                continue
            file_path = (ROOT / relative).resolve()
            if file_path.exists():
                sources.append(
                    PortfolioSource(
                        display_name=item.get("name") or _fallback_label_from_path(file_path),
                        file_path=file_path,
                    )
                )
    if sources:
        return sources

    if DATA_DIR.exists():
        for file_path in sorted(DATA_DIR.glob("*")):
            if file_path.suffix.lower() not in {".csv", ".xlsx"}:
                continue
            sources.append(
                PortfolioSource(
                    display_name=_fallback_label_from_path(file_path),
                    file_path=file_path.resolve(),
                )
            )
    return sources
