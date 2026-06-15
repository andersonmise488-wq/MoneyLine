"""Tests for BangBet 1x2 filtering, Shabiki/Mozzart handicap capture."""
from moneyline.markets.name_mapper import NameMarketMapper
from moneyline.markets.registry import MarketRegistry
from moneyline.models.schemas import Bookmaker, MarketPeriod, OddsOutcome, OutcomeSide, Sport


def test_bangbet_interval_1x2_rejected():
    reg = MarketRegistry()
    assert reg.resolve(Sport.SOCCER, "10 minutes - 1x2 from 1 to 10") is None
    assert reg.resolve(Sport.SOCCER, "Corner 1x2") is None
    assert reg.resolve(Sport.SOCCER, "1x2 (1up)") is None


def test_bangbet_plain_1x2_accepted():
    reg = MarketRegistry()
    hit = reg.resolve(Sport.SOCCER, "1x2")
    assert hit is not None
    assert hit[0] == "match_result_1x2"


def test_bangbet_first_half_1x2_period():
    mapper = NameMarketMapper()
    built = mapper.build_market(
        sport=Sport.SOCCER,
        bookmaker=Bookmaker.BANGBET,
        event_key="bangbet:1",
        market_name="1st half - 1x2",
        outcomes=[
            OddsOutcome(side=OutcomeSide.HOME, label="1", price=2.1),
            OddsOutcome(side=OutcomeSide.DRAW, label="X", price=2.2),
            OddsOutcome(side=OutcomeSide.AWAY, label="2", price=3.1),
        ],
    )
    assert built is not None
    assert built.period == MarketPeriod.FIRST_HALF


def test_shabiki_goals_handicap_3way():
    reg = MarketRegistry()
    hit = reg.resolve(Sport.SOCCER, "Goals Handicap 3 Way (-1.0)")
    assert hit is not None
    assert hit[0] == "european_handicap"


def test_shabiki_goals_handicap_asian():
    reg = MarketRegistry()
    hit = reg.resolve(Sport.SOCCER, "Goals Handicap (1.5)")
    assert hit is not None
    assert hit[0] == "asian_handicap"


def test_mozzart_handicap_win_alias():
    reg = MarketRegistry()
    hit = reg.resolve(
        Sport.SOCCER, "Handicap Win with a score difference of at least 2 goals"
    )
    assert hit is not None
    assert hit[0] == "asian_handicap"
