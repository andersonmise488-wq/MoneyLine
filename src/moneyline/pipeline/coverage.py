from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from moneyline.bookmakers.registry import LIVE_BOOKMAKERS, get_adapter
from moneyline.config_loader import get_bookmaker_config
from moneyline.constants import EVENT_LOOKAHEAD_HOURS
from moneyline.markets.registry import MarketRegistry
from moneyline.models.schemas import Bookmaker, Sport
from moneyline.sports import SUPPORTED_SPORTS

logger = logging.getLogger(__name__)

ALL_SPORTS = SUPPORTED_SPORTS


@dataclass
class SportBookmakerCoverage:
    bookmaker: Bookmaker
    sport: Sport
    events: int = 0
    markets: int = 0
    market_keys: set[str] = field(default_factory=set)
    expected_markets: set[str] = field(default_factory=set)
    missing_markets: set[str] = field(default_factory=set)
    skipped: bool = False
    skip_reason: str | None = None
    error: str | None = None


def _bookmaker_supports_sport(bookmaker: Bookmaker, sport: Sport) -> tuple[bool, str | None]:
    cfg = get_bookmaker_config(bookmaker.value)
    supported = cfg.get("supported_sports")
    if supported is not None and sport.value not in supported:
        return False, "not offered by bookmaker"
    ids = cfg.get("sport_ids") or cfg.get("sport_slugs") or {}
    if sport.value not in ids or not str(ids[sport.value]).strip():
        return False, "no sport mapping"
    return True, None


class CoverageScanner:
    """Measure event/market coverage per sport and bookmaker."""

    def __init__(
        self,
        *,
        max_events: int = 5,
        max_market_fetches: int = 3,
        lookahead_hours: int = EVENT_LOOKAHEAD_HOURS,
    ) -> None:
        self.max_events = max_events
        self.max_market_fetches = max_market_fetches
        self.lookahead_hours = lookahead_hours
        self.registry = MarketRegistry()

    async def scan_bookmaker_sport(
        self,
        bookmaker: Bookmaker,
        sport: Sport,
    ) -> SportBookmakerCoverage:
        expected = self.registry.allowed_market_keys(sport)
        row = SportBookmakerCoverage(
            bookmaker=bookmaker,
            sport=sport,
            expected_markets=expected,
        )

        ok, reason = _bookmaker_supports_sport(bookmaker, sport)
        if not ok:
            row.skipped = True
            row.skip_reason = reason
            return row

        try:
            async with get_adapter(bookmaker) as adapter:
                events = await adapter.fetch_prematch_events(
                    sport,
                    limit=self.max_events,
                    lookahead_hours=self.lookahead_hours,
                )
                row.events = len(events)

                markets = []
                for ev in events[: self.max_market_fetches]:
                    try:
                        markets.extend(await adapter.fetch_event_markets(ev, sport))
                    except Exception as exc:
                        logger.debug(
                            "Coverage markets failed %s/%s: %s",
                            bookmaker.value,
                            ev.external_id,
                            exc,
                        )

                filtered = self.registry.filter_allowed(sport, markets)
                row.markets = len(filtered)
                row.market_keys = {m.market_key for m in filtered}
                row.missing_markets = expected - row.market_keys
        except Exception as exc:
            row.error = str(exc)
            logger.warning("Coverage scan failed %s/%s: %s", bookmaker.value, sport.value, exc)

        return row

    async def scan_all(
        self,
        sports: list[Sport] | None = None,
        bookmakers: list[Bookmaker] | None = None,
    ) -> list[SportBookmakerCoverage]:
        sports = sports or ALL_SPORTS
        bookmakers = bookmakers or list(LIVE_BOOKMAKERS)

        tasks = [
            self.scan_bookmaker_sport(bm, sport)
            for sport in sports
            for bm in bookmakers
        ]
        return await asyncio.gather(*tasks)

    def summarize_by_sport(
        self, rows: list[SportBookmakerCoverage]
    ) -> dict[Sport, dict[str, int]]:
        summary: dict[Sport, dict[str, int]] = {}
        for row in rows:
            bucket = summary.setdefault(
                row.sport,
                {"bookmakers": 0, "active": 0, "events": 0, "markets": 0},
            )
            if row.skipped:
                continue
            bucket["bookmakers"] += 1
            if row.error:
                continue
            bucket["active"] += 1
            bucket["events"] += row.events
            bucket["markets"] += row.markets
        return summary
