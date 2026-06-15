from datetime import datetime, timezone

from moneyline.arb.engine import ArbitrageEngine, resolve_market_line
from moneyline.markets.grouping import effective_sub_type_id, market_group_key
from moneyline.markets.period import detect_period
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
from moneyline.timezone import format_eat


def _market(
    *,
    bookmaker: Bookmaker,
    market_key: str,
    period: MarketPeriod,
    line: float | None,
    outcomes: list[OddsOutcome],
    event_key: str = "ev1",
) -> MarketOdds:
    return MarketOdds(
        event_key=event_key,
        bookmaker=bookmaker,
        sport=Sport.SOCCER,
        market_key=market_key,
        market_display=market_key,
        period=period,
        line=line,
        outcomes=outcomes,
    )


def test_resolve_outcome_label():
    from moneyline.markets.period import resolve_outcome_label

    assert resolve_outcome_label("Under {formattedHandicap}", 6.0) == "Under 6"
    assert resolve_outcome_label("Over 2.5", 2.5) == "Over 2.5"

    assert detect_period("Total Goals 1st Half") == MarketPeriod.FIRST_HALF
    assert detect_period("Total Goals 2nd Half") == MarketPeriod.SECOND_HALF
    assert detect_period("Over/Under Full Time") == MarketPeriod.FULL_TIME
    assert detect_period("Total Goals") == MarketPeriod.FULL_TIME
    assert (
        detect_period("Total Goals Over/Under - Half Time", "over_under_goals")
        == MarketPeriod.FIRST_HALF
    )
    assert detect_period("Both Teams To Score Half Time", "btts") == MarketPeriod.FULL_TIME
    assert detect_period("Both Teams To Score 1st Half", "btts") == MarketPeriod.FIRST_HALF


def test_format_eat():
    dt = datetime(2026, 5, 23, 9, 0, tzinfo=timezone.utc)
    assert format_eat(dt) == "2026-05-23 12:00 EAT"


def test_rejects_mismatched_total_lines():
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
            Bookmaker.ODIBETS: Event(
                event_key="odibets:1",
                bookmaker=Bookmaker.ODIBETS,
                external_id="1",
                sport=Sport.SOCCER,
                home_team="A",
                away_team="B",
                start_time=start,
            ),
        },
    )
    markets = [
        _market(
            bookmaker=Bookmaker.BETIKA,
            market_key="over_under_goals",
            period=MarketPeriod.FULL_TIME,
            line=2.5,
            outcomes=[
                OddsOutcome(side=OutcomeSide.OVER, label="Over 2.5", price=2.2, line=2.5),
                OddsOutcome(side=OutcomeSide.UNDER, label="Under 2.5", price=1.7, line=2.5),
            ],
            event_key="betika:1",
        ),
        _market(
            bookmaker=Bookmaker.ODIBETS,
            market_key="over_under_goals",
            period=MarketPeriod.FULL_TIME,
            line=0.5,
            outcomes=[
                OddsOutcome(side=OutcomeSide.OVER, label="Over 0.5", price=9.0, line=0.5),
                OddsOutcome(side=OutcomeSide.UNDER, label="Under 0.5", price=1.2, line=0.5),
            ],
            event_key="odibets:1",
        ),
    ]
    by_event = {
        "betika:1": [markets[0]],
        "odibets:1": [markets[1]],
    }
    assert engine.find_arbitrage([cluster], by_event) == []


def test_finds_same_line_total_arb():
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
            Bookmaker.ODIBETS: Event(
                event_key="odibets:1",
                bookmaker=Bookmaker.ODIBETS,
                external_id="1",
                sport=Sport.SOCCER,
                home_team="A",
                away_team="B",
                start_time=start,
            ),
        },
    )
    markets = [
        _market(
            bookmaker=Bookmaker.BETIKA,
            market_key="over_under_goals",
            period=MarketPeriod.FULL_TIME,
            line=2.5,
            outcomes=[OddsOutcome(side=OutcomeSide.OVER, label="Over 2.5", price=2.2, line=2.5)],
            event_key="betika:1",
        ),
        _market(
            bookmaker=Bookmaker.ODIBETS,
            market_key="over_under_goals",
            period=MarketPeriod.FULL_TIME,
            line=2.5,
            outcomes=[OddsOutcome(side=OutcomeSide.UNDER, label="Under 2.5", price=2.2, line=2.5)],
            event_key="odibets:1",
        ),
    ]
    by_event = {
        "betika:1": [markets[0]],
        "odibets:1": [markets[1]],
    }
    results = engine.find_arbitrage([cluster], by_event)
    assert len(results) == 1
    assert results[0].line == 2.5
    assert results[0].period == MarketPeriod.FULL_TIME


