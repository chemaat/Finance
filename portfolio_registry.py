#!/usr/bin/env python3
"""Portfolio source registry and friendly naming helpers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data" / "portfolios"
REGISTRY_PATH = ROOT / "data" / "portfolio_registry.json"


@dataclass(frozen=True)
class PortfolioSource:
    display_name: str
    file_path: Path
    exists: bool
    sha256: str | None = None
    file_size_bytes: int | None = None
    synced_at: str | None = None
    source_modified_at: str | None = None
    source_file_name: str | None = None


def compute_file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_registry_record(
    name: str,
    relative_path: str,
    file_path: Path,
    source_file_name: str | None = None,
    source_modified_at: str | None = None,
) -> dict[str, Any]:
    stat = file_path.stat()
    return {
        "name": name,
        "path": relative_path,
        "sha256": compute_file_sha256(file_path),
        "file_size_bytes": stat.st_size,
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "source_modified_at": source_modified_at,
        "source_file_name": source_file_name or file_path.name,
    }


def save_portfolio_registry(payload: dict[str, Any]) -> None:
    REGISTRY_PATH.parent.mkdir(parents=True, exist_ok=True)
    REGISTRY_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


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
            exists = file_path.exists()
            sources.append(
                PortfolioSource(
                    display_name=item.get("name") or _fallback_label_from_path(file_path),
                    file_path=file_path,
                    exists=exists,
                    sha256=item.get("sha256"),
                    file_size_bytes=item.get("file_size_bytes"),
                    synced_at=item.get("synced_at"),
                    source_modified_at=item.get("source_modified_at"),
                    source_file_name=item.get("source_file_name"),
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
                        exists=True,
                        sha256=compute_file_sha256(file_path),
                        file_size_bytes=file_path.stat().st_size,
                    )
                )
    return sources
