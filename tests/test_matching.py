from datetime import datetime, timezone

from moneyline.arb.engine import ArbitrageEngine
from moneyline.markets.registry import MarketRegistry
from moneyline.matching.fuzzy import EventMatcher
from moneyline.matching.ids import normalize_parent_match_id
from moneyline.models.schemas import Bookmaker, Event, MarketOdds, MarketPeriod, MatchedEvent, OddsOutcome, OutcomeSide, Sport
from moneyline.timezone import attach_eat_if_naive


def test_normalize_parent_match_id():
    assert normalize_parent_match_id("71631024") == "71631024"
    assert normalize_parent_match_id("sr:match:71631024") == "71631024"
    assert normalize_parent_match_id("fp32_ar:match:547043") == "547043"


def test_registry_blocks_corner_1x2():
    registry = MarketRegistry()
    assert registry.resolve(Sport.SOCCER, "Corner 1x2") is None
    assert registry.resolve(Sport.SOCCER, "1x2 Total Shots (reg.time)") is None
    assert registry.resolve(Sport.SOCCER, "1x2") is not None


def test_matcher_links_sportradar_and_utc_kickoffs():
    matcher = EventMatcher(time_window_minutes=30)
    betika = Event(
        event_key="betika:71631024",
        bookmaker=Bookmaker.BETIKA,
        external_id="71631024",
        parent_match_id="71631024",
        sport=Sport.SOCCER,
        home_team="Hull City",
        away_team="Middlesbrough",
        start_time=attach_eat_if_naive(datetime(2026, 5, 23, 17, 30)),
    )
    bangbet = Event(
        event_key="bangbet:71631024",
        bookmaker=Bookmaker.BANGBET,
        external_id="71631024",
        parent_match_id="71631024",
        sport=Sport.SOCCER,
        home_team="Hull City",
        away_team="Middlesbrough FC",
        start_time=datetime(2026, 5, 23, 14, 30, tzinfo=timezone.utc),
    )
    clusters = matcher.match_events([betika, bangbet])
    assert len(clusters) == 1
    assert len(clusters[0].events) == 2


def test_rejects_same_bookmaker_on_multiple_legs():
    engine = ArbitrageEngine(min_margin_pct=0.1)
    start = datetime.now(timezone.utc)
    cluster = MatchedEvent(
        cluster_id="c1",
        sport=Sport.SOCCER,
        home_team="A",
        away_team="B",
        start_time=start,
        events={
            Bookmaker.BETIKA: Event(
                event_key="betika:1",
                bookmaker=Bookmaker.BETIKA,
                external_id="1",
                sport=Sport.SOCCER,
                home_team="A",
                away_team="B",
                start_time=start,
            ),
            Bookmaker.PALMSBET: Event(
                event_key="palmsbet:1",
                bookmaker=Bookmaker.PALMSBET,
                external_id="1",
                sport=Sport.SOCCER,
                home_team="A",
                away_team="B",
                start_time=start,
            ),
        },
    )
    markets = [
        MarketOdds(
            event_key="betika:1",
            bookmaker=Bookmaker.BETIKA,
            sport=Sport.SOCCER,
            market_key="match_result_1x2",
            market_display="1X2",
            period=MarketPeriod.FULL_TIME,
            outcomes=[OddsOutcome(side=OutcomeSide.HOME, label="1", price=4.6)],
        ),
        MarketOdds(
            event_key="palmsbet:1",
            bookmaker=Bookmaker.PALMSBET,
            sport=Sport.SOCCER,
            market_key="match_result_1x2",
            market_display="1X2",
            period=MarketPeriod.FULL_TIME,
            outcomes=[
                OddsOutcome(side=OutcomeSide.DRAW, label="Draw", price=16.0),
                OddsOutcome(side=OutcomeSide.AWAY, label="2", price=2.9),
            ],
        ),
    ]
    by_event = {"betika:1": [markets[0]], "palmsbet:1": [markets[1]]}
    assert engine.find_arbitrage([cluster], by_event) == []