def test_separates_half_periods():
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
            Bookmaker.ODIBETS: Event(
                event_key="odibets:1",
                bookmaker=Bookmaker.ODIBETS,
                external_id="1",
                sport=Sport.SOCCER,
                home_team="A",
                away_team="B",
                start_time=start,
            ),
        },
    )
    markets = [
        _market(
            bookmaker=Bookmaker.BETIKA,
            market_key="over_under_goals",
            period=MarketPeriod.FIRST_HALF,
            line=1.5,
            outcomes=[OddsOutcome(side=OutcomeSide.OVER, label="Over 1.5", price=2.0, line=1.5)],
            event_key="betika:1",
        ),
        _market(
            bookmaker=Bookmaker.ODIBETS,
            market_key="over_under_goals",
            period=MarketPeriod.FULL_TIME,
            line=1.5,
            outcomes=[OddsOutcome(side=OutcomeSide.UNDER, label="Under 1.5", price=2.0, line=1.5)],
            event_key="odibets:1",
        ),
    ]
    by_event = {
        "betika:1": [markets[0]],
        "odibets:1": [markets[1]],
    }
    assert engine.find_arbitrage([cluster], by_event) == []


def test_resolve_market_line_rejects_inconsistent_outcomes():
    market = _market(
        bookmaker=Bookmaker.BETIKA,
        market_key="over_under_goals",
        period=MarketPeriod.FULL_TIME,
        line=None,
        outcomes=[
            OddsOutcome(side=OutcomeSide.OVER, label="Over 2.5", price=2.0, line=2.5),
            OddsOutcome(side=OutcomeSide.UNDER, label="Under 0.5", price=1.8, line=0.5),
        ],
    )
    assert resolve_market_line(market) is None


def test_rejects_team_total_vs_match_total():
    engine = ArbitrageEngine(min_margin_pct=0.1)
    start = datetime.now(timezone.utc)
    cluster = MatchedEvent(
        cluster_id="c1",
        sport=Sport.SOCCER,
        home_team="Betis",
        away_team="Levante",
        start_time=start,
        events={
            Bookmaker.BETIKA: Event(
                event_key="betika:1",
                bookmaker=Bookmaker.BETIKA,
                external_id="1",
                sport=Sport.SOCCER,
                home_team="Betis",
                away_team="Levante",
                start_time=start,
            ),
            Bookmaker.SPORTPESA: Event(
                event_key="sportpesa:1",
                bookmaker=Bookmaker.SPORTPESA,
                external_id="1",
                sport=Sport.SOCCER,
                home_team="Betis",
                away_team="Levante",
                start_time=start,
            ),
        },
    )
    betika = _market(
        bookmaker=Bookmaker.BETIKA,
        market_key="over_under_goals",
        period=MarketPeriod.FULL_TIME,
        line=0.5,
        outcomes=[
            OddsOutcome(side=OutcomeSide.OVER, label="OVER 0.5", price=1.04, line=0.5),
            OddsOutcome(side=OutcomeSide.UNDER, label="UNDER 0.5", price=13.0, line=0.5),
        ],
        event_key="betika:1",
    )
    betika = betika.model_copy(update={"sub_type_id": "18", "raw_market_name": "TOTAL"})
    sportpesa = _market(
        bookmaker=Bookmaker.SPORTPESA,
        market_key="team_totals",
        period=MarketPeriod.FULL_TIME,
        line=0.5,
        outcomes=[
            OddsOutcome(side=OutcomeSide.OVER, label="OV", price=1.23, line=0.5),
            OddsOutcome(side=OutcomeSide.UNDER, label="UN", price=3.70, line=0.5),
        ],
        event_key="sportpesa:1",
    )
    sportpesa = sportpesa.model_copy(
        update={"raw_market_name": "Total Goals Over/Under Away Team - Full Time"}
    )
    by_event = {"betika:1": [betika], "sportpesa:1": [sportpesa]}
    assert engine.find_arbitrage([cluster], by_event) == []


