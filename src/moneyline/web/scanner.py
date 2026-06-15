from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone

from moneyline.arb.engine import (
    THREE_WAY_MARKET_KEYS,
    ArbitrageEngine,
    _line_ok_for_cross_book_arb,
    arb_margin,
    outcome_matches_line,
    resolve_market_line,
)
from moneyline.constants import DEFAULT_MIN_MARGIN_PCT, EVENT_LOOKAHEAD_HOURS
from moneyline.markets.spec import market_allowed_for_arb, market_spec_group_key
from moneyline.matching.confidence import cluster_allows_arbitrage
from moneyline.markets.period import label_has_unresolved_template, market_requires_line
from moneyline.models.schemas import ArbitrageOpportunity, MarketOdds, MatchedEvent, OutcomeSide, Sport
from moneyline.pipeline.collector import CollectionPipeline, resolve_market_fetch_limit
from moneyline.pipeline.collection_stats import CollectionStats
from moneyline.sports import SUPPORTED_SPORTS

logger = logging.getLogger(__name__)

# Scan all configured sports concurrently (one task per sport).
SPORT_SCAN_CONCURRENCY = max(1, len(SUPPORTED_SPORTS))


@dataclass
class ScanDiagnostics:
    events_collected: int = 0
    events_with_markets: int = 0
    markets_collected: int = 0
    clusters_matched: int = 0
    sports_scanned: int = 0
    best_cross_book_margin_pct: float | None = None
    best_cross_book_label: str | None = None
    bookmaker_stats: dict[str, dict] | None = None
    weak_bookmakers: list[str] | None = None
    arbs_by_sport: dict[str, int] | None = None
    match_review_count: int = 0
    books_paused: list[str] | None = None

    def summary(self) -> str:
        best = (
            f"{self.best_cross_book_margin_pct:.2f}%"
            if self.best_cross_book_margin_pct is not None
            else "n/a"
        )
        coverage = (
            f"{100 * self.events_with_markets / self.events_collected:.0f}% with odds"
            if self.events_collected
            else "n/a"
        )
        return (
            f"{self.events_collected:,} events ({coverage}) · "
            f"{self.markets_collected:,} markets · "
            f"{self.clusters_matched:,} matched fixtures · best cross-book margin {best}"
        )


def filter_public_arbs(
    opportunities: list[ArbitrageOpportunity],
    *,
    max_margin_pct: float = 3.0,
) -> list[ArbitrageOpportunity]:
    from moneyline.web.filters import filter_public_arbs as _filter

    return _filter(opportunities, max_margin_pct=max_margin_pct)


def filter_public_teaser_arbs(
    opportunities: list[ArbitrageOpportunity],
    *,
    min_margin_pct: float = DEFAULT_MIN_MARGIN_PCT,
    max_margin_pct: float = 3.0,
) -> list[ArbitrageOpportunity]:
    _ = min_margin_pct
    return filter_public_arbs(opportunities, max_margin_pct=max_margin_pct)


def filter_premium_arbs(
    opportunities: list[ArbitrageOpportunity],
    *,
    min_margin_pct: float = 3.01,
) -> list[ArbitrageOpportunity]:
    from moneyline.web.filters import filter_premium_arbs as _filter

    return _filter(opportunities, min_margin_pct=min_margin_pct)


