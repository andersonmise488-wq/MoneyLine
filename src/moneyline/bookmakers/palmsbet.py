from __future__ import annotations

from datetime import datetime, timezone

from moneyline.bookmakers.base import BookmakerAdapter
from moneyline.events.limits import event_limit_reached, is_unlimited_event_limit
from moneyline.events.prematch import row_is_live
from moneyline.events.window import event_in_window
from moneyline.markets.handicap import (
    parse_handicap_line,
    side_from_asian_label,
    side_from_european_label,
    side_from_yes_no_label,
)
from moneyline.markets.name_mapper import NameMarketMapper, side_from_label
from moneyline.markets.normalizer import MarketNormalizer
from moneyline.models.schemas import Bookmaker, Event, MarketOdds, OddsOutcome, Sport


class PalmsBetAdapter(BookmakerAdapter):
    bookmaker = Bookmaker.PALMSBET

    def __init__(self) -> None:
        super().__init__()
        self.mapper = NameMarketMapper()
        self.normalizer = MarketNormalizer()
        self._api = self.config["base_url"].rstrip("/")
        self._qs = self.config.get(
            "query_string",
            "timezoneOffset=-180&langId=8&skinName=palmsbet&integration=palmsbet.co.ke",
        )

    def _collect_events(self, nodes: list, out: list) -> None:
        for node in nodes:
            if isinstance(node, dict):
                if node.get("Events"):
                    out.extend(node["Events"])
                if node.get("Items"):
                    self._collect_events(node["Items"], out)

    async def fetch_prematch_events(
        self,
        sport: Sport,
        limit: int = 100,
        *,
        lookahead_hours: int | None = None,
    ) -> list[Event]:
        hours = self.resolve_lookahead_hours(lookahead_hours)
        sport_id = self.sport_param(sport)
        fetch_count = 500 if is_unlimited_event_limit(limit) else max(limit, 250)
        url = (
            f"{self._api}/Sportsbook/GetEvents?{self._qs}"
            f"&sportids={sport_id}&champids=0&categoryids=0&count={fetch_count}"
        )
        resp = await self._get(url)
        raw_events: list[dict] = []
        self._collect_events(resp.json().get("Result", {}).get("Items", []), raw_events)

        events: list[Event] = []
        for row in raw_events:
            if row_is_live(row):
                continue
            if event_limit_reached(len(events), limit):
                break
            comps = sorted(row.get("Competitors", []), key=lambda c: c.get("Order", 0))
            if len(comps) < 2:
                continue
            start = datetime.fromisoformat(str(row["EventDate"]).replace("Z", "+00:00"))
            if not event_in_window(start, hours):
                continue
            eid = str(row["Id"])
            events.append(
                Event(
                    event_key=f"palmsbet:{eid}",
                    bookmaker=Bookmaker.PALMSBET,
                    external_id=eid,
                    parent_match_id=str(row.get("ExtId") or eid),
                    sport=sport,
                    home_team=str(comps[0]["Name"]),
                    away_team=str(comps[1]["Name"]),
                    competition=str(row.get("ChampName", "")),
                    start_time=start,
                    is_live=False,
                    raw=row,
                )
            )

        return self.finalize_prematch_events(events, limit, hours)

    async def fetch_event_markets(
        self, event: Event, sport: Sport, *, is_live: bool = False
    ) -> list[MarketOdds]:
        url = f"{self._api}/Sportsbook/GetEventDetails?{self._qs}&eventId={event.external_id}"
        resp = await self._get(url)
        result = resp.json().get("Result", {})
        markets: list[MarketOdds] = []
        seen_market_ids: set[str] = set()

        for group in result.get("MarketGroups", []) or []:
            for mkt in group.get("Items", []) or []:
                market_id = str(mkt.get("Id") or "")
                if market_id and market_id in seen_market_ids:
                    continue
                if market_id:
                    seen_market_ids.add(market_id)
                name = str(mkt.get("Name", ""))
                hit = self.mapper.resolve(sport, name)
                if not hit:
                    continue
                _, spec = hit
                allowed = set(spec.get("outcomes", []))
                outcomes: list[OddsOutcome] = []

                for oc in mkt.get("Items", []) or []:
                    price = float(oc.get("Price") or 0)
                    if price <= 1:
                        continue
                    label = str(oc.get("Name", ""))
                    oc_id = str(oc.get("SelectionTypeId") or oc.get("Id") or "")
                    side = side_from_yes_no_label(label, oc_id, allowed=allowed)
                    if side is None:
                        side = side_from_european_label(label, oc_id, allowed=allowed)
                    if side is None:
                        side = side_from_asian_label(label, oc_id, allowed=allowed)
                    if side is None:
                        side = side_from_label(label, spec)
                    if side is None:
                        continue
                    line = parse_handicap_line(
                        oc.get("SPOV"),
                        mkt.get("SpecialOddsValue"),
                        name,
                        label,
                    )
                    outcomes.append(
                        OddsOutcome(
                            side=side,
                            label=label,
                            price=price,
                            line=line,
                            external_outcome_id=str(oc.get("Id", "")),
                            raw=oc,
                        )
                    )

                built = self.mapper.build_market(
                    sport=sport,
                    bookmaker=Bookmaker.PALMSBET,
                    event_key=event.event_key,
                    market_name=name,
                    outcomes=outcomes,
                    is_live=is_live,
                )
                if built:
                    markets.extend(self.normalizer.expand_by_line(built))
        return markets
