from __future__ import annotations

import asyncio
import logging
from typing import Iterable

from moneyline.arb.engine import ArbitrageEngine
from moneyline.bookmakers.registry import LIVE_BOOKMAKERS, get_adapter
from moneyline.config.settings import get_settings
from moneyline.config_loader import get_bookmaker_config, get_bookmaker_market_workers
from moneyline.constants import DEFAULT_MIN_MARGIN_PCT, EVENT_LOOKAHEAD_HOURS
from moneyline.events.limits import UNLIMITED_EVENTS
from moneyline.markets.registry import MarketRegistry
from moneyline.matching.fuzzy import EventMatcher
from moneyline.matching.review import MatchReviewQueue
from moneyline.models.schemas import ArbitrageOpportunity, Bookmaker, Event, MarketOdds, Sport
from moneyline.pipeline.book_health import BookHealthTracker
from moneyline.pipeline.collection_stats import CollectionStats
from moneyline.sports import SUPPORTED_SPORTS
from moneyline.storage.database import Storage
from moneyline.storage.raw_cache import RawOddsCache

logger = logging.getLogger(__name__)

ALL_SPORTS = SUPPORTED_SPORTS


def resolve_market_fetch_limit(max_market_fetches: int | None) -> int | None:
    """None or non-positive values fetch markets for every collected event."""
    if max_market_fetches is None or max_market_fetches <= 0:
        return None
    return max_market_fetches


def resolve_event_fetch_limit(max_events: int | None) -> int:
    """None or non-positive values fetch every event inside the lookahead window."""
    if max_events is None or max_events <= 0:
        return UNLIMITED_EVENTS
    return max_events


def market_workers_for(bookmaker: Bookmaker) -> int:
    settings = get_settings()
    return get_bookmaker_market_workers(
        bookmaker.value,
        default=settings.market_fetch_concurrency,
    )


