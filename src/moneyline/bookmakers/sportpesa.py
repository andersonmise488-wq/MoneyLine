from __future__ import annotations



from datetime import datetime, timezone



from moneyline.bookmakers.base import BookmakerAdapter

from moneyline.bookmakers.curl_client import CurlClient

from moneyline.events.limits import event_limit_reached, is_unlimited_event_limit, page_size_for

from moneyline.events.prematch import row_is_live
from moneyline.events.window import event_in_window, page_starts_after_window

from moneyline.markets.name_mapper import NameMarketMapper, side_from_label

from moneyline.models.schemas import Bookmaker, Event, MarketOdds, OddsOutcome, Sport





class SportPesaAdapter(BookmakerAdapter):

    bookmaker = Bookmaker.SPORTPESA



    def __init__(self) -> None:

        super().__init__()

        self.mapper = NameMarketMapper()

        self._base = self.config["base_url"].rstrip("/")

        self._curl: CurlClient | None = None



    async def __aenter__(self) -> SportPesaAdapter:

        self._curl = CurlClient(impersonate="chrome120", headers=self.headers)

        return self



    async def __aexit__(self, *args: object) -> None:

        if self._curl:

            self._curl.close()

            self._curl = None



    @property

    def curl(self) -> CurlClient:

        if self._curl is None:

            raise RuntimeError("SportPesaAdapter used outside async context manager")

        return self._curl

    def _game_to_event(self, row: dict, sport: Sport) -> Event | None:
        if row_is_live(row):
            return None
        comps = row.get("competitors", [])
        if len(comps) < 2 or not row.get("date"):
            return None
        start = datetime.fromisoformat(str(row["date"]).replace("Z", "+00:00"))
        gid = str(row["id"])
        country = row.get("country", {}) or {}
        competition = row.get("competition", {}) or {}
        tournament = f"{country.get('name', '')} - {competition.get('name', '')}".strip(" -")
        return Event(
            event_key=f"sportpesa:{gid}",
            bookmaker=Bookmaker.SPORTPESA,
            external_id=gid,
            parent_match_id=str(row.get("betradarId") or gid),
            sport=sport,
            home_team=str(comps[0]["name"]),
            away_team=str(comps[1]["name"]),
            competition=tournament or str(competition.get("name", "")),
            start_time=start,
            is_live=False,
            raw=row,
        )

    def _markets_from_game_rows(
        self,
        game_markets: list[dict],
        *,
        sport: Sport,
        event: Event,
        is_live: bool,
    ) -> list[MarketOdds]:
        markets: list[MarketOdds] = []
        for mkt in game_markets:
            name = str(mkt.get("name", ""))
            hit = self.mapper.resolve(sport, name)
            if not hit:
                continue
            _, spec = hit
            outcomes: list[OddsOutcome] = []
            line = float(mkt["specValue"]) if mkt.get("specValue") else None
            for sel in mkt.get("selections", []) or []:
                price = float(sel.get("odds") or 0)
                if price <= 1:
                    continue
                label = str(sel.get("shortName") or sel.get("name", ""))
                side = side_from_label(label, spec)
                if side is None:
                    side = side_from_label(str(sel.get("name", "")), spec)
                if side is None:
                    continue
                sel_line = sel.get("specValue")
                outcomes.append(
                    OddsOutcome(
                        side=side,
                        label=label,
                        price=price,
                        line=float(sel_line) if sel_line else line,
                        external_outcome_id=str(sel.get("id", "")),
                        raw=sel,
                    )
                )
            built = self.mapper.build_market(
                sport=sport,
                bookmaker=Bookmaker.SPORTPESA,
                event_key=event.event_key,
                market_name=name,
                outcomes=outcomes,
                is_live=is_live,
                line=line,
            )
            if built:
                markets.append(built)
        return markets

    async def _fetch_events_via_navigation(
        self,
        sport: Sport,
        *,
        limit: int,
        hours: int,
    ) -> list[Event]:
        """SHARK pattern: navigation tree → league games (markets inline in raw)."""
        sport_id = self.sport_param(sport)
        resp = await self.curl.async_get(f"{self._base}/api/navigation")
        if resp.status_code not in (200, 206):
            return []
        nav = resp.json()
        if not isinstance(nav, list):
            return []

        events: list[Event] = []
        seen: set[str] = set()
        for sport_data in nav:
            if str(sport_data.get("id")) != str(sport_id):
                continue
            if not sport_data.get("has_matches"):
                continue
            for country in sport_data.get("countries", []) or []:
                for league in country.get("leagues", []) or []:
                    if event_limit_reached(len(events), limit):
                        return events
                    lg_id = league.get("id")
                    if lg_id is None:
                        continue
                    url = (
                        f"{self._base}/api/upcoming/games"
                        f"?sportId={sport_id}&leagueId={lg_id}&section=league"
                    )
                    try:
                        lg_resp = await self.curl.async_get(url)
                        if lg_resp.status_code not in (200, 206):
                            continue
                        games = lg_resp.json() or []
                    except Exception:
                        continue
                    for row in games:
                        if event_limit_reached(len(events), limit):
                            break
                        event = self._game_to_event(row, sport)
                        if event is None or event.external_id in seen:
                            continue
                        if not event_in_window(event.start_time, hours):
                            continue
                        seen.add(event.external_id)
                        events.append(event)
        return events



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
        seen: set[str] = set()

        for event in await self._fetch_events_via_navigation(sport, limit=limit, hours=hours):
            seen.add(event.external_id)
            events.append(event)

        pag_min = 1

        page_size = page_size_for(limit, default=50, maximum=100)

        max_offset = 20_000 if is_unlimited_event_limit(limit) else 3_000



        while not event_limit_reached(len(events), limit):

            url = (

                f"{self._base}/api/upcoming/games"

                f"?sportId={sport_id}&section=upcoming&pag_count={page_size}&pag_min={pag_min}"

            )

            resp = await self.curl.async_get(url)

            if resp.status_code not in (200, 206):

                resp.raise_for_status()

            rows = resp.json()

            if not rows:

                break



            page_starts = [

                datetime.fromisoformat(str(row["date"]).replace("Z", "+00:00"))

                for row in rows

                if row.get("date")

            ]

            if page_starts_after_window(page_starts, hours):

                break



            for row in rows:

                if event_limit_reached(len(events), limit):

                    break

                event = self._game_to_event(row, sport)
                if event is None or event.external_id in seen:
                    continue
                if not event_in_window(event.start_time, hours):
                    continue
                seen.add(event.external_id)
                events.append(event)



            if event_limit_reached(len(events), limit):

                break

            if len(rows) < page_size:

                break

            pag_min += page_size

            if pag_min > max_offset:

                break



        return self.finalize_prematch_events(events, limit, hours)



    async def fetch_event_markets(

        self, event: Event, sport: Sport, *, is_live: bool = False

    ) -> list[MarketOdds]:

        inline = (event.raw or {}).get("markets")
        if inline:
            return self._markets_from_game_rows(
                list(inline), sport=sport, event=event, is_live=is_live
            )

        url = f"{self._base}/api/games/markets?games={event.external_id}&markets=all"

        resp = await self.curl.async_get(url)

        resp.raise_for_status()

        payload = resp.json()

        game_markets = payload.get(str(event.external_id)) or payload.get(event.external_id) or []

        return self._markets_from_game_rows(
            list(game_markets), sport=sport, event=event, is_live=is_live
        )



    async def health_check(self) -> dict:

        import time



        sport_id = self.sport_param(Sport.SOCCER)

        url = (

            f"{self._base}/api/upcoming/games"

            f"?sportId={sport_id}&section=upcoming&pag_count=2&pag_min=1"

        )

        try:

            t0 = time.perf_counter()

            resp = await self.curl.async_get(url)

            latency = (time.perf_counter() - t0) * 1000

            ok = resp.status_code in (200, 206) and resp.text[:1] == "["

            return {

                "bookmaker": self.bookmaker.value,

                "checks": [

                    {

                        "endpoint": "upcoming_games",

                        "url": url,

                        "status_code": resp.status_code,

                        "ok": ok,

                        "latency_ms": round(latency, 1),

                        "sample_bytes": len(resp.content),

                    }

                ],

            }

        except Exception as exc:

            return {

                "bookmaker": self.bookmaker.value,

                "checks": [

                    {

                        "endpoint": "upcoming_games",

                        "url": url,

                        "status_code": None,

                        "ok": False,

                        "error": str(exc),

                    }

                ],

            }


