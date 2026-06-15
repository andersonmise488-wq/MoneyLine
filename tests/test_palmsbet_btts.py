"""Tests for PalmsBet BTTS filtering and yes/no mapping."""
from moneyline.markets.handicap import side_from_yes_no_label
from moneyline.markets.name_mapper import NameMarketMapper
from moneyline.markets.registry import MarketRegistry
from moneyline.models.schemas import Bookmaker, MarketPeriod, OddsOutcome, OutcomeSide, Sport


def test_btts_corner_variant_rejected():
    reg = MarketRegistry()
    assert reg.resolve(Sport.SOCCER, "Both teams to score 4+ corners") is None
    assert reg.resolve(Sport.SOCCER, "Both teams to score 2 or more goals") is None
    assert reg.resolve(Sport.SOCCER, "Draw or both teams to score") is None
    assert reg.resolve(Sport.SOCCER, "Both teams to score 1+ cards") is None


def test_btts_standard_accepted():
    reg = MarketRegistry()
    assert reg.resolve(Sport.SOCCER, "Both teams to score") is not None
    assert reg.resolve(Sport.SOCCER, "1st half - both teams to score") is not None
    assert reg.resolve(Sport.SOCCER, "2nd half - both teams to score") is not None


def test_palmsbet_btts_half_period():
    mapper = NameMarketMapper()
    built = mapper.build_market(
        sport=Sport.SOCCER,
        bookmaker=Bookmaker.PALMSBET,
        event_key="palmsbet:1",
        market_name="2nd half - both teams to score",
        outcomes=[
            OddsOutcome(side=OutcomeSide.YES, label="Yes", price=3.6),
            OddsOutcome(side=OutcomeSide.NO, label="No", price=1.25),
        ],
    )
    assert built is not None
    assert built.market_key == "btts"
    assert built.period == MarketPeriod.SECOND_HALF


def test_altenar_yes_no_selection_ids():
    allowed = {"yes", "no"}
    assert side_from_yes_no_label("", "74", allowed=allowed) == OutcomeSide.YES
    assert side_from_yes_no_label("", "76", allowed=allowed) == OutcomeSide.NO
