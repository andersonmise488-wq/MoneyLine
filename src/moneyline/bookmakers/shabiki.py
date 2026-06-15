from __future__ import annotations

import re

from dateutil import parser as date_parser

from moneyline.bookmakers.base import BookmakerAdapter
from moneyline.events.limits import event_limit_reached
from moneyline.events.prematch import row_is_live
from moneyline.events.window import event_in_window
from moneyline.markets.name_mapper import NameMarketMapper, side_from_label
from moneyline.markets.normalizer import MarketNormalizer
from moneyline.models.schemas import Bookmaker, Event, MarketOdds, OddsOutcome, Sport

_LINE_IN_NAME = re.compile(r"\(([+-]?\d+(?:\.\d+)?)\)")


def _line_from_market_name(name: str) -> float | None:
    match = _LINE_IN_NAME.search(name)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


class ShabikiAdapter(BookmakerAdapter):
    bookmaker = Bookmaker.SHABIKI

    def __init__(self) -> None:
        super().__init__()
        self.mapper = NameMarketMapper()
        self.normalizer = MarketNormalizer()
        self._base = self.config["base_url"].rstrip("/")
        self._qs = self.config.get("query_string", "siteid=28&providerid=1&lang=en")
        self._coupon_rows: dict[str, dict[str, dict]] = {}

    async def __aenter__(self) -> ShabikiAdapter:
        await super().__aenter__()
        self._coupon_rows.clear()
        return self

    async def __aexit__(self, *args: object) -> None:
        self._coupon_rows.clear()
        await super().__aexit__(*args)

    def _team_name(self, info: dict, field: str) -> str:
        val = info.get(field, "")
        if isinstance(val, dict):
            return str(val.get("International") or val.get("langValues", {}).get("en") or "")
        return str(val)

    def _row_to_event(self, row: dict, sport: Sport) -> Event | None:
        if row_is_live(row):
            return None
        info = row.get("Info", {})
        start_raw = info.get("DateOfMatch") or info.get("StartDate") or info.get("MatchDate")
        if not start_raw:
            return None
        start = date_parser.parse(str(start_raw))
        mid = str(row.get("MatchId", ""))
        if not mid:
            return None
        tournament = info.get("TournamentName", "")
        if isinstance(tournament, dict):
            competition = str(tournament.get("International") or "")
        else:
            competition = str(tournament)
        return Event(
            event_key=f"shabiki:{mid}",
            bookmaker=Bookmaker.SHABIKI,
            external_id=mid,
            parent_match_id=str(row.get("ExternalId") or mid),
            sport=sport,
            home_team=self._team_name(info, "HomeTeamName"),
            away_team=self._team_name(info, "AwayTeamName"),
            competition=competition,
            start_time=start,
            is_live=False,
            raw=row,
        )

    async def _fetch_coupon_slice(
        self,
        sport: Sport,
        *,
        slice_start: int,
        slice_end: int,
    ) -> list[dict]:
        sport_id = self.sport_param(sport)
        url = (
            f"{self._base}/api/Pregame/Coupon?{self._qs}"
            f"&type=upcoming&sportId={sport_id}&pagination=true"
            f"&sliceStart={slice_start}&sliceEnd={slice_end}"
        )
        resp = await self._get(url)
        return resp.json().get("Contents", []) or []

    async def _load_coupon_rows(self, sport: Sport) -> dict[str, dict]:
        sport_id = self.sport_param(sport)
        cached = self._coupon_rows.get(sport_id)
        if cached is not None:
            return cached

        rows_by_id: dict[str, dict] = {}
        slice_size = 200
        slice_start = 0
        max_slices = 50

        for _ in range(max_slices):
            rows = await self._fetch_coupon_slice(
                sport, slice_start=slice_start, slice_end=slice_start + slice_size
            )
            if not rows:
                break
            for row in rows:
                mid = str(row.get("MatchId", ""))
                if mid:
                    rows_by_id[mid] = row
            if len(rows) < slice_size:
                break
            slice_start += slice_size

        self._coupon_rows[sport_id] = rows_by_id
        return rows_by_id

    async def fetch_prematch_events(
        self,
        sport: Sport,
        limit: int = 100,
        *,
        lookahead_hours: int | None = None,
    ) -> list[Event]:
        hours = self.resolve_lookahead_hours(lookahead_hours)
        events: list[Event] = []

        for row in (await self._load_coupon_rows(sport)).values():
            if event_limit_reached(len(events), limit):
                break
            event = self._row_to_event(row, sport)
            if event is None or not event_in_window(event.start_time, hours):
                continue
            events.append(event)

        return self.finalize_prematch_events(events, limit, hours)

    def _markets_from_row(
        self,
        row: dict,
        *,
        sport: Sport,
        event: Event,
        is_live: bool,
    ) -> list[MarketOdds]:
        markets: list[MarketOdds] = []
        for mkt in row.get("Markets", []) or []:
            raw_name = mkt.get("MarketName", "")
            if isinstance(raw_name, dict):
                name = str(raw_name.get("International") or raw_name.get("langValues", {}).get("en", ""))
            else:
                name = str(raw_name)
            hit = self.mapper.resolve(sport, name)
            if not hit:
                continue
            _, spec = hit
            outcomes: list[OddsOutcome] = []
            line = _line_from_market_name(name)
            if line is None and mkt.get("SpecialOddsValue") not in (None, ""):
                try:
                    line = float(mkt["SpecialOddsValue"])
                except (TypeError, ValueError):
                    line = None

            for field in mkt.get("MarketFields", []) or []:
                price = float(field.get("Value") or field.get("Odd") or field.get("Price") or 0)
                if price <= 1:
                    continue
                raw_label = field.get("FieldName", field.get("Name", ""))
                if isinstance(raw_label, dict):
                    label = str(
                        raw_label.get("International") or raw_label.get("langValues", {}).get("en", "")
                    )
                else:
                    label = str(raw_label)
                side = side_from_label(label, spec, field.get("FieldTypeId"))
                if side is None:
                    continue
                outcomes.append(
                    OddsOutcome(
                        side=side,
                        label=label,
                        price=price,
                        line=line,
                        external_outcome_id=str(field.get("FieldId", "")),
                        raw=field,
                    )
                )

            built = self.mapper.build_market(
                sport=sport,
                bookmaker=Bookmaker.SHABIKI,
                event_key=event.event_key,
                market_name=name,
                outcomes=outcomes,
                is_live=is_live,
                line=line,
            )
            if built:
                markets.extend(self.normalizer.expand_by_line(built))
        return markets

    async def fetch_event_markets(
        self, event: Event, sport: Sport, *, is_live: bool = False
    ) -> list[MarketOdds]:
        row = (await self._load_coupon_rows(sport)).get(event.external_id)
        if not row:
            return []
        return self._markets_from_row(row, sport=sport, event=event, is_live=is_live)