def _best_cross_book_margin(
    clusters: list[MatchedEvent],
    markets_by_event: dict[str, list[MarketOdds]],
    engine: ArbitrageEngine,
) -> tuple[float, str] | None:
    best: tuple[float, str] | None = None

    for cluster in clusters:
        if not cluster_allows_arbitrage(cluster):
            continue
        grouped: dict[tuple, list[MarketOdds]] = defaultdict(list)
        for bookmaker, event in cluster.events.items():
            for market in markets_by_event.get(event.event_key, []):
                if market.bookmaker != bookmaker:
                    continue
                if not market_allowed_for_arb(market):
                    continue
                line = resolve_market_line(market)
                if market_requires_line(market.market_key) and line is None:
                    continue
                if not _line_ok_for_cross_book_arb(market.market_key, line):
                    continue
                grouped[market_spec_group_key(market, line=line)].append(market)

        for (market_key, period, _sub, _scope, line, _spec_id), market_list in grouped.items():
            if len(market_list) < 2:
                continue

            best_by_side: dict[OutcomeSide, dict] = {}
            for market in market_list:
                if market.period != period:
                    continue
                market_line = resolve_market_line(market)
                if line is not None:
                    if market_line is None or abs(market_line - line) > 0.01:
                        continue
                elif market_line is not None:
                    continue

                swapped = cluster.teams_swapped.get(market.bookmaker.value, False)
                for outcome in market.outcomes:
                    if label_has_unresolved_template(outcome.label):
                        continue
                    if not outcome_matches_line(outcome.line, market.line, line):
                        continue
                    side = outcome.side
                    if swapped and side in (OutcomeSide.HOME, OutcomeSide.AWAY):
                        side = OutcomeSide.AWAY if side == OutcomeSide.HOME else OutcomeSide.HOME
                    current = best_by_side.get(side)
                    if current is None or outcome.price > current["price"]:
                        best_by_side[side] = {
                            "bookmaker": market.bookmaker.value,
                            "price": outcome.price,
                        }

            if market_key in THREE_WAY_MARKET_KEYS:
                required = (OutcomeSide.HOME, OutcomeSide.DRAW, OutcomeSide.AWAY)
                if any(side not in best_by_side for side in required):
                    continue
                legs = [best_by_side[side] for side in required]
            elif len(best_by_side) < 2:
                continue
            else:
                legs = list(best_by_side.values())

            bookies = [leg["bookmaker"] for leg in legs]
            if len(set(bookies)) != len(legs):
                continue

            _, margin = arb_margin([leg["price"] for leg in legs])
            label = f"{cluster.home_team} vs {cluster.away_team} ({market_key})"
            if best is None or margin > best[0]:
                best = (margin, label)

    return best


def _resolve_market_fetch_limit(max_markets: int) -> int | None:
    return resolve_market_fetch_limit(max_markets)


async def _scan_one_sport(
    sport: Sport,
    *,
    min_margin_pct: float,
    max_events: int,
    max_markets: int,
    lookahead_hours: int,
    probe_engine: ArbitrageEngine,
) -> tuple[Sport, list[ArbitrageOpportunity], dict, int, int, int, int, tuple[float, str] | None]:
    pipeline = CollectionPipeline(
        min_margin_pct=min_margin_pct,
        max_events=max_events,
        max_market_fetches=_resolve_market_fetch_limit(max_markets),
        lookahead_hours=lookahead_hours,
    )
    logger.info("Scanning %s…", sport.value)
    events, markets = await pipeline.collect_sport(sport)
    logger.info(
        "%s: %s events, %s markets — matching fixtures",
        sport.value,
        len(events),
        len(markets),
    )
    clusters = pipeline.matcher.match_events(events)
    markets_by_event: dict[str, list[MarketOdds]] = defaultdict(list)
    for market in markets:
        markets_by_event[market.event_key].append(market)

    best = _best_cross_book_margin(clusters, markets_by_event, probe_engine)
    opps = pipeline.detect_arbitrage(events, markets)
    logger.info(
        "%s: %s clusters, %s arbs (%s markets)",
        sport.value,
        len(clusters),
        len(opps),
        len(markets),
    )
    stats = pipeline.last_stats.to_dict() if pipeline.last_stats else {}
    return (
        sport,
        opps,
        stats,
        len(events),
        len({m.event_key for m in markets}),
        len(markets),
        len(clusters),
        best,
    )


def _stats_from_merged(merged_stats: dict[str, dict]) -> CollectionStats:
    stats = CollectionStats()
    for row in merged_stats.values():
        stats.set_row(
            bookmaker=row["bookmaker"],
            sport=row["sport"],
            events=row["events"],
            events_with_markets=row["events_with_markets"],
            markets=row["markets"],
            skipped=row.get("skipped", False),
            error=row.get("error"),
        )
    return stats


