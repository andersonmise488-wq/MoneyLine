from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from moneyline.constants import CONFIG_DIR


@lru_cache
def load_yaml(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_bookmaker_config(key: str) -> dict[str, Any]:
    return load_yaml("bookmakers.yaml")["bookmakers"][key]


def get_bookmaker_market_workers(key: str, default: int = 50) -> int:
    """Concurrent market-fetch workers for a bookmaker (per sport scan)."""
    cfg = get_bookmaker_config(key)
    workers = cfg.get("market_workers")
    if workers is not None:
        return max(1, int(workers))
    return default


def get_all_bookmakers() -> dict[str, Any]:
    return load_yaml("bookmakers.yaml")["bookmakers"]


def get_sports_config() -> dict[str, Any]:
    return load_yaml("sports.yaml")["sports"]


def get_markets_config() -> dict[str, Any]:
    return load_yaml("markets.yaml")
