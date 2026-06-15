from __future__ import annotations

from dateutil import parser as date_parser

from moneyline.bookmakers.base import BookmakerAdapter
from moneyline.matching.ids import normalize_parent_match_id
from moneyline.events.limits import event_limit_reached, max_pages_for, page_size_for
from moneyline.events.prematch import row_is_live
from moneyline.events.window import event_in_window, page_starts_after_window
from moneyline.markets.normalizer import MarketNormalizer
from moneyline.models.schemas import Bookmaker, Event, MarketOdds, Sport
from moneyline.timezone import attach_eat_if_naive


class SportradarFeedAdapter(BookmakerAdapter):
    """Shared adapter for Sportradar white-label feeds (Betika, Pepeta)."""

    normalizer: MarketNormalizer

    def __init__(self, bookmaker: Bookmaker) -> None:
        self.bookmaker = bookmaker
        super().__init__()
        self.normalizer = MarketNormalizer()

    def _row_to_event(self, row: dict, sport: Sport) -> Event:
        start = attach_eat_if_naive(date_parser.parse(str(row["start_time"])))
        ext_id = str(row.get("parent_match_id") or row.get("match_id"))
        parent_id = normalize_parent_match_id(str(row.get("parent_match_id", ""))) or ext_id
        prefix = self.bookmaker.value
        return Event(
            event_key=f"{prefix}:{ext_id}",
            bookmaker=self.bookmaker,
            external_id=ext_id,
            parent_match_id=parent_id,
            sport=sport,
            home_team=str(row["home_team"]),
            away_team=str(row["away_team"]),
            competition=str(row.get("competition_name", "")),
            start_time=start,
            is_live=False,
            raw=row,
        )

    async def _fetch_standard_pages(
        self,
        sport: Sport,
        *,
        hours: int,
        limit: int,
    ) -> list[Event]:
        sport_id = self.sport_param(sport)
        events: list[Event] = []
        page = 0
        page_size = page_size_for(limit, default=50, maximum=200)
        max_pages = max_pages_for(limit, capped=30, unlimited=300)

        while True:
            url = self._resolve_url(
                self.config["endpoints"]["prematch_matches"].format(
                    page=page, limit=page_size, sport_id=sport_id
                )
            )
            resp = await self._get(url)
            rows = resp.json().get("data", []) or []
            if not rows:
                break

            page_starts = [date_parser.parse(str(row["start_time"])) for row in rows]
            if page_starts_after_window(page_starts, hours):
                break

            for row in rows:
                if row.get("is_srl") or row.get("is_esport"):
                    continue
                if row_is_live(row):
                    continue
                event = self._row_to_event(row, sport)
                if not event_in_window(event.start_time, hours):
                    continue
                events.append(event)
                if event_limit_reached(len(events), limit):
                    break

            if event_limit_reached(len(events), limit):
                break
            if len(rows) < page_size:
                break
            page += 1
            if page >= max_pages:
                break

        return events

    async def _fetch_relaxed_pages(
        self,
        sport: Sport,
        *,
        hours: int,
        limit: int,
    ) -> list[Event]:
        """SHARK-style listing without betika filter params (page 1-based)."""
        sport_id = self.sport_param(sport)
        events: list[Event] = []
        page = 1
        page_size = 50
        max_pages = 30
        base = self.config["base_url"].rstrip("/")

        while page <= max_pages:
            url = f"{base}/v1/uo/matches?sport_id={sport_id}&limit={page_size}&page={page}"
            resp = await self._get(url)
            payload = resp.json()
            rows = payload.get("data", []) or []
            if not rows:
                break
            for row in rows:
                if row.get("is_srl") or row.get("is_esport"):
                    continue
                if row_is_live(row):
                    continue
                event = self._row_to_event(row, sport)
                if not event_in_window(event.start_time, hours):
                    continue
                events.append(event)
                if event_limit_reached(len(events), limit):
                    return events
            meta = payload.get("meta") or {}
            total = int(meta.get("total") or 0)
            if len(rows) < page_size or page * page_size >= total:
                break
            page += 1
        return events

    async def _fetch_via_competitions(
        self,
        sport: Sport,
        *,
        hours: int,
        limit: int,
    ) -> list[Event]:
        """Walk /v1/uo/sports tree and pull matches per competition (Pepeta pattern)."""
        sport_id = self.sport_param(sport)
        base = self.config["base_url"].rstrip("/")
        events: list[Event] = []
        seen: set[str] = set()

        try:
            resp = await self._get(f"{base}/v1/uo/sports")
            sports_tree = resp.json().get("data", []) or []
        except Exception:
            return []

        target = next((s for s in sports_tree if str(s.get("sport_id")) == str(sport_id)), None)
        if not target:
            return []

        competition_ids: list[str] = []
        for category in target.get("categories") or []:
            for comp in category.get("competitions") or []:
                cid = comp.get("competition_id")
                if cid is not None:
                    competition_ids.append(str(cid))

        for cid in competition_ids:
            if event_limit_reached(len(events), limit):
                break
            page = 1
            while page <= 5:
                try:
                    resp = await self._get(
                        f"{base}/v1/uo/matches?competition_id={cid}&limit=50&page={page}"
                    )
                    rows = resp.json().get("data", []) or []
                except Exception:
                    break
                if not rows:
                    break
                for row in rows:
                    if row.get("is_srl") or row.get("is_esport"):
                        continue
                    if row_is_live(row):
                        continue
                    event = self._row_to_event(row, sport)
                    if event.external_id in seen:
                        continue
                    if not event_in_window(event.start_time, hours):
                        continue
                    seen.add(event.external_id)
                    events.append(event)
                    if event_limit_reached(len(events), limit):
                        break
                if len(rows) < 50:
                    break
                page += 1

        return events

    async def fetch_prematch_events(
        self,
        sport: Sport,
        limit: int = 100,
        *,
        lookahead_hours: int | None = None,
    ) -> list[Event]:
        hours = self.resolve_lookahead_hours(lookahead_hours)
        events = await self._fetch_standard_pages(sport, hours=hours, limit=limit)

        if not events:
            events = await self._fetch_relaxed_pages(sport, hours=hours, limit=limit)

        if self.config.get("competition_listing"):
            extra = await self._fetch_via_competitions(sport, hours=hours, limit=limit)
            seen = {e.external_id for e in events}
            for event in extra:
                if event.external_id in seen:
                    continue
                events.append(event)
                seen.add(event.external_id)
                if event_limit_reached(len(events), limit):
                    break

        return self.finalize_prematch_events(events, limit, hours)

    async def fetch_event_markets(
        self, event: Event, sport: Sport, *, is_live: bool = False
    ) -> list[MarketOdds]:
        parent_id = event.parent_match_id or event.external_id
        url = self._resolve_url(
            self.config["endpoints"]["match_markets"].format(parent_match_id=parent_id)
        )
        payload = (await self._get(url)).json()
        markets: list[MarketOdds] = []

        for row in payload.get("data", []) or []:
            normalized = self.normalizer.normalize_betika_market(
                sport=sport,
                sub_type_id=str(row.get("sub_type_id", "")),
                market_name=str(row.get("name", "")),
                outcomes_raw=row.get("odds", []),
                bookmaker=self.bookmaker,
                is_live=is_live,
                event_key=event.event_key,
            )
            if normalized:
                markets.extend(self.normalizer.expand_by_line(normalized))
        return markets
