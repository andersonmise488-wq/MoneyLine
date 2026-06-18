"""Tests for incremental arb feed diff."""

from datetime import datetime, timezone

from moneyline.arb.identity import opportunity_fingerprint, opportunity_id
from moneyline.models.schemas import ArbitrageOpportunity, Sport
from moneyline.web.feed_diff import ArbFeedDiff


def _opp(margin: float, price: float = 2.0) -> ArbitrageOpportunity:
    now = datetime.now(timezone.utc)
    return ArbitrageOpportunity(
        cluster_id="c1",
        sport=Sport.SOCCER,
        market_key="match_winner",
        market_display="1X2",
        home_team="Home",
        away_team="Away",
        start_time=now,
        margin_pct=margin,
        implied_sum=0.97,
        legs=[
            {"bookmaker": "betika", "side": "home", "price": price},
            {"bookmaker": "odibets", "side": "away", "price": 2.1},
        ],
    )


def test_feed_diff_first_scan_all_added() -> None:
    diff = ArbFeedDiff()
    opp = _opp(2.5)
    added, updated, removed = diff.compute([opp])
    assert len(added) == 1
    assert not updated
    assert not removed


def test_feed_diff_no_change_empty_delta() -> None:
    diff = ArbFeedDiff()
    opp = _opp(2.5)
    diff.compute([opp])
    added, updated, removed = diff.compute([opp])
    assert not added
    assert not updated
    assert not removed


def test_feed_diff_price_change_is_updated() -> None:
    diff = ArbFeedDiff()
    opp = _opp(2.5, price=2.0)
    diff.compute([opp])
    changed = _opp(2.5, price=2.05)
    added, updated, removed = diff.compute([changed])
    assert not added
    assert len(updated) == 1
    assert not removed
    assert opportunity_id(changed) == opportunity_id(opp)
    assert opportunity_fingerprint(changed) != opportunity_fingerprint(opp)


def test_feed_diff_removed_ids() -> None:
    diff = ArbFeedDiff()
    opp = _opp(2.5)
    oid = opportunity_id(opp)
    diff.compute([opp])
    added, updated, removed = diff.compute([])
    assert not added
    assert not updated
    assert removed == [oid]
