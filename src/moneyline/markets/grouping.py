from __future__ import annotations

import re

from moneyline.config_loader import get_markets_config
from moneyline.models.schemas import MarketOdds


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().lower())


_SUB_TYPE_BY_MARKET: dict[tuple[str, str], str] = {}


def _ensure_cache() -> None:
    if _SUB_TYPE_BY_MARKET:
        return
    for sport_key, markets in get_markets_config().items():
        for market_key, spec in markets.items():
            ids = spec.get("betika_sub_type_ids", [])
            if ids:
                _SUB_TYPE_BY_MARKET[(sport_key, market_key)] = str(ids[0])


def effective_sub_type_id(market: MarketOdds) -> str:
    """Sportradar sub_type_id, or canonical id from markets.yaml for name-mapped books."""
    if market.sub_type_id:
        return str(market.sub_type_id)
    _ensure_cache()
    return _SUB_TYPE_BY_MARKET.get((market.sport.value, market.market_key), "")


def team_total_scope(market: MarketOdds) -> str:
    """Home/away scope for team total markets (empty for match-level markets)."""
    if market.market_key != "team_totals":
        return ""
    name = _norm(market.raw_market_name or market.market_display or "")
    if any(
        token in name
        for token in (
            "home team",
            "team 1",
            "team one",
            "competitor1",
            "competitor 1",
            "{home}",
            "home o/u",
            "home over",
        )
    ):
        return "home"
    if any(
        token in name
        for token in (
            "away team",
            "team 2",
            "team two",
            "competitor2",
            "competitor 2",
            "{away}",
            "away o/u",
            "away over",
        )
    ):
        return "away"
    return ""


def market_group_key(
    market: MarketOdds,
    *,
    line: float | None,
) -> tuple[str, object, str, str, float | None]:
    """Canonical cross-book grouping key aligned with Sportradar sub_type_id matching."""
    from moneyline.models.schemas import MarketPeriod

    period: MarketPeriod = market.period
    return (
        market.market_key,
        period,
        effective_sub_type_id(market),
        team_total_scope(market),
        line,
    )
