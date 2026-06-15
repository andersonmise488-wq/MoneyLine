"""Tests for handicap line/side parsing and registry routing."""
from moneyline.markets.handicap import (
    parse_european_scoreline,
    parse_handicap_line,
    side_from_european_label,
)
from moneyline.markets.normalizer import MarketNormalizer
from moneyline.markets.registry import MarketRegistry
from moneyline.models.schemas import Bookmaker, MarketOdds, MarketPeriod, OddsOutcome, OutcomeSide, Sport


def test_parse_european_scoreline():
    assert parse_european_scoreline("0:1") == -1.0
    assert parse_european_scoreline("1:0") == 1.0
    assert parse_european_scoreline("hcp=0:1") == -1.0


def test_parse_handicap_line_from_specifier():
    assert parse_handicap_line("hcp=-0.5&", "Asian Handicap") == -0.5
    assert parse_handicap_line("hcp=0:1&", "Handicap 0:1") == -1.0


def test_bangbet_handicap_0_1_is_european():
    reg = MarketRegistry()
    hit = reg.resolve(Sport.SOCCER, "Handicap 0:1")
    assert hit is not None
    assert hit[0] == "european_handicap"


def test_bangbet_asian_handicap_stays_asian():
    reg = MarketRegistry()
    hit = reg.resolve(Sport.SOCCER, "Asian Handicap")
    assert hit is not None
    assert hit[0] == "asian_handicap"


def test_palmsbet_handicap_1x2_is_european():
    reg = MarketRegistry()
    hit = reg.resolve(Sport.SOCCER, "Handicap 1x2")
    assert hit is not None
    assert hit[0] == "european_handicap"


def test_betika_european_handicap_outcomes():
    normalizer = MarketNormalizer()
    raw = [
        {
            "outcome_id": "1711",
            "display": "1 (0:1)",
            "odd_value": 5.0,
            "special_bet_value": "hcp=0:1",
        },
        {
            "outcome_id": "1712",
            "display": "X (0:1)",
            "odd_value": 3.95,
            "special_bet_value": "hcp=0:1",
        },
        {
            "outcome_id": "1713",
            "display": "2 (0:1)",
            "odd_value": 1.52,
            "special_bet_value": "hcp=0:1",
        },
    ]
    spec = {"outcomes": ["home", "draw", "away"], "line_field": "handicap"}
    outcomes = normalizer._parse_betika_outcomes(raw, spec)
    assert len(outcomes) == 3
    assert {o.side for o in outcomes} == {OutcomeSide.HOME, OutcomeSide.DRAW, OutcomeSide.AWAY}
    assert all(o.line == -1.0 for o in outcomes)


def test_three_way_handicap_name_aliases():
    reg = MarketRegistry()
    for name in (
        "3 way handicap",
        "Handicap (3 way)",
        "Handicap 3 way",
        "Goals Handicap 3 Way (-1.0)",
    ):
        hit = reg.resolve(Sport.SOCCER, name)
        assert hit is not None, name
        assert hit[0] == "european_handicap", name


def test_european_handicap_draw_labels():
    from moneyline.markets.name_mapper import side_from_label

    spec = {"outcomes": ["home", "draw", "away"]}
    for label, expected in (
        ("Draw (0:1)", OutcomeSide.DRAW),
        ("Home (0:1)", OutcomeSide.HOME),
        ("Away (0:1)", OutcomeSide.AWAY),
        ("Tie: Team 2 (1)", OutcomeSide.DRAW),
        ("1", OutcomeSide.HOME),
        ("X", OutcomeSide.DRAW),
        ("2", OutcomeSide.AWAY),
    ):
        assert side_from_label(label, spec) == expected, label


def test_expand_by_line_drops_incomplete_european():
    normalizer = MarketNormalizer()
    market = MarketOdds(
        event_key="palmsbet:1",
        bookmaker=Bookmaker.PALMSBET,
        sport=Sport.SOCCER,
        market_key="european_handicap",
        market_display="European Handicap",
        is_live=False,
        line=None,
        period=MarketPeriod.FULL_TIME,
        outcomes=[
            OddsOutcome(side=OutcomeSide.HOME, label="1 (0:2)", price=2.0, line=-2.0),
            OddsOutcome(side=OutcomeSide.DRAW, label="Draw (0:2)", price=3.0, line=-2.0),
            OddsOutcome(side=OutcomeSide.HOME, label="1 (0:1)", price=2.0, line=-1.0),
            OddsOutcome(side=OutcomeSide.DRAW, label="Draw (0:1)", price=3.0, line=-1.0),
            OddsOutcome(side=OutcomeSide.AWAY, label="2 (0:1)", price=2.0, line=-1.0),
        ],
        raw_market_name="Handicap 1x2",
    )
    expanded = normalizer.expand_by_line(market)
    assert len(expanded) == 1
    assert {o.side for o in expanded[0].outcomes} == {
        OutcomeSide.HOME,
        OutcomeSide.DRAW,
        OutcomeSide.AWAY,
    }


def test_european_side_from_team_name():
    side = side_from_european_label(
        "Bolton Wanderers (0:1)",
        "1711",
        allowed={"home", "draw", "away"},
    )
    assert side == OutcomeSide.HOME
