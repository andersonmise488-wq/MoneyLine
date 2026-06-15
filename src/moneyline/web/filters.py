from __future__ import annotations

from moneyline.constants import DEFAULT_MIN_MARGIN_PCT
from moneyline.models.schemas import ArbitrageOpportunity


def filter_realistic_arbs(
    opportunities: list[ArbitrageOpportunity],
    *,
    min_margin_pct: float = DEFAULT_MIN_MARGIN_PCT,
    max_margin_pct: float | None = None,
) -> list[ArbitrageOpportunity]:
    """Keep arbs at or above min margin; optional max_margin_pct for legacy band filters."""
    filtered = (
        opp
        for opp in opportunities
        if opp.margin_pct >= min_margin_pct
        and (max_margin_pct is None or opp.margin_pct <= max_margin_pct)
    )
    return sorted(filtered, key=lambda o: o.margin_pct, reverse=True)


def filter_public_arbs(
    opportunities: list[ArbitrageOpportunity],
    *,
    max_margin_pct: float = 3.0,
) -> list[ArbitrageOpportunity]:
    """Public teaser: low-margin opportunities only."""
    return sorted(
        (opp for opp in opportunities if opp.margin_pct <= max_margin_pct),
        key=lambda o: o.margin_pct,
        reverse=True,
    )


def filter_public_teaser_arbs(
    opportunities: list[ArbitrageOpportunity],
    *,
    max_margin_pct: float = 3.0,
) -> list[ArbitrageOpportunity]:
    return filter_public_arbs(opportunities, max_margin_pct=max_margin_pct)


def filter_all_arbs(
    opportunities: list[ArbitrageOpportunity],
    *,
    min_margin_pct: float = DEFAULT_MIN_MARGIN_PCT,
) -> list[ArbitrageOpportunity]:
    """Every detected surebet at or above the minimum margin."""
    return sorted(
        (opp for opp in opportunities if opp.margin_pct >= min_margin_pct),
        key=lambda o: o.margin_pct,
        reverse=True,
    )


def filter_premium_arbs(
    opportunities: list[ArbitrageOpportunity],
    *,
    min_margin_pct: float = 3.01,
) -> list[ArbitrageOpportunity]:
    """Subscriber band: above public cap, no upper limit."""
    return sorted(
        (opp for opp in opportunities if opp.margin_pct >= min_margin_pct),
        key=lambda o: o.margin_pct,
        reverse=True,
    )
