"""Validate arbitrage opportunities against recalculated margins and live API odds."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from moneyline.arb.engine import arb_margin
from moneyline.bookmakers.registry import get_adapter
from moneyline.constants import DEFAULT_MIN_MARGIN_PCT
from moneyline.models.schemas import ArbitrageOpportunity, Bookmaker, Event, MarketOdds, OutcomeSide, Sport


@dataclass
class LegCheckResult:
    bookmaker: str
    event_key: str
    side: str
    reported_price: float
    live_price: float | None
    market_key: str | None
    ok: bool
    detail: str


@dataclass
class OpportunityCheckResult:
    opportunity_id: str
    sport: str
    home_team: str
    away_team: str
    market_key: str
    margin_reported: float
    margin_recalc: float
    margin_ok: bool
    realistic: bool
    match_confidence: float
    legs: list[LegCheckResult] = field(default_factory=list)
    ok: bool = False
    issues: list[str] = field(default_factory=list)


def recalc_margin_from_legs(legs: list[dict[str, Any]]) -> tuple[float, float]:
    prices = [float(leg["price"]) for leg in legs]
    implied_sum, margin_pct = arb_margin(prices)
    return implied_sum, margin_pct


def margin_math_ok(opp: ArbitrageOpportunity, *, tolerance_pct: float = 0.15) -> bool:
    implied_sum, margin_pct = recalc_margin_from_legs(opp.legs)
    if abs(opp.implied_sum - implied_sum) > 0.002:
        return False
    return abs(opp.margin_pct - margin_pct) <= tolerance_pct


def _line_matches(market: MarketOdds, target: float | None) -> bool:
    if target is None:
        return market.line is None
    candidates: list[float] = []
    if market.line is not None:
        candidates.append(float(market.line))
    for outcome in market.outcomes:
        if outcome.line is not None:
            candidates.append(float(outcome.line))
    if not candidates:
        return False
    return any(abs(value - target) <= 0.05 for value in candidates)


def _find_live_price(
    markets: list[MarketOdds],
    *,
    market_key: str,
    side: str,
    line: float | None,
) -> float | None:
    side_enum = OutcomeSide(side)
    for market in markets:
        if market.market_key != market_key:
            continue
        if not _line_matches(market, line):
            continue
        for outcome in market.outcomes:
            if outcome.side == side_enum:
                return float(outcome.price)
    return None


async def verify_leg_live(
    leg: dict[str, Any],
    *,
    sport: Sport,
    market_key: str,
    line: float | None,
    events_by_key: dict[str, Event],
    price_tolerance: float = 0.05,
) -> LegCheckResult:
    bookmaker = str(leg.get("bookmaker", ""))
    event_key = str(leg.get("event_key", ""))
    side = str(leg.get("side", ""))
    reported = float(leg.get("price", 0))
    event = events_by_key.get(event_key)
    if event is None:
        return LegCheckResult(
            bookmaker=bookmaker,
            event_key=event_key,
            side=side,
            reported_price=reported,
            live_price=None,
            market_key=market_key,
            ok=False,
            detail="event_not_in_scan_batch",
        )
    try:
        async with get_adapter(Bookmaker(bookmaker)) as adapter:
            live_markets = await adapter.fetch_event_markets(event, sport)
    except Exception as exc:
        return LegCheckResult(
            bookmaker=bookmaker,
            event_key=event_key,
            side=side,
            reported_price=reported,
            live_price=None,
            market_key=market_key,
            ok=False,
            detail=f"api_error:{exc}",
        )
    live_price = _find_live_price(
        live_markets,
        market_key=market_key,
        side=side,
        line=line,
    )
    if live_price is None:
        return LegCheckResult(
            bookmaker=bookmaker,
            event_key=event_key,
            side=side,
            reported_price=reported,
            live_price=None,
            market_key=market_key,
            ok=False,
            detail="market_or_side_not_found_live",
        )
    if abs(live_price - reported) > price_tolerance:
        return LegCheckResult(
            bookmaker=bookmaker,
            event_key=event_key,
            side=side,
            reported_price=reported,
            live_price=live_price,
            market_key=market_key,
            ok=False,
            detail=f"price_drift:{reported}->{live_price}",
        )
    return LegCheckResult(
        bookmaker=bookmaker,
        event_key=event_key,
        side=side,
        reported_price=reported,
        live_price=live_price,
        market_key=market_key,
        ok=True,
        detail="ok",
    )


async def validate_opportunity(
    opp: ArbitrageOpportunity,
    *,
    events_by_key: dict[str, Event],
    verify_live: bool = True,
    price_tolerance: float = 0.05,
) -> OpportunityCheckResult:
    implied_sum, margin_recalc = recalc_margin_from_legs(opp.legs)
    issues: list[str] = []
    margin_ok = margin_math_ok(opp)
    if not margin_ok:
        issues.append(
            f"margin_mismatch reported={opp.margin_pct:.3f} recalc={margin_recalc:.3f} "
            f"implied={opp.implied_sum:.5f} vs {implied_sum:.5f}"
        )
    realistic = True

    leg_results: list[LegCheckResult] = []
    if verify_live:
        for leg in opp.legs:
            leg_result = await verify_leg_live(
                leg,
                sport=opp.sport,
                market_key=opp.market_key,
                line=opp.line,
                events_by_key=events_by_key,
                price_tolerance=price_tolerance,
            )
            leg_results.append(leg_result)
            if not leg_result.ok:
                issues.append(f"{leg_result.bookmaker}:{leg_result.detail}")

    ok = margin_ok and (not verify_live or all(r.ok for r in leg_results)) and realistic
    return OpportunityCheckResult(
        opportunity_id=f"{opp.fixture_id or opp.cluster_id}:{opp.market_key}:{opp.line}",
        sport=opp.sport.value,
        home_team=opp.home_team,
        away_team=opp.away_team,
        market_key=opp.market_key,
        margin_reported=opp.margin_pct,
        margin_recalc=margin_recalc,
        margin_ok=margin_ok,
        realistic=realistic,
        match_confidence=opp.match_confidence,
        legs=leg_results,
        ok=ok,
        issues=issues,
    )


async def validate_opportunities(
    opportunities: list[ArbitrageOpportunity],
    *,
    events: list[Event],
    verify_live: bool = True,
    max_checks: int = 25,
    price_tolerance: float = 0.05,
) -> list[OpportunityCheckResult]:
    events_by_key = {e.event_key: e for e in events}
    sorted_opps = sorted(opportunities, key=lambda o: o.margin_pct, reverse=True)
    checks = sorted_opps[:max_checks]
    results: list[OpportunityCheckResult] = []
    for opp in checks:
        results.append(
            await validate_opportunity(
                opp,
                events_by_key=events_by_key,
                verify_live=verify_live,
                price_tolerance=price_tolerance,
            )
        )
    return results


def summarize_checks(results: list[OpportunityCheckResult]) -> dict[str, Any]:
    total = len(results)
    passed = sum(1 for r in results if r.ok)
    unrealistic = sum(1 for r in results if not r.realistic)
    margin_fail = sum(1 for r in results if not r.margin_ok)
    live_fail = sum(
        1
        for r in results
        if r.legs and any(not leg.ok for leg in r.legs)
    )
    return {
        "checked": total,
        "passed": passed,
        "failed": total - passed,
        "unrealistic_margin": unrealistic,
        "margin_math_fail": margin_fail,
        "live_api_fail": live_fail,
        "pass_rate_pct": round(100 * passed / total, 1) if total else 0.0,
    }
