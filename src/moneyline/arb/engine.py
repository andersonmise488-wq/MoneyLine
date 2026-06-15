from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any



from moneyline.constants import DEFAULT_BANKROLL, DEFAULT_MIN_MARGIN_PCT, ODDS_STALENESS_SECONDS
from moneyline.canonical.markets import reject_integer_totals_enabled
from moneyline.markets.spec import market_allowed_for_arb, market_spec_for, market_spec_group_key
from moneyline.markets.period import format_line, label_has_unresolved_template, market_requires_line, period_label
from moneyline.matching.confidence import cluster_allows_arbitrage

from moneyline.models.schemas import (

    ArbitrageOpportunity,

    MarketOdds,

    MarketPeriod,

    MatchedEvent,

    OutcomeSide,

)





def implied_probability(decimal_odds: float) -> float:

    return 1.0 / decimal_odds if decimal_odds > 0 else 0.0





def arb_margin(legs: list[float]) -> tuple[float, float]:

    """Return (implied_sum, margin_pct). Positive margin = arbitrage."""

    implied_sum = sum(implied_probability(o) for o in legs)

    margin_pct = (1.0 - implied_sum) * 100.0

    return implied_sum, margin_pct





def optimal_stakes(legs: list[dict[str, Any]], bankroll: float) -> list[dict[str, Any]]:

    """Calculate Dutching stakes for equal profit across arb legs."""

    implied = [implied_probability(leg["price"]) for leg in legs]

    total_implied = sum(implied)

    if total_implied <= 0:

        return legs



    result = []

    for leg, imp in zip(legs, implied):

        stake = bankroll * imp / total_implied

        result.append({**leg, "stake": round(stake, 2), "return": round(stake * leg["price"], 2)})

    return result





def _round_line(value: float) -> float:

    return round(float(value), 2)





def resolve_market_line(market: MarketOdds) -> float | None:

    """Single canonical line for a market; None if outcomes disagree."""

    candidates: list[float] = []

    if market.line is not None:

        candidates.append(_round_line(market.line))



    for outcome in market.outcomes:

        if outcome.line is not None:

            candidates.append(_round_line(outcome.line))



    if not candidates:

        return None



    first = candidates[0]

    if all(abs(value - first) <= 0.01 for value in candidates):

        return first

    return None





def outcome_matches_line(outcome_line: float | None, market_line: float | None, target: float | None) -> bool:

    if target is None:

        return outcome_line is None and market_line is None

    actual = outcome_line if outcome_line is not None else market_line

    if actual is None:

        return False

    return abs(_round_line(actual) - target) <= 0.01





THREE_WAY_MARKET_KEYS = frozenset(
    {"match_result_1x2", "match_winner", "first_5_innings", "period_betting", "european_handicap"}
)

# Whole-number totals (e.g. 2.0) differ across books (Asian push vs European); skip for arbs.
_WHOLE_LINE_TOTAL_MARKETS = frozenset(
    {
        "over_under_goals",
        "totals",
        "team_totals",
        "corners_totals",
        "total_games",
        "quarter_totals",
        "half_totals",
        "total_points",
        "over_under_runs",
        "innings_totals",
    }
)


def _line_ok_for_cross_book_arb(market_key: str, line: float | None) -> bool:
    if line is None or market_key not in _WHOLE_LINE_TOTAL_MARKETS:
        return True
    if reject_integer_totals_enabled():
        return line != int(line)
    return True


def _market_is_fresh(market: MarketOdds, *, now: datetime, max_age_seconds: int) -> bool:
    if max_age_seconds <= 0:
        return True
    fetched = market.fetched_at
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    age = (now - fetched).total_seconds()
    return age <= max_age_seconds


def _opportunity_expires_at(
    markets: list[MarketOdds],
    *,
    now: datetime,
    max_age_seconds: int,
) -> datetime | None:
    """Arb validity = oldest contributing leg's fetch time + staleness TTL."""
    if max_age_seconds <= 0:
        return None
    timestamps: list[datetime] = []
    for market in markets:
        fetched = market.fetched_at
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        timestamps.append(fetched)
    if not timestamps:
        return now + timedelta(seconds=max_age_seconds)
    return min(timestamps) + timedelta(seconds=max_age_seconds)


