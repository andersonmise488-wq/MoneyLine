from __future__ import annotations

import time
from datetime import datetime, timezone

from dateutil import parser as date_parser

from moneyline.bookmakers.base import BookmakerAdapter
from moneyline.events.limits import event_limit_reached, max_pages_for, page_size_for
from moneyline.events.prematch import prematch_producer_id, row_is_live
from moneyline.events.window import event_in_window
from moneyline.markets.handicap import (
    parse_handicap_line,
    side_from_asian_label,
    side_from_european_label,
)
from moneyline.markets.name_mapper import NameMarketMapper, side_from_label
from moneyline.markets.normalizer import MarketNormalizer
from moneyline.matching.ids import normalize_parent_match_id
from moneyline.models.schemas import Bookmaker, Event, MarketOdds, OddsOutcome, Sport


class BangBetAdapter(BookmakerAdapter):
    bookmaker = Bookmaker.BANGBET

    def __init__(self) -> None:
        super().__init__()
        self.mapper = NameMarketMapper()
        self.normalizer = MarketNormalizer()
        self._base = self.config["base_url"].rstrip("/")

    async def fetch_prematch_events(
        self,
        sport: Sport,
        limit: int = 100,
        *,
        lookahead_hours: int | None = None,
    ) -> list[Event]:
        hours = self.resolve_lookahead_hours(lookahead_hours)
        sport_id = self.sport_param(sport)
        events: list[Event] = []
        page = 1
        page_size = page_size_for(limit, default=50, maximum=200)
        max_pages = max_pages_for(limit, capped=20, unlimited=100)
        now_ms = int(time.time() * 1000)
        cutoff_ms = now_ms + hours * 3600 * 1000
        api_total: int | None = None

        while True:
            resp = await self._post(
                f"{self._base}/match/list",
                json={"pageNo": page, "pageSize": page_size, "sportId": sport_id},
            )
            payload = resp.json()
            data = payload.get("data", {}) or {}
            if api_total is None:
                api_total = int(data.get("total") or 0)
            groups = data.get("data", [])
            if not groups:
                break

            page_rows: list[dict] = []
            for group in groups:
                page_rows.extend(group.get("matchVoList", []))

            past_cutoff = False
            for row in page_rows:
                if row_is_live(row):
                    continue
                sched_ms = int(row.get("scheduledTime") or 0)
                if sched_ms and sched_ms > cutoff_ms:
                    past_cutoff = True
                    continue
                if row.get("simTag", 0) == 1 or row.get("virtualTag", 0) == 1:
                    continue
                if event_limit_reached(len(events), limit):
                    break
                if sched_ms:
                    if row.get("scheduledDate"):
                        start = date_parser.parse(str(row["scheduledDate"]))
                    else:
                        start = datetime.fromtimestamp(sched_ms / 1000, tz=timezone.utc)
                elif row.get("scheduledDate"):
                    start = date_parser.parse(str(row["scheduledDate"]))
                else:
                    continue
                if not event_in_window(start, hours):
                    continue
                match_id = str(row["id"])
                parent_id = normalize_parent_match_id(str(row.get("betradarId") or match_id)) or match_id
                events.append(
                    Event(
                        event_key=f"bangbet:{match_id}",
                        bookmaker=Bookmaker.BANGBET,
                        external_id=match_id,
                        parent_match_id=parent_id,
                        sport=sport,
                        home_team=str(row["homeTeamName"]),
                        away_team=str(row["awayTeamName"]),
                        competition=str(row.get("tournamentName", "")),
                        start_time=start,
                        is_live=False,
                        raw=row,
                    )
                )

            if event_limit_reached(len(events), limit):
                break
            fetched_so_far = page * page_size
            if len(page_rows) < page_size or past_cutoff:
                break
            if api_total and fetched_so_far >= api_total:
                break
            page += 1
            if page > max_pages:
                break

        return self.finalize_prematch_events(events, limit, hours)

    async def fetch_event_markets(
        self, event: Event, sport: Sport, *, is_live: bool = False
    ) -> list[MarketOdds]:
        producer = prematch_producer_id(event.raw)
        resp = await self._post(
            f"{self._base}/match/odds",
            json={"matchId": event.external_id, "producer": producer},
        )
        data = resp.json().get("data", {})
        markets: list[MarketOdds] = []

        for group in data.get("marketList", []) or []:
            for mkt in group.get("markets", []) or []:
                name = str(mkt.get("name", group.get("name", "")))
                hit = self.mapper.resolve(sport, name)
                if not hit:
                    continue
                _, spec = hit
                allowed = set(spec.get("outcomes", []))
                outcomes: list[OddsOutcome] = []
                line = parse_handicap_line(mkt.get("specifiers"), name)

                for oc in mkt.get("outcomes", []) or []:
                    price = float(oc.get("odds") or 0)
                    if price <= 1:
                        continue
                    label = str(oc.get("desc") or oc.get("name", ""))
                    oc_id = str(oc.get("id", ""))
                    side = side_from_european_label(label, oc_id, allowed=allowed)
                    if side is None:
                        side = side_from_asian_label(label, oc_id, allowed=allowed)
                    if side is None:
                        side = side_from_label(label, spec) or side_from_label(oc_id, spec)
                    if side is None:
                        continue
                    oc_line = line or parse_handicap_line(oc.get("desc"), oc.get("name"))
                    outcomes.append(
                        OddsOutcome(
                            side=side,
                            label=label,
                            price=price,
                            line=oc_line,
                            external_outcome_id=oc_id,
                            raw=oc,
                        )
                    )

                built = self.mapper.build_market(
                    sport=sport,
                    bookmaker=Bookmaker.BANGBET,
                    event_key=event.event_key,
                    market_name=name,
                    outcomes=outcomes,
                    is_live=is_live,
                    line=line,
                )
                if built:
                    markets.extend(self.normalizer.expand_by_line(built))
        return markets
