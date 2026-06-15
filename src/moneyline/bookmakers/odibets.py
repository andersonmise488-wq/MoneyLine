from __future__ import annotations

from dateutil import parser as date_parser

from moneyline.bookmakers.base import BookmakerAdapter
from moneyline.events.limits import event_limit_reached, is_unlimited_event_limit
from moneyline.events.prematch import row_is_live
from moneyline.events.window import event_in_window
from moneyline.markets.normalizer import MarketNormalizer
from moneyline.matching.ids import normalize_parent_match_id
from moneyline.models.schemas import Bookmaker, Event, MarketOdds, Sport
from moneyline.timezone import attach_eat_if_naive


class OdibetsAdapter(BookmakerAdapter):
    bookmaker = Bookmaker.ODIBETS

    def __init__(self) -> None:
        super().__init__()
        self.normalizer = MarketNormalizer()
        self._odi_api = str(
            self.config.get("odi_api_url") or "https://api.odi.site/sportsbook/v1"
        ).rstrip("/")

    def _row_to_event(self, row: dict, sport: Sport) -> Event | None:
        if row_is_live(row):
            return None
        ext_id = str(row.get("parent_match_id", ""))
        if not ext_id:
            return None
        parent_id = normalize_parent_match_id(ext_id) or ext_id
        start = attach_eat_if_naive(date_parser.parse(str(row["start_time"])))
        return Event(
            event_key=f"odibets:{ext_id}",
            bookmaker=Bookmaker.ODIBETS,
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

    async def _fetch_day_page(
        self,
        sport: Sport,
        *,
        day: int,
        page: int,
        page_size: int,
    ) -> list[dict]:
        slug = self.sport_param(sport)
        url = self._resolve_url(
            self.config["endpoints"]["prematch_matches"].format(
                sport_slug=slug,
                day=day,
                page=page,
                per_page=page_size,
            )
        )
        resp = await self._get(url)
        rows: list[dict] = []
        for comp in resp.json().get("data", {}).get("competitions", []):
            rows.extend(comp.get("matches") or [])
        return rows

    async def _odi_get(self, params: dict) -> dict:
        """SHARK pattern: api.odi.site sportsbook/v1 query API."""
        from urllib.parse import urlencode

        url = f"{self._odi_api}?{urlencode(params)}"
        resp = await self._get(
            url,
            headers={
                **self.headers,
                "Authorization": "Bearer",
                "Origin": "https://odibets.com",
                "Referer": "https://odibets.com/",
            },
        )
        payload = resp.json()
        if isinstance(payload, dict) and payload.get("status_code") not in (None, 200, 0):
            raise RuntimeError(payload.get("status_description") or "odi API error")
        return payload.get("data", payload) if isinstance(payload, dict) else payload

    async def _fetch_competition_events(
        self,
        sport: Sport,
        *,
        hours: int,
        limit: int,
    ) -> list[Event]:
        """SHARK pattern: list competitions, then fetch matches per league."""
        slug = self.sport_param(sport)
        if not slug:
            return []
        try:
            comp_data = await self._odi_get(
                {"sport_id": slug, "per_page": "1000", "sportsbook": "sportsbook", "resource": "sport"}
            )
        except Exception:
            return []

        competitions = comp_data.get("competitions", []) if isinstance(comp_data, dict) else []
        events: list[Event] = []
        seen: set[str] = set()

        for comp in competitions:
            if event_limit_reached(len(events), limit):
                break
            cid = comp.get("competition_id")
            if not cid:
                continue
            try:
                match_data = await self._odi_get(
                    {
                        "sport_id": slug,
                        "competition_id": str(cid),
                        "per_page": "1000",
                        "sportsbook": "sportsbook",
                        "resource": "sport",
                    }
                )
            except Exception:
                continue
            rows = match_data.get("matches", []) if isinstance(match_data, dict) else []
            for row in rows:
                event = self._row_to_event(row, sport)
                if event is None or event.external_id in seen:
                    continue
                if not event_in_window(event.start_time, hours):
                    continue
                seen.add(event.external_id)
                events.append(event)
                if event_limit_reached(len(events), limit):
                    break
        return events

    async def fetch_prematch_events(
        self,
        sport: Sport,
        limit: int = 100,
        *,
        lookahead_hours: int | None = None,
    ) -> list[Event]:
        hours = self.resolve_lookahead_hours(lookahead_hours)
        events: list[Event] = []
        seen: set[str] = set()

        for event in await self._fetch_competition_events(sport, hours=hours, limit=limit):
            seen.add(event.external_id)
            events.append(event)

        page_size = 100
        max_days = 8 if is_unlimited_event_limit(limit) else 4
        max_pages = 30 if is_unlimited_event_limit(limit) else 5

        for day in range(max_days):
            page = 1
            while page <= max_pages:
                rows = await self._fetch_day_page(
                    sport, day=day, page=page, page_size=page_size
                )
                if not rows:
                    break

                added_on_page = 0
                for row in rows:
                    event = self._row_to_event(row, sport)
                    if event is None or event.external_id in seen:
                        continue
                    if not event_in_window(event.start_time, hours):
                        continue
                    seen.add(event.external_id)
                    events.append(event)
                    added_on_page += 1
                    if event_limit_reached(len(events), limit):
                        break

                if event_limit_reached(len(events), limit):
                    break
                if len(rows) < page_size:
                    break
                page += 1

            if event_limit_reached(len(events), limit):
                break

        return self.finalize_prematch_events(events, limit, hours)

    @staticmethod
    def _outcomes_from_market_row(row: dict) -> list[dict]:
        outcomes_raw: list[dict] = []
        for line in row.get("lines", []) or []:
            outcomes_raw.extend(line.get("outcomes", []) or [])
        if not outcomes_raw:
            outcomes_raw = list(row.get("outcomes", []) or [])
        return outcomes_raw

    async def _fetch_market_lines(self, event: Event, sub_type_id: str) -> list[dict]:
        url = self.config["endpoints"]["match_markets"].split()[1]
        if not url.startswith("http"):
            url = f"{self.config['match_url']}{url}"
        body = {
            "id": event.parent_match_id or event.external_id,
            "sub_type_id": sub_type_id,
        }
        resp = await self._post(url, json=body)
        data = resp.json().get("data", {}) or {}
        return list(data.get("market_lines") or [])

    async def _normalize_market_rows(
        self,
        rows: list[dict],
        *,
        sport: Sport,
        is_live: bool,
        event_key: str,
        event: Event,
    ) -> list[MarketOdds]:
        markets: list[MarketOdds] = []
        for row in rows:
            sub_type_id = str(row.get("sub_type_id", ""))
            market_name = str(row.get("odd_type", ""))
            line_rows: list[dict] = []
            outcomes_raw = self._outcomes_from_market_row(row)
            if outcomes_raw:
                line_rows = [{"outcomes": outcomes_raw, "specifiers": row.get("specifiers")}]
            elif sub_type_id and (sport, sub_type_id) in self.normalizer._betika_index:
                line_rows = await self._fetch_market_lines(event, sub_type_id)

            for line_row in line_rows:
                normalized = self.normalizer.normalize_odibets_market(
                    sport=sport,
                    sub_type_id=sub_type_id,
                    market_name=market_name,
                    outcomes_raw=line_row.get("outcomes") or [],
                    is_live=is_live,
                    event_key=event_key,
                )
                if normalized:
                    markets.extend(self.normalizer.expand_by_line(normalized))
        return markets

    async def _fetch_sportevent_markets(self, event: Event, sport: Sport, *, is_live: bool) -> list[MarketOdds]:
        """SHARK fallback: GET sportevent resource from api.odi.site."""
        match_id = event.parent_match_id or event.external_id
        try:
            data = await self._odi_get(
                {
                    "id": match_id,
                    "sportsbook": "sportsbook",
                    "resource": "sportevent",
                }
            )
        except Exception:
            return []
        rows = data.get("markets", []) if isinstance(data, dict) else []
        return await self._normalize_market_rows(
            list(rows),
            sport=sport,
            is_live=is_live,
            event_key=event.event_key,
            event=event,
        )

    async def fetch_event_markets(
        self, event: Event, sport: Sport, *, is_live: bool = False
    ) -> list[MarketOdds]:
        url = self.config["endpoints"]["match_markets"].split()[1]
        if not url.startswith("http"):
            url = f"{self.config['match_url']}{url}"

        body = {"id": event.parent_match_id or event.external_id, "sub_type_id": ""}
        try:
            resp = await self._post(url, json=body)
            rows = resp.json().get("data", {}).get("markets", []) or []
        except Exception:
            rows = []

        # Tennis and some sports return markets inline on the prematch row only.
        if not rows and event.raw:
            rows = list(event.raw.get("markets") or [])

        if rows:
            return await self._normalize_market_rows(
                rows, sport=sport, is_live=is_live, event_key=event.event_key, event=event
            )

        return await self._fetch_sportevent_markets(event, sport, is_live=is_live)