class ArbitrageEngine:

    """Find cross-bookmaker surebets on normalized markets."""



    def __init__(
        self,
        min_margin_pct: float = DEFAULT_MIN_MARGIN_PCT,
        bankroll: float = DEFAULT_BANKROLL,
        max_margin_pct: float | None = None,
        max_odds_age_seconds: int = ODDS_STALENESS_SECONDS,
    ) -> None:
        self.min_margin_pct = min_margin_pct
        self.bankroll = bankroll
        self.max_margin_pct = max_margin_pct
        self.max_odds_age_seconds = max_odds_age_seconds



    def find_arbitrage(

        self,

        clusters: list[MatchedEvent],

        markets_by_event: dict[str, list[MarketOdds]],

    ) -> list[ArbitrageOpportunity]:

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        opportunities: list[ArbitrageOpportunity] = []

        for cluster in clusters:

            if not cluster_allows_arbitrage(cluster):
                continue

            grouped: dict[tuple, list[MarketOdds]] = defaultdict(list)

            for bookmaker, event in cluster.events.items():
                for market in markets_by_event.get(event.event_key, []):
                    if market.bookmaker != bookmaker:
                        continue
                    if not market_allowed_for_arb(market):
                        continue
                    if not _market_is_fresh(market, now=now, max_age_seconds=self.max_odds_age_seconds):
                        continue
                    line = resolve_market_line(market)
                    if market_requires_line(market.market_key) and line is None:
                        continue
                    if not _line_ok_for_cross_book_arb(market.market_key, line):
                        continue
                    group_key = market_spec_group_key(market, line=line)
                    grouped[group_key].append(market)

            for group_key, market_list in grouped.items():
                market_key, period, _sub_type, _team_scope, line, _spec_id = group_key

                if len(market_list) < 2:

                    continue



                opp = self._scan_market(cluster, market_key, period, line, market_list)

                if opp:

                    opportunities.append(opp)



        return sorted(opportunities, key=lambda o: o.margin_pct, reverse=True)

    def _scan_market(

        self,

        cluster: MatchedEvent,

        market_key: str,

        period: MarketPeriod,

        line: float | None,

        markets: list[MarketOdds],

    ) -> ArbitrageOpportunity | None:

        best_by_side: dict[OutcomeSide, dict[str, Any]] = {}

        for market in markets:
            if market.period != period:
                continue
            market_line = resolve_market_line(market)
            if line is not None:
                if market_line is None or abs(market_line - line) > 0.01:
                    continue
            elif market_line is not None:
                continue

            swapped = cluster.teams_swapped.get(market.bookmaker.value, False)

            for outcome in market.outcomes:
                if label_has_unresolved_template(outcome.label):
                    continue
                if not outcome_matches_line(outcome.line, market.line, line):
                    continue

                side = outcome.side
                if swapped and side in (OutcomeSide.HOME, OutcomeSide.AWAY):
                    side = OutcomeSide.AWAY if side == OutcomeSide.HOME else OutcomeSide.HOME

                current = best_by_side.get(side)
                if current is None or outcome.price > current["price"]:
                    book_event = cluster.events.get(market.bookmaker)
                    leg_payload: dict[str, Any] = {
                        "bookmaker": market.bookmaker.value,
                        "side": side.value,
                        "label": outcome.label,
                        "price": outcome.price,
                        "line": line,
                        "period": period.value,
                        "event_key": market.event_key,
                    }
                    if book_event:
                        leg_payload["external_id"] = book_event.external_id
                        leg_payload["parent_match_id"] = (
                            book_event.parent_match_id or book_event.external_id
                        )
                        raw_event = book_event.raw or {}
                        if raw_event.get("gameId") is not None:
                            leg_payload["game_id"] = str(raw_event["gameId"])
                        elif raw_event.get("game_id") is not None:
                            leg_payload["game_id"] = str(raw_event["game_id"])
                    if outcome.external_outcome_id:
                        leg_payload["external_outcome_id"] = str(outcome.external_outcome_id)
                    if market.sub_type_id:
                        leg_payload["sub_type_id"] = str(market.sub_type_id)
                    outcome_raw = outcome.raw or {}
                    if outcome_raw.get("typeId") is not None:
                        leg_payload["outcome_type_id"] = str(outcome_raw["typeId"])
                    if outcome_raw.get("marketId") is not None:
                        leg_payload["market_id"] = str(outcome_raw["marketId"])
                    best_by_side[side] = leg_payload

        if market_key in THREE_WAY_MARKET_KEYS:
            required = (OutcomeSide.HOME, OutcomeSide.DRAW, OutcomeSide.AWAY)
            if any(side not in best_by_side for side in required):
                return None
            legs = [best_by_side[side] for side in required]
        elif len(best_by_side) < 2:
            return None
        elif len(best_by_side) >= 3 and OutcomeSide.DRAW in best_by_side:
            legs = [
                best_by_side[s]
                for s in (OutcomeSide.HOME, OutcomeSide.DRAW, OutcomeSide.AWAY)
                if s in best_by_side
            ]
        else:
            legs = list(best_by_side.values())

        prices = [leg["price"] for leg in legs]
        implied_sum, margin = arb_margin(prices)

        if margin <= 0:
            return None
        if margin < self.min_margin_pct:
            return None
        if self.max_margin_pct is not None and margin > self.max_margin_pct:
            return None

        bookies = [leg["bookmaker"] for leg in legs]
        if len(set(bookies)) != len(legs):
            return None



        staked_legs = optimal_stakes(legs, self.bankroll)

        display = self._market_display(markets, market_key, period, line)
        spec = market_spec_for(markets[0], line=line) if markets else None

        from moneyline.links.deep_links import attach_place_bet_urls

        return attach_place_bet_urls(
            ArbitrageOpportunity(
            cluster_id=cluster.cluster_id,
            sport=cluster.sport,
            market_key=market_key,
            market_display=display,
            period=period,
            line=line,
            home_team=cluster.home_team,
            away_team=cluster.away_team,
            competition=cluster.competition,
            start_time=cluster.start_time,
            margin_pct=round(margin, 3),
            implied_sum=round(implied_sum, 5),
            legs=staked_legs,
            fixture_id=cluster.fixture_id,
            match_confidence=cluster.match_confidence,
            market_spec_id=spec.spec_id() if spec else "",
            expires_at=_opportunity_expires_at(
                markets,
                now=datetime.now(timezone.utc),
                max_age_seconds=self.max_odds_age_seconds,
            ),
            )
        )



    def _market_display(

        self,

        markets: list[MarketOdds],

        market_key: str,

        period: MarketPeriod,

        line: float | None,

    ) -> str:

        base = markets[0].market_display if markets else market_key.replace("_", " ").title()

        parts = [base, period_label(period)]

        if line is not None:
            if market_key in _WHOLE_LINE_TOTAL_MARKETS:
                parts.append(f"Over/Under {format_line(line)}")
            else:
                parts.append(f"Line {format_line(line)}")

        return " | ".join(parts)



    def scan_single_market_across_books(

        self, markets: list[MarketOdds]

    ) -> ArbitrageOpportunity | None:

        if not markets:

            return None

        from moneyline.models.schemas import Event



        fake_event = Event(

            event_key=markets[0].event_key,

            bookmaker=markets[0].bookmaker,

            external_id="",

            sport=markets[0].sport,

            home_team="",

            away_team="",

            start_time=markets[0].fetched_at,

        )

        cluster = MatchedEvent(

            cluster_id="single",

            sport=markets[0].sport,

            home_team="",

            away_team="",

            start_time=markets[0].fetched_at,

            teams_swapped={},

            events={m.bookmaker: fake_event for m in markets},

        )

        by_event = {m.event_key: markets for m in markets}

        results = self.find_arbitrage([cluster], by_event)

        return results[0] if results else None


