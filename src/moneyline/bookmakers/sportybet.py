from __future__ import annotations

import logging
from datetime import datetime, timezone

from moneyline.bookmakers.base import BookmakerAdapter
from moneyline.events.limits import event_limit_reached
from moneyline.events.prematch import row_is_live
from moneyline.events.window import event_in_window
from moneyline.markets.name_mapper import NameMarketMapper, side_from_label
from moneyline.models.schemas import Bookmaker, Event, MarketOdds, OddsOutcome, Sport

logger = logging.getLogger(__name__)

# SportyBet event status: 0 = not started (prematch), 1 = live/in-play.
_LIVE_STATUS = frozenset({1, "1", "live", "inprogress", "in_progress"})
# Mobile /ke/m/sport uses productId=3 for prematch, 1 for live.
_PREMATCH_PRODUCT_ID = 3
_THUMBNAIL_PAGE_SIZE = 100


class SportyBetAdapter(BookmakerAdapter):
    bookmaker = Bookmaker.SPORTYBET

    def __init__(self) -> None:
        super().__init__()
        self.mapper = NameMarketMapper()
        self._api = f"{self.config['base_url'].rstrip('/')}/factsCenter"
        self._event_rows: dict[str, dict[str, dict]] = {}
        self._event_details: dict[str, dict] = {}

    async def __aenter__(self) -> SportyBetAdapter:
        await super().__aenter__()
        self._event_rows.clear()
        self._event_details.clear()
        return self

    async def __aexit__(self, *args: object) -> None:
        self._event_rows.clear()
        self._event_details.clear()
        await super().__aexit__(*args)

    @staticmethod
    def _parse_specifier(value: object) -> float | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        import re

        text = str(value)
        match = re.search(r"[-+]?\d+\.?\d*", text)
        return float(match.group()) if match else None

    @staticmethod
    def _row_is_live(row: dict) -> bool:
        if row_is_live(row):
            return True
        status = row.get("status")
        if status is None:
            return False
        if isinstance(status, int):
            return status == 1
        return str(status).lower() in _LIVE_STATUS

    @staticmethod
    def _row_start(row: dict) -> datetime | None:
        start_ms = int(row.get("estimateStartTime") or 0)
        if not start_ms:
            return None
        return datetime.fromtimestamp(start_ms / 1000, tz=timezone.utc)

    @staticmethod
    def _row_competition(row: dict) -> str:
        sport = row.get("sport") or {}
        if not isinstance(sport, dict):
            return str(row.get("categoryName") or row.get("tournamentName") or "")
        category = sport.get("category") or {}
        if not isinstance(category, dict):
            return ""
        tournament = category.get("tournament") or {}
        if isinstance(tournament, dict) and tournament.get("name"):
            return str(tournament["name"])
        return str(category.get("name") or "")

    async def _load_event_rows(self, sport: Sport) -> dict[str, dict]:
        """Load prematch events — SHARK pattern: configurableLiveOrPrematchEvents first."""
        sport_id = self.sport_param(sport)
        cached = self._event_rows.get(sport_id)
        if cached is not None:
            return cached

        rows_by_id: dict[str, dict] = {}
        try:
            resp = await self._get(
                f"{self._api}/configurableLiveOrPrematchEvents",
                params={
                    "sportId": sport_id,
                    "withTwoUpMarket": "true",
                    "withOneUpMarket": "true",
                },
            )
            payload = resp.json()
            if payload.get("bizCode") in (None, 10000):
                for block in payload.get("data", []) or []:
                    cat = str(block.get("categoryName") or "")
                    tourn = str(block.get("name") or "")
                    competition = f"{cat} - {tourn}" if cat and tourn else tourn or cat
                    for row in block.get("events", []) or []:
                        eid = str(row.get("eventId", ""))
                        if not eid or self._row_is_live(row):
                            continue
                        if competition and not row.get("categoryName"):
                            row = {**row, "categoryName": competition}
                        rows_by_id[eid] = row
        except Exception as exc:
            logger.debug("SportyBet configurable events failed for %s: %s", sport.value, exc)

        await self._load_thumbnail_rows(sport_id, rows_by_id)

        if not rows_by_id:
            logger.warning("SportyBet %s: no prematch rows from any source", sport.value)
        else:
            logger.info(
                "SportyBet %s: loaded %d prematch rows",
                sport.value,
                len(rows_by_id),
            )
        self._event_rows[sport_id] = rows_by_id
        return rows_by_id

    async def _load_thumbnail_rows(self, sport_id: str, rows_by_id: dict[str, dict]) -> None:
        """Prematch list via commonThumbnailEvents (productId=3) — fills the 72h window."""
        page_num = 1
        while True:
            try:
                resp = await self._get(
                    f"{self._api}/commonThumbnailEvents",
                    params={
                        "sportId": sport_id,
                        "productId": _PREMATCH_PRODUCT_ID,
                        "pageSize": _THUMBNAIL_PAGE_SIZE,
                        "pageNum": page_num,
                    },
                )
                payload = resp.json()
                if payload.get("bizCode") not in (None, 10000):
                    break
                batch: list[dict] = []
                for block in payload.get("data", []) or []:
                    batch.extend(block.get("events", []) or [])
                if not batch:
                    break
                for row in batch:
                    eid = str(row.get("eventId", ""))
                    if not eid or self._row_is_live(row):
                        continue
                    existing = rows_by_id.get(eid)
                    if existing and existing.get("markets") and not row.get("markets"):
                        continue
                    rows_by_id[eid] = row
                if len(batch) < _THUMBNAIL_PAGE_SIZE:
                    break
                page_num += 1
            except Exception as exc:
                logger.debug(
                    "SportyBet thumbnail page %s/%s failed: %s",
                    sport_id,
                    page_num,
                    exc,
                )
                break

    async def _fetch_event_detail(self, event_id: str) -> dict | None:
        cached = self._event_details.get(event_id)
        if cached is not None:
            return cached

        try:
            resp = await self._get(
                f"{self._api}/event",
                params={"productId": _PREMATCH_PRODUCT_ID, "eventId": event_id},
            )
            payload = resp.json()
            if payload.get("bizCode") not in (None, 10000):
                return None
            detail = payload.get("data")
            if isinstance(detail, dict):
                self._event_details[event_id] = detail
                return detail
        except Exception as exc:
            logger.debug("SportyBet event detail %s failed: %s", event_id, exc)
        return None

    def _markets_from_row(
        self,
        row: dict,
        *,
        sport: Sport,
        event: Event,
        is_live: bool,
    ) -> list[MarketOdds]:
        markets: list[MarketOdds] = []
        for mkt in row.get("markets", []) or []:
            name = str(mkt.get("name") or mkt.get("marketName", ""))
            hit = self.mapper.resolve(sport, name)
            if not hit:
                continue
            _, spec = hit
            outcomes: list[OddsOutcome] = []

            for oc in mkt.get("outcomes", []) or []:
                price = float(oc.get("odds") or oc.get("price") or 0)
                if price <= 1:
                    continue
                label = str(oc.get("desc") or oc.get("name", ""))
                side = side_from_label(label, spec)
                if side is None:
                    continue
                outcomes.append(
                    OddsOutcome(
                        side=side,
                        label=label,
                        price=price,
                        line=self._parse_specifier(mkt.get("specifier")),
                        external_outcome_id=str(oc.get("id", "")),
                        raw=oc,
                    )
                )

            built = self.mapper.build_market(
                sport=sport,
                bookmaker=Bookmaker.SPORTYBET,
                event_key=event.event_key,
                market_name=name,
                outcomes=outcomes,
                is_live=is_live,
            )
            if built:
                markets.append(built)
        return markets

    async def fetch_prematch_events(
        self,
        sport: Sport,
        limit: int = 100,
        *,
        lookahead_hours: int | None = None,
    ) -> list[Event]:
        hours = self.resolve_lookahead_hours(lookahead_hours)
        events: list[Event] = []
        rows_by_id = await self._load_event_rows(sport)

        for row in rows_by_id.values():
            if event_limit_reached(len(events), limit):
                break
            if self._row_is_live(row):
                continue
            start = self._row_start(row)
            if start is None or not event_in_window(start, hours):
                continue
            eid = str(row.get("eventId", ""))
            events.append(
                Event(
                    event_key=f"sportybet:{eid}",
                    bookmaker=Bookmaker.SPORTYBET,
                    external_id=eid,
                    parent_match_id=str(row.get("gameId") or eid),
                    sport=sport,
                    home_team=str(row.get("homeTeamName", "")),
                    away_team=str(row.get("awayTeamName", "")),
                    competition=self._row_competition(row),
                    start_time=start,
                    is_live=False,
                    raw=row,
                )
            )

        return self.finalize_prematch_events(events, limit, hours)

    async def fetch_event_markets(
        self, event: Event, sport: Sport, *, is_live: bool = False
    ) -> list[MarketOdds]:
        row = (await self._load_event_rows(sport)).get(event.external_id)
        if not row:
            return []

        if row.get("markets"):
            return self._markets_from_row(row, sport=sport, event=event, is_live=is_live)

        detail = await self._fetch_event_detail(event.external_id)
        if not detail:
            return []
        return self._markets_from_row(detail, sport=sport, event=event, is_live=is_live)
