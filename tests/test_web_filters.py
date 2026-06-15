from __future__ import annotations

from datetime import datetime, timezone

from moneyline.models.schemas import ArbitrageOpportunity, Sport
from moneyline.web.scanner import filter_premium_arbs, filter_public_arbs


def _opp(margin: float) -> ArbitrageOpportunity:
    now = datetime.now(timezone.utc)
    return ArbitrageOpportunity(
        cluster_id="c1",
        sport=Sport.SOCCER,
        market_key="1x2",
        market_display="1X2",
        home_team="A",
        away_team="B",
        start_time=now,
        margin_pct=margin,
        implied_sum=0.97,
        legs=[],
    )


def test_public_filter_up_to_three_percent() -> None:
    opps = [_opp(2.5), _opp(3.0), _opp(4.0), _opp(7.5)]
    public = filter_public_arbs(opps, max_margin_pct=3.0)
    assert [o.margin_pct for o in public] == [3.0, 2.5]


def test_premium_filter_above_public_cap() -> None:
    opps = [_opp(3.0), _opp(4.0), _opp(8.0)]
    premium = filter_premium_arbs(opps, min_margin_pct=3.01)
    assert [o.margin_pct for o in premium] == [8.0, 4.0]


def test_premium_filter_no_upper_cap() -> None:
    opps = [_opp(4.0), _opp(12.0), _opp(25.0), _opp(62.0)]
    premium = filter_premium_arbs(opps, min_margin_pct=3.01)
    assert [o.margin_pct for o in premium] == [62.0, 25.0, 12.0, 4.0]


def test_all_arbs_includes_sub_three_percent() -> None:
    from moneyline.web.filters import filter_all_arbs

    opps = [_opp(0.5), _opp(2.8), _opp(4.0), _opp(11.0)]
    all_arbs = filter_all_arbs(opps)
    assert [o.margin_pct for o in all_arbs] == [11.0, 4.0, 2.8, 0.5]
