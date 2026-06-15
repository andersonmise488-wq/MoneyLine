"""Tests for sport-scoped book market ID maps."""

from moneyline.markets.book_maps import (
    resolve_betpawa_market_type,
    resolve_sportradar_sub_type,
)
from moneyline.models.schemas import Bookmaker, Sport


def test_resolve_sportradar_sub_type_soccer_1x2():
    key = resolve_sportradar_sub_type(Bookmaker.BETIKA, Sport.SOCCER, "1")
    assert key == "match_result_1x2"


def test_resolve_sportradar_sub_type_ice_hockey_period():
    key = resolve_sportradar_sub_type(Bookmaker.ODIBETS, Sport.ICE_HOCKEY, "432")
    assert key == "period_betting"


def test_resolve_betpawa_1x2():
    key = resolve_betpawa_market_type(Sport.SOCCER, "3743")
    assert key == "match_result_1x2"