class CollectionPipeline:
    """Orchestrate odds collection, storage, matching, and arb detection."""

    def __init__(
        self,
        storage: Storage | None = None,
        min_margin_pct: float = DEFAULT_MIN_MARGIN_PCT,
        max_events: int = UNLIMITED_EVENTS,
        max_market_fetches: int | None = None,
        lookahead_hours: int = EVENT_LOOKAHEAD_HOURS,
        *,
        match_first_markets: bool | None = None,
        raw_cache: RawOddsCache | None = None,
    ) -> None:
        self.storage = storage or Storage()
        self.matcher = EventMatcher()
        settings = get_settings()
        self.arb_engine = ArbitrageEngine(
            min_margin_pct=min_margin_pct,
            max_odds_age_seconds=settings.odds_staleness_seconds,
        )
        self.max_events = resolve_event_fetch_limit(max_events)
        self.max_market_fetches = resolve_market_fetch_limit(max_market_fetches)
        self.lookahead_hours = lookahead_hours
        self.registry = MarketRegistry()
        self.last_stats = CollectionStats()
        self.match_first_markets = (
            settings.match_first_markets if match_first_markets is None else match_first_markets
        )
        self.raw_cache = raw_cache or RawOddsCache(ttl_seconds=settings.raw_cache_ttl_seconds)
        self.book_health = BookHealthTracker()
        self.review_queue = MatchReviewQueue()

    def _bookmaker_supports_sport(self, bookmaker: Bookmaker, sport: Sport) -> bool:
        cfg = get_bookmaker_config(bookmaker.value)
        supported = cfg.get("supported_sports")
        if supported is not None:
            return sport.value in supported
        ids = cfg.get("sport_ids") or cfg.get("sport_slugs") or {}
        param = str(ids.get(sport.value, "")).strip()
        return bool(param)

    def _filter_markets(self, sport: Sport, markets: list[MarketOdds]) -> list[MarketOdds]:
        return self.registry.filter_allowed(sport, markets)

    def _events_needing_markets(self, events: list[Event]) -> set[str]:
        """Cross-book fixtures only — single-book events cannot produce arbs."""
        if not self.match_first_markets:
            return {ev.event_key for ev in events}
        clusters = self.matcher.match_events(events)
        needed: set[str] = set()
        for cluster in clusters:
            if len(cluster.events) < 2:
                continue
            for ev in cluster.events.values():
                needed.add(ev.event_key)
        return needed

    async def _fetch_events_for_bookmaker(
        self, bm: Bookmaker, sport: Sport
    ) -> tuple[Bookmaker, list[Event], str | None]:
        if not self._bookmaker_supports_sport(bm, sport):
            return bm, [], "no sport mapping"
        if not self.book_health.is_available(bm):
            return bm, [], "circuit breaker open"
        try:
            async with get_adapter(bm) as adapter:
                events = await adapter.fetch_prematch_events(
                    sport,
                    limit=self.max_events,
                    lookahead_hours=self.lookahead_hours,
                )
                logger.info("%s/%s: fetched %d events", bm.value, sport.value, len(events))
                self.book_health.record_success(bm)
                return bm, events, None
        except NotImplementedError as exc:
            self.book_health.record_failure(bm, str(exc))
            return bm, [], str(exc)
        except Exception as exc:
            self.book_health.record_failure(bm, str(exc))
            logger.error("%s/%s event fetch failed: %s", bm.value, sport.value, exc)
            return bm, [], str(exc)

    async def _fetch_markets_for_bookmaker(
        self,
        bm: Bookmaker,
        sport: Sport,
        events: list[Event],
        needed_keys: set[str],
    ) -> tuple[list[MarketOdds], str | None]:
        if not events or not needed_keys:
            return [], None

        targets = [ev for ev in events if ev.event_key in needed_keys]
        targets.sort(key=lambda ev: ev.start_time)
        if self.max_market_fetches is not None:
            targets = targets[: self.max_market_fetches]

        if not targets:
            return [], None

        workers = market_workers_for(bm)
        semaphore = asyncio.Semaphore(workers)
        markets: list[MarketOdds] = []

        try:
            async with get_adapter(bm) as adapter:

                async def _one(ev: Event) -> list[MarketOdds]:
                    cached = self.raw_cache.get(bm.value, sport.value, ev.external_id)
                    if cached is not None:
                        return cached
                    async with semaphore:
                        try:
                            fetched = await adapter.fetch_event_markets(ev, sport)
                            if fetched:
                                self.raw_cache.put(bm.value, sport.value, ev.external_id, fetched)
                            return fetched
                        except Exception as exc:
                            logger.warning(
                                "Failed markets for %s/%s/%s: %s",
                                bm.value,
                                sport.value,
                                ev.external_id,
                                exc,
                            )
                            return []

                batches = await asyncio.gather(*[_one(ev) for ev in targets])
        except Exception as exc:
            self.book_health.record_failure(bm, str(exc))
            logger.error("%s/%s market adapter failed: %s", bm.value, sport.value, exc)
            return [], str(exc)

        for batch in batches:
            markets.extend(batch)
        return markets, None

    async def collect_sport(
        self,
        sport: Sport,
        bookmakers: Iterable[Bookmaker] | None = None,
    ) -> tuple[list[Event], list[MarketOdds]]:
        bookmakers = list(bookmakers or LIVE_BOOKMAKERS)
        stats = CollectionStats()

        # Phase 1 — event lists from every bookmaker in parallel
        phase1 = await asyncio.gather(
            *[self._fetch_events_for_bookmaker(bm, sport) for bm in bookmakers],
            return_exceptions=True,
        )

        book_events: dict[Bookmaker, list[Event]] = {}
        all_events: list[Event] = []
        for bm, result in zip(bookmakers, phase1):
            if isinstance(result, Exception):
                stats.set_row(
                    bookmaker=bm.value,
                    sport=sport.value,
                    events=0,
                    events_with_markets=0,
                    markets=0,
                    error=str(result),
                )
                book_events[bm] = []
                continue
            _, events, error = result
            book_events[bm] = events
            all_events.extend(events)
            stats.set_row(
                bookmaker=bm.value,
                sport=sport.value,
                events=len(events),
                events_with_markets=0,
                markets=0,
                skipped=error == "no sport mapping",
                error=error,
            )

        needed_keys = self._events_needing_markets(all_events)
        logger.info(
            "%s: %d events across %d bookmakers, %d fixtures need markets",
            sport.value,
            len(all_events),
            len(bookmakers),
            len(needed_keys),
        )

        # Phase 2 — markets only for cross-book fixtures, parallel per bookmaker
        phase2 = await asyncio.gather(
            *[
                self._fetch_markets_for_bookmaker(bm, sport, book_events.get(bm, []), needed_keys)
                for bm in bookmakers
            ],
            return_exceptions=True,
        )

        all_markets: list[MarketOdds] = []
        for bm, result in zip(bookmakers, phase2):
            key = f"{bm.value}:{sport.value}"
            row = stats.by_key.get(key)
            if isinstance(result, Exception):
                if row:
                    row.error = str(result)
                logger.error("%s/%s market fetch failed: %s", bm.value, sport.value, result)
                continue
            markets, _ = result
            markets = self._filter_markets(sport, markets)
            all_markets.extend(markets)
            if row:
                row.markets = len(markets)
                row.events_with_markets = len({m.event_key for m in markets})
                if row.events and row.events_with_markets == 0 and not row.skipped:
                    logger.warning(
                        "%s/%s: %d events but 0 with markets after phase 2",
                        bm.value,
                        sport.value,
                        row.events,
                    )

        if all_events:
            self.storage.upsert_events(all_events)
        if all_markets:
            self.storage.insert_odds(all_markets)

        self.last_stats = stats
        return all_events, all_markets

    async def collect_all_sports(
        self,
        sports: Iterable[Sport] | None = None,
        bookmakers: Iterable[Bookmaker] | None = None,
    ) -> dict[Sport, tuple[list[Event], list[MarketOdds]]]:
        sports = list(sports or ALL_SPORTS)
        results: dict[Sport, tuple[list[Event], list[MarketOdds]]] = {}

        async def _one(sport: Sport) -> tuple[Sport, tuple[list[Event], list[MarketOdds]]]:
            data = await self.collect_sport(sport, bookmakers=bookmakers)
            return sport, data

        gathered = await asyncio.gather(*[_one(s) for s in sports], return_exceptions=True)
        for sport, data in zip(sports, gathered):
            if isinstance(data, Exception):
                logger.error("Collection failed for %s: %s", sport.value, data)
                results[sport] = ([], [])
            else:
                _, payload = data
                results[sport] = payload
        return results

    async def scan_sport(
        self,
        sport: Sport,
        bookmakers: Iterable[Bookmaker] | None = None,
    ) -> list[ArbitrageOpportunity]:
        """Collect odds and detect arbs for one sport."""
        events, markets = await self.collect_sport(sport, bookmakers=bookmakers)
        return self.detect_arbitrage(events, markets)

    def detect_arbitrage(
        self,
        events: list[Event],
        markets: list[MarketOdds],
    ) -> list[ArbitrageOpportunity]:
        clusters = self.matcher.match_events(events)
        self.review_queue.ingest_clusters(clusters)
        markets_by_event: dict[str, list[MarketOdds]] = {}
        for m in markets:
            markets_by_event.setdefault(m.event_key, []).append(m)

        opportunities = self.arb_engine.find_arbitrage(clusters, markets_by_event)
        if opportunities:
            self.storage.insert_arbitrage(opportunities)
        return opportunities

    async def notify_arbitrage(
        self,
        opportunities: list[ArbitrageOpportunity],
        *,
        send_telegram: bool = False,
    ) -> int:
        if not send_telegram or not opportunities:
            return 0
        from moneyline.alerts.routing import filter_telegram_alerts
        from moneyline.alerts.telegram import send_arbitrage_alerts

        to_send = filter_telegram_alerts(opportunities, deduplicate=True)
        if not to_send:
            return 0
        return await send_arbitrage_alerts(to_send, deduplicate=False)

    async def run(
        self,
        sport: Sport,
        *,
        send_telegram: bool = False,
    ) -> list[ArbitrageOpportunity]:
        opportunities = await self.scan_sport(sport)
        await self.notify_arbitrage(opportunities, send_telegram=send_telegram)
        return opportunities

    async def run_all_sports(
        self,
        sports: Iterable[Sport] | None = None,
        *,
        send_telegram: bool = False,
    ) -> list[ArbitrageOpportunity]:
        sports = list(sports or ALL_SPORTS)
        logger.info("Scanning %d sport(s) in parallel", len(sports))

        scan_results = await asyncio.gather(
            *[self.scan_sport(sport) for sport in sports],
            return_exceptions=True,
        )

        opportunities: list[ArbitrageOpportunity] = []
        for sport, result in zip(sports, scan_results):
            if isinstance(result, Exception):
                logger.error("Arb scan failed for %s: %s", sport.value, result)
                continue
            opportunities.extend(result)

        opportunities.sort(key=lambda o: o.margin_pct, reverse=True)
        await self.notify_arbitrage(opportunities, send_telegram=send_telegram)
        return opportunities
