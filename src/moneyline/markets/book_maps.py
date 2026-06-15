"""Sport-scoped bookmaker market ID → canonical key resolution."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

from moneyline.constants import CONFIG_DIR
from moneyline.models.schemas import Bookmaker, Sport


@lru_cache
def get_book_market_maps() -> dict[str, Any]:
    path = CONFIG_DIR / "book_market_maps.yaml"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def resolve_sportradar_sub_type(
    bookmaker: Bookmaker | str,
    sport: Sport,
    sub_type_id: str,
) -> str | None:
    """Map Sportradar sub_type_id to canonical market_key for this book+sport."""
    if not sub_type_id:
        return None
    book = bookmaker.value if isinstance(bookmaker, Bookmaker) else str(bookmaker)
    maps = get_book_market_maps().get("sportradar_sub_type_id") or {}
    book_map = maps.get(book) or maps.get("betika") or {}
    sport_map = book_map.get(sport.value) or {}
    return sport_map.get(str(sub_type_id))


def resolve_betpawa_market_type(sport: Sport, market_type_id: str) -> str | None:
    if not market_type_id:
        return None
    maps = get_book_market_maps().get("betpawa_market_type_id") or {}
    sport_map = maps.get(sport.value) or {}
    return sport_map.get(str(market_type_id))


def canonical_from_book_ids(
    *,
    bookmaker: Bookmaker,
    sport: Sport,
    sub_type_id: str | None = None,
    market_type_id: str | None = None,
) -> str | None:
    if bookmaker in (Bookmaker.BETIKA, Bookmaker.ODIBETS, Bookmaker.PEPETA) and sub_type_id:
        return resolve_sportradar_sub_type(bookmaker, sport, sub_type_id)
    if bookmaker == Bookmaker.BETPAWA and market_type_id:
        return resolve_betpawa_market_type(sport, market_type_id)
    return None
