from __future__ import annotations

from datetime import datetime, timezone

from moneyline.canonical.entities import (
    fixture_id_for,
    normalize_team_canonical,
)
from moneyline.canonical.markets import (
    MarketSpec,
    market_family_requires_strict_period,
    periods_blocked,
)
from moneyline.models.schemas import MarketPeriod, Sport


def test_team_alias_resolves() -> None:
    assert normalize_team_canonical("Man Utd", sport=Sport.SOCCER) == "team:mu"
    assert normalize_team_canonical("Wolves", sport=Sport.SOCCER) == "team:wolves"
    assert normalize_team_canonical("Unknown FC", sport=Sport.SOCCER) == "unknown"


def test_fixture_id_stable() -> None:
    start = datetime(2026, 5, 24, 15, 30, tzinfo=timezone.utc)
    a = fixture_id_for(
        sport=Sport.SOCCER,
        home="Man Utd",
        away="Wolves",
        start_time=start,
    )
    b = fixture_id_for(
        sport=Sport.SOCCER,
        home="Manchester United",
        away="Wolverhampton Wanderers",
        start_time=start,
    )
    assert a == b


def test_market_spec_id() -> None:
    spec = MarketSpec(
        sport=Sport.SOCCER,
        market_family="btts",
        period=MarketPeriod.FIRST_HALF,
        line=None,
    )
    assert len(spec.spec_id()) == 16


def test_equivalence_rules() -> None:
    assert periods_blocked(MarketPeriod.FIRST_HALF, MarketPeriod.FULL_TIME)
    assert market_family_requires_strict_period("btts")
