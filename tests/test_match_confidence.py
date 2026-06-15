from __future__ import annotations

from datetime import datetime, timezone

from moneyline.arb.engine import ArbitrageEngine
from moneyline.matching.confidence import cluster_allows_arbitrage
from moneyline.matching.fuzzy import EventMatcher
from moneyline.models.schemas import (
    Bookmaker,
    Event,
    MarketOdds,
    MarketPeriod,
    MatchedEvent,
    OddsOutcome,
    OutcomeSide,
    Sport,
)


def _event(
    book: Bookmaker,
    *,
    eid: str,
    home: str,
    away: str,
    parent: str | None = None,
    competition: str | None = None,
) -> Event:
    start = datetime(2026, 5, 24, 18, 0, tzinfo=timezone.utc)
    return Event(
        event_key=f"{book.value}:{eid}",
        bookmaker=book,
        external_id=eid,
        parent_match_id=parent,
        sport=Sport.SOCCER,
        home_team=home,
        away_team=away,
        competition=competition,
        start_time=start,
    )


def test_sportradar_trio_cluster_fixture_and_confidence() -> None:
    matcher = EventMatcher()
    betika = _event(Bookmaker.BETIKA, eid="1", home="A", away="B", parent="999")
    odibets = _event(Bookmaker.ODIBETS, eid="1", home="Team A", away="Team B", parent="999")
    clusters = matcher.match_events([betika, odibets])
    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.match_confidence == 1.0
    assert cluster.match_confidence_kind == "sportradar_id"
    assert len(cluster.fixture_id) == 16
    assert cluster_allows_arbitrage(cluster)


def test_betradar_parent_id_cluster_confidence() -> None:
    matcher = EventMatcher()
    betika = _event(Bookmaker.BETIKA, eid="1", home="Hull City", away="Middlesbrough", parent="71631024")
    bangbet = _event(
        Bookmaker.BANGBET,
        eid="1",
        home="Hull City",
        away="Middlesbrough FC",
        parent="71631024",
    )
    clusters = matcher.match_events([betika, bangbet])
    assert len(clusters) == 1
    assert clusters[0].match_confidence == 0.95
    assert clusters[0].match_confidence_kind == "betradar_id"
    assert cluster_allows_arbitrage(clusters[0])


def test_fuzzy_cluster_blocks_arbitrage() -> None:
    matcher = EventMatcher()
    palmsbet = _event(
        Bookmaker.PALMSBET,
        eid="p1",
        home="Arsenal FC",
        away="Chelsea FC",
        competition="Kenyan Premier League",
    )
    betpawa = _event(
        Bookmaker.BETPAWA,
        eid="b1",
        home="Arsenal",
        away="Chelsea",
        competition="Community Shield",
    )
    clusters = matcher.match_events([palmsbet, betpawa])
    assert clusters == []


def test_fuzzy_cluster_allows_arbitrage_when_competition_aliases_match() -> None:
    matcher = EventMatcher()
    palmsbet = _event(
        Bookmaker.PALMSBET,
        eid="p1",
        home="Arsenal FC",
        away="Chelsea FC",
        competition="Premier League",
    )
    betpawa = _event(
        Bookmaker.BETPAWA,
        eid="b1",
        home="Arsenal",
        away="Chelsea",
        competition="EPL",
    )
    clusters = matcher.match_events([palmsbet, betpawa])
    assert len(clusters) == 1
    cluster = clusters[0]
    assert cluster.match_confidence_kind == "fuzzy_competition"
    assert cluster_allows_arbitrage(cluster)


def test_fuzzy_only_cluster_still_blocked_for_arbs() -> None:
    start = datetime(2026, 5, 24, 18, 0, tzinfo=timezone.utc)
    palmsbet = _event(
        Bookmaker.PALMSBET,
        eid="p1",
        home="Arsenal FC",
        away="Chelsea FC",
        competition="Kenyan Premier League",
    )
    betpawa = _event(
        Bookmaker.BETPAWA,
        eid="b1",
        home="Arsenal",
        away="Chelsea",
        competition="Community Shield",
    )
    cluster = MatchedEvent(
        cluster_id="fz_manual",
        sport=Sport.SOCCER,
        home_team=palmsbet.home_team,
        away_team=palmsbet.away_team,
        start_time=start,
        match_confidence=0.80,
        match_confidence_kind="fuzzy_only",
        events={Bookmaker.PALMSBET: palmsbet, Bookmaker.BETPAWA: betpawa},
    )
    assert not cluster_allows_arbitrage(cluster)
    engine = ArbitrageEngine(min_margin_pct=0.1)
    markets = [
        MarketOdds(
            event_key=palmsbet.event_key,
            bookmaker=Bookmaker.PALMSBET,
            sport=Sport.SOCCER,
            market_key="btts",
            market_display="BTTS",
            period=MarketPeriod.FULL_TIME,
            outcomes=[
                OddsOutcome(side=OutcomeSide.YES, label="Yes", price=2.5),
                OddsOutcome(side=OutcomeSide.NO, label="No", price=1.5),
            ],
        ),
        MarketOdds(
            event_key=betpawa.event_key,
            bookmaker=Bookmaker.BETPAWA,
            sport=Sport.SOCCER,
            market_key="btts",
            market_display="BTTS",
            period=MarketPeriod.FULL_TIME,
            outcomes=[
                OddsOutcome(side=OutcomeSide.YES, label="Yes", price=1.4),
                OddsOutcome(side=OutcomeSide.NO, label="No", price=3.5),
            ],
        ),
    ]
    by_event = {
        palmsbet.event_key: [markets[0]],
        betpawa.event_key: [markets[1]],
    }
    assert engine.find_arbitrage([cluster], by_event) == []


def test_low_confidence_manual_cluster_blocked() -> None:
    start = datetime(2026, 5, 24, 18, 0, tzinfo=timezone.utc)
    cluster = MatchedEvent(
        cluster_id="fz_abc",
        sport=Sport.SOCCER,
        home_team="A",
        away_team="B",
        start_time=start,
        match_confidence=0.80,
        match_confidence_kind="fuzzy_only",
        events={
            Bookmaker.PALMSBET: Event(
                event_key="palmsbet:1",
                bookmaker=Bookmaker.PALMSBET,
                external_id="1",
                sport=Sport.SOCCER,
                home_team="A",
                away_team="B",
                start_time=start,
            ),
            Bookmaker.BETPAWA: Event(
                event_key="betpawa:1",
                bookmaker=Bookmaker.BETPAWA,
                external_id="1",
                sport=Sport.SOCCER,
                home_team="A",
                away_team="B",
                start_time=start,
            ),
        },
    )
    assert not cluster_allows_arbitrage(cluster)