async def _scan_all(
    *,
    min_margin_pct: float,
    max_events: int,
    max_markets: int,
    lookahead_hours: int,
    sports: list[Sport],
) -> tuple[list[ArbitrageOpportunity], ScanDiagnostics]:
    probe_engine = ArbitrageEngine(min_margin_pct=-100.0, max_margin_pct=None)
    diagnostics = ScanDiagnostics(sports_scanned=len(sports))
    opportunities: list[ArbitrageOpportunity] = []
    merged_stats: dict[str, dict] = {}
    arbs_by_sport: dict[str, int] = {s.value: 0 for s in sports}
    sport_sem = asyncio.Semaphore(SPORT_SCAN_CONCURRENCY)
    logger.info(
        "Full arb scan: %d sport(s) in parallel — %s",
        len(sports),
        ", ".join(s.value for s in sports),
    )

    async def _run_sport(sport: Sport):
        async with sport_sem:
            return await _scan_one_sport(
                sport,
                min_margin_pct=min_margin_pct,
                max_events=max_events,
                max_markets=max_markets,
                lookahead_hours=lookahead_hours,
                probe_engine=probe_engine,
            )

    results = await asyncio.gather(
        *[_run_sport(sport) for sport in sports],
        return_exceptions=True,
    )

    for sport, result in zip(sports, results):
        if isinstance(result, Exception):
            logger.error("Scan failed for %s: %s", sport.value, result)
            arbs_by_sport[sport.value] = 0
            continue
        (
            _sport,
            opps,
            stats,
            event_count,
            events_with_markets,
            market_count,
            cluster_count,
            best,
        ) = result
        merged_stats.update(stats)
        diagnostics.events_collected += event_count
        diagnostics.events_with_markets += events_with_markets
        diagnostics.markets_collected += market_count
        diagnostics.clusters_matched += cluster_count
        arbs_by_sport[_sport.value] = len(opps)
        opportunities.extend(opps)
        if best and (
            diagnostics.best_cross_book_margin_pct is None
            or best[0] > diagnostics.best_cross_book_margin_pct
        ):
            diagnostics.best_cross_book_margin_pct = round(best[0], 3)
            diagnostics.best_cross_book_label = best[1]

    diagnostics.bookmaker_stats = merged_stats or None
    from moneyline.config.settings import get_settings

    aggregated = _stats_from_merged(merged_stats)
    diagnostics.weak_bookmakers = aggregated.weak_bookmakers(
        match_first_markets=get_settings().match_first_markets,
    ) or None
    diagnostics.arbs_by_sport = arbs_by_sport

    from moneyline.pipeline.handshake import build_ops_diagnostics

    ops = build_ops_diagnostics(
        events_collected=diagnostics.events_collected,
        lookahead_hours=lookahead_hours,
    )
    diagnostics.match_review_count = ops["match_review_count"]
    diagnostics.books_paused = ops["books_paused"]

    opportunities.sort(key=lambda o: o.margin_pct, reverse=True)
    return opportunities, diagnostics


def run_arb_scan(
    *,
    min_margin_pct: float = DEFAULT_MIN_MARGIN_PCT,
    max_events: int = 0,
    max_markets: int = 0,
    lookahead_hours: int = EVENT_LOOKAHEAD_HOURS,
    sports: list[Sport] | None = None,
) -> tuple[list[ArbitrageOpportunity], datetime, ScanDiagnostics]:
    target_sports = sports or SUPPORTED_SPORTS
    opportunities, diagnostics = asyncio.run(
        _scan_all(
            min_margin_pct=min_margin_pct,
            max_events=max_events,
            max_markets=max_markets,
            lookahead_hours=lookahead_hours,
            sports=target_sports,
        )
    )
    return opportunities, datetime.now(timezone.utc), diagnostics
