from datetime import datetime, timezone

from moneyline.markets.normalizer import MarketNormalizer
from moneyline.matching.fuzzy import EventMatcher
from moneyline.models.schemas import Bookmaker, MarketOdds, MarketPeriod, OddsOutcome, OutcomeSide, Sport


def test_expand_by_line_splits_over_under():
    normalizer = MarketNormalizer()
    market = MarketOdds(
        event_key="betika:1",
        bookmaker=Bookmaker.BETIKA,
        sport=Sport.SOCCER,
        market_key="over_under_goals",
        market_display="Over/Under Goals",
        period=MarketPeriod.FULL_TIME,
        line=2.5,
        sub_type_id="18",
        outcomes=[
            OddsOutcome(side=OutcomeSide.OVER, label="OVER 2.5", price=1.21, line=2.5),
            OddsOutcome(side=OutcomeSide.UNDER, label="UNDER 2.5", price=4.5, line=2.5),
            OddsOutcome(side=OutcomeSide.OVER, label="OVER 3.5", price=1.53, line=3.5),
            OddsOutcome(side=OutcomeSide.UNDER, label="UNDER 3.5", price=2.5, line=3.5),
        ],
    )
    split = normalizer.expand_by_line(market)
    assert len(split) == 2
    assert {m.line for m in split} == {2.5, 3.5}
    assert all(len(m.outcomes) == 2 for m in split)


def test_sportradar_parent_id_skips_fuzzy_name_check():
    matcher = EventMatcher(time_window_minutes=30)
    betika = __import__("moneyline.models.schemas", fromlist=["Event"]).Event(
        event_key="betika:99",
        bookmaker=Bookmaker.BETIKA,
        external_id="99",
        parent_match_id="34277499",
        sport=Sport.SOCCER,
        home_team="BILBAO",
        away_team="Osasuna",
        start_time=datetime(2026, 5, 24, 18, 0, tzinfo=timezone.utc),
    )
    odibets = __import__("moneyline.models.schemas", fromlist=["Event"]).Event(
        event_key="odibets:99",
        bookmaker=Bookmaker.ODIBETS,
        external_id="99",
        parent_match_id="34277499",
        sport=Sport.SOCCER,
        home_team="Athletic Bilbao",
        away_team="CA Osasuna",
        start_time=datetime(2026, 5, 24, 18, 0, tzinfo=timezone.utc),
    )
    clusters = matcher.match_events([betika, odibets])
    assert len(clusters) == 1
    assert Bookmaker.BETIKA in clusters[0].events
    assert Bookmaker.ODIBETS in clusters[0].events