def test_synthetic_sub_type_aligns_sportpesa_match_total_with_sportradar():
    market = _market(
        bookmaker=Bookmaker.SPORTPESA,
        market_key="over_under_goals",
        period=MarketPeriod.FULL_TIME,
        line=2.5,
        outcomes=[OddsOutcome(side=OutcomeSide.OVER, label="OV", price=2.0, line=2.5)],
    )
    assert effective_sub_type_id(market) == "18"
    key = market_group_key(market, line=2.5)
    assert key[2] == "18"


def test_whole_number_total_line_rejected_for_arb():
    engine = ArbitrageEngine(min_margin_pct=0.1)
    start = datetime.now(timezone.utc)
    cluster = MatchedEvent(
        cluster_id="c1",
        sport=Sport.SOCCER,
        home_team="A",
        away_team="B",
        start_time=start,
        events={
            Bookmaker.BETPAWA: Event(
                event_key="betpawa:1",
                bookmaker=Bookmaker.BETPAWA,
                external_id="1",
                sport=Sport.SOCCER,
                home_team="A",
                away_team="B",
                start_time=start,
            ),
            Bookmaker.SPORTPESA: Event(
                event_key="sportpesa:1",
                bookmaker=Bookmaker.SPORTPESA,
                external_id="1",
                sport=Sport.SOCCER,
                home_team="A",
                away_team="B",
                start_time=start,
            ),
        },
    )
    markets = [
        _market(
            bookmaker=Bookmaker.SPORTPESA,
            market_key="over_under_goals",
            period=MarketPeriod.FULL_TIME,
            line=2.0,
            outcomes=[OddsOutcome(side=OutcomeSide.OVER, label="OV", price=1.28, line=2.0)],
            event_key="sportpesa:1",
        ),
        _market(
            bookmaker=Bookmaker.BETPAWA,
            market_key="over_under_goals",
            period=MarketPeriod.FULL_TIME,
            line=2.0,
            outcomes=[OddsOutcome(side=OutcomeSide.UNDER, label="UN", price=10.0, line=2.0)],
            event_key="betpawa:1",
        ),
    ]
    by_event = {"betpawa:1": [markets[1]], "sportpesa:1": [markets[0]]}
    assert engine.find_arbitrage([cluster], by_event) == []


def test_sportpesa_half_time_total_does_not_arb_with_full_time():
    engine = ArbitrageEngine(min_margin_pct=0.1)
    start = datetime.now(timezone.utc)
    cluster = MatchedEvent(
        cluster_id="c1",
        sport=Sport.SOCCER,
        home_team="A",
        away_team="B",
        start_time=start,
        events={
            Bookmaker.SPORTPESA: Event(
                event_key="sportpesa:1",
                bookmaker=Bookmaker.SPORTPESA,
                external_id="1",
                sport=Sport.SOCCER,
                home_team="A",
                away_team="B",
                start_time=start,
            ),
            Bookmaker.BETIKA: Event(
                event_key="betika:1",
                bookmaker=Bookmaker.BETIKA,
                external_id="1",
                sport=Sport.SOCCER,
                home_team="A",
                away_team="B",
                start_time=start,
            ),
        },
    )
    sportpesa_half = _market(
        bookmaker=Bookmaker.SPORTPESA,
        market_key="over_under_goals",
        period=MarketPeriod.FIRST_HALF,
        line=0.5,
        outcomes=[
            OddsOutcome(side=OutcomeSide.OVER, label="OV", price=1.04, line=0.5),
            OddsOutcome(side=OutcomeSide.UNDER, label="UN", price=13.0, line=0.5),
        ],
        event_key="sportpesa:1",
    ).model_copy(update={"raw_market_name": "Total Goals Over/Under - Half Time"})
    betika_ft = _market(
        bookmaker=Bookmaker.BETIKA,
        market_key="over_under_goals",
        period=MarketPeriod.FULL_TIME,
        line=0.5,
        outcomes=[
            OddsOutcome(side=OutcomeSide.OVER, label="OVER 0.5", price=1.03, line=0.5),
            OddsOutcome(side=OutcomeSide.UNDER, label="UNDER 0.5", price=15.0, line=0.5),
        ],
        event_key="betika:1",
    )
    by_event = {"sportpesa:1": [sportpesa_half], "betika:1": [betika_ft]}
    assert engine.find_arbitrage([cluster], by_event) == []
