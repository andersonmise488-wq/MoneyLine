from moneyline.markets.name_mapper import NameMarketMapper
from moneyline.models.schemas import Bookmaker, OddsOutcome, OutcomeSide, Sport


def test_cricket_match_winner_accepts_two_way_outcomes() -> None:
    mapper = NameMarketMapper()
    built = mapper.build_market(
        sport=Sport.CRICKET,
        bookmaker=Bookmaker.PALMSBET,
        event_key="palmsbet:1",
        market_name="Winner",
        outcomes=[
            OddsOutcome(side=OutcomeSide.HOME, label="1", price=1.35),
            OddsOutcome(side=OutcomeSide.AWAY, label="2", price=2.9),
        ],
    )
    assert built is not None
    assert built.market_key == "match_winner"


def test_handball_three_way_winner_from_sportpesa_label() -> None:
    mapper = NameMarketMapper()
    built = mapper.build_market(
        sport=Sport.HANDBALL,
        bookmaker=Bookmaker.SPORTPESA,
        event_key="sportpesa:1",
        market_name="3 Way Winner",
        outcomes=[
            OddsOutcome(side=OutcomeSide.HOME, label="1", price=2.1),
            OddsOutcome(side=OutcomeSide.DRAW, label="X", price=3.2),
            OddsOutcome(side=OutcomeSide.AWAY, label="2", price=2.8),
        ],
    )
    assert built is not None
    assert built.market_key == "match_winner"


def test_ice_hockey_three_way_full_time_maps_to_match_result() -> None:
    mapper = NameMarketMapper()
    built = mapper.build_market(
        sport=Sport.ICE_HOCKEY,
        bookmaker=Bookmaker.SPORTPESA,
        event_key="sportpesa:2",
        market_name="3 Way - Full Time",
        outcomes=[
            OddsOutcome(side=OutcomeSide.HOME, label="1", price=2.5),
            OddsOutcome(side=OutcomeSide.DRAW, label="X", price=3.4),
            OddsOutcome(side=OutcomeSide.AWAY, label="2", price=2.6),
        ],
    )
    assert built is not None
    assert built.market_key == "match_result_1x2"
