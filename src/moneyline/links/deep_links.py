"""Per-bookmaker deep links to match pages and selections."""

from __future__ import annotations

import urllib.parse
from typing import Any

from moneyline.models.schemas import ArbitrageOpportunity, Sport

_SPORTY_SPORT_SLUG: dict[str, str] = {
    Sport.SOCCER.value: "football",
    Sport.TENNIS.value: "tennis",
    Sport.BASKETBALL.value: "basketball",
    Sport.VOLLEYBALL.value: "volleyball",
    Sport.HANDBALL.value: "handball",
    Sport.BASEBALL.value: "baseball",
    Sport.CRICKET.value: "cricket",
    Sport.ICE_HOCKEY.value: "ice-hockey",
}

_ODIBETS_SPORT_SLUG: dict[str, str] = {
    Sport.SOCCER.value: "soccer",
    Sport.TENNIS.value: "tennis",
    Sport.BASKETBALL.value: "basketball",
    Sport.VOLLEYBALL.value: "volleyball",
    Sport.HANDBALL.value: "handball",
    Sport.BASEBALL.value: "baseball",
    Sport.CRICKET.value: "cricket",
    Sport.ICE_HOCKEY.value: "ice-hockey",
}


def _query_url(base: str, params: dict[str, str]) -> str:
    clean = {k: v for k, v in params.items() if v}
    if not clean:
        return base
    return f"{base}?{urllib.parse.urlencode(clean)}"


def _match_id(leg: dict[str, Any]) -> str:
    return str(leg.get("parent_match_id") or leg.get("external_id") or "").strip()


def _event_id(leg: dict[str, Any]) -> str:
    return str(leg.get("external_id") or leg.get("parent_match_id") or "").strip()


def build_place_bet_url(leg: dict[str, Any], *, sport: str, market_key: str = "") -> str | None:
    """Return a bookmaker URL for the leg's match and selection when possible."""
    del market_key  # reserved for future market-specific routes
    bookmaker = str(leg.get("bookmaker", "")).lower()
    match_id = _match_id(leg)
    event_id = _event_id(leg)
    outcome_id = str(leg.get("external_outcome_id") or "").strip()
    sub_type_id = str(leg.get("sub_type_id") or "").strip()
    outcome_type_id = str(leg.get("outcome_type_id") or "").strip()
    market_id = str(leg.get("market_id") or "").strip()
    game_id = str(leg.get("game_id") or "").strip()

    if bookmaker in {"betika", "pepeta"}:
        if not match_id:
            return None
        site = "https://www.betika.com/en-ke" if bookmaker == "betika" else "https://www.pepeta.com"
        return _query_url(
            f"{site}/m/bet/{match_id}",
            {"sub_type_id": sub_type_id, "outcome_id": outcome_id},
        )

    if bookmaker == "odibets":
        if not match_id:
            return None
        return _query_url(
            f"https://odibets.com/match-details/{match_id}",
            {"sub_type_id": sub_type_id, "outcome_id": outcome_id},
        )

    if bookmaker == "sportybet":
        slug = _SPORTY_SPORT_SLUG.get(sport, sport.replace("_", "-"))
        target = event_id or game_id
        if not target:
            return None
        encoded = urllib.parse.quote(target, safe="")
        params: dict[str, str] = {}
        if outcome_id:
            params["outcomeId"] = outcome_id
        if market_id:
            params["marketId"] = market_id
        return _query_url(
            f"https://www.sportybet.com/ke/m/sport/{slug}/event/{encoded}",
            params,
        )

    if bookmaker == "betpawa":
        if not event_id:
            return None
        params = {}
        if outcome_id:
            params["outcomeId"] = outcome_id
            params["priceId"] = outcome_id
        elif outcome_type_id:
            params["priceId"] = outcome_type_id
        return _query_url(f"https://www.betpawa.co.ke/event/{event_id}", params)

    if bookmaker == "sportpesa":
        if not event_id:
            return None
        slug = _ODIBETS_SPORT_SLUG.get(sport, sport.replace("_", "-"))
        params = {}
        if outcome_id:
            params["selection"] = outcome_id
        return _query_url(f"https://www.ke.sportpesa.com/en/sports-betting/{slug}/games/{event_id}", params)

    if bookmaker == "mozzartbet":
        if not event_id:
            return None
        return f"https://www.mozzartbet.co.ke/en#/match/{event_id}"

    if bookmaker == "bangbet":
        if not event_id:
            return None
        encoded = urllib.parse.quote(event_id, safe="")
        return f"https://www.bangbet.com/sport/match/{encoded}"

    if bookmaker == "shabiki":
        if not event_id:
            return None
        params = {}
        if outcome_id:
            params["selection"] = outcome_id
        return _query_url(f"https://shabiki.com/match/{event_id}", params)

    if bookmaker == "palmsbet":
        if not event_id:
            return None
        params = {}
        if outcome_id:
            params["selection"] = outcome_id
        return _query_url(f"https://www.palmsbet.co.ke/sports#/event/{event_id}", params)

    return None


def attach_place_bet_urls(opportunity: ArbitrageOpportunity) -> ArbitrageOpportunity:
    """Add place_bet_url to each leg on a copy of the opportunity."""
    sport = opportunity.sport.value
    market_key = opportunity.market_key
    updated_legs: list[dict[str, Any]] = []
    for leg in opportunity.legs:
        enriched = dict(leg)
        enriched["place_bet_url"] = build_place_bet_url(enriched, sport=sport, market_key=market_key)
        updated_legs.append(enriched)
    return opportunity.model_copy(update={"legs": updated_legs})
