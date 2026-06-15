from __future__ import annotations

from datetime import datetime, timezone

from dateutil import parser as date_parser

from moneyline.bookmakers.base import BookmakerAdapter
from moneyline.events.limits import event_limit_reached, is_unlimited_event_limit
from moneyline.events.window import event_in_window, page_starts_after_window
from moneyline.markets.name_mapper import NameMarketMapper, side_from_label
from moneyline.markets.normalizer import MarketNormalizer
from moneyline.models.schemas import Bookmaker, Event, MarketOdds, OddsOutcome, Sport


class MozzartBetAdapter(BookmakerAdapter):
    """MozzartBet Kenya prematch API (betOffer2 + getBettingOdds + getAllGames)."""

    bookmaker = Bookmaker.MOZZARTBET

    def __init__(self) -> None:
        super().__init__()
        self.mapper = NameMarketMapper()
        self.normalizer = MarketNormalizer()
        self._base = self.config["base_url"].rstrip("/")
        self._subgames_cache: dict[Sport, list[int]] = {}
        self._all_games_cache: dict | None = None

    async def _load_all_games(self) -> dict:
        if self._all_games_cache is None:
            resp = await self._get(f"{self._base}/getAllGames")
            payload = resp.json()
            self._all_games_cache = payload if isinstance(payload, dict) else {}
        return self._all_games_cache

    async def _subgames_for_sport(self, sport: Sport) -> list[int]:
        if sport in self._subgames_cache:
            return self._subgames_cache[sport]

        games = await self._load_all_games()
        sport_id = str(int(self.sport_param(sport)))
        sport_groups = games.get(sport_id, []) if isinstance(games, dict) else []
        seen: set[int] = set()
        ids: list[int] = []
        for group in sport_groups:
            for sid in group.get("subgameIds", []) or []:
                try:
                    value = int(sid)
                except (TypeError, ValueError):
                    continue
                if value not in seen:
                    seen.add(value)
                    ids.append(value)
        if not ids:
            ids = [1001001001, 1001001002, 1001001003, 1001002001, 1001002002]
        self._subgames_cache[sport] = ids
        return self._subgames_cache[sport]

    def _parse_start(self, start_raw: object) -> datetime:
        if isinstance(start_raw, (int, float)) or str(start_raw).isdigit():
            return datetime.fromtimestamp(int(start_raw) / 1000, tz=timezone.utc)
        return date_parser.parse(str(start_raw))

    @staticmethod
    def _parse_line(special_odd_value: object) -> float | None:
        if special_odd_value is None:
            return None
        text = str(special_odd_value).strip()
        if not text or text in ("-1", "0"):
            return None
        try:
            return float(text.replace(",", "."))
        except ValueError:
            return None

    async def fetch_prematch_events(
        self,
        sport: Sport,
        limit: int = 100,
        *,
        lookahead_hours: int | None = None,
    ) -> list[Event]:
        hours = self.resolve_lookahead_hours(lookahead_hours)
        sport_id = int(self.sport_param(sport))
        events: list[Event] = []
        page_size = 250
        offset = 0
        max_offset = 10_000 if is_unlimited_event_limit(limit) else 500

        while True:
            resp = await self._post(
                f"{self._base}/betOffer2",
                json={
                    "sportIds": [sport_id],
                    "competitionIds": [],
                    "sort": "bytime",
                    "specials": None,
                    "subgames": [],
                    "size": page_size,
                    "mostPlayed": False,
                    "type": "betting",
                    "numberOfGames": 0,
                    "activeCompleteOffer": False,
                    "lang": "en",
                    "date": None,
                    "offset": offset,
                },
            )
            rows = resp.json().get("matches", []) or []
            if not rows:
                break

            page_starts = [self._parse_start(row["startTime"]) for row in rows if row.get("startTime")]
            if page_starts_after_window(page_starts, hours):
                break

            for row in rows:
                if event_limit_reached(len(events), limit):
                    break
                parts = row.get("participants", [])
                if len(parts) < 2:
                    continue
                home = parts[0].get("name") or parts[0].get("description", "")
                away = parts[1].get("name") or parts[1].get("description", "")
                mid = str(row["id"])
                start = self._parse_start(row["startTime"])
                if not event_in_window(start, hours):
                    continue
                events.append(
                    Event(
                        event_key=f"mozzartbet:{mid}",
                        bookmaker=Bookmaker.MOZZARTBET,
                        external_id=mid,
                        parent_match_id=mid,
                        sport=sport,
                        home_team=str(home),
                        away_team=str(away),
                        competition=str(row.get("competition_name_en", "")),
                        start_time=start,
                        is_live=False,
                        raw=row,
                    )
                )

            if event_limit_reached(len(events), limit):
                break
            if len(rows) < page_size:
                break
            offset += page_size
            if offset > max_offset:
                break

        return self.finalize_prematch_events(events, limit, hours)

    async def fetch_event_markets(
        self, event: Event, sport: Sport, *, is_live: bool = False
    ) -> list[MarketOdds]:
        subgames = await self._subgames_for_sport(sport)
        resp = await self._post(
            f"{self._base}/getBettingOdds",
            json={"matchIds": [int(event.external_id)], "subgames": subgames},
        )
        payload = resp.json()
        if not isinstance(payload, list) or not payload:
            return []

        row = payload[0] or {}
        markets: list[MarketOdds] = []
        grouped: dict[tuple[str, float | None], list[OddsOutcome]] = {}

        kodds = row.get("kodds") or {}
        for kodd in kodds.values():
            if not kodd or not isinstance(kodd, dict):
                continue
            sg = kodd.get("subGame") or {}
            if not isinstance(sg, dict):
                continue
            game_name = str(sg.get("gameName", ""))
            label = str(sg.get("subGameName", ""))
            try:
                price = float(kodd.get("value") or 0)
            except (TypeError, ValueError):
                continue
            if price <= 1:
                continue

            hit = self.mapper.resolve(sport, game_name)
            if not hit:
                continue
            _, spec = hit
            side = side_from_label(label, spec)
            if side is None:
                continue

            line = self._parse_line(kodd.get("specialOddValue"))
            key = (game_name, line)
            grouped.setdefault(key, []).append(
                OddsOutcome(
                    side=side,
                    label=label,
                    price=price,
                    line=line,
                    external_outcome_id=str(kodd.get("id", "")),
                    raw=kodd,
                )
            )

        for (name, line), outcomes in grouped.items():
            built = self.mapper.build_market(
                sport=sport,
                bookmaker=Bookmaker.MOZZARTBET,
                event_key=event.event_key,
                market_name=name,
                outcomes=outcomes,
                is_live=False,
                line=line,
            )
            if built:
                markets.extend(self.normalizer.expand_by_line(built))

        return markets
