from __future__ import annotations

from moneyline.markets.guard import is_combo_market, is_interval_market
from moneyline.markets.handicap import side_from_european_label
from moneyline.markets.period import detect_period
from moneyline.markets.registry import MarketRegistry
from moneyline.models.schemas import Bookmaker, MarketOdds, OddsOutcome, OutcomeSide, Sport

_THREE_WAY_MARKET_KEYS = frozenset(
    {"match_result_1x2", "european_handicap", "period_betting", "first_5_innings"}
)
_TWO_WAY_WINNER_KEYS = frozenset({"match_winner", "moneyline"})
_THREE_WAY_SIDES = frozenset({OutcomeSide.HOME, OutcomeSide.DRAW, OutcomeSide.AWAY})
_TWO_WAY_WINNER_SIDES = frozenset({OutcomeSide.HOME, OutcomeSide.AWAY})


class NameMarketMapper(MarketRegistry):
    """Resolve bookmaker market labels and build normalized MarketOdds."""

    def build_market(
        self,
        *,
        sport: Sport,
        bookmaker: Bookmaker,
        event_key: str,
        market_name: str,
        outcomes: list[OddsOutcome],
        is_live: bool = False,
        line: float | None = None,
        sub_type_id: str | None = None,
    ) -> MarketOdds | None:
        hit = self.resolve(sport, market_name)
        if not hit:
            return None
        if is_combo_market(market_name) or is_interval_market(market_name):
            return None
        market_key, spec = hit
        if spec.get("live_only") and not is_live:
            return None
        if not outcomes:
            return None
        sides = {o.side for o in outcomes}
        allowed = set(spec.get("outcomes", []))
        if market_key in _THREE_WAY_MARKET_KEYS:
            if sides != _THREE_WAY_SIDES:
                return None
        elif "draw" in allowed:
            if sides != _THREE_WAY_SIDES:
                return None
        elif allowed <= _TWO_WAY_WINNER_SIDES:
            if sides != _TWO_WAY_WINNER_SIDES:
                return None
        period = detect_period(market_name, market_key, spec)
        return MarketOdds(
            event_key=event_key,
            bookmaker=bookmaker,
            sport=sport,
            market_key=market_key,
            market_display=spec["display"],
            is_live=is_live,
            line=line,
            period=period,
            outcomes=outcomes,
            raw_market_name=market_name,
            sub_type_id=sub_type_id,
        )


def parse_1x2_outcomes(
    home_price: float | None = None,
    draw_price: float | None = None,
    away_price: float | None = None,
    *,
    home_label: str = "1",
    draw_label: str = "X",
    away_label: str = "2",
) -> list[OddsOutcome]:
    out: list[OddsOutcome] = []
    if home_price and home_price > 1:
        out.append(OddsOutcome(side=OutcomeSide.HOME, label=home_label, price=float(home_price)))
    if draw_price and draw_price > 1:
        out.append(OddsOutcome(side=OutcomeSide.DRAW, label=draw_label, price=float(draw_price)))
    if away_price and away_price > 1:
        out.append(OddsOutcome(side=OutcomeSide.AWAY, label=away_label, price=float(away_price)))
    return out


def side_from_label(
    label: str,
    spec: dict,
    selection_type_id: str | int | None = None,
) -> OutcomeSide | None:
    allowed = set(spec.get("outcomes", []))
    if "draw" in allowed:
        euro = side_from_european_label(label, selection_type_id, allowed=allowed)
        if euro is not None:
            return euro
    n = label.strip().lower()
    n = " ".join(n.split())
    if n in ("1", "home", "w1") and "home" in allowed:
        return OutcomeSide.HOME
    if n.startswith("team 1") or n.startswith("home") or n.startswith("w1"):
        if "home" in allowed:
            return OutcomeSide.HOME
    if n in ("x", "draw") or n.startswith("draw") or n.startswith("tie"):
        if "draw" in allowed:
            return OutcomeSide.DRAW
    if n in ("2", "away", "w2") and "away" in allowed:
        return OutcomeSide.AWAY
    if n.startswith("team 2") or n.startswith("away") or n.startswith("w2"):
        if "away" in allowed:
            return OutcomeSide.AWAY
    if n in ("h1", "w1") and "home" in allowed:
        return OutcomeSide.HOME
    if n in ("h2", "w2") and "away" in allowed:
        return OutcomeSide.AWAY
    if "over" in n and "over" in allowed:
        return OutcomeSide.OVER
    if "under" in n and "under" in allowed:
        return OutcomeSide.UNDER
    if n in ("yes", "gg") and "yes" in allowed:
        return OutcomeSide.YES
    if n in ("no", "ng") and "no" in allowed:
        return OutcomeSide.NO
    if "score" in allowed:
        return OutcomeSide.SCORE
    if "player" in allowed:
        return OutcomeSide.PLAYER
    return None
