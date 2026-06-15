from __future__ import annotations



import json

import urllib.parse



from dateutil import parser as date_parser



from moneyline.bookmakers.base import BookmakerAdapter

from moneyline.events.limits import event_limit_reached, is_unlimited_event_limit

from moneyline.events.prematch import row_is_live
from moneyline.events.window import event_in_window, page_starts_after_window

from moneyline.markets.name_mapper import NameMarketMapper, side_from_label
from moneyline.markets.normalizer import MarketNormalizer
from moneyline.markets.period import resolve_outcome_label

from moneyline.models.schemas import Bookmaker, Event, MarketOdds, OddsOutcome, Sport





class BetPawaAdapter(BookmakerAdapter):

    bookmaker = Bookmaker.BETPAWA



    def __init__(self) -> None:

        super().__init__()

        self.mapper = NameMarketMapper()
        self.normalizer = MarketNormalizer()

        self._api = f"{self.config['base_url'].rstrip('/')}/v3"



    def _events_query(self, category_id: str, limit: int, *, skip: int = 0) -> str:

        payload = {

            "queries": [

                {

                    "query": {"eventType": "UPCOMING", "categories": [category_id]},

                    "view": {"marketTypes": ["1X2"]},

                    "sort": {"startTime": "ASC"},

                    "take": limit,

                    "skip": skip,

                }

            ]

        }

        return urllib.parse.quote(json.dumps(payload, separators=(",", ":")))



    async def fetch_prematch_events(

        self,

        sport: Sport,

        limit: int = 100,

        *,

        lookahead_hours: int | None = None,

    ) -> list[Event]:

        hours = self.resolve_lookahead_hours(lookahead_hours)

        category_id = self.sport_param(sport)

        events: list[Event] = []

        page_size = 100

        skip = 0

        max_skip = 20_000 if is_unlimited_event_limit(limit) else 1_000



        while True:

            url = (

                f"{self._api}/events/lists/by-queries?"

                f"q={self._events_query(category_id, page_size, skip=skip)}"

            )

            resp = await self._get(url)

            batch: list[dict] = []

            for block in resp.json().get("responses", []):

                batch.extend(block.get("responses", []) or [])

            if not batch:

                break



            page_starts = [

                date_parser.parse(str(row["startTime"]))

                for row in batch

                if row.get("startTime")

            ]

            if page_starts_after_window(page_starts, hours):

                break



            for row in batch:

                if event_limit_reached(len(events), limit):

                    break

                if row_is_live(row):
                    continue

                participants = sorted(row.get("participants", []), key=lambda p: p.get("position", 0))

                if len(participants) < 2:

                    continue

                start = date_parser.parse(str(row["startTime"]))

                if not event_in_window(start, hours):

                    continue

                home = participants[0]["name"]

                away = participants[1]["name"]

                eid = str(row["id"])

                widget_id = next(

                    (w["id"] for w in row.get("widgets", []) if w.get("type") == "SPORTRADAR"),

                    eid,

                )

                events.append(

                    Event(

                        event_key=f"betpawa:{eid}",

                        bookmaker=Bookmaker.BETPAWA,

                        external_id=eid,

                        parent_match_id=str(widget_id),

                        sport=sport,

                        home_team=str(home),

                        away_team=str(away),

                        competition=str(row.get("competition", {}).get("name", "")),

                        start_time=start,

                        is_live=False,

                        raw=row,

                    )

                )



            if event_limit_reached(len(events), limit):

                break

            if len(batch) < page_size:

                break

            skip += page_size

            if skip > max_skip:

                break



        return self.finalize_prematch_events(events, limit, hours)



    async def fetch_event_markets(

        self, event: Event, sport: Sport, *, is_live: bool = False

    ) -> list[MarketOdds]:

        resp = await self._get(f"{self._api}/events/{event.external_id}")

        markets: list[MarketOdds] = []



        for row in resp.json().get("markets", []) or []:

            mt = row.get("marketType", {})

            name = str(mt.get("displayName") or mt.get("name", ""))

            mt_id = str(mt.get("id", ""))
            from moneyline.markets.book_maps import resolve_betpawa_market_type

            hit = None
            canonical_key = resolve_betpawa_market_type(sport, mt_id)
            if canonical_key:
                spec = self.mapper.market_spec(sport, canonical_key)
                if spec:
                    hit = (canonical_key, spec)
            if not hit:
                hit = self.mapper.resolve(sport, name)
            if not hit:
                continue
            _, spec = hit

            outcomes: list[OddsOutcome] = []



            for price_row in row.get("row", []) or []:

                line = price_row.get("handicap")

                for price in price_row.get("prices", []) or []:

                    p = float(price.get("price") or 0)

                    if p <= 1:

                        continue

                    label = resolve_outcome_label(

                        str(price.get("displayName") or price.get("name", "")),

                        float(line) if line is not None else None,

                    )

                    side = side_from_label(label, spec)

                    if side is None:

                        continue

                    outcomes.append(

                        OddsOutcome(

                            side=side,

                            label=label,

                            price=p,

                            line=float(line) if line is not None else None,

                            external_outcome_id=str(price.get("id", "")),

                            raw=price,

                        )

                    )



            built = self.mapper.build_market(

                sport=sport,

                bookmaker=Bookmaker.BETPAWA,

                event_key=event.event_key,

                market_name=name,

                outcomes=outcomes,

                is_live=is_live,

            )

            if built:

                markets.extend(self.normalizer.expand_by_line(built))

        return markets


