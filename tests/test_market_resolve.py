from moneyline.canonical.markets import detect_settlement
from moneyline.markets.registry import MarketRegistry
from moneyline.markets.resolve import pattern_matches_name
from moneyline.markets.spec import market_spec_for
from moneyline.models.schemas import Bookmaker, MarketOdds, MarketPeriod, Sport


def test_pattern_match_rejects_bare_total_token():
    assert not pattern_matches_name("total", "corner match bet")
    assert pattern_matches_name("total goals", "total goals over/under - full time")


def test_volleyball_bare_total_not_mapped_to_total_points():
    reg = MarketRegistry()
    hit = reg.resolve(Sport.VOLLEYBALL, "Total")
    assert hit is None or hit[0] != "total_points"


def test_settlement_splits_regular_time_and_incl_ot():
    regular = MarketOdds(
        event_key="x:1",
        bookmaker=Bookmaker.SPORTYBET,
        sport=Sport.BASKETBALL,
        market_key="totals",
        market_display="Total Points",
        period=MarketPeriod.FULL_TIME,
        line=180.5,
        outcomes=[],
        raw_market_name="Total Points",
    )
    incl_ot = regular.model_copy(
        update={"raw_market_name": "Total (incl. overtime)", "market_display": "Total (incl. overtime)"}
    )
    assert market_spec_for(regular).settlement == "regular_time"
    assert market_spec_for(incl_ot).settlement == "incl_ot"
    assert market_spec_for(regular).spec_id() != market_spec_for(incl_ot).spec_id()


def test_detect_settlement_ot_aliases():
    assert detect_settlement("2 way - ot") == "incl_ot"
    assert detect_settlement("Winner (incl. overtime)") == "incl_ot"
    assert detect_settlement("Match Result") == "regular_time"
