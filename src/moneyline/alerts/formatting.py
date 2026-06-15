"""Betting-language formatters for alerts and dashboards."""

from __future__ import annotations

from moneyline.markets.period import format_line
from moneyline.models.schemas import ArbitrageOpportunity, OutcomeSide

_HANDICAP_MARKET_KEYS = frozenset(
    {
        "asian_handicap",
        "european_handicap",
        "game_handicap",
        "spread",
        "set_handicap",
        "run_line",
        "puck_line",
    }
)


def format_signed_handicap(value: float) -> str:
    text = format_line(value)
    if value > 0:
        return f"+{text}"
    return text


def handicap_line_for_side(side: str, line: float | None) -> float | None:
    if line is None:
        return None
    if side == OutcomeSide.HOME.value:
        return line
    if side == OutcomeSide.AWAY.value:
        return -line
    return None


def format_bet_pick(opportunity: ArbitrageOpportunity, leg: dict) -> str:
    """Format a leg as betting language, e.g. Arsenal (-2) @ 6.00."""
    side = str(leg.get("side", "")).lower()
    price = float(leg["price"])
    label = str(leg.get("label", "")).strip()
    line = leg.get("line")
    if line is None:
        line = opportunity.line
    market_key = opportunity.market_key
    price_text = f"@ {price:.2f}"

    if market_key in _HANDICAP_MARKET_KEYS:
        if side in (OutcomeSide.HOME.value, OutcomeSide.AWAY.value):
            signed = handicap_line_for_side(side, line)
            if signed is not None:
                team = (
                    opportunity.home_team
                    if side == OutcomeSide.HOME.value
                    else opportunity.away_team
                )
                return f"{team} ({format_signed_handicap(signed)}) {price_text}"
        if side == OutcomeSide.DRAW.value:
            return f"{label or 'Draw'} {price_text}"

    if side == OutcomeSide.OVER.value:
        if line is not None:
            return f"Over {format_line(line)} {price_text}"
        return f"{label or 'Over'} {price_text}"

    if side == OutcomeSide.UNDER.value:
        if line is not None:
            return f"Under {format_line(line)} {price_text}"
        return f"{label or 'Under'} {price_text}"

    if market_key == "btts":
        if side == OutcomeSide.YES.value:
            return f"BTTS Yes {price_text}"
        if side == OutcomeSide.NO.value:
            return f"BTTS No {price_text}"

    if side == OutcomeSide.YES.value:
        return f"Yes {price_text}"
    if side == OutcomeSide.NO.value:
        return f"No {price_text}"
    if side == OutcomeSide.HOME.value:
        return f"{opportunity.home_team} {price_text}"
    if side == OutcomeSide.AWAY.value:
        return f"{opportunity.away_team} {price_text}"
    if side == OutcomeSide.DRAW.value:
        return f"Draw {price_text}"

    return f"{label or side} {price_text}"
