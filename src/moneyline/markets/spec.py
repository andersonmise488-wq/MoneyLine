from __future__ import annotations

from moneyline.canonical.markets import MarketSpec, detect_settlement, is_blocked_market_family, market_spec_id, raw_name_blocked
from moneyline.markets.grouping import effective_sub_type_id, team_total_scope
from moneyline.models.schemas import MarketOdds, MarketPeriod


def market_spec_for(market: MarketOdds, *, line: float | None = None) -> MarketSpec:
    resolved_line = line if line is not None else market.line
    raw_label = market.raw_market_name or market.market_display or ""
    return MarketSpec(
        sport=market.sport,
        market_family=market.market_key,
        period=market.period,
        line=resolved_line,
        scope=team_total_scope(market),
        settlement=detect_settlement(raw_label),
        sub_type_id=effective_sub_type_id(market),
    )


def market_spec_group_key(
    market: MarketOdds,
    *,
    line: float | None,
) -> tuple[str, MarketPeriod, str, str, float | None, str]:
    """Cross-book grouping key including canonical market_spec_id."""
    spec = market_spec_for(market, line=line)
    return (
        market.market_key,
        market.period,
        effective_sub_type_id(market),
        team_total_scope(market),
        line,
        spec.spec_id(),
    )


def market_allowed_for_arb(market: MarketOdds) -> bool:
    if is_blocked_market_family(market.market_key):
        return False
    if raw_name_blocked(market.raw_market_name or market.market_display):
        return False
    return True
