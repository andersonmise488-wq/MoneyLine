"""Test SportPesa maps team totals separately from match totals."""
from moneyline.markets.registry import MarketRegistry
from moneyline.models.schemas import Sport


def test_sportpesa_team_total_not_match_total():
    reg = MarketRegistry()
    hit = reg.resolve(Sport.SOCCER, "Total Goals Over/Under Away Team - Full Time")
    assert hit is not None
    assert hit[0] == "team_totals"


def test_sportpesa_match_total_stays_match_total():
    reg = MarketRegistry()
    hit = reg.resolve(Sport.SOCCER, "Total Goals Over/Under - Full Time")
    assert hit is not None
    assert hit[0] == "over_under_goals"


def test_sportpesa_half_time_total_is_first_half_period():
    from moneyline.markets.name_mapper import NameMarketMapper
    from moneyline.models.schemas import Bookmaker, MarketPeriod, OddsOutcome, OutcomeSide

    mapper = NameMarketMapper()
    built = mapper.build_market(
        sport=Sport.SOCCER,
        bookmaker=Bookmaker.SPORTPESA,
        event_key="sportpesa:1",
        market_name="Total Goals Over/Under - Half Time",
        outcomes=[
            OddsOutcome(side=OutcomeSide.OVER, label="OV", price=1.5, line=0.5),
            OddsOutcome(side=OutcomeSide.UNDER, label="UN", price=2.5, line=0.5),
        ],
        line=0.5,
    )
    assert built is not None
    assert built.market_key == "over_under_goals"
    assert built.period == MarketPeriod.FIRST_HALF


def test_betpawa_away_team_total_not_match_total():
    reg = MarketRegistry()
    hit = reg.resolve(Sport.SOCCER, "Over/Under | {away} | Full Time")
    assert hit is not None
    assert hit[0] == "team_totals"


def test_sportpesa_euro_handicap_not_asian():
    reg = MarketRegistry()
    hit = reg.resolve(Sport.SOCCER, "Euro Handicap")
    assert hit is not None
    assert hit[0] == "european_handicap"

    from moneyline.markets.name_mapper import NameMarketMapper
    from moneyline.models.schemas import Bookmaker, MarketPeriod, OddsOutcome, OutcomeSide

    mapper = NameMarketMapper()
    built = mapper.build_market(
        sport=Sport.SOCCER,
        bookmaker=Bookmaker.SPORTPESA,
        event_key="sportpesa:1",
        market_name="Euro Handicap",
        outcomes=[
            OddsOutcome(side=OutcomeSide.HOME, label="1", price=1.56, line=1.0),
            OddsOutcome(side=OutcomeSide.DRAW, label="X", price=4.30, line=1.0),
            OddsOutcome(side=OutcomeSide.AWAY, label="2", price=3.70, line=1.0),
        ],
        line=1.0,
    )
    assert built is not None
    assert built.market_key == "european_handicap"
    assert built.period == MarketPeriod.FULL_TIME


def test_combo_total_market_rejected():
    reg = MarketRegistry()
    assert reg.resolve(Sport.SOCCER, "Full time result + Total Goals Over/Under") is None
