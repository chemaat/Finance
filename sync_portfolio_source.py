#!/usr/bin/env python3
"""Sync a canonical portfolio file into the repo only when it changes."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from portfolio_registry import (
    DATA_DIR,
    REGISTRY_PATH,
    build_registry_record,
    compute_file_sha256,
    save_portfolio_registry,
)


ROOT = Path(__file__).resolve().parent
LOCK_PATH = ROOT / "data" / ".portfolio_registry.lock"


class RegistryLock:
    def __enter__(self) -> "RegistryLock":
        deadline = time.time() + 15.0
        while True:
            try:
                fd = os.open(LOCK_PATH, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.close(fd)
                return self
            except FileExistsError:
                if time.time() >= deadline:
                    raise TimeoutError("Timed out waiting for the portfolio registry lock.")
                time.sleep(0.1)

    def __exit__(self, exc_type, exc, tb) -> None:
        if LOCK_PATH.exists():
            LOCK_PATH.unlink()


def load_payload() -> dict:
    if REGISTRY_PATH.exists():
        return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    return {"portfolios": []}


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync a portfolio file into data/portfolios and update registry metadata.")
    parser.add_argument("--name", required=True, help="Display name, e.g. MAIN GBM")
    parser.add_argument("--source", required=True, help="Source file path")
    parser.add_argument("--target", required=True, help="Target file name inside data/portfolios, e.g. main_gbm.csv")
    args = parser.parse_args()

    source = Path(args.source).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Source file not found: {source}")
    if source.suffix.lower() not in {".csv", ".xlsx"}:
        raise ValueError("Only .csv and .xlsx portfolio files are supported.")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    target = (DATA_DIR / args.target).resolve()
    if target.parent != DATA_DIR.resolve():
        raise ValueError("Target must be a direct child of data/portfolios.")

    source_hash = compute_file_sha256(source)
    target_hash = compute_file_sha256(target) if target.exists() else None
    changed = source_hash != target_hash
    if changed:
        shutil.copy2(source, target)

    with RegistryLock():
        payload = load_payload()
        relative_path = str(target.relative_to(ROOT))
        source_modified_at = datetime.fromtimestamp(source.stat().st_mtime, tz=timezone.utc).isoformat()
        updated_record = build_registry_record(
            name=args.name,
            relative_path=relative_path,
            file_path=target,
            source_file_name=source.name,
            source_modified_at=source_modified_at,
        )
        updated_record["last_sync_changed"] = changed

        portfolios = []
        replaced = False
        for item in payload.get("portfolios", []):
            if item.get("name") == args.name:
                portfolios.append(updated_record)
                replaced = True
            else:
                portfolios.append(item)
        if not replaced:
            portfolios.append(updated_record)
        payload["portfolios"] = portfolios
        save_portfolio_registry(payload)

    print(
        {
            "portfolio": args.name,
            "target": relative_path,
            "changed": changed,
            "sha256": updated_record["sha256"],
            "synced_at": updated_record["synced_at"],
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
